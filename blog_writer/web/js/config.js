/**
 * 配置管理
 * 敏感信息（API Key、Base URL 等）不传输到前端，仅显示配置状态
 */

const Config = {
    _apiKeyConfigured: false,
    _baseUrlConfigured: false,

    _safeReadBool(obj, field) {
        if (!obj) return false;
        const val = obj[field];
        if (val && typeof val === 'object') return val.configured === true;
        if (typeof val === 'string') return val.length > 0;
        return false;
    },

    async load() {
        try {
            const data = await Api.admin('/config');

            this._fillLLMForm(data);
            this._fillWorkflowForm(data);
            Stats.update();

            // 加载当前并发数
            try {
                const concurrency = await Api.get('/api/tasks/concurrency');
                const el = document.getElementById('maxConcurrentTasks');
                if (el && concurrency.max_concurrent) {
                    el.value = concurrency.max_concurrent;
                }
            } catch (e) {
                // 忽略并发信息加载失败
            }
        } catch (e) {
            console.error('Load config error:', e);
        }
    },

    _fillLLMForm(data) {
        const llmEl = document.getElementById('llmModel');
        if (!llmEl) return;

        const models = data.llm?.models || {};
        const defaultModel = data.llm?.default_model || 'default';

        const modelOptions = Object.keys(models);
        llmEl.innerHTML = modelOptions.length > 0
            ? modelOptions.map(m =>
                `<option value="${m}" ${m === defaultModel ? 'selected' : ''}>${m} - ${models[m].model || 'unknown'}</option>`
            ).join('')
            : '<option value="default">默认模型</option>';

        const selectedModel = models[defaultModel] || models[modelOptions[0]] || {};

        // Base URL - 只显示配置状态
        this._baseUrlConfigured = this._safeReadBool(selectedModel, 'base_url');
        this._updateSensitiveStatus();

        // API Key - 只显示配置状态
        this._apiKeyConfigured = this._safeReadBool(selectedModel, 'api_key');

        document.getElementById('llmModelName').value = selectedModel.model || '';
        document.getElementById('llmTemperature').value = selectedModel.temperature ?? 0.7;
        document.getElementById('llmMaxTokens').value = selectedModel.max_tokens || 8192;
    },

    _updateSensitiveStatus() {
        // API Key
        const keyEl = document.getElementById('apiKeyStatus');
        if (keyEl) {
            if (this._apiKeyConfigured) {
                keyEl.innerHTML = '<span class="sensitive-status-dot configured"></span> 已配置';
                keyEl.className = 'sensitive-status configured';
            } else {
                keyEl.innerHTML = '<span class="sensitive-status-dot not-configured"></span> 未配置';
                keyEl.className = 'sensitive-status not-configured';
            }
        }
        // Base URL
        const urlEl = document.getElementById('baseUrlStatus');
        if (urlEl) {
            if (this._baseUrlConfigured) {
                urlEl.innerHTML = '<span class="sensitive-status-dot configured"></span> 已配置';
                urlEl.className = 'sensitive-status configured';
            } else {
                urlEl.innerHTML = '<span class="sensitive-status-dot not-configured"></span> 未配置';
                urlEl.className = 'sensitive-status not-configured';
            }
        }
    },

    _fillWorkflowForm(data) {
        document.getElementById('wfDefaultMode').value = data.workflow?.default_mode || 'supervised';
        document.getElementById('wfMaxIterations').value = data.workflow?.max_iterations_per_step || 20;
        document.getElementById('wfStepTimeout').value = data.workflow?.step_timeout_minutes || 10;
        document.getElementById('wfInstanceRoot').value = data.workflow?.instance_root || './instance';
    },

    async saveLLM() {
        try {
            const modelKey = document.getElementById('llmModel').value;
            const data = {
                llm: {
                    default_model: modelKey,
                    models: {
                        [modelKey]: {
                            model: document.getElementById('llmModelName').value,
                            temperature: parseFloat(document.getElementById('llmTemperature').value),
                            max_tokens: parseInt(document.getElementById('llmMaxTokens').value)
                        }
                    }
                }
            };
            // 注意：api_key 和 base_url 不在此处发送，通过专用弹窗修改
            await Api.admin('/config', { method: 'PUT', body: data });
            UI.showToast('✅ LLM配置已保存', 'success');
            UI.addLog('🔧 LLM配置已更新', 'info');
        } catch (e) {
            UI.showToast('❌ 保存失败: ' + e.message, 'error');
        }
    },

    async saveWorkflow() {
        try {
            const data = {
                workflow: {
                    default_mode: document.getElementById('wfDefaultMode').value,
                    max_iterations_per_step: parseInt(document.getElementById('wfMaxIterations').value),
                    step_timeout_minutes: parseInt(document.getElementById('wfStepTimeout').value),
                    instance_root: document.getElementById('wfInstanceRoot').value
                }
            };
            await Api.admin('/config', { method: 'PUT', body: data });
            UI.showToast('✅ 工作流配置已保存', 'success');
            UI.addLog('🔧 工作流配置已更新', 'info');
        } catch (e) {
            UI.showToast('❌ 保存失败: ' + e.message, 'error');
        }
    },

    async testLLM() {
        try {
            const result = await Api.admin('/config/test-llm');
            if (result.success) {
                UI.showToast('✅ LLM连接测试成功', 'success');
                UI.addLog('🔌 LLM连接测试成功', 'info');
            } else {
                UI.showToast('❌ 连接失败: ' + result.message, 'error');
                UI.addLog('❌ LLM连接失败: ' + result.message, 'error');
            }
        } catch (e) {
            UI.showToast('❌ 测试失败: ' + e.message, 'error');
        }
    }
};

