/**
 * 任务管理
 */

const Tasks = {
    _currentTaskId: null,
    _currentFileName: null,
    _detailPollTimer: null,

    async start(brandPath, keywords, userNote, mode, forbiddenWhitelist, model, temperature, maxTokens, priority, brandSiteUrl, visualMode, scheduledAt) {
        if (!keywords) {
            UI.showToast('请输入关键词', 'warn');
            return;
        }

        const priorityLabels = {3: '高', 2: '中', 1: '低'};
        UI.addLog(`🚀 启动新任务: ${keywords}`, 'info');
        UI.addLog(`   模式: ${mode}`, 'info');
        UI.addLog(`   优先级: ${priorityLabels[priority] || '中'}`, 'info');
        if (model) UI.addLog(`   模型: ${model}`, 'info');
        if (temperature !== undefined) UI.addLog(`   温度系数: ${temperature}`, 'info');
        if (maxTokens !== undefined) UI.addLog(`   最大输出 Token: ${maxTokens}`, 'info');
        if (forbiddenWhitelist) UI.addLog(`   禁用词白名单: ${forbiddenWhitelist}`, 'info');
        if (brandSiteUrl) UI.addLog(`   品牌官网: ${brandSiteUrl}`, 'info');
        if (scheduledAt) UI.addLog(`   ⏰ 定时启动: ${new Date(scheduledAt).toLocaleString()}`, 'warn');
        const modeLabels = { relaxed: '宽松校验', strict: '严格校验', placeholder: '占位符模式' };
        if (visualMode && visualMode !== 'relaxed') {
            UI.addLog(`   🖼️ 图片校验模式: ${modeLabels[visualMode] || visualMode}`, 'warn');
        }

        try {
            const payload = {
                brand_path: brandPath,
                keywords,
                user_note: userNote,
                mode,
                priority: priority || 2
            };
            if (model && model !== 'default') payload.model = model;
            if (temperature !== undefined) payload.temperature = temperature;
            if (maxTokens !== undefined) payload.max_tokens = maxTokens;
            if (forbiddenWhitelist && String(forbiddenWhitelist).trim()) payload.forbidden_whitelist = String(forbiddenWhitelist).trim();
            if (brandSiteUrl && String(brandSiteUrl).trim()) payload.brand_site_url = String(brandSiteUrl).trim();
            if (visualMode && visualMode !== 'relaxed') payload.visual_mode = visualMode;
            if (scheduledAt) payload.scheduled_at = scheduledAt;
            
            const result = await Api.post('/api/tasks/start', payload);
            
            UI.addLog(`   ✅ 任务已创建: ${result.task_id}`, 'info');
            this.poll(result.task_id);
            this.refresh();
            
            IframeBridge.taskCompleted(result.task_id, { status: 'started' });
            return result;
        } catch (e) {
            UI.addLog(`   ❌ 启动失败: ${e.message}`, 'error');
            if (State.taskAuthRequired && Api.isAuthError(e.message)) {
                Api.promptLogin('当前环境启动任务需要登录或 API Token');
            } else {
                UI.showToast(`❌ ${e.message}`, 'error', 5000);
            }
            throw e;
        }
    },

    poll(taskId) {
        let lastLogIndex = 0;
        let scheduledLogged = false;
        let backoffMs = 8000;
        const tick = async () => {
            try {
                const task = await Api.get(`/api/tasks/${taskId}`);
                const logs = await Api.get(`/api/tasks/${taskId}/logs`);
                backoffMs = 8000;
                
                if (logs.logs && logs.logs.length > lastLogIndex) {
                    logs.logs.slice(lastLogIndex).forEach(l => UI.addLog(l));
                    lastLogIndex = logs.logs.length;
                }

                if (task.status === 'scheduled') {
                    if (!scheduledLogged) {
                        UI.addLog(`   ⏰ 任务已定时，将在指定时间由服务器自动执行`, 'info');
                        scheduledLogged = true;
                    }
                    setTimeout(tick, 15000);
                    return;
                }

                if (task.status === 'running' || task.status === 'waiting_review' || task.status === 'queued') {
                    setTimeout(tick, backoffMs);
                } else {
                    UI.addLog(`   📊 任务结束: ${UI.getStatusLabel(task.status)}`, 
                        task.status === 'completed' ? 'info' : 'warn');
                    this.refresh();
                    IframeBridge.taskCompleted(taskId, { status: task.status, token_usage: task.token_usage });
                }
            } catch (e) {
                console.error('Poll error:', e);
                const msg = String(e && e.message || e);
                if (/429|过于频繁|Rate limit/i.test(msg)) {
                    backoffMs = Math.min(60000, Math.max(backoffMs * 2, 15000));
                    UI.addLog(`   ⏳ 轮询触发限流，${Math.round(backoffMs / 1000)}s 后重试`, 'warn');
                }
                setTimeout(tick, backoffMs);
            }
        };
        setTimeout(tick, 8000);
    },

    async refresh() {
        try {
            const [data, concurrency] = await Promise.all([
                Api.get('/api/tasks'),
                Api.get('/api/tasks/concurrency').catch(() => null)
            ]);
            const list = document.getElementById('taskList');
            
            // 更新并发信息显示
            if (concurrency) {
                const concurrencyEl = document.getElementById('concurrencyInfo');
                if (concurrencyEl) {
                    concurrencyEl.innerHTML = `🔄 并发 ${concurrency.running}/${concurrency.max_concurrent}` +
                        (concurrency.queued > 0 ? ` · 🕐 排队 ${concurrency.queued}` : '');
                }
            }
            
            if (!data.tasks || data.tasks.length === 0) {
                list.innerHTML = '<p class="text-gray-500 text-center py-8">暂无任务，请创建新任务</p>';
                this._updateLastRefresh();
                return;
            }

            list.innerHTML = data.tasks.map(t => this._renderTaskCard(t)).join('');
            
            this._updateLastRefresh();
            Stats.update();
        } catch (e) {
            console.error('Refresh tasks error:', e);
            if (State.taskAuthRequired && Api.isAuthError(e.message)) {
                Api.promptLogin('当前环境查看任务需要登录或 API Token');
            }
            const lastUpdate = document.getElementById('taskLastUpdate');
            if (lastUpdate) {
                lastUpdate.textContent = '⚠️ 刷新失败';
                lastUpdate.className = 'text-xs text-red-400';
            }
        }
    },

    _taskProgress(task) {
        const sp = task.step_progress || task.stepProgress;
        if (sp) {
            return {
                current: sp.current ?? task.current_step ?? 0,
                total: sp.total ?? task.total_steps ?? 0,
                percent: sp.percent ?? 0,
                label: sp.completed_count ?? sp.completedCount ?? task.current_step ?? 0,
            };
        }
        const total = task.total_steps || 0;
        const current = task.current_step || 0;
        return {
            current,
            total,
            percent: total ? Math.round((current / total) * 100) : 0,
            label: current,
        };
    },

    _renderQualityGates(task) {
        const el = document.getElementById('taskDetailQualityGates');
        if (!el) return;
        const gates = task.quality_gates || task.qualityGates;
        const summary = task.publish_summary || task.publishSummary;
        if (!gates && !summary) {
            el.classList.add('hidden');
            el.innerHTML = '';
            return;
        }
        const parts = [];
        if (gates) {
            const contentOk = gates.content && gates.content.ok;
            const visualsOk = gates.visuals && gates.visuals.ok;
            if (gates.content) parts.push(`内容校验: ${contentOk === true ? '通过' : contentOk === false ? '未通过' : '未知'}`);
            if (gates.visuals) parts.push(`配图校验: ${visualsOk === true ? '通过' : visualsOk === false ? '未通过' : '未知'}`);
            if (gates.internal_link_count != null) parts.push(`内链: ${gates.internal_link_count} 条`);
        }
        if (summary && (summary.post_url || summary.postUrl)) {
            parts.push(`发布: ${UI.escapeHtml(summary.post_url || summary.postUrl)}`);
        }
        el.innerHTML = `<strong>质量门禁</strong> · ${parts.map(p => UI.escapeHtml(p)).join(' · ')}`;
        el.classList.remove('hidden');
    },

    _priorityBadge(t) {
        const priority = (t.extra && t.extra.priority) || 2;
        if (priority === 3) return '<span class="px-1.5 py-0.5 text-xs rounded bg-red-100 text-red-700">🔴 高</span>';
        if (priority === 1) return '<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 text-green-700">🟢 低</span>';
        return '';
    },

    _renderTaskCard(t) {
        const isQueued = t.status === 'queued';
        const isScheduled = t.status === 'scheduled';
        const isRunning = t.status === 'running' || t.status === 'pending';
        const isPaused = t.status === 'paused';
        const isWaiting = t.status === 'waiting_review';
        const isFinished = ['completed', 'failed', 'cancelled', 'completed_partial'].includes(t.status);

        const scheduledAt = (t.extra && t.extra.scheduled_at) ? new Date(t.extra.scheduled_at).toLocaleString() : '';

        let actions = '';
        if (isScheduled) {
            actions += `<button onclick="event.stopPropagation(); Tasks.cancel('${UI.escapeAttr(t.task_id)}')" class="btn btn-outline btn-xs text-red-500" title="取消定时任务">❌ 取消定时</button>`;
        }
        if (isQueued) {
            const currentPriority = (t.extra && t.extra.priority) || 2;
            actions += `<button onclick="event.stopPropagation(); Tasks.boostPriority('${UI.escapeAttr(t.task_id)}')" class="btn btn-outline btn-xs" title="提升优先级">⬆️ 提升</button>`;
            actions += `<button onclick="event.stopPropagation(); Tasks.cancelQueue('${UI.escapeAttr(t.task_id)}')" class="btn btn-outline btn-xs text-red-500" title="取消排队">❌ 取消排队</button>`;
        }
        if (isRunning || isWaiting) {
            actions += `<button onclick="event.stopPropagation(); Tasks.pause('${UI.escapeAttr(t.task_id)}')" class="btn btn-outline btn-xs" title="暂停任务（可继续）">⏸️ 暂停</button>`;
            actions += `<button onclick="event.stopPropagation(); Tasks.cancel('${UI.escapeAttr(t.task_id)}')" class="btn btn-outline btn-xs text-red-500" title="取消任务（不可恢复）">⏹️ 取消</button>`;
        }
        if (isPaused) {
            actions += `<button onclick="event.stopPropagation(); Tasks.resume('${UI.escapeAttr(t.task_id)}')" class="btn btn-outline btn-xs" title="继续任务">▶️ 继续</button>`;
            actions += `<button onclick="event.stopPropagation(); Tasks.cancel('${UI.escapeAttr(t.task_id)}')" class="btn btn-outline btn-xs text-red-500" title="取消任务">⏹️ 取消</button>`;
        }
        if (isFinished) {
            actions += `<button onclick="event.stopPropagation(); Tasks.rerun('${UI.escapeAttr(t.task_id)}')" class="btn btn-outline btn-xs" title="从头重新运行">🔄 重跑</button>`;
        }
        actions += `<button onclick="event.stopPropagation(); Tasks.showDetail('${UI.escapeAttr(t.task_id)}')" class="btn btn-primary btn-xs" title="查看详情">👁️ 详情</button>`;
        actions += `<button onclick="event.stopPropagation(); Tasks.delete('${UI.escapeAttr(t.task_id)}')" class="btn btn-outline btn-xs text-red-500" title="删除任务">🗑️ 删除</button>`;

        const prog = this._taskProgress(t);

        return `
            <div class="border rounded-lg p-4 card-hover cursor-pointer" onclick="Tasks.showDetail('${UI.escapeAttr(t.task_id)}')">
                <div class="flex justify-between items-start">
                    <div class="flex-1">
                        <div class="font-medium text-gray-800 flex items-center gap-2">
                            ${UI.escapeHtml(t.keywords || '未知任务')}
                            ${Tasks._priorityBadge(t)}
                        </div>
                        <div class="text-xs text-gray-500 mt-1">${UI.escapeHtml(t.task_id)}</div>
                    </div>
                    <span class="px-2 py-1 text-xs rounded ${UI.getStatusColor(t.status)}">
                        ${UI.getStatusIcon(t.status)} ${UI.getStatusLabel(t.status)}
                    </span>
                </div>
                <div class="mt-3 flex justify-between items-center text-xs text-gray-500">
                    <div class="flex gap-3">
                        <span>📊 ${UI.escapeHtml(prog.label)}/${UI.escapeHtml(prog.total || '?')} 步骤 (${prog.percent}%)</span>
                        <span>🎯 ${UI.escapeHtml(t.mode)}</span>
                        ${isScheduled && scheduledAt ? `<span class="text-purple-600">⏰ ${UI.escapeHtml(scheduledAt)}</span>` : ''}
                    </div>
                    ${t.token_usage ? `<span class="text-purple-600 font-medium">🔤 ${UI.formatTokens(t.token_usage)} tokens</span>` : ''}
                </div>
                <div class="mt-3 flex gap-2 flex-wrap">
                    ${actions}
                </div>
            </div>
        `;
    },

    _updateLastRefresh() {
        const el = document.getElementById('taskLastUpdate');
        if (el) {
            const now = new Date();
            const time = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            el.textContent = `最后更新: ${time}`;
            el.className = 'text-xs text-gray-400';
        }
    },

    async showDetail(taskId) {
        this._currentTaskId = taskId;
        const modal = document.getElementById('taskDetailModal');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        
        await this._loadDetail(taskId);
        
        // 启动详情页轮询（运行中任务）
        if (this._detailPollTimer) clearInterval(this._detailPollTimer);
        this._detailPollTimer = setInterval(() => {
            if (this._currentTaskId) {
                this._loadDetail(this._currentTaskId, true);
            }
        }, 10000);
    },

    closeDetail() {
        const modal = document.getElementById('taskDetailModal');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        this._currentTaskId = null;
        if (this._detailPollTimer) {
            clearInterval(this._detailPollTimer);
            this._detailPollTimer = null;
        }
    },

    async _loadDetail(taskId, silent = false) {
        try {
            const task = await Api.get(`/api/tasks/${taskId}`);
            
            // 标题
            document.getElementById('taskDetailTitle').textContent = task.keywords || '未知任务';
            document.getElementById('taskDetailSubtitle').textContent = `任务ID: ${task.task_id}`;
            
            // 状态
            const statusEl = document.getElementById('taskDetailStatus');
            statusEl.textContent = `${UI.getStatusIcon(task.status)} ${UI.getStatusLabel(task.status)}`;
            statusEl.className = `px-3 py-1 text-sm rounded-full ${UI.getStatusColor(task.status)}`;
            
            // 进度
            const prog = this._taskProgress(task);
            document.getElementById('taskDetailProgress').textContent =
                `📊 ${prog.label}/${prog.total || '?'} 步骤 (${prog.percent}%)`;
            document.getElementById('taskDetailProgressBar').style.width = `${prog.percent}%`;
            document.getElementById('taskDetailMode').textContent = `🎯 ${task.mode}`;

            this._renderQualityGates(task);
            
            // Token
            if (task.token_usage) {
                document.getElementById('taskDetailTokens').textContent = `🔤 ${UI.formatTokens(task.token_usage)} tokens`;
            }
            
            // 运行时长
            const durationEl = document.getElementById('taskDetailDuration');
            if (task.start_time) {
                const start = new Date(task.start_time);
                const end = task.end_time ? new Date(task.end_time) : new Date();
                const seconds = (end - start) / 1000;
                if (seconds > 0) {
                    durationEl.textContent = `⏱️ ${UI.formatDuration(seconds)}`;
                }
            }
            
            // 操作按钮
            this._renderDetailActions(task);
            
            // 文件列表
            await this._loadTaskFiles(taskId);
            
            // 步骤
            this._renderSteps(task);
            
            // 如果任务已结束，停止轮询
            if (!['running', 'waiting_review', 'pending', 'paused'].includes(task.status)) {
                if (this._detailPollTimer) {
                    clearInterval(this._detailPollTimer);
                    this._detailPollTimer = null;
                }
            }
        } catch (e) {
            if (!silent) console.error('Load detail error:', e);
        }
    },

    _renderDetailActions(task) {
        const container = document.getElementById('taskDetailActions');
        const tid = UI.escapeAttr(task.task_id);
        let buttons = '';
        
        // 检测视觉问题：如果任务在 S007/S009 阶段失败，显示"使用占位图继续"按钮
        const hasVisualIssue = this._detectVisualIssue(task);
        if (hasVisualIssue && ['failed', 'completed_partial', 'paused'].includes(task.status)) {
            buttons += `<button onclick="Tasks.skipVisualAndPublish('${tid}')" class="btn btn-warning btn-sm" title="使用占位图继续发布">🖼️ 使用占位图发布</button>`;
        }
        
        if (['running', 'pending', 'waiting_review'].includes(task.status)) {
            buttons += `<button onclick="Tasks.pause('${tid}')" class="btn btn-outline btn-sm">⏸️ 暂停</button>`;
            buttons += `<button onclick="Tasks.cancel('${tid}')" class="btn btn-outline btn-sm text-red-500">⏹️ 取消</button>`;
        }
        if (task.status === 'paused') {
            buttons += `<button onclick="Tasks.resume('${tid}')" class="btn btn-outline btn-sm">▶️ 继续</button>`;
            buttons += `<button onclick="Tasks.cancel('${tid}')" class="btn btn-outline btn-sm text-red-500">⏹️ 取消</button>`;
        }
        if (['completed', 'failed', 'cancelled', 'completed_partial'].includes(task.status)) {
            buttons += `<button onclick="Tasks.rerun('${tid}')" class="btn btn-outline btn-sm">🔄 重跑</button>`;
            buttons += `<button onclick="Tasks.showRerunOptions('${tid}')" class="btn btn-outline btn-sm">📋 选节点重跑</button>`;
        }
        buttons += `<button onclick="Tasks.delete('${tid}')" class="btn btn-outline btn-sm text-red-500">🗑️ 删除</button>`;
        
        container.innerHTML = buttons;
    },
    
    _detectVisualIssue(task) {
        const results = task.results || [];
        const visualSteps = ['S007-visual.json', 'step.blog.writer.visual'];
        const gateSteps = ['S009-gate.json', 'step.blog.writer.gate'];
        
        // Check if visual step has issues
        for (const r of results) {
            const step = (r.step || r.node_id || '').toLowerCase();
            if (visualSteps.some(s => step.includes(s.toLowerCase().replace('.json', '').split('-').pop()))) {
                if (r.status === 'failed' || r.status === 'error') return true;
            }
            if (gateSteps.some(s => step.includes(s.toLowerCase().replace('.json', '').split('-').pop()))) {
                if (r.status === 'failed') return true;
            }
        }
        
        // Check quality gates
        const gates = task.quality_gates || task.qualityGates;
        if (gates && gates.visuals && gates.visuals.ok === false) return true;
        
        return false;
    },
    
    async skipVisualAndPublish(taskId) {
        if (!confirm('将从"发布包"节点开始重跑，使用占位图替代真实图片。\n\n适合场景：图片生成质量不佳或失败，但需要快速输出发布包，后续人工替换图片。\n\n核心正文 HTML 质量不受影响。')) return;

        try {
            UI.addLog(`🖼️ 为任务 ${taskId} 启用占位图模式...`, 'warn');

            const body = {
                nodeFile: 'S010-publish.json',
                visualMode: 'placeholder'
            };
            
            const result = await Api.post(`/api/tasks/${taskId}/rerun-from`, body);
            UI.addLog(`   ✅ 已触发占位图发布: ${result.message}`, 'info');
            UI.showToast('已启用占位图模式，正在重新生成发布包...', 'success');
            this.refresh();
            this._loadDetail(taskId);
        } catch (e) {
            UI.showToast(`❌ 操作失败: ${e.message}`, 'error');
        }
    },

    async _loadTaskFiles(taskId) {
        try {
            const data = await Api.get(`/api/tasks/${taskId}/files`);
            const container = document.getElementById('taskDetailFiles');
            
            if (!data.files || data.files.length === 0) {
                container.innerHTML = '<p class="text-gray-400 text-center py-8 text-sm">暂无生成文件</p>';
                return;
            }
            
            container.innerHTML = data.files.map(f => `
                <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
                    <div class="flex items-center gap-3 flex-1 min-w-0">
                        <span class="text-xl">${this._getFileIcon(f.name)}</span>
                        <div class="min-w-0">
                            <div class="font-medium text-sm text-gray-800 truncate">${UI.escapeHtml(f.name)}</div>
                            <div class="text-xs text-gray-500">${UI.formatSize(f.size)} · ${new Date(f.modified_at).toLocaleString('zh-CN')}</div>
                        </div>
                    </div>
                    <div class="flex gap-2">
                        <button onclick="Tasks.viewFile('${UI.escapeAttr(taskId)}', '${UI.escapeAttr(f.name)}')" class="btn btn-primary btn-xs">👁️ 查看</button>
                        <button onclick="Tasks.downloadFile('${UI.escapeAttr(taskId)}', '${UI.escapeAttr(f.name)}')" class="btn btn-outline btn-xs">⬇️ 下载</button>
                    </div>
                </div>
            `).join('');
        } catch (e) {
            console.error('Load files error:', e);
            document.getElementById('taskDetailFiles').innerHTML = '<p class="text-red-400 text-center py-8 text-sm">加载文件列表失败</p>';
        }
    },

    _renderSteps(task) {
        const container = document.getElementById('taskDetailSteps');
        const results = task.results || [];
        const completed = task.completed_steps || [];
        
        if (results.length === 0 && completed.length === 0) {
            container.innerHTML = '<p class="text-gray-400 text-center py-8 text-sm">暂无执行记录</p>';
            return;
        }
        
        let html = '';
        
        // 已完成步骤
        if (results.length > 0) {
            html += '<div class="space-y-2">';
            results.forEach((r, i) => {
                const statusColor = r.status === 'success' ? 'text-green-600' : r.status === 'failed' ? 'text-red-600' : 'text-yellow-600';
                const statusIcon = r.status === 'success' ? '✅' : r.status === 'failed' ? '❌' : '⏳';
                html += `
                    <div class="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                        <span class="text-lg">${statusIcon}</span>
                        <div class="flex-1">
                            <div class="font-medium text-sm">步骤 ${i + 1}: ${UI.escapeHtml(r.node_id || '未知')}</div>
                            <div class="text-xs text-gray-500 mt-1">
                                状态: <span class="${statusColor}">${UI.escapeHtml(r.status || '未知')}</span>
                                ${r.token_usage?.total_tokens_used ? ` · Token: ${UI.formatTokens(r.token_usage.total_tokens_used)}` : ''}
                                ${r.iterations ? ` · 迭代: ${r.iterations}` : ''}
                            </div>
                        </div>
                    </div>
                `;
            });
            html += '</div>';
        }
        
        container.innerHTML = html;
    },

    switchDetailTab(tab) {
        ['files', 'steps', 'logs'].forEach(t => {
            const btn = document.getElementById(`tabDetail${t.charAt(0).toUpperCase() + t.slice(1)}`);
            const content = document.getElementById(`taskDetail${t.charAt(0).toUpperCase() + t.slice(1)}`);
            if (t === tab) {
                btn.className = 'px-4 py-2 text-sm font-medium border-b-2 border-blue-500 text-blue-600';
                content.classList.remove('hidden');
            } else {
                btn.className = 'px-4 py-2 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700';
                content.classList.add('hidden');
            }
        });
        
        // 切换到日志时加载日志
        if (tab === 'logs' && this._currentTaskId) {
            this._loadTaskLogs(this._currentTaskId);
        }
    },

    async _loadTaskLogs(taskId) {
        try {
            const data = await Api.get(`/api/tasks/${taskId}/logs`);
            const logs = data.logs || [];
            document.getElementById('taskDetailLogContent').textContent = logs.join('\n');
        } catch (e) {
            document.getElementById('taskDetailLogContent').textContent = '加载日志失败: ' + e.message;
        }
    },

    async viewFile(taskId, filename) {
        this._currentTaskId = taskId;
        this._currentFileName = filename;
        
        const modal = document.getElementById('fileViewerModal');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        
        document.getElementById('fileViewerTitle').textContent = filename;
        document.getElementById('fileViewerSubtitle').textContent = `任务: ${taskId}`;
        document.getElementById('fileViewerContent').textContent = '加载中...';
        
        try {
            const response = await fetch(`/api/tasks/${taskId}/files/${encodeURIComponent(filename)}`);
            if (response.ok) {
                const text = await response.text();
                document.getElementById('fileViewerContent').textContent = text;
            } else {
                document.getElementById('fileViewerContent').textContent = '加载失败: ' + response.status;
            }
        } catch (e) {
            document.getElementById('fileViewerContent').textContent = '加载失败: ' + e.message;
        }
    },

    closeFileViewer() {
        const modal = document.getElementById('fileViewerModal');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        this._currentFileName = null;
    },

    downloadFile(taskId, filename) {
        window.open(`/api/tasks/${taskId}/files/${encodeURIComponent(filename)}?download=true`, '_blank');
    },

    downloadCurrentFile() {
        if (this._currentTaskId && this._currentFileName) {
            this.downloadFile(this._currentTaskId, this._currentFileName);
        }
    },

    _getFileIcon(filename) {
        const ext = filename.split('.').pop().toLowerCase();
        const icons = {
            'md': '📝', 'txt': '📄', 'json': '📋', 'html': '🌐', 'xml': '📰',
            'csv': '📊', 'yaml': '⚙️', 'yml': '⚙️', 'png': '🖼️', 'jpg': '🖼️',
            'jpeg': '🖼️', 'gif': '🖼️', 'pdf': '📕', 'zip': '📦',
        };
        return icons[ext] || '📄';
    },

    async cancel(taskId) {
        if (!confirm('确定要取消这个任务吗？取消后无法继续，只能重新运行。')) return;
        try {
            await Api.post(`/api/tasks/${taskId}/cancel`);
            UI.showToast('✅ 任务已取消', 'success');
            this.refresh();
            if (this._currentTaskId === taskId) this._loadDetail(taskId);
        } catch (e) {
            UI.showToast('❌ 取消失败: ' + e.message, 'error');
        }
    },

    async pause(taskId) {
        try {
            await Api.post(`/api/tasks/${taskId}/pause`);
            UI.showToast('✅ 任务已暂停，可点击继续恢复', 'success');
            this.refresh();
            if (this._currentTaskId === taskId) this._loadDetail(taskId);
        } catch (e) {
            UI.showToast('❌ 暂停失败: ' + e.message, 'error');
        }
    },

    async resume(taskId) {
        try {
            await Api.post(`/api/tasks/${taskId}/resume`);
            UI.showToast('✅ 任务已继续', 'success');
            this.refresh();
            if (this._currentTaskId === taskId) this._loadDetail(taskId);
        } catch (e) {
            UI.showToast('❌ 操作失败: ' + e.message, 'error');
        }
    },

    async rerun(taskId, nodeFile, userNote, brandSiteUrl, visualMode) {
        const startNode = nodeFile || 'S000-startup.json';
        if (!confirm(`确定要从 ${startNode} 开始重跑吗？之前的结果会被清除。`)) return;
        try {
            const body = { nodeFile: startNode };
            if (userNote) body.userNote = userNote;
            if (brandSiteUrl && String(brandSiteUrl).trim()) {
                body.brandSiteUrl = String(brandSiteUrl).trim();
            }
            if (visualMode && visualMode !== 'relaxed') body.visualMode = visualMode;
            await Api.post(`/api/tasks/${taskId}/rerun-from`, body);
            const modeLabels = { relaxed: '', strict: '（严格校验）', placeholder: '（占位符模式）' };
            UI.showToast('✅ 任务已开始重跑' + (modeLabels[visualMode] || ''), 'success');
            this.refresh();
            if (this._currentTaskId === taskId) this._loadDetail(taskId);
        } catch (e) {
            UI.showToast('❌ 重跑失败: ' + e.message, 'error');
        }
    },

    _rerunTaskId: null,

    showRerunOptions(taskId) {
        this._rerunTaskId = taskId;
        const nodes = [
            { file: 'S000-startup.json', name: '启动初始化' },
            { file: 'S001-bid-infer.json', name: 'BID自动推断' },
            { file: 'S002-content-prd.json', name: '内容PRD' },
            { file: 'S003-structure.json', name: '结构生成' },
            { file: 'S004-draft.json', name: '正文写作' },
            { file: 'S005-field.json', name: '字段化' },
            { file: 'S006-preview.json', name: '呈现文档' },
            { file: 'S007-visual.json', name: '视觉素材' },
            { file: 'S008-review-draft.json', name: '自审打分' },
            { file: 'S009-gate.json', name: 'Gate校验' },
            { file: 'S010-publish.json', name: '发布包' },
            { file: 'S011-publish-wp.json', name: 'WordPress发布' },
        ];
        const select = document.getElementById('rerunNodeSelect');
        select.innerHTML = nodes.map(n => `<option value="${n.file}">${n.file} - ${n.name}</option>`).join('');
        select.value = 'S000-startup.json';
        document.getElementById('rerunUserNote').value = '';
        const siteInput = document.getElementById('rerunBrandSiteUrl');
        if (siteInput) siteInput.value = '';
        const skipSelect = document.getElementById('rerunVisualMode');
        if (skipSelect) skipSelect.value = 'relaxed';
        const modal = document.getElementById('rerunModal');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    },

    closeRerunModal() {
        const modal = document.getElementById('rerunModal');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        this._rerunTaskId = null;
    },

    confirmRerun() {
        const taskId = this._rerunTaskId;
        const nodeFile = document.getElementById('rerunNodeSelect').value;
        const userNote = document.getElementById('rerunUserNote').value.trim();
        const brandSiteUrl = (document.getElementById('rerunBrandSiteUrl')?.value || '').trim();
        const visualMode = document.getElementById('rerunVisualMode')?.value || 'relaxed';
        if (brandSiteUrl && !/^https?:\/\/.+/i.test(brandSiteUrl)) {
            UI.showToast('品牌官网地址需以 http:// 或 https:// 开头', 'warn');
            return;
        }
        if (!taskId || !nodeFile) return;
        this.closeRerunModal();
        this.rerun(taskId, nodeFile, userNote, brandSiteUrl, visualMode);
    },

    async delete(taskId) {
        if (!confirm('确定要删除这个任务吗？此操作不可恢复！')) return;
        try {
            await Api.delete(`/api/tasks/${taskId}`);
            UI.showToast('✅ 任务已删除', 'success');
            this.closeDetail();
            this.refresh();
        } catch (e) {
            UI.showToast('❌ 删除失败: ' + e.message, 'error');
        }
    },

    async cancelQueue(taskId) {
        if (!confirm('确定要取消这个排队中的任务吗？')) return;
        try {
            await Api.post(`/api/tasks/${taskId}/cancel-queue`);
            UI.showToast('✅ 排队任务已取消', 'success');
            this.refresh();
        } catch (e) {
            UI.showToast('❌ 取消失败: ' + e.message, 'error');
        }
    },

    async boostPriority(taskId) {
        try {
            await Api.put(`/api/tasks/${taskId}/priority`, { priority: 3 });
            UI.showToast('✅ 优先级已提升为高', 'success');
            this.refresh();
        } catch (e) {
            UI.showToast('❌ 提升失败: ' + e.message, 'error');
        }
    },
};

