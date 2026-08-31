"""限流与任务只读轮询豁免。"""
from blog_writer.main import _is_task_poll_get


def test_task_poll_get_exempt_paths():
    assert _is_task_poll_get("GET", "/api/tasks") is True
    assert _is_task_poll_get("GET", "/api/tasks/task_1") is True
    assert _is_task_poll_get("GET", "/api/tasks/task_1/logs") is True
    assert _is_task_poll_get("GET", "/api/v1/tasks/concurrency") is True
    assert _is_task_poll_get("GET", "/api/tasks/scheduled") is True


def test_non_poll_not_exempt():
    assert _is_task_poll_get("POST", "/api/tasks/start") is False
    assert _is_task_poll_get("POST", "/api/tasks/task_1/cancel") is False
    assert _is_task_poll_get("GET", "/api/brands") is False
    assert _is_task_poll_get("GET", "/api/auth/me") is False


def test_default_config_rate_limit_relaxed():
    from blog_writer.config_manager import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["security"]["rate_limit_per_minute"] >= 120
    assert DEFAULT_CONFIG["security"].get("rate_limit_burst", 0) >= 120
