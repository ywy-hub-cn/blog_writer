"""
WorkflowService 集成测试

测试工作流服务与执行器的集成，包括：
- 工作流节点执行流程
- 错误处理和重试机制
- 状态持久化和恢复
"""
import json
import tempfile
import os
import time
from pathlib import Path
from typing import Dict, Any
from unittest.mock import MagicMock, AsyncMock

import pytest
import asyncio


class MockLLMProvider:
    """模拟LLM提供者"""
    
    def __init__(self):
        self.chat_count = 0
        self._stats = {
            "total_tokens_used": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0
        }
    
    async def chat(self, messages, tools=None):
        self.chat_count += 1
        return MagicMock(
            content="Test response",
            tool_calls=None
        )
    
    def get_stats(self):
        return self._stats


@pytest.fixture
def temp_workflow_dir():
    """创建临时工作流目录"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield tmp_dir


@pytest.fixture
def mock_llm_provider():
    """创建模拟LLM提供者"""
    return MockLLMProvider()


class TestWorkflowExecution:
    """测试工作流执行流程"""
    
    def test_pure_code_executor_inherits_base(self, temp_workflow_dir):
        """验证 PureCodeExecutor 继承自 BaseExecutor"""
        from blog_writer.agent.hybrid_executor import PureCodeExecutor
        from blog_writer.agent.base_executor import BaseExecutor
        
        node = {
            "id": "test",
            "exec_type": "pure_code",
            "resources": {"script": "pass"}
        }
        executor = PureCodeExecutor(
            node_definition=node,
            instance_dir=temp_workflow_dir
        )
        
        assert isinstance(executor, BaseExecutor)
        assert hasattr(executor, 'log')
        assert hasattr(executor, '_list_available_files')
        assert hasattr(executor, '_run_checks')
    
    def test_llm_completion_executor_inherits_base(self, temp_workflow_dir):
        """验证 LLMCompletionExecutor 继承自 BaseExecutor"""
        from blog_writer.agent.hybrid_executor import LLMCompletionExecutor
        from blog_writer.agent.base_executor import BaseExecutor
        
        node = {
            "id": "test",
            "exec_type": "llm_completion",
            "resources": {
                "prompt_template": "Test",
                "system_prompt": "You are helpful."
            }
        }
        llm = MockLLMProvider()
        executor = LLMCompletionExecutor(
            llm_provider=llm,
            node_definition=node,
            instance_dir=temp_workflow_dir
        )
        
        assert isinstance(executor, BaseExecutor)
        assert hasattr(executor, 'log')
        assert hasattr(executor, '_list_available_files')
        assert hasattr(executor, '_run_checks')
    
    def test_agent_executor_inherits_base(self, temp_workflow_dir):
        """验证 AgentExecutor 继承自 BaseExecutor"""
        from blog_writer.agent.executor import AgentExecutor
        from blog_writer.agent.base_executor import BaseExecutor
        
        node = {
            "id": "test",
            "exec_type": "agent_action",
            "actions": []
        }
        llm = MockLLMProvider()
        executor = AgentExecutor(
            llm_provider=llm,
            node_definition=node,
            instance_dir=temp_workflow_dir
        )
        
        assert isinstance(executor, BaseExecutor)
        assert hasattr(executor, 'log')
        assert hasattr(executor, '_list_available_files')
        assert hasattr(executor, '_run_checks')
    
    @pytest.mark.asyncio
    async def test_pure_code_execution(self, temp_workflow_dir):
        """测试纯代码执行"""
        from blog_writer.agent.hybrid_executor import PureCodeExecutor
        
        node = {
            "id": "test",
            "exec_type": "pure_code",
            "resources": {
                "script": "x = 42\nresult = f'Value is {x}'"
            }
        }
        executor = PureCodeExecutor(
            node_definition=node,
            instance_dir=temp_workflow_dir
        )
        
        result = await executor.execute({})
        
        assert result["status"] == "success"
        assert result["node_id"] == "test"
        assert isinstance(result["outputs"], dict)
    
    @pytest.mark.asyncio
    async def test_pure_code_with_checks(self, temp_workflow_dir):
        """测试带检查的纯代码执行"""
        from blog_writer.agent.hybrid_executor import PureCodeExecutor
        
        node = {
            "id": "test",
            "exec_type": "pure_code",
            "resources": {
                "script": "x = 42\nresult = x"
            },
            "checks": [
                {
                    "id": "check1",
                    "rule": "不为空",
                    "target": "output:result"
                }
            ]
        }
        executor = PureCodeExecutor(
            node_definition=node,
            instance_dir=temp_workflow_dir
        )
        
        result = await executor.execute({})
        
        assert result["status"] == "success"
        assert result["checks_passed"] is True
        assert len(result["checks_results"]) == 1
    
    @pytest.mark.asyncio
    async def test_pure_code_empty_script(self, temp_workflow_dir):
        """测试空脚本的纯代码执行"""
        from blog_writer.agent.hybrid_executor import PureCodeExecutor
        
        node = {
            "id": "test",
            "exec_type": "pure_code",
            "resources": {
                "script": ""
            }
        }
        executor = PureCodeExecutor(
            node_definition=node,
            instance_dir=temp_workflow_dir
        )
        
        result = await executor.execute({})
        
        # 空脚本应该返回成功
        assert result["status"] == "success"
    
    def test_factory_raises_for_missing_llm(self, temp_workflow_dir):
        """测试工厂在缺少LLM时抛出异常"""
        from blog_writer.agent.hybrid_executor import NodeExecutorFactory
        
        node = {
            "id": "test",
            "exec_type": "llm_completion"
        }
        
        with pytest.raises(ValueError) as exc_info:
            NodeExecutorFactory.create_executor(
                node_definition=node,
                llm_provider=None,
                instance_dir=temp_workflow_dir
            )
        
        assert "需要LLM提供者" in str(exc_info.value)
    
    def test_factory_pure_code_no_llm_needed(self, temp_workflow_dir):
        """测试纯代码执行器不需要LLM"""
        from blog_writer.agent.hybrid_executor import NodeExecutorFactory, PureCodeExecutor
        
        node = {
            "id": "test",
            "exec_type": "pure_code"
        }
        
        executor = NodeExecutorFactory.create_executor(
            node_definition=node,
            llm_provider=None,
            instance_dir=temp_workflow_dir
        )
        
        assert isinstance(executor, PureCodeExecutor)
    
    def test_factory_human_review_returns_none(self, temp_workflow_dir):
        """测试human_review类型返回None"""
        from blog_writer.agent.hybrid_executor import NodeExecutorFactory
        
        node = {
            "id": "test",
            "exec_type": "human_review"
        }
        
        executor = NodeExecutorFactory.create_executor(
            node_definition=node,
            llm_provider=None,
            instance_dir=temp_workflow_dir
        )
        
        assert executor is None


class TestConfigManagerHotReload:
    """测试 ConfigManager 热更新功能"""
    
    def test_atomic_save(self, temp_workflow_dir):
        """测试原子写入"""
        from blog_writer.config_manager import ConfigManager
        
        config_path = os.path.join(temp_workflow_dir, "test_config.json")
        manager = ConfigManager(config_path=config_path, auto_reload=False)
        
        # 修改并保存
        manager.set("test.key", "value")
        
        # 验证文件存在且是有效JSON
        assert os.path.exists(config_path)
        with open(config_path, 'r') as f:
            data = json.load(f)
        assert data["test"]["key"] == "value"
        
        # 验证没有临时文件残留
        tmp_path = config_path + ".tmp"
        assert not os.path.exists(tmp_path)
    
    def test_hot_reload_detects_changes(self, temp_workflow_dir):
        """测试热更新检测文件变化"""
        from blog_writer.config_manager import ConfigManager
        
        config_path = os.path.join(temp_workflow_dir, "test_config.json")
        manager = ConfigManager(config_path=config_path, auto_reload=True)
        
        # 记录初始值
        initial_value = manager.get("test.key", "default")
        
        # 直接修改文件（模拟外部修改）
        time.sleep(0.1)  # 确保mtime变化
        with open(config_path, 'r') as f:
            data = json.load(f)
        data["test"] = {"key": "modified"}
        with open(config_path, 'w') as f:
            json.dump(data, f)
        
        # 再次获取应触发热更新
        new_value = manager.get("test.key", "default")
        assert new_value == "modified"
    
    def test_change_callback(self, temp_workflow_dir):
        """测试配置变更回调"""
        from blog_writer.config_manager import ConfigManager
        
        config_path = os.path.join(temp_workflow_dir, "test_config.json")
        manager = ConfigManager(config_path=config_path, auto_reload=False)
        
        changes = []
        
        def on_change(new_config):
            changes.append(new_config)
        
        manager.on_change(on_change)
        
        # 手动触发重载
        manager.reload_if_changed()
        
        # 没有变化时不应触发回调
        assert len(changes) == 0
        
        # 修改文件
        time.sleep(0.1)
        config_path = manager.config_path
        with open(config_path, 'r') as f:
            data = json.load(f)
        data["version"] = 2
        with open(config_path, 'w') as f:
            json.dump(data, f)
        
        # 触发重载
        result = manager.reload_if_changed()
        
        assert result is True
        assert len(changes) == 1
    
    def test_thread_safety(self, temp_workflow_dir):
        """测试线程安全"""
        import threading
        from blog_writer.config_manager import ConfigManager
        
        config_path = os.path.join(temp_workflow_dir, "test_config.json")
        manager = ConfigManager(config_path=config_path, auto_reload=False)
        
        errors = []
        
        def set_value(key, value):
            try:
                manager.set(key, value)
            except Exception as e:
                errors.append(str(e))
        
        # 并发写入
        threads = []
        for i in range(10):
            t = threading.Thread(target=set_value, args=(f"thread.key.{i}", i))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # 验证没有错误
        assert len(errors) == 0
        
        # 验证所有值都正确写入
        for i in range(10):
            assert manager.get(f"thread.key.{i}") == i


class TestStatePersistence:
    """测试状态持久化"""
    
    def test_state_validation_rejects_invalid(self):
        """测试状态验证拒绝无效数据"""
        from blog_writer.workflow_service import WorkflowService
        
        # 创建实例来测试验证方法
        ws = WorkflowService.__new__(WorkflowService)
        
        # 无效状态
        invalid_state = {"status": "invalid_status", "task_id": "test"}
        assert ws._validate_state(invalid_state) is False
        
        # 缺少必需字段
        missing_field = {"status": "pending"}
        assert ws._validate_state(missing_field) is False
    
    def test_state_validation_accepts_valid(self):
        """测试状态验证接受有效数据"""
        from blog_writer.workflow_service import WorkflowService
        
        ws = WorkflowService.__new__(WorkflowService)
        
        # 有效状态
        valid_state = {
            "task_id": "test",
            "status": "running",
            "current_step": 1,
            "total_steps": 5
        }
        assert ws._validate_state(valid_state) is True
    
    def test_state_validation_checks_types(self):
        """测试状态验证检查数据类型"""
        from blog_writer.workflow_service import WorkflowService
        
        ws = WorkflowService.__new__(WorkflowService)
        
        # 类型错误
        wrong_type = {
            "task_id": "test",
            "status": "pending",
            "current_step": "not_a_number",
            "total_steps": 5
        }
        assert ws._validate_state(wrong_type) is False
