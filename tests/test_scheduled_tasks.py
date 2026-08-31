"""定时任务端到端测试 - API 层完整链路（贴合 Java 对接场景）。

复用 test_start_task_aliases 的 TestClient 启动模式。
"""
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from blog_writer.security.auth import _hash_password


@pytest.fixture
def sched_client(temp_dir, monkeypatch):
    config_path = Path(temp_dir) / "config.json"
    instance = Path(temp_dir) / "instance"
    instance.mkdir(parents=True, exist_ok=True)
    nodes = Path(__file__).resolve().parents[1] / "blog_writer" / "nodes"

    config = {
        "security": {
            "admin_password_hash": _hash_password("sched-test-pass"),
            "token_expire_hours": 1,
            "api_token": "sched-test-token",
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
    monkeypatch.setenv("BLOG_WRITER_API_TOKEN", "sched-test-token")
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

    from contextlib import ExitStack

    class _NoLimit:
        """关闭限流：测试中多次触发 /api/tasks/start 不会被 429。"""
        def is_allowed(self, *a, **k):
            return True, None

    with ExitStack() as stack:
        stack.enter_context(patch("blog_writer.main.config", cfg))
        stack.enter_context(
            patch("blog_writer.main.get_rate_limiter", return_value=_NoLimit())
        )
        from blog_writer.main import app

        with TestClient(app) as client:
            yield client


@pytest.fixture(autouse=True)
def _no_background_workflow():
    with patch("blog_writer.api.tasks._safe_start_task", return_value=None):
        yield


def _future2259():
    return (datetime.now(timezone.utc) + timedelta(hours=36)).isoformat().replace(
        "+00:00", "Z"
    )


def _past():
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


class TestScheduledApi:
    def test_create_scheduled_task_returns_scheduled(self, sched_client: TestClient):
        r = sched_client.post(
            "/api/tasks/start",
            json={
                "brandPath": "brands/sms-boosting",
                "keywords": "scheduled e2e",
                "scheduledAt": _future2259(),
            },
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["status"] == "scheduled"
        assert data["task_id"]
        assert data["scheduled_at"]

    def test_create_scheduled_does_not_start_workflow(self, sched_client: TestClient):
        # scheduled 分支不应调用 _safe_start_task（start_workflow 不触发）
        with patch(
            "blog_writer.api.tasks._safe_start_task",
            side_effect=AssertionError("scheduled 任务不应启动 workflow"),
        ):
            r = sched_client.post(
                "/api/tasks/start",
                json={
                    "brandPath": "brands/sms-boosting",
                    "keywords": "should-not-run",
                    "scheduledAt": _future2259(),
                },
            )
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "scheduled"

    def test_create_scheduled_rejects_past_time(self, sched_client: TestClient):
        # 过去时间被 assert_scheduled_at_is_future 拒绝 → 422
        r = sched_client.post(
            "/api/tasks/start",
            json={
                "brandPath": "brands/sms-boosting",
                "keywords": "past",
                "scheduledAt": _past(),
            },
        )
        assert r.status_code == 422

    def test_create_scheduled_rejects_invalid_format(self, sched_client: TestClient):
        r = sched_client.post(
            "/api/tasks/start",
            json={
                "brandPath": "brands/sms-boosting",
                "keywords": "bad",
                "scheduledAt": "not-a-date",
            },
        )
        assert r.status_code == 422

    def test_without_scheduled_keeps_legacy_behavior(self, sched_client: TestClient):
        # 不带 scheduledAt → 行为与旧版一致（status=started，触发 workflow）
        called = []
        import blog_writer.api.tasks as tasks_mod

        with patch.object(
            tasks_mod,
            "_safe_start_task",
            side_effect=lambda *a, **k: called.append(a),
        ):
            r = sched_client.post(
                "/api/tasks/start",
                json={"brandPath": "brands/sms-boosting", "keywords": "legacy path"},
            )
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "started"
        assert len(called) == 1

    def test_create_scheduled_with_callback_saved(self, sched_client: TestClient):
        # scheduled + callbackUrl：webhook 必须注册（BUG-A/B 修复回归）
        r = sched_client.post(
            "/api/tasks/start",
            json={
                "brandPath": "brands/sms-boosting",
                "keywords": "cb",
                "scheduledAt": _future2259(),
                "callbackUrl": "https://example.com/cb",
                "callbackEvents": ["task.created", "task.completed"],
            },
        )
        assert r.status_code == 200
        data = r.json()["data"]
        # 从 service 检查 webhook 已注册
        from blog_writer.service_manager import get_service
        from blog_writer.api.webhooks import get_webhook_manager

        svc = get_service()
        task = svc.get_task_status(data["task_id"])
        assert task["status"] == "scheduled"
        wm = get_webhook_manager()
        assert wm.has_callback(data["task_id"]) is True

    def test_list_tasks_includes_scheduled(self, sched_client: TestClient):
        r = sched_client.post(
            "/api/tasks/start",
            json={
                "brandPath": "brands/sms-boosting",
                "keywords": "listme",
                "scheduledAt": _future2259(),
            },
        )
        tid = r.json()["data"]["task_id"]
        r2 = sched_client.get("/api/tasks")
        tasks = r2.json()["data"]["tasks"]
        sched = [t for t in tasks if t["task_id"] == tid]
        assert len(sched) == 1
        assert sched[0]["status"] == "scheduled"

    def test_get_scheduled_detail(self, sched_client: TestClient):
        r = sched_client.post(
            "/api/tasks/start",
            json={
                "brandPath": "brands/sms-boosting",
                "keywords": "detail",
                "scheduledAt": _future2259(),
            },
        )
        tid = r.json()["data"]["task_id"]
        r2 = sched_client.get(f"/api/tasks/{tid}")
        assert r2.status_code == 200
        data = r2.json()["data"]
        assert data["status"] == "scheduled"
        # scheduled 任务点击详情不应崩溃（enrich 容错）
        assert "step_progress" in data

    def test_cancel_scheduled_task(self, sched_client: TestClient):
        r = sched_client.post(
            "/api/tasks/start",
            json={
                "brandPath": "brands/sms-boosting",
                "keywords": "cancelme",
                "scheduledAt": _future2259(),
            },
        )
        tid = r.json()["data"]["task_id"]
        r2 = sched_client.post(f"/api/tasks/{tid}/cancel")
        assert r2.status_code == 200
        r3 = sched_client.get(f"/api/tasks/{tid}")
        assert r3.json()["data"]["status"] == "cancelled"

    def test_idempotency_key_hit_scheduled(self, sched_client: TestClient):
        headers = {"Idempotency-Key": "sched-idem-key-001"}
        body = {
            "brandPath": "brands/sms-boosting",
            "keywords": "idem",
            "scheduledAt": _future2259(),
        }
        r1 = sched_client.post("/api/tasks/start", json=body, headers=headers)
        assert r1.json()["data"]["status"] == "scheduled"
        r2 = sched_client.post("/api/tasks/start", json=body, headers=headers)
        # 二次请求命中幂等键，不重复创建
        r2data = r2.json()["data"]
        assert r2data.get("idempotent_hit", False) or r2data["task_id"] == r1.json()["data"]["task_id"]

    def test_legacy_field_format_with_schedule(self, sched_client: TestClient):
        # Java brandId + keyword + scheduledAt 组合
        r = sched_client.post(
            "/api/tasks/start",
            json={
                "brandId": "sms-boosting",
                "keyword": "legacy with schedule",
                "scheduledAt": _future2259(),
            },
        )
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "scheduled"


class TestScheduledServiceDispatch:
    # 调度器到期触发：在 service 层构造已到期 scheduled 任务，验证 _dispatch_due 发现并标记 queued
    def test_dispatch_due_scheduled_marks_queued(self, workflow_service, monkeypatch):
        from datetime import datetime, timezone, timedelta

        svc = workflow_service
        # 构造一个"已到期"的 scheduled 任务
        duetime = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        scheduled_params = {
            "brand_path": "./brands/sms-boosting",
            "keywords": "due now",
            "mode": "auto",
            "priority": 2,
            "skip_visual_check": False,
            "visual_mode": "relaxed",
            "forbidden_whitelist": [],
        }
        svc.pre_register_task(
            task_id="task_due_dispatch",
            brand_path="./brands/sms-boosting",
            keywords="due now",
            priority=2,
            skip_visual_check=False,
            visual_mode="relaxed",
        )
        t = svc._tasks["task_due_dispatch"]
        t["status"] = "scheduled"
        extra = dict(t["extra"])
        extra["scheduled_at"] = duetime
        extra["scheduled_params"] = scheduled_params
        t["extra"] = extra
        svc._save_state("task_due_dispatch")

        # mock start_workflow 避免真正执行
        import asyncio

        launched = {}

        async def fake_start(**kwargs):
            launched.update(kwargs)
            return {}

        monkeypatch.setattr(svc, "start_workflow", fake_start)

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(svc._dispatch_due_scheduled_tasks())
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        # 到期任务被识别并 launch → status 变 queued，启动参数含绝对 brand_path
        assert launched.get("keywords") == "due now"
        status = svc._tasks["task_due_dispatch"]["status"]
        assert status in ("queued", "running")

    def test_scheduled_not_due_not_dispatched(self, workflow_service, monkeypatch):
        svc = workflow_service
        future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        scheduled_params = {
            "brand_path": "./brands/sms-boosting",
            "keywords": "not due",
            "mode": "auto",
            "priority": 2,
            "skip_visual_check": False,
            "visual_mode": "relaxed",
            "forbidden_whitelist": [],
        }
        svc.pre_register_task(
            task_id="task_not_due",
            brand_path="./brands/sms-boosting",
            keywords="not due",
        )
        t = svc._tasks["task_not_due"]
        t["status"] = "scheduled"
        extra = dict(t["extra"])
        extra["scheduled_at"] = future
        extra["scheduled_params"] = scheduled_params
        t["extra"] = extra
        svc._save_state("task_not_due")

        launched = {"hit": False}

        async def fake_start(**kwargs):
            launched["hit"] = True
            return {}

        monkeypatch.setattr(svc, "start_workflow", fake_start)

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(svc._dispatch_due_scheduled_tasks())
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        assert launched["hit"] is False
        assert svc._tasks["task_not_due"]["status"] == "scheduled"


class TestOvernightVisibility:
    """完整链路验证：设定时 → 跑完落库 → 服务重启（模拟过夜）→ 次日仍可见结果。"""

    def test_completed_scheduled_task_survives_restart(self, temp_dir, monkeypatch):
        # 相同节点的临时实例根与固定 sqlite 路径
        from pathlib import Path
        import json, sys
        from blog_writer.config_manager import ConfigManager
        from blog_writer.workflow_service import WorkflowService

        instance = Path(temp_dir) / "instance"
        instance.mkdir(parents=True, exist_ok=True)
        nodes = Path(__file__).resolve().parents[1] / "blog_writer" / "nodes"
        sqlite_path = instance / "blog_writer.db"

        cfg_path = Path(temp_dir) / "config.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "workflow": {
                        "nodes_dir": str(nodes),
                        "instance_root": str(instance),
                        "use_database": True,
                        "use_file_fallback": False,
                    },
                    "database": {
                        "backend": "sqlite",
                        "sqlite_path": str(sqlite_path),
                    },
                    "llm": {"models": {"default": {}}},
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # ================= 第一天：运营设置定时任务 =================
        cfg1 = ConfigManager(str(cfg_path))
        svc1 = WorkflowService(cfg1)
        svc1.pre_register_task(
            task_id="task_overnight",
            brand_path="./brands/sms-boosting",
            keywords="overnight keyword",
            scheduled_at="2099-12-31T23:00:00+08:00",
        )
        t = svc1._tasks["task_overnight"]
        t["status"] = "scheduled"
        extra = dict(t["extra"])
        extra["scheduled_at"] = "2099-12-31T23:00:00+08:00"
        extra["scheduled_params"] = {
            "brand_path": "./brands/sms-boosting",
            "keywords": "overnight keyword",
            "mode": "auto",
            "priority": 2,
            "skip_visual_check": False,
            "visual_mode": "relaxed",
            "forbidden_whitelist": [],
        }
        t["extra"] = extra
        svc1._save_state("task_overnight")  # scheduled 状态写库

        # ================= 夜里：调度器触发并跑完 =================
        t = svc1._tasks["task_overnight"]
        t["status"] = "completed"
        t["results"] = [
            {
                "node": "S007-visual",
                "output_path": "instance/task_overnight/final.md",
                "token_usage": {"total_tokens_used": 1234},
            }
        ]
        t["end_time"] = "2099-12-31T23:30:00+00:00"
        t["mode"] = "auto"
        svc1._save_state("task_overnight")  # completed 终态 + 结果写库

        # 关闭第一天服务（清理 DB 连接，模拟服务重启）
        svc1._db.close_all()
        from blog_writer.db import DatabaseManager
        if DatabaseManager._instance is not None:
            DatabaseManager._instance = None
        svc1._db = None

        # ================= 第二天：新服务实例，运营打开前端 =================
        svc2 = WorkflowService(ConfigManager(str(cfg_path)))
        tasks = svc2.list_tasks()
        overnight = [x for x in tasks if x["task_id"] == "task_overnight"]
        assert len(overnight) == 1, "任务不存在（未持久化）"
        assert overnight[0]["status"] == "completed", (
            f"状态丢失: {overnight[0]['status']}"
        )
        assert overnight[0]["keywords"] == "overnight keyword"
        assert overnight[0]["token_usage"] == 1234, (
            f"Token 用量未恢复: {overnight[0]['token_usage']}"
        )

        # 清理
        svc2._db.close_all()
        if DatabaseManager._instance is not None:
            DatabaseManager._instance = None
        svc2._db = None