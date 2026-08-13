"""
WorkflowService 单元测试
"""
import json
import asyncio
import tempfile
from pathlib import Path
from typing import Dict, Any

import pytest

from blog_writer.workflow_service import WorkflowService, DEFAULT_MAX_RETRIES


class TestWorkflowServiceInit:
    """测试WorkflowService初始化"""
    
    def test_init_with_config(self, workflow_service, config_manager):
        """测试使用配置初始化"""
        assert workflow_service.config == config_manager
        assert workflow_service.nodes_dir.exists()
        assert workflow_service.instance_root.exists()
    
    def test_init_creates_directories(self, temp_dir, config_manager):
        """测试初始化时创建目录"""
        nodes_dir = Path(temp_dir) / "nodes"
        instance_root = Path(temp_dir) / "instance"
        
        config_manager.set("workflow.nodes_dir", str(nodes_dir))
        config_manager.set("workflow.instance_root", str(instance_root))
        
        # 创建必要的节点文件
        nodes_dir.mkdir(parents=True, exist_ok=True)
        with open(nodes_dir / "test-node.json", 'w') as f:
            json.dump({
                "id": "test",
                "name": "Test",
                "seq": 1,
                "kind": "pure_code",
                "exec_type": "pure_code",
                "resources": {"script": "print('test')"},
                "actions": [],
                "checks": []
            }, f)
        
        service = WorkflowService(config_manager)
        assert service.nodes_dir == nodes_dir
        assert service.instance_root == instance_root


class TestNodeLoading:
    """测试节点加载"""
    
    def test_list_nodes(self, workflow_service):
        """测试列出节点"""
        nodes = workflow_service.list_nodes()
        assert isinstance(nodes, list)
        assert len(nodes) > 0
        
        # 检查节点结构
        node = nodes[0]
        assert "file" in node
        assert "id" in node
        assert "name" in node
        assert "exec_type" in node or "kind" in node
    
    def test_load_node_definition(self, workflow_service):
        """测试加载节点定义"""
        nodes_dir = workflow_service.nodes_dir
        node_files = list(nodes_dir.glob("*.json"))
        
        if node_files:
            node_def = workflow_service.load_node_definition(node_files[0].name)
            assert isinstance(node_def, dict)
            assert "id" in node_def
    
    def test_load_nonexistent_node(self, workflow_service):
        """测试加载不存在的节点"""
        with pytest.raises(FileNotFoundError):
            workflow_service.load_node_definition("nonexistent.json")
    
    def test_load_registry(self, workflow_service, temp_dir):
        """测试加载注册表"""
        # 创建临时registry文件
        nodes_dir = workflow_service.nodes_dir
        registry_path = nodes_dir.parent / "registry.json"
        
        registry_data = {
            "step_order": ["test-node.json"]
        }
        
        with open(registry_path, 'w') as f:
            json.dump(registry_data, f)
        
        registry = workflow_service.load_registry()
        assert isinstance(registry, dict)
        assert "step_order" in registry


class TestStatePersistence:
    """测试状态持久化"""
    
    def test_save_and_load_state(self, workflow_service, temp_dir):
        """测试保存和加载状态"""
        task_id = "test_task_state"
        task_state = {
            "task_id": task_id,
            "status": "running",
            "mode": "auto",
            "current_step": 0,
            "total_steps": 3,
            "start_time": "2024-01-01T00:00:00",
            "brand_path": "/test/brand",
            "keywords": "test keyword",
            "step_files": ["step1.json", "step2.json"],
            "completed_steps": [],
            "results": [],
            "outputs": {},
            "retry_counts": {},
            "end_time": "",
            "log": ["log1", "log2"]
        }
        
        # 设置内存中的任务
        workflow_service._tasks[task_id] = task_state
        
        # 保存状态
        workflow_service._save_state(task_id)
        
        # 清除内存
        if task_id in workflow_service._tasks:
            del workflow_service._tasks[task_id]
        
        # 加载状态
        loaded_state = workflow_service._load_state(task_id)
        assert loaded_state is not None
        assert loaded_state["task_id"] == task_id
        assert loaded_state["status"] == "running"
        assert loaded_state["total_steps"] == 3
    
    def test_load_nonexistent_state(self, workflow_service):
        """测试加载不存在的状态"""
        result = workflow_service._load_state("nonexistent_task_id")
        assert result is None
    
    def test_get_task_status(self, workflow_service):
        """测试获取任务状态"""
        task_id = "test_status_task"
        task_state = {
            "task_id": task_id,
            "status": "completed",
            "mode": "auto",
            "current_step": 5,
            "total_steps": 5,
            "start_time": "2024-01-01T00:00:00",
            "brand_path": "/test",
            "keywords": "test",
            "step_files": [],
            "completed_steps": ["step1", "step2"],
            "results": [],
            "outputs": {},
            "retry_counts": {},
            "end_time": "2024-01-01T00:10:00"
        }
        
        workflow_service._tasks[task_id] = task_state
        
        result = workflow_service.get_task_status(task_id)
        assert result is not None
        assert result["status"] == "completed"
    
    def test_get_task_status_not_found(self, workflow_service):
        """测试获取不存在的任务状态"""
        result = workflow_service.get_task_status("nonexistent")
        assert result is None


