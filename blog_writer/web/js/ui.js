/**
 * 全局状态
 */

const State = {
    currentTab: 'run',
    currentNodeId: null,
    apiKeyVisible: false,
    pollingTimers: [],
    taskAuthRequired: false,

    addTimer(fn, delay) {
        const id = setInterval(fn, delay);
        this.pollingTimers.push(id);
        return id;
    },

    clearAllTimers() {
        this.pollingTimers.forEach(id => clearInterval(id));
        this.pollingTimers = [];
    }
};

/**
 * Tab 切换管理
 */
const Tabs = {
    _order: ['run', 'review', 'brands', 'nodes', 'config'],

    switch(tab) {
        // 管理Tab需要权限
        if ((tab === 'nodes' || tab === 'config') && !Auth.isLoggedIn()) {
            Auth.openLoginModal();
            return;
        }

        State.currentTab = tab;
        
        this._order.forEach(t => {
            const btn = document.getElementById(`tab-${t}`);
            const content = document.getElementById(`content-${t}`);
            if (!btn || !content) return;
            
            if (t === tab) {
                btn.classList.add('active');
                content.classList.remove('hidden');
            } else {
                btn.classList.remove('active');
                content.classList.add('hidden');
            }
        });

        UI.addLog(`📑 切换到「${this._label(tab)}」`, 'step');
        
        // 懒加载Tab数据
        if (tab === 'nodes') Nodes.load();
        if (tab === 'review') Reviews.refresh();
        if (tab === 'config') Config.load();
        if (tab === 'brands') {
            // 品牌管理页面（优先使用原生JS版本，Vue3版本作为备选）
            if (typeof BrandManager !== 'undefined' && BrandManager.load) {
                BrandManager.load();
            } else if (window.VueBrandManager && window.VueBrandManager.mount) {
                window.VueBrandManager.mount();
            }
        }
    },

    _label(t) {
        return { run: '任务运行', review: '人工审核', brands: '品牌管理', nodes: '节点管理', config: '系统配置' }[t] || t;
    }
};

/**
 * UI 工具函数
 */
const UI = {
    _logBuffer: [],
    _maxLogs: 200,

    /**
     * HTML 转义（防止 XSS）
     * 用于 innerHTML 中的用户输入内容
     */
    escapeHtml(text) {
        if (text === null || text === undefined) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    },

    /**
     * HTML 属性转义（防止属性注入）
     * 用于 onclick、value 等属性中的用户输入
     */
    escapeAttr(text) {
        if (text === null || text === undefined) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    },

    addLog(message, type = 'info') {
        const logDiv = document.getElementById('logOutput');
        if (!logDiv) return;
        
        const colorMap = {
            info: 'text-green-400',
            warn: 'text-yellow-400',
            error: 'text-red-400',
            step: 'text-blue-400',
            sys: 'text-purple-400'
        };
        
        const div = document.createElement('div');
        div.className = colorMap[type] || 'text-green-400';
        const time = new Date().toLocaleTimeString();
        div.textContent = `[${time}] ${message}`;
        
        logDiv.appendChild(div);
        
        // 限制日志数量
        while (logDiv.children.length > this._maxLogs) {
            logDiv.removeChild(logDiv.firstChild);
        }
        
        logDiv.scrollTop = logDiv.scrollHeight;
        
        this._logBuffer.push({ time, message, type });
        if (this._logBuffer.length > this._maxLogs) {
            this._logBuffer.shift();
        }
    },

    clearLogs() {
        const logDiv = document.getElementById('logOutput');
        if (logDiv) logDiv.innerHTML = '<div class="text-gray-500">日志已清空</div>';
        this._logBuffer = [];
    },

    downloadLogs() {
        const content = this._logBuffer.map(l => `[${l.time}] ${l.message}`).join('\n');
        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `blog-writer-logs-${Date.now()}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    },

    showToast(message, type = 'info', duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `fixed top-4 right-4 toast toast-${type} z-50`;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    },

    confirm(message) {
        return window.confirm(message);
    },

    alert(message) {
        window.alert(message);
    },

    getStatusLabel(status) {
        return {
            'running': '运行中',
            'completed': '已完成',
            'completed_partial': '部分完成',
            'waiting_review': '待审核',
            'paused': '已暂停',
            'cancelled': '已取消',
            'rejected': '已驳回',
            'failed': '失败',
            'pending': '排队中',
            'queued': '排队中',
            'scheduled': '定时等待'
        }[status] || status;
    },

    getStatusColor(status) {
        return {
            'running': 'bg-blue-100 text-blue-700',
            'completed': 'bg-green-100 text-green-700',
            'completed_partial': 'bg-green-100 text-green-700',
            'waiting_review': 'bg-yellow-100 text-yellow-700',
            'paused': 'bg-gray-100 text-gray-700',
            'cancelled': 'bg-red-100 text-red-700',
            'rejected': 'bg-red-100 text-red-700',
            'failed': 'bg-red-100 text-red-700',
            'pending': 'bg-gray-100 text-gray-700',
            'queued': 'bg-orange-100 text-orange-700',
            'scheduled': 'bg-purple-100 text-purple-700'
        }[status] || 'bg-gray-100 text-gray-700';
    },

    getStatusIcon(status) {
        return {
            'running': '⏳', 'completed': '✅', 'completed_partial': '⚠️',
            'waiting_review': '👁️', 'paused': '⏸️',
            'cancelled': '❌', 'rejected': '🚫',
            'failed': '❌', 'pending': '⏳', 'queued': '🕐',
            'scheduled': '⏰'
        }[status] || '❓';
    },

    formatTokens(n) {
        if (!n) return '0';
        if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
        return n.toString();
    },

    estimateCost(tokens) {
        const cost = (tokens * 0.000002).toFixed(4);
        return `¥${cost}`;
    },

    formatDuration(seconds) {
        if (!seconds || seconds < 60) return `${Math.round(seconds)}s`;
        if (seconds < 3600) return `${Math.round(seconds / 60)}m ${Math.round(seconds % 60)}s`;
        return `${Math.round(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
    },

    formatSize(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB';
    }
};
