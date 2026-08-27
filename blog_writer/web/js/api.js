/**
 * API 客户端抽象层
 * 所有HTTP请求统一入口，支持自动鉴权、错误处理、iframe通信
 */

const Api = {
    _baseUrl: '',
    
    setBaseUrl(url) {
        this._baseUrl = url || '';
    },

    _getToken() {
        const token = localStorage.getItem('adminToken');
        const expireAt = parseInt(localStorage.getItem('tokenExpireAt') || '0', 10);
        if (token && expireAt && Date.now() >= expireAt * 1000) {
            return null;
        }
        return token || null;
    },

    isAuthError(message) {
        const msg = String(message || '');
        return /未提供认证|Token无效|登录已过期|认证失败|401|403/.test(msg);
    },

    promptLogin(reason) {
        UI.showToast(reason || '请先登录后再操作', 'warn', 5000);
        UI.addLog(`⚠️ ${reason || '需要登录'}，正在打开登录窗口...`, 'warn');
        if (typeof Auth !== 'undefined' && Auth.openLoginModal) {
            setTimeout(() => Auth.openLoginModal(), 300);
        }
    },

    _buildHeaders(customHeaders = {}, isFormData = false) {
        // FormData 请求不设置 Content-Type，让浏览器自动添加带 boundary 的 multipart/form-data
        const headers = isFormData ? { ...customHeaders } : { 'Content-Type': 'application/json', ...customHeaders };
        const token = this._getToken();
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        return headers;
    },

    async request(endpoint, options = {}) {
        const url = this._baseUrl + endpoint;
        const isFormData = options.body instanceof FormData;
        const headers = this._buildHeaders(options.headers, isFormData);
        
        try {
            const response = await fetch(url, {
                headers,
                ...options,
                body: options.body ? (isFormData || typeof options.body === 'string' ? options.body : JSON.stringify(options.body)) : undefined
            });
            
            const text = await response.text();
            let json = null;
            try { json = text ? JSON.parse(text) : null; } catch {}

            if (response.status === 401) {
                Auth.clearToken();
                Auth.applyUI();
                const msg = (json && json.message) || '登录已过期，请重新登录';
                throw new Error(msg);
            }
            if (response.status === 503) {
                throw new Error((json && json.message) || '服务暂不可用');
            }
            if (!response.ok) {
                let msg = (json && (json.message || json.detail)) || `HTTP ${response.status}`;
                // 422 验证错误：尝试从 data.details 提取具体字段错误
                if (response.status === 422 && json && json.data && json.data.details) {
                    msg = json.data.details.join('; ');
                }
                throw new Error(typeof msg === 'string' ? msg : `HTTP ${response.status}`);
            }

            // 统一响应 envelope: {code, message, data, timestamp}
            if (json && typeof json === 'object' && 'code' in json && 'data' in json) {
                if (json.code !== 0) {
                    throw new Error(json.message || `业务错误 ${json.code}`);
                }
                const data = json.data;
                if (data !== null && typeof data === 'object' && !Array.isArray(data)) {
                    return { ...data, code: json.code, message: json.message };
                }
                // data 为数组/标量时，保留在 data 字段，同时摊平常见包装
                return { data, code: json.code, message: json.message };
            }
            return json;
        } catch (e) {
            if (e instanceof TypeError) {
                throw new Error('网络连接失败，请检查服务状态');
            }
            throw e;
        }
    },

    get(endpoint) {
        return this.request(endpoint);
    },

    post(endpoint, data) {
        return this.request(endpoint, { method: 'POST', body: data });
    },

    put(endpoint, data) {
        return this.request(endpoint, { method: 'PUT', body: data });
    },

    delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    },

    upload(endpoint, formData) {
        return this.request(endpoint, { method: 'POST', body: formData });
    },

    admin(endpoint, options = {}) {
        const fullPath = endpoint.startsWith('/') ? endpoint : '/' + endpoint;
        return this.request(fullPath, {
            ...options,
            headers: { 'X-Admin-Request': 'true' }
        });
    }
};

/**
 * iframe 通信支持
 * 当页面作为iframe嵌入公司平台时，通过postMessage接收认证token
 */
const IframeBridge = {
    isEmbedded: false,
    origin: '*',

    init() {
        this.isEmbedded = window.self !== window.top;
        if (this.isEmbedded) {
            document.documentElement.classList.add('embedded-mode');
            this._listen();
            this._notifyParent();
        }
    },

    _listen() {
        window.addEventListener('message', (event) => {
            const data = event.data;
            if (!data || typeof data !== 'object') return;
            
            if (data.type === 'SSO_TOKEN') {
                if (data.token) {
                    Auth.saveToken(data.token, data.expire_at || Math.floor(Date.now() / 1000) + 86400);
                    Auth.applyUI();
                    UI.addLog('✅ SSO 认证成功（来自父页面）', 'info');
                }
            } else if (data.type === 'SSO_LOGOUT') {
                Auth.clearToken();
                Auth.applyUI();
            } else if (data.type === 'CONFIG_UPDATE') {
                if (data.config) {
                    document.dispatchEvent(new CustomEvent('config:external-update', { detail: data.config }));
                }
            } else if (data.type === 'THEME') {
                if (data.theme) {
                    document.documentElement.setAttribute('data-theme', data.theme);
                }
            }
        });
    },

    _notifyParent() {
        window.parent.postMessage({ type: 'CHILD_READY', version: '1.0.0' }, '*');
    },

    notify(event, payload = {}) {
        if (!this.isEmbedded) return;
        window.parent.postMessage({ type: event, ...payload }, this.origin);
    },

    ready() {
        this.notify('APP_READY', { 
            routes: ['run', 'review', 'nodes', 'config'],
            version: '1.0.0'
        });
    },

    taskCompleted(taskId, result) {
        this.notify('TASK_COMPLETED', { task_id: taskId, result });
    },

    taskFailed(taskId, error) {
        this.notify('TASK_FAILED', { task_id: taskId, error });
    },

    reviewRequested(taskId, nodeName) {
        this.notify('REVIEW_REQUESTED', { task_id: taskId, node_name: nodeName });
    }
};
