"""
单元测试 conftest.py - 共享的 fixtures 和配置
"""
import os
import sys
import tempfile
import shutil
from pathlib import Path

import pytest

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from blog_writer.config_manager import ConfigManager
from blog_writer.workflow_service import WorkflowService


@pytest.fixture(autouse=True)
def cleanup_database_manager():
    """autouse fixture：每个测试后清理 DatabaseManager 单例，防止连接泄漏。"""
    yield
    try:
        from blog_writer.db import DatabaseManager, SQLDatabaseManager
        if DatabaseManager._instance is not None:
            DatabaseManager._instance.close_all()
            DatabaseManager._instance = None
        if SQLDatabaseManager._instance is not None:
            SQLDatabaseManager._instance.close_all()
            SQLDatabaseManager._instance = None
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_auth_env(monkeypatch):
    """autouse fixture：清除 .env 泄漏的认证环境变量，防止跨测试污染。

    ConfigManager._ensure_dotenv_loaded() 会加载项目根的 .env 文件，
    其中 BLOG_WRITER_ADMIN_PASSWORD 等变量会覆盖测试中通过配置文件设置的密码，
    导致认证测试失败。此 fixture 确保每个测试在干净的环境中运行。
    """
    for var in (
        "BLOG_WRITER_ADMIN_PASSWORD",
        "BLOG_WRITER_OPERATOR_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def temp_dir():
    """创建临时目录"""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def config_manager(temp_dir):
    """创建配置管理器"""
    config_path = Path(temp_dir) / "config.json"
    config = ConfigManager(str(config_path))
    return config


@pytest.fixture
def workflow_service(temp_dir, config_manager):
    """创建工作流服务"""
    nodes_dir = Path(temp_dir) / "nodes"
    instance_root = Path(temp_dir) / "instance"
    
    nodes_dir.mkdir(parents=True, exist_ok=True)
    instance_root.mkdir(parents=True, exist_ok=True)
    
    # 创建简单的节点定义
    simple_node = {
        "id": "test.step",
        "name": "Test Step",
        "seq": 1,
        "kind": "pure_code",
        "exec_type": "pure_code",
        "resources": {
            "script": "print('hello')"
        },
        "actions": [],
        "checks": []
    }
    
    with open(nodes_dir / "test-node.json", 'w') as f:
        import json
        json.dump(simple_node, f)
    
    # 覆盖配置：路径全部落在临时目录，避免相对 CWD 打不开 sqlite
    config_manager.set("workflow.nodes_dir", str(nodes_dir))
    config_manager.set("workflow.instance_root", str(instance_root))
    config_manager.set("database.backend", "sqlite")
    config_manager.set("database.sqlite_path", str(instance_root / "blog_writer.db"))
    
    service = WorkflowService(config_manager)
    yield service
    try:
        if getattr(service, "_db", None) is not None:
            service._db.close_all()
    except Exception:
        pass


@pytest.fixture
def sample_node_def():
    """示例节点定义"""
    return {
        "id": "test.sample",
        "name": "Sample Node",
        "seq": 1,
        "kind": "agent_action",
        "exec_type": "agent_action",
        "resources": {
            "prompt_template": "Test prompt",
            "system_prompt": "You are a test assistant."
        },
        "actions": [
            {
                "name": "Test Action",
                "workflow": "Do something",
                "output": {
                    "path": "output.md",
                    "name": "test_output"
                }
            }
        ],
        "checks": [
            {
                "id": "check-1",
                "rule": "文件不为空",
                "target": "file:output.md"
            }
        ]
    }


@pytest.fixture
def sample_pure_code_node():
    """示例纯代码节点定义"""
    return {
        "id": "test.pure_code",
        "name": "Pure Code Node",
        "seq": 1,
        "kind": "pure_code",
        "exec_type": "pure_code",
        "resources": {
            "script": """
import json
result = {"status": "success", "data": "test"}
with open("_output.json", "w") as f:
    json.dump(result, f)
"""
        },
        "actions": [],
        "checks": []
    }