class TestTaskLifecycle:
    """测试任务生命周期"""
    
    def test_list_tasks_empty(self, workflow_service):
        """测试空任务列表"""
        tasks = workflow_service.list_tasks()
        assert isinstance(tasks, list)
    
    def test_cancel_task(self, workflow_service):
        """测试取消任务"""
        task_id = "test_cancel_task"
        workflow_service._tasks[task_id] = {
            "task_id": task_id,
            "status": "running",
            "mode": "auto",
            "current_step": 1,
            "total_steps": 5,
            "start_time": "2024-01-01T00:00:00",
            "brand_path": "",
            "keywords": "",
            "step_files": [],
            "completed_steps": [],
            "results": [],
            "outputs": {},
            "retry_counts": {}
        }
        
        result = workflow_service.cancel_task(task_id)
        assert result is True
        assert workflow_service._tasks[task_id]["status"] == "cancelled"
    
    def test_cancel_nonexistent_task(self, workflow_service):
        """测试取消不存在的任务"""
        result = workflow_service.cancel_task("nonexistent")
        assert result is False
    
    def test_pause_and_resume_task(self, workflow_service):
        """测试暂停和恢复任务"""
        task_id = "test_pause_resume"
        workflow_service._tasks[task_id] = {
            "task_id": task_id,
            "status": "running",
            "mode": "auto",
            "current_step": 1,
            "total_steps": 5,
            "start_time": "2024-01-01T00:00:00",
            "brand_path": "",
            "keywords": "",
            "step_files": [],
            "completed_steps": [],
            "results": [],
            "outputs": {},
            "retry_counts": {}
        }
        
        # 暂停
        result = workflow_service.pause_task(task_id)
        assert result is True
        assert workflow_service._tasks[task_id]["status"] == "paused"
        
        # 恢复
        result = workflow_service.resume_task(task_id)
        assert result is True
        assert workflow_service._tasks[task_id]["status"] == "running"
    
    def test_pause_non_running_task(self, workflow_service):
        """测试暂停非运行中的任务"""
        task_id = "test_pause_non_running"
        workflow_service._tasks[task_id] = {
            "task_id": task_id,
            "status": "completed",
            "mode": "auto",
            "current_step": 5,
            "total_steps": 5,
            "start_time": "2024-01-01T00:00:00",
            "brand_path": "",
            "keywords": "",
            "step_files": [],
            "completed_steps": [],
            "results": [],
            "outputs": {},
            "retry_counts": {}
        }
        
        result = workflow_service.pause_task(task_id)
        assert result is False
    
    def test_resume_non_paused_task(self, workflow_service):
        """测试恢复非暂停状态的任务"""
        task_id = "test_resume_non_paused"
        workflow_service._tasks[task_id] = {
            "task_id": task_id,
            "status": "completed",
            "mode": "auto",
            "current_step": 5,
            "total_steps": 5,
            "start_time": "2024-01-01T00:00:00",
            "brand_path": "",
            "keywords": "",
            "step_files": [],
            "completed_steps": [],
            "results": [],
            "outputs": {},
            "retry_counts": {}
        }
        
        result = workflow_service.resume_task(task_id)
        assert result is False


