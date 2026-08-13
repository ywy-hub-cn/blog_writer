"""
数据库模块测试
"""
import tempfile
import os
import json
import pytest


class TestDatabaseManager:
    """测试数据库管理器"""
    
    def test_init_creates_tables(self, temp_dir):
        from blog_writer.db import DatabaseManager
        import sqlite3
        
        db_path = os.path.join(temp_dir, "test_db.db")
        # 需要重置单例
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        
        db = DatabaseManager(db_path=db_path)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        assert "tasks" in tables
        assert "task_logs" in tables
        assert "node_definitions" in tables
        assert "audit_log" in tables
        assert "schema_version" in tables
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
    
    def test_singleton_pattern(self, temp_dir):
        from blog_writer.db import DatabaseManager
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        db1 = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        db2 = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        
        assert db1 is db2
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
    
    def test_wal_mode(self, temp_dir):
        from blog_writer.db import DatabaseManager
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        conn = db.conn
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0].lower() == "wal"
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None


class TestTaskRepository:
    """测试任务仓库"""
    
    def test_save_and_load_task(self, temp_dir):
        from blog_writer.db import DatabaseManager, TaskRepository
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        repo = TaskRepository(db)
        
        task = {
            "task_id": "test-001",
            "status": "running",
            "mode": "auto",
            "current_step": 2,
            "total_steps": 5,
            "start_time": "2024-01-01T00:00:00",
            "step_files": ["S000.json", "S001.json", "S002.json"],
            "completed_steps": ["S000.json", "S001.json"],
            "results": [{"step": "S000.json", "status": "success"}],
            "outputs": {"content": "test"},
            "retry_counts": {},
        }
        
        repo.save_task(task)
        loaded = repo.load_task("test-001")
        
        assert loaded is not None
        assert loaded["task_id"] == "test-001"
        assert loaded["status"] == "running"
        assert loaded["current_step"] == 2
        assert loaded["total_steps"] == 5
        assert loaded["step_files"] == ["S000.json", "S001.json", "S002.json"]
        assert loaded["completed_steps"] == ["S000.json", "S001.json"]
        assert len(loaded["results"]) == 1
        assert loaded["outputs"]["content"] == "test"
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
    
    def test_list_tasks(self, temp_dir):
        from blog_writer.db import DatabaseManager, TaskRepository
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        repo = TaskRepository(db)
        
        for i in range(3):
            task = {
                "task_id": f"test-{i}",
                "status": "pending" if i == 0 else "completed",
                "mode": "auto",
                "current_step": 0,
                "total_steps": 3,
                "start_time": "2024-01-01T00:00:00",
            }
            repo.save_task(task)
        
        all_tasks = repo.list_tasks()
        assert len(all_tasks) >= 3
        
        pending = repo.list_tasks(status="pending")
        assert len(pending) >= 1
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
    
    def test_delete_task(self, temp_dir):
        from blog_writer.db import DatabaseManager, TaskRepository, TaskLogRepository
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        task_repo = TaskRepository(db)
        log_repo = TaskLogRepository(db)
        
        task = {
            "task_id": "to-delete",
            "status": "completed",
            "mode": "auto",
            "current_step": 0,
            "total_steps": 1,
            "start_time": "2024-01-01T00:00:00",
        }
        task_repo.save_task(task)
        log_repo.add_log("to-delete", "test log")
        
        task_repo.delete_task("to-delete")
        
        loaded = task_repo.load_task("to-delete")
        assert loaded is None
        
        logs = log_repo.get_logs("to-delete")
        assert len(logs) == 0
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None


