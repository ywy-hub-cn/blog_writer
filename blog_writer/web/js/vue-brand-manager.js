/**
 * 品牌管理 - Vue3 组件化实现
 *
 * 这是前端 Vue3 迁移的示范组件，展示：
 * 1. 响应式状态管理（替代全局对象 + 手动 DOM 操作）
 * 2. 模板语法自动 HTML 转义（消除 XSS 风险）
 * 3. 组件化结构（可复用、可维护）
 * 4. 生命周期钩子（替代手动 init 调用）
 *
 * 挂载点：#brand-manager-app
 */

// 注意：Vue 解构放在函数内部，避免 Vue 加载失败时影响整个页面
let _vueReady = false;
let _createApp, _ref, _computed, _onMounted;

function _ensureVue() {
    if (_vueReady) return true;
    if (typeof Vue === 'undefined') {
        console.error('[VueBrandManager] Vue 未加载');
        return false;
    }
    try {
        _createApp = Vue.createApp;
        _ref = Vue.ref;
        _computed = Vue.computed;
        _onMounted = Vue.onMounted;
        _vueReady = true;
        console.log('[VueBrandManager] Vue 初始化成功');
        return true;
    } catch (e) {
        console.error('[VueBrandManager] Vue 初始化失败:', e);
        return false;
    }
}

