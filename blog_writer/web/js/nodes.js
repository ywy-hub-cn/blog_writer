/**
 * 节点管理
 */

const Nodes = {
    async load() {
        try {
            const data = await Api.get('/api/nodes');
            const list = document.getElementById('nodeList');
            if (!data.nodes || data.nodes.length === 0) {
                list.innerHTML = '<p class="text-gray-500 text-sm text-center py-4">暂无节点</p>';
                return;
            }
            list.innerHTML = data.nodes.map(n => `
                <div onclick="Nodes.select('${n.file}')" class="border rounded-lg p-3 cursor-pointer hover:bg-blue-50 transition-colors" data-id="${n.file}">
                    <div class="font-medium text-sm text-gray-800">${n.name || n.id}</div>
                    <div class="text-xs text-gray-500">S${String(n.seq || 0).padStart(3, '0')} · ${n.exec_type || n.kind || 'unknown'}</div>
                </div>
            `).join('');
        } catch (e) {
            console.error('Load nodes error:', e);
        }
    },

    async select(filename) {
        try {
            const nodes = await Api.get('/api/nodes');
            const node = nodes.nodes.find(n => n.file === filename);
            if (!node) return;

            const detail = await Api.get(`/api/nodes/${node.id}`);
            State.currentNodeId = node.id;
            
            document.getElementById('nodeEditorTitle').textContent = `📝 ${node.name} - ${filename}`;
            document.getElementById('nodeEditor').value = JSON.stringify(detail, null, 2);
            
            document.querySelectorAll('#nodeList > div').forEach(d => {
                d.classList.toggle('bg-blue-100', d.dataset.id === filename);
            });
        } catch (e) {
            console.error('Select node error:', e);
        }
    },

    async save() {
        if (!State.currentNodeId) {
            UI.showToast('请先选择一个节点', 'warn');
            return;
        }
        try {
            const nodeData = JSON.parse(document.getElementById('nodeEditor').value);
            // 客户端敏感内容预检
            const sensitiveCheck = this._checkSensitive(nodeData);
            if (sensitiveCheck.length > 0) {
                if (!UI.confirm(
                    '⚠️ 节点数据中检测到疑似敏感信息:\n' +
                    sensitiveCheck.join('\n') +
                    '\n\n继续保存可能会暴露这些信息，确定要保存吗？'
                )) return;
            }
            await Api.admin(`/nodes/${State.currentNodeId}`, {
                method: 'PUT',
                body: nodeData
            });
            UI.showToast('✅ 保存成功', 'success');
            UI.addLog(`📝 节点已保存: ${State.currentNodeId}`, 'info');
        } catch (e) {
            UI.showToast('❌ 保存失败: ' + e.message, 'error');
        }
    },

    _checkSensitive(obj) {
        const patterns = [
            { re: /sk-[a-zA-Z0-9]{16,}/, desc: 'API Key (sk-...)' },
            { re: /api[_-]?key\s*[:=]\s*[a-zA-Z0-9_-]{8,}/i, desc: 'API Key 配置' },
            { re: /Bearer\s+[a-zA-Z0-9_\-.]{20,}/i, desc: 'Bearer Token' },
            { re: /password\s*[:=]\s*[^\s,]{4,}/i, desc: '密码' },
            { re: /secret\s*[:=]\s*[^\s,]{4,}/i, desc: '密钥' },
        ];
        const warnings = [];
        function scan(v, path) {
            if (typeof v === 'string') {
                for (const p of patterns) {
                    if (p.re.test(v)) { warnings.push(path + ': ' + p.desc); break; }
                }
            } else if (v && typeof v === 'object') {
                for (const k of Object.keys(v)) scan(v[k], path ? path + '.' + k : k);
            }
        }
        scan(obj, '');
        return warnings;
    },

    async validate() {
        if (!State.currentNodeId) {
            UI.showToast('请先选择一个节点', 'warn');
            return;
        }
        try {
            const result = await Api.get(`/api/nodes/${State.currentNodeId}/validate`);
            const vr = document.getElementById('validationResult');
            if (result.validation.valid) {
                vr.innerHTML = '<div class="bg-green-50 text-green-700 p-3 rounded-lg">✅ 校验通过</div>';
            } else {
                vr.innerHTML = '<div class="bg-red-50 text-red-700 p-3 rounded-lg">' +
                    '❌ 校验失败:<br>' + result.validation.errors.join('<br>') + '</div>';
            }
        } catch (e) {
            console.error('Validate error:', e);
        }
    },

    async delete() {
        if (!State.currentNodeId) {
            UI.showToast('请先选择一个节点', 'warn');
            return;
        }
        if (!UI.confirm('确定要删除此节点吗？删除前会自动备份。')) return;
        
        try {
            await Api.admin(`/nodes/${State.currentNodeId}`, { method: 'DELETE' });
            UI.showToast('✅ 节点已删除', 'success');
            State.currentNodeId = null;
            document.getElementById('nodeEditor').value = '';
            this.load();
        } catch (e) {
            UI.showToast('❌ 删除失败: ' + e.message, 'error');
        }
    },

    createNew() {
        const newNode = {
            id: "step.blog.writer.new_node",
            name: "新节点",
            seq: 99,
            kind: "llm_completion",
            description: "",
            llm_model: "default",
            resources: {
                prompt_template: "在此处定义prompt模板，使用{{param}}作为变量",
                system_prompt: "You are a helpful assistant."
            },
            constraints: { must: [], forbidden: [] },
            actions: [{ name: "生成输出", output: { path: "output.md", name: "输出" } }],
            checks: [{ id: 1, rule: "输出文件存在且内容不为空", target: "file:output.md" }]
        };
        document.getElementById('nodeEditor').value = JSON.stringify(newNode, null, 2);
        State.currentNodeId = 'new_node';
        document.getElementById('nodeEditorTitle').textContent = '📝 新节点（请填写后保存）';
    }
};
