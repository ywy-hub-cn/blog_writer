"""定时任务调度：解析、未来时间校验、queued 状态可恢复。"""
from datetime import datetime, timedelta, timezone

import pytest

from blog_writer.workflow_service import (
    WorkflowService,
    assert_scheduled_at_is_future,
    parse_scheduled_at,
    scheduled_at_is_due,
)


def _state(status: str) -> dict:
    return {
        "task_id": "task_test",
        "status": status,
        "current_step": 0,
        "total_steps": 0,
        "step_files": [],
        "completed_steps": [],
    }


def test_parse_scheduled_at_utc_z():
    dt = parse_scheduled_at("2026-08-31T14:00:00Z")
    assert dt == datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)


def test_scheduled_at_is_due_past_and_future():
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert scheduled_at_is_due(past) is True
    assert scheduled_at_is_due(future) is False


def test_assert_scheduled_at_rejects_past():
    past = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    with pytest.raises(ValueError, match="晚于当前时间"):
        assert_scheduled_at_is_future(past)


def test_assert_scheduled_at_accepts_future_and_normalizes():
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    normalized = assert_scheduled_at_is_future(future.isoformat())
    assert normalized.endswith("Z") or "+00:00" in normalized or normalized.endswith("+00:00")
    parsed = parse_scheduled_at(normalized)
    assert parsed > datetime.now(timezone.utc)


def test_validate_state_accepts_queued_and_scheduled():
    ws = WorkflowService.__new__(WorkflowService)
    assert ws._validate_state(_state("queued")) is True
    assert ws._validate_state(_state("scheduled")) is True
    assert ws._validate_state(_state("bogus")) is False


def test_start_task_request_rejects_past_scheduled_at():
    from blog_writer.api.tasks import StartTaskRequest

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with pytest.raises(Exception):
        StartTaskRequest.model_validate(
            {
                "brandPath": "brands/sms-boosting",
                "keywords": "test",
                "scheduledAt": past,
            }
        )


def test_start_task_request_accepts_future_scheduled_at():
    from blog_writer.api.tasks import StartTaskRequest

    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    req = StartTaskRequest.model_validate(
        {
            "brandPath": "brands/sms-boosting",
            "keywords": "test",
            "scheduledAt": future,
        }
    )
    assert req.scheduled_at is not None
    assert scheduled_at_is_due(req.scheduled_at) is False
