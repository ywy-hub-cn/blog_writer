"""回归：解析 file::exec check、finalize 保留 failed、本轮安全与状态修复。"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from blog_writer.agent.base_executor import BaseExecutor
from blog_writer.agent.executor import AgentExecutor


def test_parse_check_target_with_exec():
    t, path, cmd = BaseExecutor.parse_check_target(
        "file:发布记录.json::exec:python3 -c 'print(1)'"
    )
    assert t == "file"
    assert path == "发布记录.json"
    assert cmd.startswith("python3")


@pytest.mark.asyncio
async def test_exec_check_post_id(tmp_path: Path):
    (tmp_path / "发布记录.json").write_text(
        '{"post_id": 0, "status": "draft"}', encoding="utf-8"
    )

    class DummyLLM:
        def get_stats(self):
            return {}

        async def chat(self, **kwargs):
            raise RuntimeError("no llm")

    # 使用单引号包裹 -c 代码，避免转义歧义
    exec_cmd = (
        "python -c 'import json; d=json.load(open(\"发布记录.json\",encoding=\"utf-8\")); "
        "raise SystemExit(0 if d.get(\"post_id\",0)>0 else 1)'"
    )
    node = {
        "id": "step.blog.writer.publish_wp",
        "name": "wp",
        "checks": [
            {
                "id": 2,
                "rule": "post_id>0",
                "target": f"file:发布记录.json::exec:{exec_cmd}",
            }
        ],
    }
    ex = AgentExecutor(
        llm_provider=DummyLLM(),
        node_definition=node,
        instance_dir=str(tmp_path),
        max_iterations=1,
    )
    t, path, cmd = BaseExecutor.parse_check_target(node["checks"][0]["target"])
    assert t == "file" and path == "发布记录.json" and cmd
    ok = await ex._run_checks()
    assert ok is False


def test_finalize_preserves_failed(temp_dir, config_manager):
    from blog_writer.workflow_service import WorkflowService

    svc = WorkflowService(config=config_manager)
    tid = "t-fail-preserve"
    svc._tasks[tid] = {
        "task_id": tid,
        "status": "failed",
        "completed_steps": [],
        "results": [],
        "outputs": {},
        "step_files": ["a.json"],
    }
    out = svc._finalize_task(
        tid,
        [{"step": "a.json", "status": "partial"}],
        {},
        ["a.json"],
        lambda m: None,
    )
    assert out["status"] == "failed"


def test_finalize_partial_not_completed(temp_dir, config_manager):
    from blog_writer.workflow_service import WorkflowService

    svc = WorkflowService(config=config_manager)
    tid = "t-partial"
    svc._tasks[tid] = {
        "task_id": tid,
        "status": "running",
        "completed_steps": ["a.json"],
        "results": [],
        "outputs": {},
        "step_files": ["a.json"],
    }
    out = svc._finalize_task(
        tid,
        [{"step": "a.json", "status": "partial"}],
        {},
        ["a.json"],
        lambda m: None,
    )
    assert out["status"] == "completed_partial"


def test_review_decision_roundtrip_via_extra(temp_dir, config_manager):
    from blog_writer.workflow_service import WorkflowService

    svc = WorkflowService(config=config_manager)
    tid = "t-review-extra"
    svc._tasks[tid] = {
        "task_id": tid,
        "status": "waiting_review",
        "mode": "manual",
        "current_step": 0,
        "total_steps": 1,
        "start_time": "2024-01-01T00:00:00",
        "brand_path": "",
        "keywords": "",
        "step_files": ["s.json"],
        "completed_steps": [],
        "results": [],
        "outputs": {},
        "retry_counts": {},
        "review_decision": "approve",
        "review_modifications": {"note": "ok"},
        "extra": {},
    }
    svc._save_state(tid)
    # 模拟内存丢失后从持久化恢复
    del svc._tasks[tid]
    loaded = svc._ensure_task_loaded(tid)
    assert loaded is not None
    assert loaded.get("review_decision") == "approve"
    assert loaded.get("review_modifications", {}).get("note") == "ok"


def test_resolve_client_ip_ignores_xff_from_untrusted(monkeypatch):
    from blog_writer.api.deps import resolve_client_ip

    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1")
    req = MagicMock()
    req.client.host = "203.0.113.9"
    req.headers.get = lambda k, d="": "10.0.0.1" if k == "x-forwarded-for" else d
    assert resolve_client_ip(req) == "203.0.113.9"


def test_resolve_client_ip_trusts_xff_from_proxy(monkeypatch):
    from blog_writer.api.deps import resolve_client_ip

    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1,10.0.0.1")
    req = MagicMock()
    req.client.host = "10.0.0.1"
    req.headers.get = (
        lambda k, d="": "198.51.100.7, 10.0.0.1" if k == "x-forwarded-for" else d
    )
    assert resolve_client_ip(req) == "198.51.100.7"


def test_endpoint_prefix_limit():
    from blog_writer.security.rate_limiter import RateLimiter

    limiter = RateLimiter(
        global_rate=1000,
        global_burst=500,
        per_client_rate=100,
        per_client_window=60,
        audit_enabled=False,
    )
    limiter.set_endpoint_limit("/api/admin/", 2, 60)
    cid = "c1"
    assert limiter.is_allowed(cid, "/api/admin/users")[0] is True
    assert limiter.is_allowed(cid, "/api/admin/config")[0] is True
    allowed, reason = limiter.is_allowed(cid, "/api/admin/nodes")
    assert allowed is False
    assert "Endpoint" in reason


def test_finalize_collapses_retry_errors(temp_dir, config_manager):
    from blog_writer.workflow_service import WorkflowService

    svc = WorkflowService(config=config_manager)
    tid = "t-retry-ok"
    svc._tasks[tid] = {
        "task_id": tid,
        "status": "running",
        "completed_steps": ["a.json"],
        "results": [],
        "outputs": {},
        "step_files": ["a.json"],
    }
    out = svc._finalize_task(
        tid,
        [
            {"step": "a.json", "status": "error"},
            {"step": "a.json", "status": "success"},
        ],
        {},
        ["a.json"],
        lambda m: None,
    )
    assert out["status"] == "completed"
    assert len(out["results"]) == 1
    assert out["results"][0]["status"] == "success"


def test_validate_task_id_rejects_traversal():
    from blog_writer.security.path_security import validate_task_id, safe_basename

    assert validate_task_id("task_2024_ab12") is True
    assert validate_task_id("../etc") is False
    assert validate_task_id("a/b") is False
    assert validate_task_id("a\\b") is False
    assert safe_basename("../../x.json") == "x.json"
    assert safe_basename(None) == "file.json"


def test_cancel_waiting_review_persists_reject(temp_dir, config_manager):
    from blog_writer.workflow_service import WorkflowService

    svc = WorkflowService(config=config_manager)
    tid = "t-cancel-review"
    svc._tasks[tid] = {
        "task_id": tid,
        "status": "waiting_review",
        "mode": "manual",
        "current_step": 0,
        "total_steps": 1,
        "start_time": "2024-01-01T00:00:00",
        "brand_path": "",
        "keywords": "",
        "step_files": ["s.json"],
        "completed_steps": [],
        "results": [],
        "outputs": {},
        "retry_counts": {},
        "extra": {},
    }
    assert svc.cancel_task(tid) is True
    assert svc._tasks[tid]["status"] == "cancelled"
    assert svc._tasks[tid]["review_decision"] == "reject"


def test_save_task_preserves_logs(temp_dir):
    """INSERT OR REPLACE 曾因 CASCADE 清空 task_logs；UPSERT 后应保留。"""
    import os
    from blog_writer.db import DatabaseManager, TaskRepository, TaskLogRepository

    try:
        if DatabaseManager._instance is not None:
            DatabaseManager._instance.close_all()
    except Exception:
        pass
    DatabaseManager._instance = None

    db = DatabaseManager(db_path=os.path.join(temp_dir, "upsert_logs.db"))
    tasks = TaskRepository(db)
    logs = TaskLogRepository(db)
    tid = "upsert-log-task"
    tasks.save_task({
        "task_id": tid,
        "status": "running",
        "mode": "auto",
        "current_step": 0,
        "total_steps": 1,
        "start_time": "2024-01-01T00:00:00",
    })
    logs.add_log(tid, "first")
    tasks.save_task({
        "task_id": tid,
        "status": "running",
        "mode": "auto",
        "current_step": 1,
        "total_steps": 1,
        "start_time": "2024-01-01T00:00:00",
        "keywords": "k",
    })
    assert len(logs.get_logs(tid)) == 1
    assert logs.get_logs(tid)[0]["log_entry"] == "first"

    try:
        if DatabaseManager._instance is not None:
            DatabaseManager._instance.close_all()
    except Exception:
        pass
    DatabaseManager._instance = None


def test_webhook_url_blocks_private(monkeypatch):
    from blog_writer.security.url_safety import is_safe_webhook_url

    assert is_safe_webhook_url("http://127.0.0.1/hook", resolve_dns=False)[0] is False
    assert is_safe_webhook_url("http://localhost/hook", resolve_dns=False)[0] is False
    assert is_safe_webhook_url("http://10.0.0.5/x", resolve_dns=False)[0] is False
    assert is_safe_webhook_url("https://example.com/cb", resolve_dns=False)[0] is True


def test_prune_outputs_for_steps():
    from blog_writer.workflow.helpers import prune_outputs_for_steps

    def load_node(sf):
        return {
            "actions": [
                {"name": "draft", "output": {"id": "draft_id", "path": "001 草稿.md"}}
            ]
        }

    outputs = {
        "draft": "x",
        "draft_id": "x",
        "001 草稿.md": "x",
        "001_草稿.md": "x",
        "keep_me": "y",
    }
    pruned = prune_outputs_for_steps(outputs, {"S005.json"}, load_node)
    assert "keep_me" in pruned
    assert "draft" not in pruned
    assert "draft_id" not in pruned


@pytest.mark.asyncio
async def test_exec_check_rejects_shell():
    from blog_writer.agent.base_executor import BaseExecutor

    class Dummy(BaseExecutor):
        def __init__(self):
            self.instance_dir = "."
            self.logs = []

        def log(self, msg):
            self.logs.append(msg)

        async def _evaluate_check(self, rule, target):
            return True

        async def execute(self, params):
            return {}

    d = Dummy()
    ok = await d._run_exec_check("echo hi")
    assert ok is False
    assert any("rejected" in x for x in d.logs)


def test_task_access_owner_isolation():
    from blog_writer.api.task_access import assert_task_access, filter_tasks_for_user
    import pytest
    from fastapi import HTTPException

    admin = {"user_id": "admin", "role": "admin"}
    user_a = {"user_id": "a", "role": "user"}
    user_b = {"user_id": "b", "role": "user"}
    task = {"task_id": "t1", "owner_id": "a", "extra": {"owner_id": "a"}}
    assert assert_task_access(admin, task) is task
    assert assert_task_access(user_a, task) is task
    with pytest.raises(HTTPException) as ei:
        assert_task_access(user_b, task)
    assert ei.value.status_code == 404
    tasks = filter_tasks_for_user(user_a, [task, {"task_id": "t2", "owner_id": "b"}])
    assert len(tasks) == 1 and tasks[0]["task_id"] == "t1"


def test_normalize_step_files_rejects_unknown(temp_dir, config_manager):
    from blog_writer.workflow_service import WorkflowService
    import pytest

    svc = WorkflowService(config=config_manager)
    # monkey registry
    svc.load_registry = lambda: {"step_order": ["a.json", "b.json"]}
    assert svc.normalize_step_files(["b.json", "a.json"]) == ["a.json", "b.json"]
    with pytest.raises(ValueError):
        svc.normalize_step_files(["evil.json"])


def test_pre_register_rejects_duplicate(temp_dir, config_manager):
    from blog_writer.workflow_service import WorkflowService
    import pytest

    svc = WorkflowService(config=config_manager)
    tid = "dup-task-1"
    svc.pre_register_task(tid, brand_path="b", keywords="k")
    with pytest.raises(ValueError, match="已存在"):
        svc.pre_register_task(tid, brand_path="b", keywords="k")


def test_find_node_file_rejects_traversal(temp_dir):
    from pathlib import Path
    from blog_writer.node_utils import find_node_file

    nodes = Path(temp_dir) / "nodes"
    nodes.mkdir()
    (nodes / "S001.json").write_text('{"id":"step.a","name":"a"}', encoding="utf-8")
    secret = Path(temp_dir) / "secret.json"
    secret.write_text('{"leak":true}', encoding="utf-8")
    assert find_node_file(nodes, "../secret.json") is None
    assert find_node_file(nodes, "..\\secret.json") is None
    assert find_node_file(nodes, "S001.json") is not None


def test_approve_review_rejects_overwrite(temp_dir, config_manager):
    import asyncio
    from blog_writer.workflow_service import WorkflowService

    svc = WorkflowService(config=config_manager)
    tid = "t-review-once"
    svc._pause_events[tid] = asyncio.Event()
    svc._tasks[tid] = {
        "task_id": tid,
        "status": "waiting_review",
        "mode": "manual",
        "step_files": ["s.json"],
        "completed_steps": [],
        "results": [],
        "outputs": {},
        "retry_counts": {},
        "extra": {},
    }
    assert svc.approve_review(tid, "approve") is True
    # 不同决策不可覆盖
    assert svc.approve_review(tid, "reject") is False
    assert svc._tasks[tid]["review_decision"] == "approve"
    # 相同决策幂等
    assert svc.approve_review(tid, "approve") is True


def test_sso_fetch_userinfo_fails_closed():
    from blog_writer.integrations import SSOAuthProvider

    p = SSOAuthProvider({"security": {"sso": {"enabled": True, "userinfo_url": ""}}})
    assert p._fetch_user_info("tok", {"userinfo_url": ""}) is None


def test_revoke_all_tokens_clears_memory_and_store(temp_dir, monkeypatch):
    from blog_writer.security.auth import AuthManager, _active_tokens, _persist_token
    from blog_writer.state_store import get_state_store, reset_state_store_for_tests

    monkeypatch.setenv("BLOG_WRITER_STATE_BACKEND", "memory")
    monkeypatch.delenv("REDIS_URL", raising=False)
    reset_state_store_for_tests()
    _active_tokens.clear()

    _persist_token("tok-a", {"expire_at": 9e12, "created_at": 1}, 3600)
    _persist_token("tok-b", {"expire_at": 9e12, "created_at": 1}, 3600)
    assert AuthManager.verify_token("tok-a")
    n = AuthManager.revoke_all_tokens()
    assert n >= 2
    assert not AuthManager.verify_token("tok-a")
    assert not AuthManager.verify_token("tok-b")
    assert get_state_store().keys("blog_writer:auth:token:") == []


@pytest.mark.asyncio
async def test_step_timeout_via_wait_for():
    """单步执行超时应抛 asyncio.TimeoutError（编排层会记 error）。"""
    import asyncio

    async def slow():
        await asyncio.sleep(1)
        return {"status": "success"}

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(slow(), timeout=0.05)


@pytest.mark.asyncio
async def test_sso_blocks_local_password_login(monkeypatch):
    """启用 SSO 且未允许本地降级时，password-only 登录应 401。"""
    from fastapi import HTTPException, Request
    from unittest.mock import MagicMock
    from blog_writer.api import auth as auth_mod

    class FakeCfg:
        def get_all(self):
            return {
                "security": {
                    "sso": {"enabled": True, "allow_local_fallback": False},
                }
            }

    monkeypatch.setattr(
        "blog_writer.service_manager.get_config",
        lambda: FakeCfg(),
    )
    auth_mod.reset_auth_provider_cache()

    class FakeProvider:
        def authenticate(self, credentials):
            return None

    monkeypatch.setattr(auth_mod, "_get_auth_provider", lambda: FakeProvider())

    req = MagicMock(spec=Request)
    login_req = auth_mod.LoginRequest(password="test-admin-pass")
    with pytest.raises(HTTPException) as ei:
        await auth_mod.login(req, login_req)
    assert ei.value.status_code == 401
    assert "SSO" in str(ei.value.detail)


def test_sso_allow_local_fallback_helper(monkeypatch):
    from blog_writer.api import auth as auth_mod

    class FakeCfg:
        def get_all(self):
            return {"security": {"sso": {"enabled": True, "allow_local_fallback": True}}}

    monkeypatch.setattr(
        "blog_writer.service_manager.get_config",
        lambda: FakeCfg(),
    )
    assert auth_mod._is_sso_enabled() is True
    assert auth_mod._allow_local_fallback() is True


def test_mysql_task_logs_ddl_uses_varchar():
    from blog_writer.db import _MYSQL_CREATE_TABLES_SQL

    logs_ddl = next(s for s in _MYSQL_CREATE_TABLES_SQL if "task_logs" in s and "log_entry" in s)
    assert "task_id VARCHAR(255)" in logs_ddl
    assert "task_id TEXT" not in logs_ddl


def test_sanitize_config_nested_secrets():
    from blog_writer.api.admin.config import _sanitize_config_update

    raw = {
        "security": {
            "sso": {
                "enabled": True,
                "client_secret": "real-secret",
                "api_token": "****hidden",
            }
        },
        "api_key": "****",
    }
    cleaned = _sanitize_config_update(raw)
    assert cleaned["security"]["sso"]["enabled"] is True
    assert cleaned["security"]["sso"]["client_secret"] == "real-secret"
    assert "api_token" not in cleaned["security"]["sso"]
    assert "api_key" not in cleaned


def test_sso_flags_helper():
    from blog_writer.api.admin.config import _sso_flags

    assert _sso_flags({"security": {"sso": {"enabled": True}}}) == (True, False)
    assert _sso_flags({"sso": {"enabled": True, "allow_local_fallback": True}}) == (True, True)
    assert _sso_flags({}) == (False, False)


@pytest.mark.asyncio
async def test_safe_start_task_no_wait_for_by_default(monkeypatch):
    import asyncio
    from blog_writer.api import tasks as tasks_mod

    monkeypatch.delenv("BLOG_WRITER_TASK_TIMEOUT_SECONDS", raising=False)
    called = {"wait_for": False}
    real_wait_for = asyncio.wait_for

    async def spy_wait_for(coro, timeout=None):
        called["wait_for"] = True
        return await real_wait_for(coro, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait_for", spy_wait_for)

    async def quick():
        return "done"

    await tasks_mod._safe_start_task(quick(), task_id=None)
    assert called["wait_for"] is False


@pytest.mark.asyncio
async def test_safe_start_task_env_timeout_marks_failed(monkeypatch, temp_dir, config_manager):
    import asyncio
    from blog_writer.api import tasks as tasks_mod
    from blog_writer.workflow_service import WorkflowService

    monkeypatch.setenv("BLOG_WRITER_TASK_TIMEOUT_SECONDS", "0.05")
    svc = WorkflowService(config=config_manager)
    tid = "t-overall-timeout"
    svc._tasks[tid] = {
        "task_id": tid,
        "status": "running",
        "extra": {},
        "step_files": [],
        "completed_steps": [],
        "results": [],
        "outputs": {},
    }
    monkeypatch.setattr(tasks_mod, "get_service", lambda: svc)

    async def slow():
        await asyncio.sleep(1)

    await tasks_mod._safe_start_task(slow(), task_id=tid)
    assert svc._tasks[tid]["status"] == "failed"
    assert "timeout" in (svc._tasks[tid].get("extra") or {}).get("last_error", "")


def test_node_schema_rejects_path_id():
    from blog_writer.node_utils import validate_node_schema

    bad = {
        "id": "../evil",
        "name": "x",
        "seq": 1,
        "kind": "pure_code",
        "actions": [],
        "checks": [],
    }
    result = validate_node_schema(bad)
    assert result["valid"] is False
    assert any("路径" in e or ".." in e for e in result["errors"])


def test_resume_brand_path_rejects_traversal():
    from pydantic import ValidationError
    from blog_writer.api.tasks import ResumeFromRequest

    with pytest.raises(ValidationError):
        ResumeFromRequest(nodeFile="a.json", brandPath="../etc")


def test_review_decision_state_store_roundtrip(monkeypatch):
    from blog_writer.state_store import reset_state_store_for_tests
    from blog_writer.workflow import review_wait as rw

    monkeypatch.setenv("BLOG_WRITER_STATE_BACKEND", "memory")
    monkeypatch.delenv("REDIS_URL", raising=False)
    reset_state_store_for_tests()

    rw.publish_review_decision("t1", "approve", {"note": "ok"})
    data = rw.load_external_review_decision("t1")
    assert data["decision"] == "approve"
    assert data["modifications"]["note"] == "ok"
    rw.clear_external_review_decision("t1")
    assert rw.load_external_review_decision("t1") is None


def test_get_llm_provider_caches_by_model(temp_dir, config_manager):
    from blog_writer.workflow_service import WorkflowService

    # 注入第二模型配置
    config_manager.set("llm.models.review", {
        "provider": "openai_compatible",
        "base_url": "https://example.invalid/v1",
        "api_key": "sk-x",
        "model": "review-model",
        "temperature": 0.2,
        "max_tokens": 1024,
        "timeout": 30,
    })
    svc = WorkflowService(config=config_manager)
    a = svc.get_llm_provider("default")
    b = svc.get_llm_provider("review")
    c = svc.get_llm_provider("default")
    assert a is c
    assert a is not b
    assert getattr(b, "model", None) == "review-model"


@pytest.mark.asyncio
async def test_await_human_review_picks_up_external_decision(
    temp_dir, config_manager, monkeypatch
):
    import asyncio
    from blog_writer.state_store import reset_state_store_for_tests
    from blog_writer.workflow import review_wait as rw
    from blog_writer.workflow_service import WorkflowService

    monkeypatch.setenv("BLOG_WRITER_STATE_BACKEND", "memory")
    monkeypatch.delenv("REDIS_URL", raising=False)
    reset_state_store_for_tests()

    svc = WorkflowService(config=config_manager)
    tid = "t-ext-review"
    svc._tasks[tid] = {
        "task_id": tid,
        "status": "running",
        "keywords": "k",
        "extra": {},
        "completed_steps": [],
        "results": [],
        "outputs": {},
    }
    logs = []

    async def _approve_soon():
        await asyncio.sleep(0.2)
        rw.publish_review_decision(tid, "approve", {})

    asyncio.create_task(_approve_soon())
    cancelled, decision, mods = await svc._await_human_review(
        tid,
        node_id="n1",
        node_name="review",
        step_file="r.json",
        mode="supervised",
        outputs={},
        node_results=[],
        task_log=logs.append,
        reason="test",
        poll_seconds=0.1,
    )
    assert cancelled is False
    assert decision == "approve"


def test_resolve_step_timeout_prefers_node():
    from blog_writer.workflow.budgets import resolve_step_timeout_seconds

    seconds, mins = resolve_step_timeout_seconds(
        global_minutes=10,
        node_def={"resources": {"step_timeout_minutes": 0.5}},
    )
    assert mins == 0.5
    assert seconds == 30.0  # clamp lower bound


def test_token_budget_exceeded():
    from blog_writer.workflow.budgets import token_budget_exceeded

    results = [
        {"token_usage": {"total_tokens": 100}},
        {"token_usage": {"total_tokens_used": 50}},
    ]
    exceeded, used, limit = token_budget_exceeded(results, 120)
    assert exceeded is True
    assert used == 150
    assert limit == 120
    ok, used2, limit2 = token_budget_exceeded(results, 0)
    assert ok is False and limit2 == 0


def test_task_control_mixin_on_service(temp_dir, config_manager):
    from blog_writer.workflow.task_control import TaskControlMixin
    from blog_writer.workflow_service import WorkflowService

    svc = WorkflowService(config=config_manager)
    assert isinstance(svc, TaskControlMixin)
    tid = "t-pause"
    svc._tasks[tid] = {"task_id": tid, "status": "running", "extra": {}}
    assert svc.pause_task(tid) is True
    assert svc._tasks[tid]["status"] == "paused"


# --- code-review-cursor-prompts.md 选定修复回归 ---


def test_env_overrides_config_when_nonempty(monkeypatch, temp_dir):
    from blog_writer.config_manager import ConfigManager

    cfg_path = Path(temp_dir) / "cfg.json"
    cfg_path.write_text(
        json.dumps(
            {
                "security": {
                    "admin_password": "from-file",
                    "admin_password_env": "BLOG_WRITER_ADMIN_PASSWORD",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BLOG_WRITER_ADMIN_PASSWORD", "from-env")
    cm = ConfigManager(str(cfg_path), auto_reload=False)
    assert cm.get("security.admin_password") == "from-env"


def test_node_backup_version_increments_after_delete(temp_dir):
    from blog_writer.config_manager import NodeBackupManager

    nodes = Path(temp_dir) / "nodes"
    backup = Path(temp_dir) / "backup"
    nodes.mkdir()
    (nodes / "S001-demo.json").write_text('{"id":"S001"}', encoding="utf-8")
    mgr = NodeBackupManager(str(nodes), str(backup), max_versions=10)
    v1 = mgr.backup_node("S001")
    assert v1 and v1.endswith("_v1")
    v2 = mgr.backup_node("S001")
    assert v2 and v2.endswith("_v2")
    # 删除中间版本后仍应递增到 v3，而非回落到目录数量
    import shutil

    shutil.rmtree(Path(v1))
    v3 = mgr.backup_node("S001")
    assert v3 and v3.endswith("_v3")


def test_replace_sql_placeholders_skips_quoted_question():
    from blog_writer.db import _replace_sql_placeholders

    sql = "SELECT '?' AS q, col FROM t WHERE id = ?"
    out = _replace_sql_placeholders(sql)
    assert "'?'" in out
    assert out.endswith("%s")
    assert out.count("%s") == 1


def test_endpoint_buckets_survive_client_cleanup():
    from blog_writer.security.rate_limiter import RateLimiter

    limiter = RateLimiter(
        global_rate=1000,
        global_burst=500,
        per_client_rate=100,
        per_client_window=60,
        audit_enabled=False,
    )
    limiter.set_endpoint_limit("/api/v1/auth/login", 5, 60)
    for _ in range(3):
        limiter.is_allowed("c1", "/api/v1/auth/login")
    assert "endpoint:/api/v1/auth/login" in limiter._endpoint_buckets
    # 客户端桶清理不应清空端点桶
    limiter._client_buckets.clear()
    allowed, _ = limiter.is_allowed("c2", "/api/v1/auth/login")
    assert allowed is True
    assert limiter._endpoint_buckets["endpoint:/api/v1/auth/login"].current_count() >= 1


@pytest.mark.asyncio
async def test_tool_registry_max_calls(tmp_path: Path):
    from blog_writer.agent.tools import ToolRegistry

    reg = ToolRegistry(
        working_dir=str(tmp_path),
        instance_dir=str(tmp_path),
        max_tool_calls=2,
    )
    r1 = await reg.execute("list_files", {})
    r2 = await reg.execute("list_files", {})
    r3 = await reg.execute("list_files", {})
    assert r1.get("status") == "success"
    assert r2.get("status") == "success"
    assert r3.get("status") == "error"
    assert "超限" in (r3.get("error") or "")


def test_task_memory_cleanup_keeps_cache(temp_dir, config_manager):
    from blog_writer.workflow_service import WorkflowService

    svc = WorkflowService(config=config_manager)
    tid = "t-cleanup-mem"
    svc._tasks[tid] = {
        "task_id": tid,
        "status": "completed",
        "end_time": "2026-08-04T00:00:00",
        "owner_id": "u1",
        "results": [{"x": 1}],
        "outputs": {"a": "b"},
        "extra": {},
    }
    svc._task_logs[tid] = ["log"]
    svc._cleanup_task_memory(tid)
    assert tid not in svc._tasks
    assert tid not in svc._task_logs
    cached = svc.get_task_status(tid)
    assert cached is not None
    assert cached.get("status") == "completed"
    assert "results" not in cached


def test_prometheus_histogram_buckets():
    from blog_writer.integrations import MetricsCollector

    mc = MetricsCollector()
    mc.observe_histogram("latency", 0.01)
    mc.observe_histogram("latency", 0.2)
    out = mc.generate_prometheus()
    assert 'blog_writer_latency_seconds_bucket{le="0.01"}' in out
    assert 'blog_writer_latency_seconds_bucket{le="+Inf"}' in out
    assert "blog_writer_latency_seconds_count 2" in out
    assert "blog_writer_latency_seconds_sum" in out


def test_sandbox_rejects_dunder_escape(tmp_path: Path):
    from blog_writer.agent.sandbox import (
        SandboxPolicyError,
        run_python_sync,
        validate_python_source,
    )

    with pytest.raises(SandboxPolicyError):
        validate_python_source("print(open.__globals__)")
    with pytest.raises(SandboxPolicyError):
        validate_python_source("import os\nos.system('echo x')")

    out = run_python_sync("print(1+1)", instance_dir=tmp_path)
    assert out.get("returncode") == 0
    assert "2" in (out.get("stdout") or "")

    with pytest.raises(SandboxPolicyError):
        run_python_sync("print(open.__globals__)", instance_dir=tmp_path)


def test_config_update_fires_on_change(temp_dir):
    from blog_writer.config_manager import ConfigManager

    path = Path(temp_dir) / "c.json"
    path.write_text("{}", encoding="utf-8")
    cm = ConfigManager(str(path), auto_reload=False)
    seen = []
    cm.on_change(lambda cfg: seen.append(cfg.get("workflow", {}).get("default_mode")))
    cm.update({"workflow": {"default_mode": "auto"}})
    assert seen == ["auto"]
    cm.set("workflow.default_mode", "manual")
    assert seen[-1] == "manual"


def test_service_manager_shares_config_with_set(temp_dir):
    from blog_writer.config_manager import ConfigManager
    from blog_writer import service_manager as sm

    sm.reset_for_tests()
    path = Path(temp_dir) / "shared.json"
    path.write_text("{}", encoding="utf-8")
    cfg = ConfigManager(str(path), auto_reload=False)
    sm.set_config(cfg)
    assert sm.get_config() is cfg
    svc = sm.get_service()
    assert svc.config is cfg
    sm.reset_for_tests()


def test_apply_runtime_config_refreshes_flags(temp_dir, config_manager):
    from blog_writer.workflow_service import WorkflowService

    svc = WorkflowService(config=config_manager)
    config_manager.set("workflow.use_file_fallback", True)
    svc.apply_runtime_config()
    assert svc._use_file_fallback is True


def test_retry_node_rejects_unknown_step(temp_dir, config_manager):
    from blog_writer.workflow_service import WorkflowService

    svc = WorkflowService(config=config_manager)
    tid = "t-retry-bad"
    svc._tasks[tid] = {
        "task_id": tid,
        "status": "failed",
        "step_files": ["a.json", "b.json"],
        "completed_steps": ["a.json"],
        "results": [],
        "outputs": {},
        "retry_counts": {},
        "extra": {},
    }
    assert svc.retry_node(tid, "not-exist.json") is False
    assert svc._tasks[tid]["status"] == "failed"
    assert "not-exist.json" not in svc._tasks[tid].get("retry_counts", {})


def test_exhausted_client_does_not_drain_global_bucket():
    from blog_writer.security.rate_limiter import RateLimiter

    limiter = RateLimiter(
        global_rate=1000,
        global_burst=8,
        per_client_rate=2,
        per_client_window=60,
        audit_enabled=False,
    )
    for _ in range(30):
        limiter.is_allowed("flooder", "/api/x")
    allowed, reason = limiter.is_allowed("other", "/api/x")
    assert allowed is True, reason
