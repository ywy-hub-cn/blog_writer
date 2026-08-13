/**
 * 品牌管理 - 品牌列表、文件查看、重命名、删除
 */

const BrandManager = {
    _currentBrandId: null,
    _currentDisplayName: null,

    /**
     * 加载品牌管理列表（详细模式）
     */
    async load() {
        try {
            const data = await Api.get('/api/brands?verbose=true');
            const list = document.getElementById('brandManagerList');

            if (!data.brands || data.brands.length === 0) {
                list.innerHTML = '<p class="text-gray-400 text-center py-8 text-sm">暂无品牌，点击右上角「上传新品牌」</p>';
                return;
            }

            const html = data.brands.map(b => `
                <div class="border rounded-lg p-4 hover:border-blue-300 transition-colors">
                    <div class="flex justify-between items-start">
                        <div class="flex-1 min-w-0">
                            <div class="font-medium text-gray-800 truncate">${this._escape(b.display_name)}</div>
                            <div class="text-xs text-gray-500 mt-1 font-mono">${this._escape(b.brand_id)}</div>
                            <div class="flex gap-4 mt-2 text-xs text-gray-500">
                                <span>📄 ${b.file_count || 0} 个文件</span>
                                <span>💾 ${this._formatSize(b.total_size || 0)}</span>
                                <span>🕐 ${this._formatDate(b.updated_at)}</span>
                            </div>
                        </div>
                        <div class="flex gap-2 ml-4 flex-shrink-0">
                            <button onclick="BrandManager.viewFiles('${b.brand_id}', '${this._escapeAttr(b.display_name)}')"
                                    class="btn btn-outline btn-sm" title="查看文件">
                                📂 文件
                            </button>
                            <button onclick="BrandManager.openRenameModal('${b.brand_id}', '${this._escapeAttr(b.display_name)}')"
                                    class="btn btn-outline btn-sm" title="重命名">
                                ✏️
                            </button>
                            <button onclick="BrandManager.deleteBrand('${b.brand_id}', '${this._escapeAttr(b.display_name)}')"
                                    class="btn btn-outline btn-sm text-red-600 hover:bg-red-50" title="删除">
                                🗑️
                            </button>
                        </div>
                    </div>
                </div>
            `).join('');
            list.innerHTML = html;
        } catch (e) {
            console.error('加载品牌列表失败:', e);
            const list = document.getElementById('brandManagerList');
            if (list) list.innerHTML = '<p class="text-red-400 text-center py-8 text-sm">加载失败，请刷新重试</p>';
        }
    },

    /**
     * 查看品牌文件列表
     */
    async viewFiles(brandId, displayName) {
        this._currentBrandId = brandId;
        document.getElementById('brandFilesTitle').textContent = `${displayName} - 文件列表`;
        document.getElementById('brandFilesModal').classList.remove('hidden');
        document.getElementById('brandFilesModal').classList.add('flex');

        const fileList = document.getElementById('brandFilesList');
        fileList.innerHTML = '<p class="text-gray-400 text-center py-4">加载中...</p>';

        try {
            const data = await Api.get(`/api/brands/${brandId}/files`);

            if (!data.files || data.files.length === 0) {
                fileList.innerHTML = '<p class="text-gray-400 text-center py-4">该品牌暂无文件</p>';
                return;
            }

            fileList.innerHTML = data.files.map(f => `
                <div class="flex justify-between items-center p-3 bg-gray-50 rounded">
                    <div class="flex-1 min-w-0">
                        <div class="text-sm font-medium text-gray-700 truncate">${this._escape(f.name)}</div>
                        <div class="text-xs text-gray-500 mt-1">${this._formatSize(f.size)} · ${this._formatDate(f.modified_at)}</div>
                    </div>
                </div>
            `).join('');
        } catch (e) {
            console.error('加载文件列表失败:', e);
            fileList.innerHTML = '<p class="text-red-400 text-center py-4">加载失败</p>';
        }
    },

    closeFilesModal() {
        document.getElementById('brandFilesModal').classList.add('hidden');
        document.getElementById('brandFilesModal').classList.remove('flex');
    },

    /**
     * 重命名品牌
     */
    openRenameModal(brandId, displayName) {
        this._currentBrandId = brandId;
        this._currentDisplayName = displayName;
        document.getElementById('brandRenameInput').value = displayName;
        document.getElementById('brandRenameModal').classList.remove('hidden');
        document.getElementById('brandRenameModal').classList.add('flex');
        setTimeout(() => document.getElementById('brandRenameInput').focus(), 100);
    },

    closeRenameModal() {
        document.getElementById('brandRenameModal').classList.add('hidden');
        document.getElementById('brandRenameModal').classList.remove('flex');
        this._currentBrandId = null;
    },

    async confirmRename() {
        const newName = document.getElementById('brandRenameInput').value.trim();
        if (!newName) {
            alert('品牌名称不能为空');
            return;
        }
        if (newName === this._currentDisplayName) {
            this.closeRenameModal();
            return;
        }

        try {
            const formData = new FormData();
            formData.append('display_name', newName);
            await Api.put(`/api/brands/${this._currentBrandId}`, formData);
            this.closeRenameModal();
            await this.load();
            // 同步刷新任务页面的品牌下拉
            if (typeof Brands !== 'undefined' && Brands.load) {
                Brands.load();
            }
            UI.addLog(`✅ 品牌已重命名: ${this._currentDisplayName} → ${newName}`, 'info');
        } catch (e) {
            console.error('重命名失败:', e);
            alert(`重命名失败: ${e.message || e}`);
        }
    },

    /**
     * 删除品牌
     */
    async deleteBrand(brandId, displayName) {
        if (!confirm(`确定要删除品牌「${displayName}」吗？\n\n此操作不可恢复，品牌目录和所有文件将被永久删除。\n已使用该品牌创建的任务不受影响。`)) {
            return;
        }

        try {
            await Api.delete(`/api/brands/${brandId}`);
            await this.load();
            // 同步刷新任务页面的品牌下拉
            if (typeof Brands !== 'undefined' && Brands.load) {
                Brands.load();
            }
            UI.addLog(`🗑️ 品牌已删除: ${displayName}`, 'warn');
        } catch (e) {
            console.error('删除失败:', e);
            alert(`删除失败: ${e.message || e}`);
        }
    },

    // ========== 工具函数 ==========

    _escape(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    _escapeAttr(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    },

    _formatSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    },

    _formatDate(dateStr) {
        if (!dateStr) return '-';
        try {
            const d = new Date(dateStr);
            return d.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch {
            return dateStr;
        }
    }
};
