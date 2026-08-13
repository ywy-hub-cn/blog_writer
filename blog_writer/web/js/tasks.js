/**
 * 任务管理
 */

const Tasks = {
    async start(brandPath, keywords, userNote, mode, forbiddenWhitelist, model, temperature, maxTokens) {
        if (!keywords) {
            UI.showToast('请输入关键词', 'warn');
            return;
        }

        UI.addLog(`🚀 启动新任务: ${keywords}`, 'info');
        UI.addLog(`   模式: ${mode}`, 'info');
        if (model) {
            UI.addLog(`   模型: ${model}`, 'info');
        }
        if (temperature !== undefined) {
            UI.addLog(`   温度系数: ${temperature}`, 'info');
        }
        if (maxTokens !== undefined) {
            UI.addLog(`   最大输出 Token: ${maxTokens}`, 'info');
        }
        if (forbiddenWhitelist) {
            UI.addLog(`   禁用词白名单: ${forbiddenWhitelist}`, 'info');
        }

        try {
            const payload = {
                brand_path: brandPath,
                keywords,
                user_note: userNote,
                mode
            };
            if (model && model !== 'default') {
                payload.model = model;
            }
            if (temperature !== undefined) {
                payload.temperature = temperature;
            }
            if (maxTokens !== undefined) {
                payload.max_tokens = maxTokens;
            }
            if (forbiddenWhitelist && String(forbiddenWhitelist).trim()) {
                payload.forbidden_whitelist = String(forbiddenWhitelist).trim();
            }
            const result = await Api.post('/api/tasks/start', payload);
            
            UI.addLog(`   ✅ 任务已创建: ${result.task_id}`, 'info');
            this.poll(result.task_id);
            this.refresh();
            
            // 通知父页面
            IframeBridge.taskCompleted(result.task_id, { status: 'started' });
            
            return result;
        } catch (e) {
            UI.addLog(`   ❌ 启动失败: ${e.message}`, 'error');
            throw e;
        }
    },

    poll(taskId) {
        let lastLogIndex = 0;

        const tick = async () => {
            try {
                const task = await Api.get(`/api/tasks/${taskId}`);
                const logs = await Api.get(`/api/tasks/${taskId}/logs`);
                
                if (logs.logs && logs.logs.length > lastLogIndex) {
                    const newLogs = logs.logs.slice(lastLogIndex);
                    newLogs.forEach(l => UI.addLog(l));
                    lastLogIndex = logs.logs.length;
                }

                if (task.status === 'running' || task.status === 'waiting_review') {
                    setTimeout(tick, 3000);
                } else {
                    UI.addLog(`   📊 任务结束: ${UI.getStatusLabel(task.status)}`, 
                        task.status === 'completed' ? 'info' : 'warn');
                    this.refresh();
                    
                    IframeBridge.taskCompleted(taskId, {
                        status: task.status,
                        token_usage: task.token_usage
                    });
                }
            } catch (e) {
                console.error('Poll error:', e);
            }
        };

        setTimeout(tick, 3000);
    },

    async refresh() {
        try {
            const data = await Api.get('/api/tasks');
            const list = document.getElementById('taskList');
            
            if (!data.tasks || data.tasks.length === 0) {
                list.innerHTML = '<p class="text-gray-500 text-center py-8">暂无任务，请创建新任务</p>';
                this._updateLastRefresh();
                return;
            }

            list.innerHTML = data.tasks.map(t => `
                <div class="border rounded-lg p-4 card-hover cursor-pointer" onclick="Tasks.showDetail('${UI.escapeAttr(t.task_id)}')">
                    <div class="flex justify-between items-start">
                        <div class="flex-1">
                            <div class="font-medium text-gray-800">${UI.escapeHtml(t.keywords || '未知任务')}</div>
                            <div class="text-xs text-gray-500 mt-1">${UI.escapeHtml(t.task_id)}</div>
                        </div>
                        <span class="px-2 py-1 text-xs rounded ${UI.getStatusColor(t.status)}">
                            ${UI.getStatusIcon(t.status)} ${UI.getStatusLabel(t.status)}
                        </span>
                    </div>
                    <div class="mt-3 flex justify-between items-center text-xs text-gray-500">
                        <div class="flex gap-3">
                            <span>📊 ${UI.escapeHtml(t.current_step)}/${UI.escapeHtml(t.total_steps || '?')} 步骤</span>
                            <span>🎯 ${UI.escapeHtml(t.mode)}</span>
                        </div>
                        ${t.token_usage ? `<span class="text-purple-600 font-medium">🔤 ${UI.formatTokens(t.token_usage)} tokens</span>` : ''}
                    </div>
                </div>
            `).join('');
            
            this._updateLastRefresh();
            Stats.update();
        } catch (e) {
            console.error('Refresh tasks error:', e);
            const lastUpdate = document.getElementById('taskLastUpdate');
            if (lastUpdate) {
                lastUpdate.textContent = '⚠️ 刷新失败';
                lastUpdate.className = 'text-xs text-red-400';
            }
        }
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
        try {
            const task = await Api.get(`/api/tasks/${taskId}`);
            const logs = await Api.get(`/api/tasks/${taskId}/logs`);

            UI.addLog(`\n📋 任务详情: ${taskId}`, 'step');
            UI.addLog(`   状态: ${UI.getStatusLabel(task.status)}`, 'info');
            UI.addLog(`   步骤: ${task.current_step}/${task.total_steps || '?'}`, 'info');

            if (task.results && task.results.length > 0) {
                const totalTokens = task.results.reduce((sum, r) => sum + (r.token_usage?.total_tokens || 0), 0);
                if (totalTokens > 0) {
                    UI.addLog(`   🔤 Token消耗: ${UI.formatTokens(totalTokens)} tokens`, 'info');
                    task.results.forEach((r, i) => {
                        const stepTokens = r.token_usage?.total_tokens || 0;
                        if (stepTokens > 0) {
                            UI.addLog(`      步骤 ${i+1} (${r.node_id}): ${UI.formatTokens(stepTokens)} tokens`, 'info');
                        }
                    });
                }
            }

            if (logs.logs) {
                logs.logs.forEach(l => UI.addLog(l));
            }

            if (task.status === 'waiting_review') {
                UI.addLog(`\n   ⏸️ 等待人工审核: ${task.review_node_name}`, 'warn');
                UI.addLog(`   请前往「人工审核」Tab进行审核`, 'warn');
                IframeBridge.reviewRequested(taskId, task.review_node_name);
            }
        } catch (e) {
            console.error('Show detail error:', e);
        }
    }
};

/**
 * 统计功能
 */
const Stats = {
    async update() {
        try {
            if (Auth.isLoggedIn()) {
                // 已登录：调用管理员统计接口
                const endpoint = '/api/admin/config/stats';
                const data = await Api.get(endpoint);
                this._renderStats(data);
            } else {
                // 未登录：从任务列表计算基本统计
                const data = await Api.get('/api/tasks');
                const tasks = data.tasks || [];
                const completed = tasks.filter(t => t.status === 'completed' || t.status === 'completed_partial').length;
                const running = tasks.filter(t => t.status === 'running' || t.status === 'pending').length;
                const pending = tasks.filter(t => t.status === 'waiting_review').length;
                this._renderBasicStats(completed, running, pending);
            }
        } catch (e) {
            console.error('Stats update error:', e);
            // 出错时尝试从任务列表计算
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