class TestReviewFlow:
    """测试审核流程"""
    
    def test_get_pending_reviews_empty(self, workflow_service):
        """测试获取空审核列表"""
        reviews = workflow_service.get_pending_reviews()
        assert isinstance(reviews, list)
        assert len(reviews) == 0
    
    def test_approve_review(self, workflow_service):
        """测试批准审核"""
        task_id = "test_approve_review"
        
        # 创建等待审核的任务
        pause_event = asyncio.Event()
        workflow_service._pause_events[task_id] = pause_event
        
        workflow_service._tasks[task_id] = {
            "task_id": task_id,
            "status": "waiting_review",
            "mode": "supervised",
            "review_node": "test.node",
            "review_node_name": "Test Node",
            "current_step": 2,
            "total_steps": 5,
            "start_time": "2024-01-01T00:00:00",
            "brand_path": "",
            "keywords": "",
            "step_files": [],
            "completed_steps": [],
            "results": [],
            "outputs": {},
            "retry_counts": {}
        }
        
        result = workflow_service.approve_review(task_id, "approve")
        assert result is True
        assert workflow_service._tasks[task_id]["review_decision"] == "approve"
        
        # 检查事件被触发
        assert pause_event.is_set()
    
    def test_approve_nonexistent_review(self, workflow_service):
        """测试批准不存在的审核"""
        result = workflow_service.approve_review("nonexistent", "approve")
        assert result is False
    
    def test_get_pending_reviews(self, workflow_service):
        """测试获取待审核列表"""
        task_id = "test_pending_review"
        
        workflow_service._tasks[task_id] = {
            "task_id": task_id,
            "status": "waiting_review",
            "mode": "supervised",
            "review_node": "test.review",
            "review_node_name": "Review Node",
            "keywords": "test keyword",
            "current_step": 3,
            "total_steps": 5,
            "start_time": "2024-01-01T00:00:00",
            "brand_path": "",
            "step_files": [],
            "completed_steps": [],
            "results": [],
            "outputs": {},
            "retry_counts": {}
        }
        
        reviews = workflow_service.get_pending_reviews()
        assert len(reviews) == 1
        assert reviews[0]["task_id"] == task_id
        assert reviews[0]["node_id"] == "test.review"


class TestRetryNode:
    """测试节点重试"""
    
    def test_retry_node(self, workflow_service):
        """测试重试节点"""
        task_id = "test_retry_node"
        node_file = "step1.json"
        
        workflow_service._tasks[task_id] = {
            "task_id": task_id,
            "status": "failed",
            "mode": "auto",
            "current_step": 1,
            "total_steps": 3,
            "start_time": "2024-01-01T00:00:00",
            "brand_path": "",
            "keywords": "",
            "step_files": ["step1.json", "step2.json", "step3.json"],
            "completed_steps": ["step1.json", "step2.json"],
            "results": [
                {"step": "step1.json", "status": "success"},
                {"step": "step2.json", "status": "success"}
            ],
            "outputs": {},
            "retry_counts": {"step1.json": 1}
        }
        
        result = workflow_service.retry_node(task_id, node_file)
        assert result is True
        
        # 检查完成步骤中已移除该节点
        completed = workflow_service._tasks[task_id]["completed_steps"]
        assert node_file not in completed
        
        # 检查重试计数增加
        retry_counts = workflow_service._tasks[task_id]["retry_counts"]
        assert retry_counts.get(node_file, 0) == 2
    
    def test_retry_nonexistent_node(self, workflow_service):
        """测试重试不存在的节点"""
        result = workflow_service.retry_node("nonexistent", "step.json")
        assert result is False


class TestWorkflowConfig:
    """测试工作流配置"""
    
    def test_default_max_retries(self):
        """测试默认最大重试次数"""
        assert DEFAULT_MAX_RETRIES == 3
    
    def test_get_all_tasks(self, workflow_service):
        """测试获取所有任务"""
        tasks = workflow_service.get_all_tasks()
        assert isinstance(tasks, dict)
    
    def test_get_task_logs(self, workflow_service):
        """测试获取任务日志"""
        logs = workflow_service.get_task_logs("nonexistent")
        assert logs == []


class TestLLMProvider:
    """测试LLM提供者管理"""
    
    def test_has_llm_provider_initially_false(self, workflow_service):
        """测试初始时LLM提供者不存在"""
        assert workflow_service.has_llm_provider() is False
    
    def test_reload_llm(self, workflow_service):
        """测试重载LLM"""
        # 即使没有创建过，也能安全调用
        workflow_service.reload_llm()
        assert workflow_service.has_llm_provider() is False