/**
 * 统计功能
 */
const Stats = {
    async update() {
        try {
            if (Auth.isLoggedIn()) {
                const data = await Api.get('/api/admin/config/stats');
                this._renderStats(data);
            } else {
                const data = await Api.get('/api/tasks');
                const tasks = data.tasks || [];
                const completed = tasks.filter(t => t.status === 'completed' || t.status === 'completed_partial').length;
                const running = tasks.filter(t => t.status === 'running' || t.status === 'pending').length;
                const pending = tasks.filter(t => t.status === 'waiting_review').length;
                this._renderBasicStats(completed, running, pending);
            }
        } catch (e) {
            console.error('Stats update error:', e);
            try {
                const data = await Api.get('/api/tasks');
                const tasks = data.tasks || [];
                const completed = tasks.filter(t => t.status === 'completed' || t.status === 'completed_partial').length;
                const running = tasks.filter(t => t.status === 'running' || t.status === 'pending').length;
                const pending = tasks.filter(t => t.status === 'waiting_review').length;
                this._renderBasicStats(completed, running, pending);
            } catch (e2) {
                console.error('Stats fallback error:', e2);
            }
        }
    },

    _renderStats(data) {
        document.getElementById('statCompleted').textContent = data.completed_tasks || 0;
        document.getElementById('statRunning').textContent = data.running_tasks || 0;
        document.getElementById('statPending').textContent = data.pending_reviews || 0;

        if (Auth.isLoggedIn()) {
            const llmTokens = data.llm_stats?.total_tokens_used || 0;
            const llmCalls = data.llm_stats?.total_calls || 0;
            const totalTokens = data.total_tokens_consumed || llmTokens;
            this._updateNavStats(data, totalTokens, llmCalls);
            this._updateMobileStats(data, totalTokens, llmCalls);
            this._updateSystemStats(totalTokens, llmCalls);
            this._updateConfigStats(totalTokens, llmCalls, data);
        }
    },

    _renderBasicStats(completed, running, pending) {
        const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        set('statCompleted', completed);
        set('statRunning', running);
        set('statPending', pending);
        set('navCompleted', completed);
        set('navRunning', running);
        set('navPending', pending);
        set('mobCompleted', completed);
        set('mobRunning', running);
        set('mobPending', pending);
    },

    _updateNavStats(data, totalTokens, llmCalls) {
        const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        set('navCompleted', data.completed_tasks || 0);
        set('navRunning', data.running_tasks || 0);
        set('navPending', data.pending_reviews || 0);
        set('navTokenCount', UI.formatTokens(totalTokens));
        set('navCallCount', llmCalls.toLocaleString());
        set('navCost', UI.estimateCost(totalTokens));
    },

    _updateMobileStats(data, totalTokens, llmCalls) {
        const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        set('mobCompleted', data.completed_tasks || 0);
        set('mobRunning', data.running_tasks || 0);
        set('mobPending', data.pending_reviews || 0);
        set('mobCalls', llmCalls.toLocaleString());
        set('mobTokens', UI.formatTokens(totalTokens));
        set('mobCost', UI.estimateCost(totalTokens));
        const bar = document.getElementById('mobileStatsBar');
        if (bar) bar.style.display = 'flex';
    },

    _updateSystemStats(totalTokens, llmCalls) {
        const el = (id) => document.getElementById(id);
        const avgCalls = llmCalls > 0 ? Math.round(totalTokens / llmCalls) : 0;
        if (el('statTokens')) el('statTokens').textContent = UI.formatTokens(totalTokens);
        if (el('statCalls')) el('statCalls').textContent = llmCalls.toLocaleString();
        if (el('statAvgTokens')) el('statAvgTokens').textContent = avgCalls.toLocaleString();
        if (el('statCost')) el('statCost').textContent = UI.estimateCost(totalTokens);
    },

    _updateConfigStats(totalTokens, llmCalls, data) {
        const el = (id) => document.getElementById(id);
        if (el('statTotalTokens')) el('statTotalTokens').textContent = totalTokens.toLocaleString();
        if (el('statTotalCalls')) el('statTotalCalls').textContent = llmCalls.toLocaleString();
        if (el('statAvgTokens')) el('statAvgTokens').textContent = 
            llmCalls > 0 ? Math.round(totalTokens / llmCalls).toLocaleString() : '0';
        if (el('statEstCost')) el('statEstCost').textContent = UI.estimateCost(totalTokens);
        if (data.total_tasks !== undefined) {
            if (el('statTotal')) el('statTotal').textContent = data.total_tasks;
            if (el('statSuccessRate')) el('statSuccessRate').textContent = (data.success_rate || 0).toFixed(1) + '%';
            if (el('statAvgDuration')) el('statAvgDuration').textContent = UI.formatDuration(data.avg_duration_seconds || 0);
        }
    }
};
