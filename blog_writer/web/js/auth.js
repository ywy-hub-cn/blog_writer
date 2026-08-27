/**
 * 认证管理
 * 支持本地JWT认证 + iframe SSO token注入
 */

const Auth = {
    _token: null,
    _expireAt: 0,

    init() {
        this._token = localStorage.getItem('adminToken');
        this._expireAt = parseInt(localStorage.getItem('tokenExpireAt') || '0');
        
        // 检查iframe SSO注入的token
        IframeBridge.init();
        
        if (IframeBridge.isEmbedded && !this.isLoggedIn()) {
            UI.showLoginHint('等待公司平台认证...');
        } else {
            this.applyUI();
        }
    },

    isLoggedIn() {
        return this._token && Date.now() < this._expireAt * 1000;
    },

    saveToken(token, expireAt) {
        this._token = token;
        this._expireAt = expireAt;
        localStorage.setItem('adminToken', token);
        localStorage.setItem('tokenExpireAt', expireAt.toString());
    },

    clearToken() {
        this._token = null;
        this._expireAt = 0;
        localStorage.removeItem('adminToken');
        localStorage.removeItem('tokenExpireAt');
    },

    getToken() {
        return this._token;
    },

    openLoginModal() {
        const modal = document.getElementById('loginModal');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        const err = document.getElementById('loginError');
        if (err) err.classList.add('hidden');
        const pwd = document.getElementById('adminPassword');
        if (pwd) {
            pwd.value = '';
            setTimeout(() => pwd.focus(), 100);
        }
    },

    closeLoginModal() {
        const modal = document.getElementById('loginModal');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    },

    async login(password) {
        const result = await Api.post('/api/auth/login', { password });
        if (result.success && result.token) {
            const expireAt = Math.floor(Date.now() / 1000) + (result.expires_in || 86400);
            this.saveToken(result.token, expireAt);
            this.applyUI();
            this.closeLoginModal();
            UI.addLog('✅ 管理员登录成功', 'info');
            return true;
        }
        return false;
    },

    async logout() {
        if (!this.isLoggedIn()) return true;
        try {
            await Api.post('/api/auth/logout', {});
        } catch (e) {
            console.warn('登出请求失败', e);
        }
        this.clearToken();
        this.applyUI();
        UI.addLog('👋 已退出登录', 'info');
        
        // 隐藏移动端统计栏
        const mobBar = document.getElementById('mobileStatsBar');
        if (mobBar) mobBar.style.display = 'none';
        
        // 通知父页面
        IframeBridge.notify('LOGOUT');
        return true;
    },

    applyUI() {
        const app = document.getElementById('app');
        const loginBtn = document.getElementById('adminLoginBtn');
        const adminUser = document.getElementById('adminUser');

        if (this.isLoggedIn()) {
            app.classList.add('admin-unlocked');
            loginBtn.classList.add('hidden');
            adminUser.classList.remove('hidden');
            adminUser.classList.add('flex');
        } else {
            app.classList.remove('admin-unlocked');
            if (loginBtn) loginBtn.classList.remove('hidden');
            if (adminUser) {
                adminUser.classList.add('hidden');
                adminUser.classList.remove('flex');
            }
            const current = State.currentTab;
            if (current === 'nodes' || current === 'config') {
                Tabs.switch('run');
            }
        }
    },

    showLoginHint(msg) {
        const hint = document.getElementById('loginHint');
        if (hint) {
            hint.textContent = msg;
            hint.style.display = 'block';
            hint.classList.remove('hidden');
        }
    },

    hideLoginHint() {
        const hint = document.getElementById('loginHint');
        if (hint) {
            hint.style.display = 'none';
            hint.classList.add('hidden');
        }
    }
};