class TestTaskLogRepository:
    """测试任务日志仓库"""
    
    def test_add_and_get_logs(self, temp_dir):
        from blog_writer.db import DatabaseManager, TaskLogRepository, TaskRepository
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        task_repo = TaskRepository(db)
        repo = TaskLogRepository(db)
        
        # 先创建任务（满足外键约束）
        task_repo.save_task({
            "task_id": "task-001",
            "status": "running",
            "mode": "auto",
            "current_step": 0,
            "total_steps": 1,
            "start_time": "2024-01-01T00:00:00",
        })
        
        repo.add_log("task-001", "Log entry 1")
        repo.add_log("task-001", "Log entry 2")
        repo.add_log("task-001", "Log entry 3")
        
        logs = repo.get_logs("task-001")
        assert len(logs) == 3
        assert logs[0]["log_entry"] == "Log entry 1"
        assert logs[1]["log_entry"] == "Log entry 2"
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
    
    def test_count_logs(self, temp_dir):
        from blog_writer.db import DatabaseManager, TaskLogRepository, TaskRepository
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        task_repo = TaskRepository(db)
        repo = TaskLogRepository(db)
        
        # 先创建任务
        task_repo.save_task({
            "task_id": "task-count",
            "status": "running",
            "mode": "auto",
            "current_step": 0,
            "total_steps": 1,
            "start_time": "2024-01-01T00:00:00",
        })
        
        for i in range(5):
            repo.add_log("task-count", f"Log {i}")
        
        count = repo.count_logs("task-count")
        assert count == 5
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None


class TestAuditLogRepository:
    """测试审计日志仓库"""
    
    def test_log_and_query_events(self, temp_dir):
        from blog_writer.db import DatabaseManager, AuditLogRepository
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        repo = AuditLogRepository(db)
        
        repo.log_event(
            event_type="task_created",
            event_source="workflow_service",
            details="Task created: task-001",
            actor="admin"
        )
        repo.log_event(
            event_type="task_completed",
            event_source="workflow_service",
            details="Task completed: task-001",
            actor="admin"
        )
        
        events = repo.query_events(event_type="task_created")
        assert len(events) >= 1
        assert events[0]["event_type"] == "task_created"
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
    
    def test_query_with_filters(self, temp_dir):
        from blog_writer.db import DatabaseManager, AuditLogRepository
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        repo = AuditLogRepository(db)
        
        repo.log_event("login", "auth", "User logged in")
        repo.log_event("api_call", "nodes", "Node executed")
        repo.log_event("login", "auth", "User logged out")
        
        login_events = repo.query_events(event_type="login")
        assert len(login_events) >= 2
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None


class TestNodeDefinitionRepository:
    """测试节点定义仓库"""
    
    def test_save_and_load_node(self, temp_dir):
        from blog_writer.db import DatabaseManager, NodeDefinitionRepository
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        repo = NodeDefinitionRepository(db)
        
        node_def = {
            "id": "S001",
            "name": "Research",
            "exec_type": "agent_action",
            "seq": 1,
            "actions": [{"type": "search", "query": "AI trends"}],
        }
        
        repo.save_node("S001", node_def)
        loaded = repo.load_node("S001")
        
        assert loaded is not None
        assert loaded["id"] == "S001"
        assert loaded["name"] == "Research"
        assert loaded["exec_type"] == "agent_action"
        assert len(loaded["actions"]) == 1
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
    
    def test_list_nodes(self, temp_dir):
        from blog_writer.db import DatabaseManager, NodeDefinitionRepository
        
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=os.path.join(temp_dir, "test.db"))
        repo = NodeDefinitionRepository(db)
        
        repo.save_node("S001", {"id": "S001", "name": "Research", "exec_type": "agent_action", "seq": 1})
        repo.save_node("S002", {"id": "S002", "name": "Write", "exec_type": "llm_completion", "seq": 2})
        
        nodes = repo.list_nodes()
        assert len(nodes) >= 2
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None


@pytest.fixture
def temp_dir():
    """创建临时目录"""
    import tempfile
    from blog_writer.db import DatabaseManager
    
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp
        # 确保所有数据库连接已关闭
        try:
            if DatabaseManager._instance is not None:
                DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None
