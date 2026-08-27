"""启动任务 API 对接字段兼容测试（Java 常见写法）。"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from blog_writer.security.auth import _hash_password


@pytest.fixture
def start_alias_client(temp_dir, monkeypatch):
    config_path = Path(temp_dir) / "config.json"
    instance = Path(temp_dir) / "instance"
    instance.mkdir(parents=True, exist_ok=True)
    nodes = Path(__file__).resolve().parents[1] / "blog_writer" / "nodes"

    config = {
        "security": {
            "admin_password_hash": _hash_password("alias-test-pass"),
            "token_expire_hours": 1,
            "api_token": "alias-test-token",
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
    monkeypatch.setenv("BLOG_WRITER_API_TOKEN", "alias-test-token")
    monkeypatch.setenv("BLOG_WRITER_STATE_BACKEND", "memory")
    monkeypatch.delenv("BLOG_WRITER_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("BLOG_WRITER_OPERATOR_PASSWORD", raising=False)

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
            yield client


@pytest.fixture(autouse=True)
def _no_background_workflow():
    with patch("blog_writer.api.tasks._safe_start_task", return_value=None):
        yield


class TestStartTaskIntegrationAliases:
    def test_accepts_brand_id_alias(self, start_alias_client: TestClient):
        r = start_alias_client.post(
            "/api/tasks/start",
            json={"brandId": "sms-boosting", "keywords": "integration test"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("code") == 0
        assert body["data"]["task_id"]

    def test_accepts_keyword_singular(self, start_alias_client: TestClient):
        r = start_alias_client.post(
            "/api/tasks/start",
            json={"brandPath": "brands/sms-boosting", "keyword": "singular keyword"},
        )
        assert r.status_code == 200
        assert r.json().get("code") == 0

    def test_accepts_keywords_list(self, start_alias_client: TestClient):
        r = start_alias_client.post(
            "/api/tasks/start",
            json={"brandId": "sms-boosting", "keywords": ["kw1", "kw2"]},
        )
        assert r.status_code == 200
        assert r.json().get("code") == 0

    def test_rejects_missing_keywords(self, start_alias_client: TestClient):
        r = start_alias_client.post("/api/tasks/start", json={"brandId": "sms-boosting"})
        assert r.status_code == 422
