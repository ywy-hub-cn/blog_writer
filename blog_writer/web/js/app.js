/**
 * 应用入口 - 初始化和事件绑定
 */

const App = {
    init() {
        Auth.init();
        this._bindEvents();
        this._startPolling();
        this._checkSystem();
        
        IframeBridge.ready();
        
        UI.addLog('🚀 Blog-Writer AI 工作流系统已启动', 'info');
        UI.addLog(`📱 运行模式: ${IframeBridge.isEmbedded ? '嵌入模式' : '独立模式'}`, 'sys');
        
        Tasks.refresh();
        Stats.update();
        Brands.load();
        if (typeof updateUserNoteCount === 'function') updateUserNoteCount();
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
        // 任务列表轮询（15秒，避免触发服务端限流 10/60s；有运行中任务时由 poll() 高频更新）
        State.addTimer(() => Tasks.refresh(), 15000);
        // 统计数据轮询（15秒，未登录时从任务列表计算）
        State.addTimer(() => Stats.update(), 15000);
        // 系统状态检查
        State.addTimer(() => this._checkSystem(), 60000);
    },

    async _checkSystem() {
        try {
            const resp = await fetch('/health');
            const json = await resp.json();
            const raw = (json && json.data) ? json.data : json;
            const data = (typeof Api !== 'undefined' && Api._normalizeData)
                ? Api._normalizeData(raw)
                : raw;
            State.taskAuthRequired = !!(data.task_auth_required ?? data.taskAuthRequired);

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

            if (State.taskAuthRequired && typeof Auth !== 'undefined' && !Auth.isLoggedIn()) {
                Auth.showLoginHint('外部对接模式：启动任务需 API Token 或登录');
            } else if (typeof Auth !== 'undefined') {
                Auth.hideLoginHint();
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
function updateUserNoteCount() {
    const note = document.getElementById('userNote')?.value || '';
    const countEl = document.getElementById('userNoteCount');
    if (countEl) countEl.textContent = `${[...note].length} 字`;
}

function openStartConfirmModal() {
    const brandPath = Brands.getSelectedPath();
    if (!brandPath) {
        UI.showToast('请先选择品牌', 'warn');
        return;
    }
    const keywords = (document.getElementById('keywords')?.value || '').trim();
    if (!keywords) {
        UI.showToast('请输入关键词', 'warn');
        return;
    }
    const siteUrl = (document.getElementById('brandSiteUrl')?.value || '').trim();
    if (siteUrl && !/^https?:\/\/.+/i.test(siteUrl)) {
        UI.showToast('品牌官网地址需以 http:// 或 https:// 开头', 'warn');
        return;
    }
    const note = document.getElementById('userNote')?.value || '';
    const brandSelect = document.getElementById('brandSelect');
    const brandLabel = brandSelect?.selectedOptions?.[0]?.textContent?.trim() || brandPath;
    document.getElementById('startConfirmBrand').textContent = brandLabel;
    document.getElementById('startConfirmKeywords').textContent = keywords;
    document.getElementById('startConfirmSiteUrl').textContent = siteUrl || '（未填写）';
    document.getElementById('startConfirmNote').textContent = note.trim() ? note : '（未填写）';
    document.getElementById('startConfirmNoteCount').textContent = `${[...note].length} 字`;
    const modal = document.getElementById('startConfirmModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function closeStartConfirmModal() {
    const modal = document.getElementById('startConfirmModal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}

function confirmStartTask() {
    closeStartConfirmModal();
    const brandPath = Brands.getSelectedPath();
    const temperature = document.getElementById('temperature')?.value;
    const maxTokens = document.getElementById('maxTokens')?.value;
    const priority = document.getElementById('taskPriority')?.value || '2';
    const visualMode = document.getElementById('visualMode')?.value || 'relaxed';
    const enableSchedule = document.getElementById('enableSchedule')?.checked || false;
    const scheduledVal = document.getElementById('scheduledAt')?.value || '';
    let scheduledAt = null;
    if (enableSchedule) {
        if (!scheduledVal) {
            UI.showToast('请选择定时启动时间', 'warn');
            return;
        }
        const d = new Date(scheduledVal);
        if (isNaN(d.getTime())) {
            UI.showToast('定时时间格式无效', 'warn');
            return;
        }
        if (d.getTime() <= Date.now()) {
            UI.showToast('定时时间必须晚于当前时间', 'warn');
            return;
        }
        scheduledAt = d.toISOString();
    }
    Tasks.start(
        brandPath,
        document.getElementById('keywords').value,
        document.getElementById('userNote').value,
        document.getElementById('runMode').value,
        document.getElementById('forbiddenWhitelist')?.value || '',
        document.getElementById('aiModel')?.value || 'default',
        temperature ? parseFloat(temperature) : undefined,
        maxTokens ? parseInt(maxTokens) : undefined,
        parseInt(priority),
        document.getElementById('brandSiteUrl')?.value || '',
        visualMode,
        scheduledAt
    );
}

function startTask() {
    openStartConfirmModal();
}
function toggleScheduleInput() {
    const checked = document.getElementById('enableSchedule')?.checked || false;
    const group = document.getElementById('scheduleInputGroup');
    if (group) {
        group.classList.toggle('hidden', !checked);
    }
    if (!checked) {
        const el = document.getElementById('scheduledAt');
        if (el) el.value = '';
    }
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
