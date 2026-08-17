/**
 * 应用入口 - 初始化和事件绑定
 */

const App = {
    init() {
        Auth.init();
        this._bindEvents();
        this._startPolling();
        
        IframeBridge.ready();
        
        UI.addLog('🚀 Blog-Writer AI 工作流系统已启动', 'info');
        UI.addLog(`📱 运行模式: ${IframeBridge.isEmbedded ? '嵌入模式' : '独立模式'}`, 'sys');
        
        Tasks.refresh();
        Stats.update();
        Brands.load();
    },

    _bindEvents() {
        // 键盘支持
        const pwd = document.getElementById('adminPassword');
        if (pwd) {
            pwd.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') Auth.login(pwd.value);
            });
        }

        // iframe SSO 事件监听已在 IframeBridge.init() 中完成
        document.addEventListener('config:external-update', (e) => {
            UI.addLog('🔄 配置已由父页面更新', 'sys');
            if (Auth.isLoggedIn()) {
                Config.load();
            }
        });
    },

    _startPolling() {
        // 任务列表轮询（5秒，状态更新更及时）
        State.addTimer(() => Tasks.refresh(), 5000);
        // 统计数据轮询（15秒，未登录时从任务列表计算）
        State.addTimer(() => Stats.update(), 15000);
        // 系统状态检查
        State.addTimer(() => this._checkSystem(), 60000);
    },

    async _checkSystem() {
        try {
            const resp = await fetch('/health');
            const data = await resp.json();
            const statusEl = document.querySelector('#systemStatus span:last-child');
            const dot = document.querySelector('#systemStatus span:first-child');
            
            if (data.status === 'healthy') {
                if (dot) dot.className = 'w-2 h-2 bg-green-500 rounded-full status-running';
                if (statusEl) statusEl.textContent = '系统运行中';
            } else if (data.status === 'degraded') {
                if (dot) dot.className = 'w-2 h-2 bg-yellow-500 rounded-full status-running';
                if (statusEl) statusEl.textContent = '系统降级';
            } else {
                if (dot) dot.className = 'w-2 h-2 bg-red-500 rounded-full';
                if (statusEl) statusEl.textContent = '系统异常';
            }
        } catch (e) {
            console.error('Health check failed:', e);
        }
    }
};

// 全局函数桥接 - 保持 onclick 兼容性
function openLoginModal() { Auth.openLoginModal(); }
function closeLoginModal() { Auth.closeLoginModal(); }
function doLogin() {
    const pwd = document.getElementById('adminPassword');
    const err = document.getElementById('loginError');
    if (!pwd || !pwd.value) {
        if (err) {
            err.textContent = '请输入密码';
            err.style.display = 'block';
        }
        return;
    }
    Auth.login(pwd.value).then((success) => {
        if (!success) {
            if (err) {
                err.textContent = '密码错误，请重试';
                err.style.display = 'block';
            }
        } else {
            // 登录成功后重新加载需要鉴权的数据
            Brands.load();
            Tasks.refresh();
            Stats.update();
        }
    });
}
function doLogout() { Auth.logout(); }
function switchTab(tab) { Tabs.switch(tab); }
function startTask() {
    const brandPath = Brands.getSelectedPath();
    if (!brandPath) {
        UI.showToast('请先选择品牌', 'warn');
        return;
    }
    const temperature = document.getElementById('temperature')?.value;
    const maxTokens = document.getElementById('maxTokens')?.value;
    const priority = document.getElementById('taskPriority')?.value || '2';
    Tasks.start(
        brandPath,
        document.getElementById('keywords').value,
        document.getElementById('userNote').value,
        document.getElementById('runMode').value,
        document.getElementById('forbiddenWhitelist')?.value || '',
        document.getElementById('aiModel')?.value || 'default',
        temperature ? parseFloat(temperature) : undefined,
        maxTokens ? parseInt(maxTokens) : undefined,
        parseInt(priority)
    );
}
function refreshTasks() { Tasks.refresh(); }
function showTaskDetail(id) { Tasks.showDetail(id); }
function refreshReviews() { Reviews.refresh(); }
function submitReview(taskId, decision) { Reviews.submit(taskId, decision); }
function loadNodes() { Nodes.load(); }
function selectNode(filename) { Nodes.select(filename); }
function saveNode() { Nodes.save(); }
function validateNode() { Nodes.validate(); }
function deleteNode() { Nodes.delete(); }
function createNewNode() { Nodes.createNew(); }
function loadConfig() { Config.load(); }
function saveLLMConfig() { Config.saveLLM(); }
function saveWorkflowConfig() { Config.saveWorkflow(); }
async function saveConcurrencyConfig() {
    const n = parseInt(document.getElementById('maxConcurrentTasks').value);
    if (!n || n < 1 || n > 20) {
        UI.showToast('并发数必须在1-20之间', 'warn');
        return;
    }
    try {
        await Api.put('/api/tasks/concurrency', { max_concurrent: n });
        UI.showToast(`✅ 最大并发数已调整为 ${n}`, 'success');
        Tasks.refresh();
    } catch (e) {
        UI.showToast('❌ 调整失败: ' + e.message, 'error');
    }
}
function testLLMConnection() { Config.testLLM(); }
function downloadLogs() { UI.downloadLogs(); }
function clearLogs() { UI.clearLogs(); }

// DOM 加载完成后启动
document.addEventListener('DOMContentLoaded', () => App.init());
