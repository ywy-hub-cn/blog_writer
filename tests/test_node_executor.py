"""
NodeExecutorFactory 单元测试
"""
import json
import tempfile
import sys
from pathlib import Path
from typing import Dict, Any

import pytest

from blog_writer.agent.hybrid_executor import (
    NodeExecutorFactory,
    PureCodeExecutor,
    LLMCompletionExecutor
)


class TestNodeExecutorFactory:
    """测试节点执行器工厂"""
    
    def test_exec_type_map_exists(self):
        """测试执行类型映射存在"""
        assert hasattr(NodeExecutorFactory, 'EXEC_TYPE_MAP')
        assert isinstance(NodeExecutorFactory.EXEC_TYPE_MAP, dict)
    
    def test_all_exec_types_registered(self):
        """测试所有执行类型已注册"""
        expected_types = ['pure_code', 'llm_completion', 'agent_action', 'human_review', 'system_check']
        for t in expected_types:
            assert t in NodeExecutorFactory.EXEC_TYPE_MAP, f"缺少执行类型: {t}"
    
    def test_get_exec_type_with_exec_type(self):
        """测试从 exec_type 字段获取类型"""
        node = {
            "exec_type": "pure_code",
            "kind": "agent_action"
        }
        result = NodeExecutorFactory.get_exec_type(node)
        assert result == "pure_code"
    
    def test_get_exec_type_with_kind_fallback(self):
        """测试回退到 kind 字段"""
        node = {
            "kind": "llm_completion"
        }
        result = NodeExecutorFactory.get_exec_type(node)
        assert result == "llm_completion"
    
    def test_get_exec_type_default(self):
        """测试默认类型"""
        node = {}
        result = NodeExecutorFactory.get_exec_type(node)
        assert result == "agent_action"
    
    def test_get_exec_type_invalid(self):
        """测试无效类型回退"""
        node = {
            "exec_type": "invalid_type"
        }
        result = NodeExecutorFactory.get_exec_type(node)
        # 无效类型会返回原值或回退值
        assert result is not None
    
    def test_create_executor_pure_code(self, temp_dir):
        """测试创建纯代码执行器"""
        node = {
            "exec_type": "pure_code",
            "id": "test"
        }
        executor = NodeExecutorFactory.create_executor(
            node_definition=node,
            llm_provider=None,
            instance_dir=temp_dir
        )
        assert isinstance(executor, PureCodeExecutor)
    
    def test_create_executor_llm_completion(self, temp_dir):
        """测试创建LLM完成执行器（缺少LLM提供者时抛出异常）"""
        node = {
            "exec_type": "llm_completion",
            "id": "test"
        }
        # llm_completion 需要LLM提供者，没有时应抛出ValueError
        with pytest.raises(ValueError, match="需要LLM提供者"):
            NodeExecutorFactory.create_executor(
                node_definition=node,
                llm_provider=None,
                instance_dir=temp_dir
            )
    
    def test_create_executor_invalid_type(self, temp_dir):
        """测试创建无效类型执行器"""
        node = {
            "exec_type": "nonexistent_type",
            "id": "test"
        }
        # 无效类型会回退到默认类型agent_action，需要LLM提供者
        with pytest.raises(ValueError, match="需要LLM提供者"):
            NodeExecutorFactory.create_executor(
                node_definition=node,
                llm_provider=None,
                instance_dir=temp_dir
            )
    
    def test_create_executor_human_review(self, temp_dir):
        """测试创建human_review类型执行器（返回None，由工作流直接处理）"""
        node = {
            "exec_type": "human_review",
            "id": "test.review"
        }
        executor = NodeExecutorFactory.create_executor(
            node_definition=node,
            llm_provider=None,
            instance_dir=temp_dir
        )
        # human_review 不需要执行器，由工作流服务直接处理
        assert executor is None
    
    def test_create_executor_unknown_type_fallback(self, temp_dir):
        """测试未知类型回退到默认类型 agent_action"""
        node = {
            "exec_type": "unknown_type_xyz",
            "id": "test"
        }
        # 未知类型回退到默认agent_action，需要LLM提供者
        with pytest.raises(ValueError, match="需要LLM提供者"):
            NodeExecutorFactory.create_executor(
                node_definition=node,
                llm_provider=None,
                instance_dir=temp_dir
            )


class TestPureCodeExecutor:
    """测试纯代码执行器"""
    
    def test_initialization(self, temp_dir):
        """测试初始化"""
        node = {
            "id": "test.code",
            "exec_type": "pure_code",
            "resources": {"script": "print('hello')"}
        }
        executor = PureCodeExecutor(
            node_definition=node,
            instance_dir=temp_dir
        )
        assert executor is not None
    
    def test_has_execute_method(self, temp_dir):
        """测试execute方法存在"""
        node = {
            "id": "test.code",
            "exec_type": "pure_code",
            "resources": {"script": "print('hello')"}
        }
        executor = PureCodeExecutor(
            node_definition=node,
            instance_dir=temp_dir
        )
        assert hasattr(executor, 'execute')


class TestLLMCompletionExecutor:
    """测试LLM完成执行器"""
    
    def test_initialization(self, temp_dir):
        """测试初始化"""
        node = {
            "id": "test.llm",
            "exec_type": "llm_completion",
            "resources": {
                "prompt_template": "Test prompt",
                "system_prompt": "You are a test assistant."
            }
        }
        executor = LLMCompletionExecutor(
            node_definition=node,
            llm_provider=None,
            instance_dir=temp_dir
        )
        assert executor is not None
    
    def test_has_execute_method(self, temp_dir):
        """测试execute方法存在"""
        node = {
            "id": "test.llm",
            "exec_type": "llm_completion",
            "resources": {
                "prompt_template": "Test prompt",
                "system_prompt": "Test system"
            }
        }
        executor = LLMCompletionExecutor(
            node_definition=node,
            llm_provider=None,
            instance_dir=temp_dir
        )
        assert hasattr(executor, 'execute')
