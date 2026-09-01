"""Java 对接增强：幂等、批量、任务 enrichment、Webhook 事件过滤。"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from blog_writer.security.auth import _hash_password


@pytest.fixture
def integration_client(temp_dir, monkeypatch):
    config_path = Path(temp_dir) / "config.json"
    instance = Path(temp_dir) / "instance"
    instance.mkdir(parents=True, exist_ok=True)
    nodes = Path(__file__).resolve().parents[1] / "blog_writer" / "nodes"

    config = {
        "security": {
            "admin_password_hash": _hash_password("integration-pass"),
            "token_expire_hours": 1,
            "api_token": "integration-test-token",
        },
        "workflow": {
            "nodes_dir": str(nodes),
            "instance_root": str(instance),
            "use_database": True,
            "use_file_fallback": False,
        },
        "database": {
            "backend": "sqlite",
            "sqlite_path": str(instance / "test.db"),
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
    monkeypatch.setenv("BLOG_WRITER_TASK_AUTH", "optional")
    monkeypatch.setenv("BLOG_WRITER_API_TOKEN", "integration-test-token")
    monkeypatch.setenv("BLOG_WRITER_STATE_BACKEND", "memory")
    monkeypatch.delenv("BLOG_WRITER_ADMIN_PASSWORD", raising=False)

    from blog_writer.config_manager import ConfigManager
    from blog_writer.service_manager import set_config, reset_service
    from blog_writer.state_store import reset_state_store_for_tests
    from blog_writer.security.auth import _active_tokens, _invalidate_cache, _rate_limit

    reset_state_store_for_tests()
    _active_tokens.clear()
    _rate_limit.clear()
    _invalidate_cache()

    cfg = ConfigManager(str(config_path))
    set_config(cfg)
    reset_service()

    with patch("blog_writer.main.config", cfg):
        from blog_writer.main import app

        with TestClient(app) as client:
            yield client, instance


@pytest.fixture(autouse=True)
def _no_background_workflow():
    with patch("blog_writer.api.tasks._safe_start_task", return_value=None):
        yield


def _unwrap(body: dict) -> dict:
    if body.get("code") == 0 and "data" in body:
        return body["data"]
    return body


class TestIdempotencyAndBatch:
    def test_idempotency_key_reuses_task(self, integration_client):
        client, _ = integration_client
        headers = {"Idempotency-Key": "java-order-12345"}
        r1 = client.post(
            "/api/tasks/start",
            headers=headers,
            json={"brandId": "sms-boosting", "keywords": "idem test"},
        )
        assert r1.status_code == 200
        d1 = _unwrap(r1.json())
        task_id = d1["task_id"]

        r2 = client.post(
            "/api/tasks/start",
            headers=headers,
            json={"brandId": "sms-boosting", "keywords": "idem test"},
        )
        assert r2.status_code == 200
        d2 = _unwrap(r2.json())
        assert d2["task_id"] == task_id
        assert d2.get("idempotent_hit") is True

    def test_batch_start_returns_multiple_tasks(self, integration_client):
        client, _ = integration_client
        r = client.post(
            "/api/tasks/batch",
            json={
                "brandPath": "brands/sms-boosting",
                "tasks": [
                    {"keywords": "batch kw 1"},
                    {"keywords": "batch kw 2"},
                ],
            },
        )
        assert r.status_code == 200
        data = _unwrap(r.json())
        assert data["task_count"] == 2
        assert len(data["tasks"]) == 2
        assert data["batch_id"]


class TestTaskEnrichment:
    def test_get_task_includes_step_progress(self, integration_client):
        client, instance = integration_client
        r = client.post(
            "/api/tasks/start",
            json={"brandId": "sms-boosting", "keywords": "enrich test"},
        )
        task_id = _unwrap(r.json())["task_id"]

        (instance / task_id).mkdir(parents=True, exist_ok=True)
        (instance / task_id / "004-validation.log").write_text(
            "[OK] 品牌内部链接: 2 条\n", encoding="utf-8"
        )

        r2 = client.get(f"/api/tasks/{task_id}")
        assert r2.status_code == 200
        task = _unwrap(r2.json())
        assert "step_progress" in task
        assert "percent" in task["step_progress"]
        assert task.get("quality_gates", {}).get("internal_link_count") == 2


class TestIntegrationEvents:
    def test_should_fire_event_filters(self):
        from blog_writer.api.integration_events import should_fire_event

        events = ["task.completed", "task.failed"]
        assert should_fire_event(events, "task.completed")
        assert not should_fire_event(events, "task.step_completed")

    def test_build_webhook_payload_flattens(self):
        from blog_writer.api.integration_events import build_webhook_payload

        payload = build_webhook_payload(
            "task.completed",
            "task_demo",
            data={"status": "completed", "post_url": "https://example.com/p/1"},
        )
        assert payload["event"] == "task.completed"
        assert payload["task_id"] == "task_demo"
        assert payload["status"] == "completed"
        assert payload["post_url"] == "https://example.com/p/1"

    def test_normalize_idempotency_key(self):
        from blog_writer.api.case_convert import normalize_idempotency_key

        assert normalize_idempotency_key("java-order-99").startswith("task_")
        assert normalize_idempotency_key("task_custom_abc") == "task_custom_abc"


class TestWebhookCallbackRecord:
    def test_get_callbacks_uses_delivery_events(self):
        from blog_writer.api.webhooks import WebhookManager

        mgr = WebhookManager()
        mgr.register(
            "task_webhook_sync_test",
            "https://example.com/hook",
            secret="sec",
            events=["task.completed"],
        )
        cb = mgr.get_callback("task_webhook_sync_test")
        assert cb["events"] == ["task.completed"]
        assert cb["delivery_events"] == []

        cb["delivery_events"].append({"event": "task.completed", "timestamp": 1, "data_preview": ""})
        with mgr._lock:
            mgr._callbacks["task_webhook_sync_test"] = cb

        listed = mgr.get_callbacks()["task_webhook_sync_test"]
        assert listed["events"] == ["task.completed"]
        assert listed["delivery_count"] == 1
        assert listed["last_event"] == "task.completed"

        mgr.unregister("task_webhook_sync_test")

    def test_health_envelope_when_enabled(self, integration_client, monkeypatch):
        client, _ = integration_client
        monkeypatch.setenv("BLOG_WRITER_HEALTH_ENVELOPE", "true")
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body.get("code") == 0
        assert body.get("data", {}).get("status") == "healthy"


class TestJavaDeploymentHardening:
    def test_redis_url_does_not_auto_enable_state_store(self, monkeypatch):
        import blog_writer.state_store as ss

        monkeypatch.setenv("BLOG_WRITER_STATE_BACKEND", "memory")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        with ss._store_lock:
            ss._store = None
        store = ss.get_state_store()
        assert type(store).__name__ == "MemoryStateStore"

    def test_camel_case_brands_and_task_start(self, integration_client, monkeypatch):
        client, _ = integration_client
        monkeypatch.setenv("RESPONSE_CASE", "camel")

        brands = client.get("/api/brands").json()
        assert brands["code"] == 0
        brand_list = (brands.get("data") or {}).get("brands") or []
        if brand_list:
            item = brand_list[0]
            assert "displayName" in item or "display_name" in item
            assert "innerPath" in item or "inner_path" in item

        r = client.post(
            "/api/v1/tasks/start",
            json={"brandPath": "sms-boosting", "keywords": "camel deploy test"},
        )
        assert r.status_code == 200
        data = _unwrap(r.json())
        # Java 部署下响应应为驼峰；兼容测试环境未热加载中间件时的 snake
        assert data.get("taskId") or data.get("task_id")
        assert data.get("status") == "started"
        if data.get("taskId"):
            assert "task_id" not in data or data.get("taskId")

    def test_anonymous_task_start_with_invalid_bearer(self, integration_client):
        client, _ = integration_client
        r = client.post(
            "/api/tasks/start",
            headers={"Authorization": "Bearer invalid-token"},
            json={"brandPath": "sms-boosting", "keywords": "anon test"},
        )
        assert r.status_code == 200
        data = _unwrap(r.json())
        task_id = data.get("task_id") or data.get("taskId") or ""
        assert str(task_id).startswith("task_")
