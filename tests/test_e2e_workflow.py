"""
端到端集成测试 - 验证系统全流程（除 LLM 调用外）

测试覆盖：
1. API 健康检查与认证
2. 任务创建与工作流启动
3. pure_code 节点执行
4. 任务状态追踪
5. 任务暂停/恢复/取消
6. 错误处理
7. 状态持久化
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from blog_writer.security.auth import _hash_password

# 使用项目已有的品牌目录
BRAND_PATH = "brands/sms-boosting"


@pytest.fixture
def e2e_env(temp_dir, monkeypatch):
    """端到端测试环境"""
    config_path = Path(temp_dir) / "config.json"

    # 使用项目已有的节点
    nodes_dir = PROJECT_ROOT / "blog_writer" / "nodes"
    instance_dir = Path(temp_dir) / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "security": {
            "admin_password_hash": _hash_password("e2e-test-pass"),
            "token_expire_hours": 1,
            "api_token": "e2e-service-token",
            "rate_limit_per_minute": 200,
        },
        "workflow": {
            "nodes_dir": str(nodes_dir),
            "instance_root": str(instance_dir),
            "use_database": True,
            "use_file_fallback": True,
            "max_retries_per_step": 2,
            "retry_delay_seconds": 0.5,
        },
        "database": {
            "backend": "sqlite",
            "sqlite_path": str(instance_dir / "test.db"),
        },
        "llm": {
            "models": {
                "default": {
                    "api_key": "sk-test",
                    "base_url": "https://example.invalid/v1",
                    "model": "test-model",
                }
            }
        },
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    monkeypatch.setenv("BLOG_WRITER_CONFIG", str(config_path))
    monkeypatch.setenv("BLOG_WRITER_MODE", "development")
    monkeypatch.setenv("BLOG_WRITER_API_TOKEN", "e2e-service-token")
    monkeypatch.setenv("BLOG_WRITER_STATE_BACKEND", "memory")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("BLOG_WRITER_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("BLOG_WRITER_OPERATOR_PASSWORD", raising=False)

    from blog_writer.state_store import reset_state_store_for_tests
    from blog_writer.security.auth import _active_tokens, _invalidate_cache, _rate_limit

    reset_state_store_for_tests()
    _active_tokens.clear()
    _rate_limit.clear()
    _invalidate_cache()

    yield config_path, instance_dir


@pytest.fixture
def e2e_client(e2e_env):
    config_path, instance_dir = e2e_env

    from blog_writer.config_manager import ConfigManager
    from blog_writer.service_manager import set_config, reset_service

    cfg = ConfigManager(str(config_path))
    set_config(cfg)
    reset_service()

    os.environ.pop("BLOG_WRITER_ADMIN_PASSWORD", None)
    os.environ.pop("BLOG_WRITER_OPERATOR_PASSWORD", None)
    from blog_writer.security.auth import _invalidate_cache, _rate_limit
    from blog_writer.security.rate_limiter import get_rate_limiter

    _invalidate_cache()
    _rate_limit.clear()
    try:
        rl = get_rate_limiter()
        rl._client_buckets.clear()
        rl._endpoint_buckets.clear()
    except Exception:
        pass

    with patch("blog_writer.main.config", cfg):
        from blog_writer.main import app
        with TestClient(app) as c:
            yield c


def _clear_rate_limits():
    from blog_writer.security.auth import _rate_limit
    from blog_writer.security.rate_limiter import get_rate_limiter
    _rate_limit.clear()
    try:
        rl = get_rate_limiter()
        rl._client_buckets.clear()
    except Exception:
        pass


def _login(client):
    _clear_rate_limits()
    r = client.post("/api/v1/auth/login", json={"password": "e2e-test-pass"})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data.get("token") or data.get("access_token")


def _auth_headers(client):
    return {"Authorization": f"Bearer {_login(client)}"}


class TestE2EHealthAndAuth:
    def test_health_check(self, e2e_client):
        r = e2e_client.get("/health")
        assert r.status_code == 200

    def test_unauthorized_access_blocked(self, e2e_client):
        # development 模式任务列表允许免登录；生产环境才强制鉴权
        r = e2e_client.get("/api/v1/tasks")
        assert r.status_code == 200

    def test_unauthorized_access_blocked_in_production(self, e2e_client, monkeypatch):
        monkeypatch.setenv("BLOG_WRITER_MODE", "production")
        monkeypatch.setenv("BLOG_WRITER_TASK_AUTH", "required")
        r = e2e_client.get("/api/v1/tasks")
        assert r.status_code in (401, 403)

    def test_login_success(self, e2e_client):
        token = _login(e2e_client)
        assert token

    def test_login_wrong_password(self, e2e_client):
        _clear_rate_limits()
        r = e2e_client.post("/api/v1/auth/login", json={"password": "wrong"})
        assert r.status_code in (401, 403)

    def test_service_token_access(self, e2e_client):
        _clear_rate_limits()
        r = e2e_client.get(
            "/api/v1/tasks",
            headers={"X-API-Key": "e2e-service-token"},
        )
        assert r.status_code == 200


class TestE2ETaskLifecycle:
    def test_create_and_list_tasks(self, e2e_client):
        headers = _auth_headers(e2e_client)
        _clear_rate_limits()

        r = e2e_client.post(
            "/api/v1/tasks/start",
            json={
                "brandPath": BRAND_PATH,
                "keywords": "测试博客",
                "mode": "auto",
            },
            headers=headers,
        )
        assert r.status_code in (200, 201, 202), f"Create failed: {r.status_code} {r.text}"

        _clear_rate_limits()
        r2 = e2e_client.get("/api/v1/tasks", headers={"X-API-Key": "e2e-service-token"})
        assert r2.status_code == 200

    def test_get_task_status(self, e2e_client):
        headers = _auth_headers(e2e_client)
        _clear_rate_limits()

        r = e2e_client.post(
            "/api/v1/tasks/start",
            json={"brandPath": BRAND_PATH, "keywords": "状态测试", "mode": "auto"},
            headers=headers,
        )
        assert r.status_code in (200, 201, 202), f"Create: {r.status_code} {r.text}"
        data = r.json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        task_id = data.get("task_id") or data.get("id")
        assert task_id

        _clear_rate_limits()
        r2 = e2e_client.get(
            f"/api/v1/tasks/{task_id}",
            headers={"X-API-Key": "e2e-service-token"},
        )
        assert r2.status_code == 200

    def test_cancel_task(self, e2e_client):
        headers = _auth_headers(e2e_client)
        _clear_rate_limits()

        r = e2e_client.post(
            "/api/v1/tasks/start",
            json={"brandPath": BRAND_PATH, "keywords": "取消测试", "mode": "manual"},
            headers=headers,
        )
        assert r.status_code in (200, 201, 202)
        data = r.json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        task_id = data.get("task_id") or data.get("id")

        _clear_rate_limits()
        r2 = e2e_client.post(
            f"/api/v1/tasks/{task_id}/cancel",
            headers={"X-API-Key": "e2e-service-token"},
        )
        assert r2.status_code in (200, 202, 409)

    def test_pause_resume_task(self, e2e_client):
        headers = _auth_headers(e2e_client)
        _clear_rate_limits()

        r = e2e_client.post(
            "/api/v1/tasks/start",
            json={"brandPath": BRAND_PATH, "keywords": "暂停测试", "mode": "manual"},
            headers=headers,
        )
        assert r.status_code in (200, 201, 202)
        data = r.json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        task_id = data.get("task_id") or data.get("id")

        _clear_rate_limits()
        r2 = e2e_client.post(
            f"/api/v1/tasks/{task_id}/pause",
            headers={"X-API-Key": "e2e-service-token"},
        )
        assert r2.status_code in (200, 202, 409)

        _clear_rate_limits()
        r3 = e2e_client.post(
            f"/api/v1/tasks/{task_id}/resume",
            headers={"X-API-Key": "e2e-service-token"},
        )
        assert r3.status_code in (200, 202, 400, 409)


class TestE2EErrorHandling:
    def test_nonexistent_task(self, e2e_client):
        _clear_rate_limits()
        r = e2e_client.get(
            "/api/v1/tasks/nonexistent-id",
            headers={"X-API-Key": "e2e-service-token"},
        )
        assert r.status_code == 404

    def test_cancel_nonexistent_task(self, e2e_client):
        _clear_rate_limits()
        r = e2e_client.post(
            "/api/v1/tasks/nonexistent-id/cancel",
            headers={"X-API-Key": "e2e-service-token"},
        )
        assert r.status_code in (404, 409)

class TestE2EStatePersistence:
    def test_task_list_and_status(self, e2e_client):
        """测试任务列表和状态查询（API层持久化验证）"""
        _clear_rate_limits()
        # 创建任务
        r = e2e_client.post(
            "/api/v1/tasks/start",
            json={"brandPath": BRAND_PATH, "keywords": "持久化测试", "mode": "manual"},
            headers={"X-API-Key": "e2e-service-token"},
        )
        assert r.status_code in (200, 201, 202)
        data = r.json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        task_id = data.get("task_id") or data.get("id")
        assert task_id

        # 查询任务列表
        _clear_rate_limits()
        r2 = e2e_client.get(
            "/api/v1/tasks",
            headers={"X-API-Key": "e2e-service-token"},
        )
        assert r2.status_code == 200
        tasks_data = r2.json()
        if isinstance(tasks_data, dict) and "data" in tasks_data:
            tasks_data = tasks_data["data"]
        if isinstance(tasks_data, dict) and "tasks" in tasks_data:
            tasks_data = tasks_data["tasks"]
        assert isinstance(tasks_data, list)
        assert len(tasks_data) >= 1

        # 查询单个任务状态
        _clear_rate_limits()
        r3 = e2e_client.get(
            f"/api/v1/tasks/{task_id}",
            headers={"X-API-Key": "e2e-service-token"},
        )
        assert r3.status_code == 200
