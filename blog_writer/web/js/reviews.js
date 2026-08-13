/**
 * 人工审核管理
 */

const Reviews = {
    async refresh() {
        try {
            const data = await Api.get('/api/tasks/reviews/pending');
            const list = document.getElementById('reviewList');
            
            if (!data.reviews || data.reviews.length === 0) {
                list.innerHTML = '<p class="text-gray-500 text-center py-8">暂无待审核任务 🎉</p>';
                return;
            }

            list.innerHTML = data.reviews.map(r => `
                <div class="border rounded-xl p-5 card-hover">
                    <div class="flex justify-between items-start mb-4">
                        <div>
                            <h3 class="font-bold text-gray-800">${r.keywords || '未知任务'}</h3>
                            <p class="text-sm text-gray-500 mt-1">任务ID: ${r.task_id}</p>
                            <p class="text-sm text-gray-500">审核节点: ${r.node_name}</p>
                        </div>
                        <span class="px-3 py-1 bg-yellow-100 text-yellow-700 rounded-full text-sm">👁️ 待审核</span>
                    </div>
                    <div class="flex gap-3">
                        <button onclick="Reviews.submit('${r.task_id}', 'approve')" 
                            class="flex-1 bg-green-500 text-white py-2 rounded-lg hover:bg-green-600">
                            ✅ 通过
                        </button>
                        <button onclick="Reviews.submit('${r.task_id}', 'modify')" 
                            class="flex-1 bg-yellow-500 text-white py-2 rounded-lg hover:bg-yellow-600">
                            ✏️ 修改后通过
                        </button>
                        <button onclick="Reviews.submit('${r.task_id}', 'reject')" 
                            class="flex-1 bg-red-500 text-white py-2 rounded-lg hover:bg-red-600">
                            ❌ 驳回
                        </button>
                    </div>
                </div>
            `).join('');
        } catch (e) {
            console.error('Refresh reviews error:', e);
        }
    },

    async submit(taskId, decision) {
        try {
            await Api.post(`/api/tasks/${taskId}/review`, { decision });
            UI.showToast('✅ 审核已提交', 'success');
            UI.addLog(`📋 任务 ${taskId} 审核: ${decision}`, 'info');
            this.refresh();
            Tasks.refresh();
        } catch (e) {
            UI.showToast('❌ 提交失败: ' + e.message, 'error');
        }
    }
};
