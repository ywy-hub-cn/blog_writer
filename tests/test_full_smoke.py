"""全项目 API + 工具链冒烟测试（不调用真实 LLM）。"""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from blog_writer.security.auth import _hash_password

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def smoke_client(temp_dir, monkeypatch):
    config_path = Path(temp_dir) / "config.json"
    instance = Path(temp_dir) / "instance"
    instance.mkdir(parents=True, exist_ok=True)
    nodes = PROJECT_ROOT / "blog_writer" / "nodes"

    config = {
        "security": {
            "admin_password_hash": _hash_password("smoke-pass"),
            "token_expire_hours": 1,
            "api_token": "smoke-token",
            "rate_limit_per_minute": 200,
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
    monkeypatch.setenv("BLOG_WRITER_API_TOKEN", "smoke-token")
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


def _data(body: dict) -> dict:
    if body.get("code") == 0 and "data" in body:
        return body["data"]
    return body


class TestFullProjectSmoke:
    def test_root_health_ready(self, smoke_client):
        client, _ = smoke_client
        assert client.get("/").status_code == 200
        assert client.get("/health").status_code == 200
        r = client.get("/ready")
        assert r.status_code in (200, 503)

    def test_health_envelope(self, smoke_client, monkeypatch):
        client, _ = smoke_client
        monkeypatch.setenv("BLOG_WRITER_HEALTH_ENVELOPE", "true")
        body = client.get("/health").json()
        assert body.get("code") == 0
        assert body.get("data", {}).get("status") == "healthy"

    def test_auth_and_admin_routes(self, smoke_client):
        client, _ = smoke_client
        login = client.post("/api/auth/login", json={"password": "smoke-pass"})
        assert login.status_code == 200
        token = _data(login.json()).get("token")
        assert token

        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/nodes", headers=headers).status_code == 200
        assert client.get("/api/admin/config", headers=headers).status_code == 200
        assert client.get("/api/webhooks", headers=headers).status_code == 200

    def test_brands_list(self, smoke_client):
        client, _ = smoke_client
        r = client.get("/api/brands")
        assert r.status_code == 200

    def test_task_lifecycle_api(self, smoke_client):
        client, instance = smoke_client
        from blog_writer.security.auth import _rate_limit
        from blog_writer.security.rate_limiter import get_rate_limiter

        _rate_limit.clear()
        try:
            get_rate_limiter().reset()
        except Exception:
            pass

        start = client.post(
            "/api/v1/tasks/start",
            headers={"Idempotency-Key": "smoke-full-001"},
            json={
                "brandPath": "brands/sms-boosting",
                "keywords": "smoke test keyword",
                "brandSiteUrl": "https://example.com",
            },
        )
        assert start.status_code == 200
        task_id = _data(start.json())["task_id"]
        assert task_id.startswith("task_")

        dup = client.post(
            "/api/v1/tasks/start",
            headers={"Idempotency-Key": "smoke-full-001"},
            json={"brandPath": "brands/sms-boosting", "keywords": "smoke test keyword"},
        )
        assert _data(dup.json()).get("idempotent_hit") is True

        batch = client.post(
            "/api/v1/tasks/batch",
            json={
                "brandPath": "brands/sms-boosting",
                "tasks": [{"keywords": "batch a"}, {"keywords": "batch b"}],
            },
        )
        assert batch.status_code == 200
        assert _data(batch.json())["task_count"] == 2

        (instance / task_id).mkdir(parents=True, exist_ok=True)
        (instance / task_id / "004-validation.log").write_text(
            "[OK] 品牌内部链接: 1 条\n", encoding="utf-8"
        )

        detail = _data(client.get(f"/api/tasks/{task_id}").json())
        assert "step_progress" in detail
        assert detail.get("quality_gates", {}).get("internal_link_count") == 1

        listing = _data(client.get("/api/tasks").json())
        assert any(t["task_id"] == task_id for t in listing["tasks"])

        assert client.get(f"/api/tasks/{task_id}/logs").status_code == 200
        assert client.get("/api/tasks/concurrency").status_code == 200

    def test_openapi_paths_exist(self):
        spec = json.loads(
            (PROJECT_ROOT / "docs" / "integration" / "openapi.json").read_text(encoding="utf-8")
        )
        paths = spec.get("paths", {})
        for p in (
            "/api/v1/tasks/start",
            "/api/v1/tasks/batch",
            "/api/tasks/start",
            "/api/tasks/batch",
        ):
            assert p in paths, f"missing openapi path {p}"

    def test_tools_validate_and_assemble(self, tmp_path):
        spec = importlib.util.spec_from_file_location(
            "assemble_publish_smoke",
            PROJECT_ROOT / "tools" / "blog-writer" / "assemble_publish.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        draft = """# OTP SMS Guide

OTP SMS helps users verify accounts. [1][2]

## First
OTP SMS details.
## Second
OTP SMS details.
## Third
Details.
## Fourth
Details.
## FAQ
Question?
Answer.
Question?
Answer.
Question?
Answer.

[SMSBoosting OTP SMS](https://example.com/otp-sms/)

## References
- [Source One](https://external.com/one) — first claim
- [Source Two](https://external.org/two) — second claim
"""

        (tmp_path / "000 BID.json").write_text(
            json.dumps({
                "keyword": "OTP SMS",
                "title": "OTP SMS Guide",
                "slug": "otp-sms",
                "meta_description": "Guide",
                "summary": {"keyword": "OTP SMS"},
            }),
            encoding="utf-8",
        )
        (tmp_path / "001 启动确认.md").write_text("## 品牌官网\n\nhttps://example.com\n", encoding="utf-8")
        (tmp_path / "004 正文.md").write_text(draft, encoding="utf-8")
        (tmp_path / "006 呈现文档.html").write_text(
            '<div class="blog-content"><p>body</p></div>', encoding="utf-8"
        )

        v_spec = importlib.util.spec_from_file_location(
            "validate_content_smoke",
            PROJECT_ROOT / "tools" / "blog-writer" / "validate_content.py",
        )
        vmod = importlib.util.module_from_spec(v_spec)
        v_spec.loader.exec_module(vmod)
        assert vmod.validate_content(str(tmp_path), "https://example.com") is True

        _, json_path = mod.assemble(tmp_path)
        pkg = json.loads(json_path.read_text(encoding="utf-8"))
        assert pkg["schema_version"] == "1.0"
        assert pkg["brand_site_url"] == "https://example.com"
        assert mod.extract_brand_site_url(tmp_path) == "https://example.com"