function buildBrandManagerApp() {
    return {
        setup() {
            // ========== 响应式状态 ==========
            const brands = _ref([]);
            const loading = _ref(false);
            const error = _ref('');

            // 文件详情弹窗
            const showFilesModal = _ref(false);
            const currentBrandFiles = _ref([]);
            const currentBrandName = _ref('');

            // 重命名弹窗
            const showRenameModal = _ref(false);
            const renameInput = _ref('');
            const renameBrandId = _ref('');
            const renameOriginalName = _ref('');

            // ========== 计算属性 ==========
            const totalBrands = _computed(() => brands.value.length);
            const totalFiles = _computed(() =>
                brands.value.reduce((sum, b) => sum + (b.file_count || 0), 0)
            );

            // ========== 方法 ==========
            async function loadBrands() {
                loading.value = true;
                error.value = '';
                try {
                    const data = await Api.get('/api/brands?verbose=true');
                    brands.value = data.brands || [];
                    console.log('[VueBrandManager] 加载品牌列表成功:', brands.value.length);
                } catch (e) {
                    error.value = e.message || '加载失败';
                    console.error('[VueBrandManager] 加载品牌列表失败:', e);
                } finally {
                    loading.value = false;
                }
            }

            async function viewFiles(brandId, displayName) {
                currentBrandName.value = displayName;
                showFilesModal.value = true;
                currentBrandFiles.value = [];
                try {
                    const data = await Api.get(`/api/brands/${brandId}/files`);
                    currentBrandFiles.value = data.files || [];
                } catch (e) {
                    console.error('[VueBrandManager] 加载文件列表失败:', e);
                }
            }

            function closeFilesModal() {
                showFilesModal.value = false;
                currentBrandFiles.value = [];
            }

            function openRenameModal(brandId, displayName) {
                renameBrandId.value = brandId;
                renameOriginalName.value = displayName;
                renameInput.value = displayName;
                showRenameModal.value = true;
            }

            function closeRenameModal() {
                showRenameModal.value = false;
                renameInput.value = '';
                renameBrandId.value = '';
            }

            async function confirmRename() {
                const newName = renameInput.value.trim();
                if (!newName) {
                    alert('品牌名称不能为空');
                    return;
                }
                if (newName === renameOriginalName.value) {
                    closeRenameModal();
                    return;
                }
                try {
                    const formData = new FormData();
                    formData.append('display_name', newName);
                    await Api.put(`/api/brands/${renameBrandId.value}`, formData);
                    closeRenameModal();
                    await loadBrands();
                    if (typeof Brands !== 'undefined' && Brands.load) {
                        Brands.load();
                    }
                    UI.addLog(`✅ 品牌已重命名: ${renameOriginalName.value} → ${newName}`, 'info');
                } catch (e) {
                    alert(`重命名失败: ${e.message || e}`);
                }
            }

            async function deleteBrand(brandId, displayName) {
                if (!confirm(`确定要删除品牌「${displayName}」吗？\n\n此操作不可恢复，品牌目录和所有文件将被永久删除。\n已使用该品牌创建的任务不受影响。`)) {
                    return;
                }
                try {
                    await Api.delete(`/api/brands/${brandId}`);
                    await loadBrands();
                    if (typeof Brands !== 'undefined' && Brands.load) {
                        Brands.load();
                    }
                    UI.addLog(`🗑️ 品牌已删除: ${displayName}`, 'warn');
                } catch (e) {
                    alert(`删除失败: ${e.message || e}`);
                }
            }

            function openUploadModal() {
                if (typeof Brands !== 'undefined' && Brands.openUploadModal) {
                    Brands.openUploadModal();
                }
            }

            // 工具函数
            function formatSize(bytes) {
                if (!bytes) return '0 B';
                const k = 1024;
                const sizes = ['B', 'KB', 'MB', 'GB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
            }

            function formatDate(dateStr) {
                if (!dateStr) return '-';
                try {
                    return new Date(dateStr).toLocaleString('zh-CN', {
                        year: 'numeric', month: '2-digit', day: '2-digit',
                        hour: '2-digit', minute: '2-digit'
                    });
                } catch {
                    return dateStr;
                }
            }

            // ========== 生命周期 ==========
            _onMounted(() => {
                loadBrands();
            });

            return {
                brands, loading, error,
                showFilesModal, currentBrandFiles, currentBrandName,
                showRenameModal, renameInput,
                totalBrands, totalFiles,
                loadBrands, viewFiles, closeFilesModal,
                openRenameModal, closeRenameModal, confirmRename,
                deleteBrand, openUploadModal,
                formatSize, formatDate,
            };
        },
        template: `
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">📦 品牌管理</h3>
                    <div class="flex items-center gap-3">
                        <span class="text-xs text-gray-500">共 {{ totalBrands }} 个品牌 / {{ totalFiles }} 个文件</span>
                        <button @click="openUploadModal" class="btn btn-primary btn-sm">+ 上传新品牌</button>
                    </div>
                </div>

                <div v-if="loading" class="text-center py-8">
                    <p class="text-gray-400 text-sm">加载中...</p>
                </div>

                <div v-else-if="error" class="text-center py-8">
                    <p class="text-red-400 text-sm">{{ error }}</p>
                    <button @click="loadBrands" class="btn btn-outline btn-sm mt-2">重试</button>
                </div>

                <div v-else-if="brands.length === 0" class="text-center py-8">
                    <p class="text-gray-400 text-sm">暂无品牌，点击右上角「上传新品牌」</p>
                </div>

                <div v-else class="space-y-3">
                    <div v-for="brand in brands" :key="brand.brand_id"
                         class="border rounded-lg p-4 hover:border-blue-300 transition-colors">
                        <div class="flex justify-between items-start">
                            <div class="flex-1 min-w-0">
                                <div class="font-medium text-gray-800 truncate">{{ brand.display_name }}</div>
                                <div class="text-xs text-gray-500 mt-1 font-mono">{{ brand.brand_id }}</div>
                                <div class="flex gap-4 mt-2 text-xs text-gray-500">
                                    <span>📄 {{ brand.file_count || 0 }} 个文件</span>
                                    <span>💾 {{ formatSize(brand.total_size) }}</span>
                                    <span>🕐 {{ formatDate(brand.updated_at) }}</span>
                                </div>
                            </div>
                            <div class="flex gap-2 ml-4 flex-shrink-0">
                                <button @click="viewFiles(brand.brand_id, brand.display_name)"
                                        class="btn btn-outline btn-sm" title="查看文件">
                                    📂 文件
                                </button>
                                <button @click="openRenameModal(brand.brand_id, brand.display_name)"
                                        class="btn btn-outline btn-sm" title="重命名">
                                    ✏️
                                </button>
                                <button @click="deleteBrand(brand.brand_id, brand.display_name)"
                                        class="btn btn-outline btn-sm text-red-600 hover:bg-red-50" title="删除">
                                    🗑️
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div v-if="showFilesModal" class="modal" style="display: flex;">
                <div class="modal-content max-w-2xl">
                    <div class="modal-header">
                        <h3 class="text-lg font-semibold">{{ currentBrandName }} - 文件列表</h3>
                        <button @click="closeFilesModal" class="text-gray-400 hover:text-gray-600 text-2xl">&times;</button>
                    </div>
                    <div class="space-y-2 max-h-96 overflow-y-auto">
                        <p v-if="currentBrandFiles.length === 0" class="text-gray-400 text-center py-4">该品牌暂无文件</p>
                        <div v-for="file in currentBrandFiles" :key="file.name"
                             class="flex justify-between items-center p-3 bg-gray-50 rounded">
                            <div class="flex-1 min-w-0">
                                <div class="text-sm font-medium text-gray-700 truncate">{{ file.name }}</div>
                                <div class="text-xs text-gray-500 mt-1">{{ formatSize(file.size) }} · {{ formatDate(file.modified_at) }}</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div v-if="showRenameModal" class="modal" style="display: flex;">
                <div class="modal-content max-w-md">
                    <div class="modal-header">
                        <h3 class="text-lg font-semibold">重命名品牌</h3>
                        <button @click="closeRenameModal" class="text-gray-400 hover:text-gray-600 text-2xl">&times;</button>
                    </div>
                    <div class="space-y-4">
                        <div>
                            <label class="form-label">品牌显示名称</label>
                            <input v-model="renameInput" type="text" class="form-input"
                                   placeholder="输入新的品牌名称" @keyup.enter="confirmRename">
                        </div>
                        <p class="text-xs text-gray-500">注意：只修改显示名称，品牌ID和目录名不变。</p>
                        <div class="flex justify-end gap-2">
                            <button @click="closeRenameModal" class="btn btn-outline">取消</button>
                            <button @click="confirmRename" class="btn btn-primary">确认</button>
                        </div>
                    </div>
                </div>
            </div>
        `
    };
}

// 挂载 Vue 应用
function mountBrandManager() {
    console.log('[VueBrandManager] mountBrandManager 被调用');

    if (!_ensureVue()) {
        console.error('[VueBrandManager] Vue 未就绪，无法挂载');
        // 后备方案：显示原生JS版本
        const mountPoint = document.getElementById('brand-manager-app');
        if (mountPoint) {
            mountPoint.innerHTML = '<p class="text-gray-400 text-center py-8">Vue 未加载，请刷新页面重试</p>';
        }
        return;
    }

    const mountPoint = document.getElementById('brand-manager-app');
    if (!mountPoint) {
        console.error('[VueBrandManager] 找不到挂载点 #brand-manager-app');
        return;
    }

    if (mountPoint.__vue_app__) {
        console.log('[VueBrandManager] 已挂载，跳过');
        return;
    }

    try {
        const app = _createApp(buildBrandManagerApp());
        app.mount('#brand-manager-app');
        mountPoint.__vue_app__ = app;
        console.log('[VueBrandManager] 挂载成功');
    } catch (e) {
        console.error('[VueBrandManager] 挂载失败:', e);
        mountPoint.innerHTML = '<p class="text-red-400 text-center py-8">组件加载失败: ' + e.message + '</p>';
    }
}

// 暴露全局方法供 Tab 切换时调用
window.VueBrandManager = {
    mount: mountBrandManager,
    reload: () => {
        const mountPoint = document.getElementById('brand-manager-app');
        if (mountPoint && mountPoint.__vue_app__) {
            mountPoint.dispatchEvent(new CustomEvent('vue-reload'));
        }
    }
};

console.log('[VueBrandManager] 脚本加载完成');

// 自动尝试挂载（DOM已就绪，因为脚本在body末尾）
// 暂时禁用，使用原生JS版本
/*
try {
    if (document.getElementById('brand-manager-app')) {
        console.log('[VueBrandManager] 找到挂载点，自动挂载');
        mountBrandManager();
    } else {
        console.log('[VueBrandManager] 未找到挂载点，等待Tab切换');
    }
} catch (e) {
    console.error('[VueBrandManager] 自动挂载失败:', e);
}
*/
