/**
 * 品牌管理 - 下拉列表加载、上传新品牌（支持多文件 / 文件夹上传）
 *
 * 设计要点：
 * - inner_path 仅保存在 JS 内存的 Map 中，不渲染到 DOM，避免向页面暴露内部磁盘路径
 * - 下拉框 option 的 value 为 display_name，提交任务时通过 Map 查取对应的 inner_path
 * - 支持两种上传方式：多选文件 / 选择整个文件夹（文件夹内所有 .md/.txt 递归收集）
 */
const Brands = {
    // display_name -> inner_path 映射（仅内存，不暴露到 DOM）
    _pathMap: {},

    /**
     * 加载品牌列表并渲染下拉框
     */
    async load() {
        try {
            const data = await Api.get('/api/brands');
            const brands = (data && data.brands) || [];

            this._pathMap = {};
            const select = document.getElementById('brandSelect');
            if (!select) return;

            // 保留当前选中值，刷新后尝试恢复
            const prevSelected = select.value;

            select.innerHTML = '<option value="">-- 请选择品牌 --</option>';

            brands.forEach(b => {
                if (!b || !b.display_name) return;
                this._pathMap[b.display_name] = b.inner_path;
                const opt = document.createElement('option');
                opt.value = b.display_name;
                opt.textContent = b.display_name;
                select.appendChild(opt);
            });

            // 恢复之前的选中（如果还存在）
            if (prevSelected && this._pathMap[prevSelected]) {
                select.value = prevSelected;
            }
        } catch (e) {
            // 列表接口为公开读取，正常不会 401；其他错误静默记录即可
            console.warn('加载品牌列表失败:', e);
        }
    },

    /**
     * 获取当前选中品牌的 inner_path（仅内存读取，不暴露到页面）
     */
    getSelectedPath() {
        const select = document.getElementById('brandSelect');
        if (!select || !select.value) return '';
        return this._pathMap[select.value] || '';
    },

    /**
     * 打开上传弹窗
     */
    openUploadModal() {
        const modal = document.getElementById('brandUploadModal');
        if (!modal) return;
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        // 重置表单
        const nameInput = document.getElementById('brandDisplayName');
        const fileInput = document.getElementById('brandFiles');
        const folderInput = document.getElementById('brandFolderFiles');
        const errorEl = document.getElementById('brandUploadError');
        const previewEl = document.getElementById('brandFilePreview');
        if (nameInput) nameInput.value = '';
        if (fileInput) fileInput.value = '';
        if (folderInput) folderInput.value = '';
        if (errorEl) { errorEl.style.display = 'none'; errorEl.textContent = ''; }
        if (previewEl) previewEl.textContent = '';
        // 聚焦名称输入框
        setTimeout(() => nameInput && nameInput.focus(), 100);
    },

    /**
     * 关闭上传弹窗
     */
    closeUploadModal() {
        const modal = document.getElementById('brandUploadModal');
        if (!modal) return;
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    },

    /**
     * 文件选择变化时更新预览
     */
    onFilesSelected() {
        this._updatePreview();
    },

    /**
     * 文件夹选择变化时更新预览
     */
    onFolderSelected() {
        this._updatePreview();
    },

    /**
     * 收集所有已选文件（多文件 input + 文件夹 input 合并）
     */
    _collectFiles() {
        const fileInput = document.getElementById('brandFiles');
        const folderInput = document.getElementById('brandFolderFiles');
        const files = [];
        if (fileInput && fileInput.files) {
            for (const f of fileInput.files) files.push(f);
        }
        if (folderInput && folderInput.files) {
            for (const f of folderInput.files) files.push(f);
        }
        return files;
    },

    /**
     * 更新已选文件预览
     */
    _updatePreview() {
        const previewEl = document.getElementById('brandFilePreview');
        if (!previewEl) return;
        const files = this._collectFiles();
        if (files.length === 0) {
            previewEl.textContent = '';
            return;
        }
        // 只显示前 10 个文件名，超出显示数量
        const names = files.slice(0, 10).map(f => {
            // 文件夹上传的文件有 webkitRelativePath，显示相对路径更清晰
            return f.webkitRelativePath || f.name;
        });
        const more = files.length > 10 ? `...等 ${files.length} 个文件` : '';
        previewEl.innerHTML = `已选 ${files.length} 个文件：<br>${names.join('<br>')}${more}`;
    },

    /**
     * 提交品牌上传
     */
    async upload() {
        const nameInput = document.getElementById('brandDisplayName');
        const errorEl = document.getElementById('brandUploadError');

        const displayName = (nameInput && nameInput.value || '').trim();
        const files = this._collectFiles();

        // 校验
        if (!displayName) {
            this._showError('请输入品牌显示名称');
            return;
        }
        if (files.length === 0) {
            this._showError('请至少选择一个品牌文档文件或文件夹');
            return;
        }

        // 前端预校验文件后缀和大小
        const allowedExt = ['.md', '.txt'];
        const maxSize = 10 * 1024 * 1024;
        for (const f of files) {
            const ext = '.' + (f.name.split('.').pop() || '').toLowerCase();
            if (!allowedExt.includes(ext)) {
                const label = f.webkitRelativePath || f.name;
                this._showError(`文件 ${label} 类型不允许，仅支持 .md / .txt`);
                return;
            }
            if (f.size > maxSize) {
                const label = f.webkitRelativePath || f.name;
                this._showError(`文件 ${label} 超过大小限制（单文件最大 10MB）`);
                return;
            }
        }

        // 构建 FormData
        const formData = new FormData();
        formData.append('display_name', displayName);
        for (const f of files) {
            formData.append('files', f);
        }

        try {
            UI.addLog(`📤 正在上传品牌资料: ${displayName}（${files.length} 个文件）`, 'info');
            const result = await Api.upload('/api/brands/upload', formData);

            UI.addLog(`✅ 品牌上传成功: ${displayName}（${result.brand_id}）`, 'info');

            // 关闭弹窗
            this.closeUploadModal();

            // 刷新下拉列表
            await this.load();

            // 自动选中新上传的品牌
            const select = document.getElementById('brandSelect');
            if (select && displayName) {
                select.value = displayName;
            }

            UI.showToast('品牌上传成功，已自动选中', 'success');
        } catch (e) {
            console.error('品牌上传失败:', e);
            const msg = e.message || '上传失败，请重试';

            // 未登录时自动唤起登录弹窗
            if (msg.includes('未提供认证') || msg.includes('Token无效') || msg.includes('登录已过期') || msg.includes('401')) {
                this._showError('请先登录后再上传品牌资料');
                UI.addLog('⚠️ 上传需要登录，正在打开登录窗口...', 'warn');
                setTimeout(() => {
                    this.closeUploadModal();
                    if (typeof openLoginModal === 'function') openLoginModal();
                }, 800);
                return;
            }

            this._showError(msg);
            UI.addLog(`❌ 品牌上传失败: ${msg}`, 'error');
        }
    },

    _showError(msg) {
        const errorEl = document.getElementById('brandUploadError');
        if (errorEl) {
            errorEl.textContent = msg;
            errorEl.style.display = 'block';
        }
    }
};