// ========== API Key 修改弹窗 ==========

function showChangeApiKeyModal() {
    const modal = document.getElementById('apiKeyModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    const err = document.getElementById('apiKeyError');
    if (err) err.style.display = 'none';
    const newKey = document.getElementById('newApiKey');
    const confirmKey = document.getElementById('confirmApiKey');
    if (newKey) { newKey.value = ''; setTimeout(() => newKey.focus(), 100); }
    if (confirmKey) confirmKey.value = '';
}

function closeApiKeyModal() {
    const modal = document.getElementById('apiKeyModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}

async function saveApiKey() {
    const err = document.getElementById('apiKeyError');
    const newKey = document.getElementById('newApiKey');
    const confirmKey = document.getElementById('confirmApiKey');

    if (!newKey || !newKey.value.trim()) {
        if (err) { err.textContent = '请输入 API Key'; err.style.display = 'block'; }
        return;
    }
    if (newKey.value !== confirmKey.value) {
        if (err) { err.textContent = '两次输入的 API Key 不一致'; err.style.display = 'block'; }
        return;
    }

    try {
        const modelKey = document.getElementById('llmModel').value;
        await Api.admin('/config', {
            method: 'PUT',
            body: {
                llm: {
                    models: {
                        [modelKey]: { api_key: newKey.value.trim() }
                    }
                }
            }
        });
        Config._apiKeyConfigured = true;
        Config._updateSensitiveStatus();
        closeApiKeyModal();
        UI.showToast('✅ API Key 已更新', 'success');
        UI.addLog('🔑 API Key 已更新', 'info');
    } catch (e) {
        if (err) { err.textContent = '保存失败: ' + e.message; err.style.display = 'block'; }
    }
}

async function clearApiKey() {
    if (!UI.confirm('确定要清除 API Key 吗？清除后 LLM 功能将不可用。')) return;
    try {
        const modelKey = document.getElementById('llmModel').value;
        await Api.admin('/config', {
            method: 'PUT',
            body: {
                llm: {
                    models: {
                        [modelKey]: { api_key: '' }
                    }
                }
            }
        });
        Config._apiKeyConfigured = false;
        Config._updateSensitiveStatus();
        UI.showToast('✅ API Key 已清除', 'success');
        UI.addLog('🔑 API Key 已清除', 'info');
    } catch (e) {
        UI.showToast('❌ 清除失败: ' + e.message, 'error');
    }
}

// ========== Base URL 修改弹窗 ==========

function showChangeBaseUrlModal() {
    const modal = document.getElementById('baseUrlModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    const err = document.getElementById('baseUrlError');
    if (err) err.style.display = 'none';
    const input = document.getElementById('newBaseUrl');
    if (input) { input.value = ''; setTimeout(() => input.focus(), 100); }
}

function closeBaseUrlModal() {
    const modal = document.getElementById('baseUrlModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}

async function saveBaseUrl() {
    const err = document.getElementById('baseUrlError');
    const input = document.getElementById('newBaseUrl');

    if (!input || !input.value.trim()) {
        if (err) { err.textContent = '请输入 Base URL'; err.style.display = 'block'; }
        return;
    }

    try {
        const modelKey = document.getElementById('llmModel').value;
        await Api.admin('/config', {
            method: 'PUT',
            body: {
                llm: {
                    models: {
                        [modelKey]: { base_url: input.value.trim() }
                    }
                }
            }
        });
        Config._baseUrlConfigured = true;
        Config._updateSensitiveStatus();
        closeBaseUrlModal();
        UI.showToast('✅ Base URL 已更新', 'success');
        UI.addLog('🔗 Base URL 已更新', 'info');
    } catch (e) {
        if (err) { err.textContent = '保存失败: ' + e.message; err.style.display = 'block'; }
    }
}