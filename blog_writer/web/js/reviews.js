/**
 * 人工审核管理
 */

const Reviews = {
    _expandedTaskId: null,

    async refresh() {
        try {
            const data = await Api.get('/api/tasks/reviews/pending');
            const list = document.getElementById('reviewList');
            
            if (!data.reviews || data.reviews.length === 0) {
                list.innerHTML = '<p class="text-gray-500 text-center py-8">暂无待审核任务 🎉</p>';
                return;
            }

            list.innerHTML = data.reviews.map(r => this._renderReviewCard(r)).join('');
        } catch (e) {
            console.error('Refresh reviews error:', e);
        }
    },

    _renderReviewCard(r) {
        const isExpanded = this._expandedTaskId === r.task_id;
        return `
            <div class="border rounded-xl p-5 card-hover">
                <div class="flex justify-between items-start mb-4">
                    <div class="flex-1">
                        <h3 class="font-bold text-gray-800">${UI.escapeHtml(r.keywords || '未知任务')}</h3>
                        <p class="text-sm text-gray-500 mt-1">任务ID: ${UI.escapeHtml(r.task_id)}</p>
                        <p class="text-sm text-gray-500">审核节点: ${UI.escapeHtml(r.node_name || '未知')}</p>
                    </div>
                    <span class="px-3 py-1 bg-yellow-100 text-yellow-700 rounded-full text-sm">👁️ 待审核</span>
                </div>
                
                <!-- 查看内容按钮 -->
                <div class="mb-4">
                    <button onclick="Reviews.toggleContent('${UI.escapeAttr(r.task_id)}')" class="btn btn-outline btn-sm">
                        ${isExpanded ? '📖 收起内容' : '📖 查看待审核内容'}
                    </button>
                </div>
                
                <!-- 待审核内容区域 -->
                <div id="reviewContent_${UI.escapeAttr(r.task_id)}" class="${isExpanded ? '' : 'hidden'} mb-4">
                    <div id="reviewContentBody_${UI.escapeAttr(r.task_id)}" class="bg-gray-50 rounded-lg p-4 max-h-96 overflow-y-auto">
                        <p class="text-gray-400 text-sm">加载中...</p>
                    </div>
                </div>
                
                <div class="flex gap-3">
                    <button onclick="Reviews.submit('${UI.escapeAttr(r.task_id)}', 'approve')" 
                        class="flex-1 bg-green-500 text-white py-2 rounded-lg hover:bg-green-600">
                        ✅ 通过
                    </button>
                    <button onclick="Reviews.submit('${UI.escapeAttr(r.task_id)}', 'modify')" 
                        class="flex-1 bg-yellow-500 text-white py-2 rounded-lg hover:bg-yellow-600">
                        ✏️ 修改后通过
                    </button>
                    <button onclick="Reviews.submit('${UI.escapeAttr(r.task_id)}', 'reject')" 
                        class="flex-1 bg-red-500 text-white py-2 rounded-lg hover:bg-red-600">
                        ❌ 驳回
                    </button>
                </div>
            </div>
        `;
    },

    async toggleContent(taskId) {
        if (this._expandedTaskId === taskId) {
            this._expandedTaskId = null;
            this.refresh();
            return;
        }
        
        this._expandedTaskId = taskId;
        this.refresh();
        
        // 加载内容
        await this._loadReviewContent(taskId);
    },

    async _loadReviewContent(taskId) {
        const bodyEl = document.getElementById(`reviewContentBody_${taskId}`);
        if (!bodyEl) return;
        
        try {
            // 获取任务文件列表
            const data = await Api.get(`/api/tasks/${taskId}/files`);
            const files = data.files || [];
            
            if (files.length === 0) {
                bodyEl.innerHTML = '<p class="text-gray-400 text-sm">暂无生成文件</p>';
                return;
            }
            
            // 找到最新的md文件（通常是待审核的内容）
            const mdFiles = files.filter(f => f.name.endsWith('.md') || f.name.endsWith('.txt'))
                .sort((a, b) => new Date(b.modified_at) - new Date(a.modified_at));
            
            if (mdFiles.length === 0) {
                bodyEl.innerHTML = '<p class="text-gray-400 text-sm">暂无文本文件</p>';
                return;
            }
            
            // 显示文件列表和最新文件内容
            let html = '<div class="mb-3 flex gap-2 flex-wrap">';
            mdFiles.forEach(f => {
                html += `<button onclick="Reviews.loadFileContent('${UI.escapeAttr(taskId)}', '${UI.escapeAttr(f.name)}')" 
                    class="btn btn-outline btn-xs text-xs">${UI.escapeHtml(f.name)}</button>`;
            });
            html += '</div>';
            html += '<div id="reviewFileContent" class="bg-white p-4 rounded border text-sm whitespace-pre-wrap break-words max-h-72 overflow-y-auto">加载中...</div>';
            bodyEl.innerHTML = html;
            
            // 自动加载最新文件
            await this.loadFileContent(taskId, mdFiles[0].name);
        } catch (e) {
            bodyEl.innerHTML = `<p class="text-red-400 text-sm">加载失败: ${UI.escapeHtml(e.message)}</p>`;
        }
    },

    async loadFileContent(taskId, filename) {
        const contentEl = document.getElementById('reviewFileContent');
        if (!contentEl) return;
        
        contentEl.textContent = '加载中...';
        
        try {
            const response = await fetch(`/api/tasks/${taskId}/files/${encodeURIComponent(filename)}`);
            if (response.ok) {
                const text = await response.text();
                contentEl.textContent = text;
            } else {
                contentEl.textContent = '加载失败: ' + response.status;
            }
        } catch (e) {
            contentEl.textContent = '加载失败: ' + e.message;
        }
    },

    async submit(taskId, decision) {
        try {
            await Api.post(`/api/tasks/${taskId}/review`, { decision });
            UI.showToast('✅ 审核已提交', 'success');
            UI.addLog(`📋 任务 ${taskId} 审核: ${decision}`, 'info');
            this._expandedTaskId = null;
            this.refresh();
            Tasks.refresh();
        } catch (e) {
            UI.showToast('❌ 提交失败: ' + e.message, 'error');
        }
    }
};
