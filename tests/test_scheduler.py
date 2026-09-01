"""定时任务调度：解析、未来时间校验、queued 状态可恢复。"""
from datetime import datetime, timedelta, timezone

import pytest

from blog_writer.workflow_service import (
    WorkflowService,
    assert_scheduled_at_is_future,
    assert_scheduled_end_after_start,
    parse_scheduled_at,
    scheduled_at_is_due,
)


def test_default_callback_events_include_schedule_lifecycle():
    from blog_writer.api.integration_events import DEFAULT_CALLBACK_EVENTS, build_webhook_payload

    for ev in ("task.started", "task.paused", "task.resumed", "task.cancelled"):
        assert ev in DEFAULT_CALLBACK_EVENTS

    payload = build_webhook_payload(
        "task.paused",
        "task_x",
        {
            "status": "paused",
            "reason": "schedule_end",
            "scheduled_at": "2026-09-01T10:00:00Z",
            "scheduled_end_at": "2026-09-01T18:00:00Z",
        },
    )
    assert payload["event"] == "task.paused"
    assert payload["task_id"] == "task_x"
    assert payload["reason"] == "schedule_end"


def test_webhook_payload_camel_for_java(monkeypatch):
    monkeypatch.setenv("RESPONSE_CASE", "camel")
    from blog_writer.api.integration_events import build_webhook_payload

    payload = build_webhook_payload(
        "task.started",
        "task_y",
        {
            "status": "queued",
            "reason": "schedule_due",
            "scheduled_at": "2026-09-01T10:00:00Z",
            "scheduled_end_at": "2026-09-01T18:00:00Z",
        },
    )
    assert payload["taskId"] == "task_y"
    assert payload["scheduledAt"] == "2026-09-01T10:00:00Z"
    assert payload["scheduledEndAt"] == "2026-09-01T18:00:00Z"
    assert payload["reason"] == "schedule_due"


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


def test_assert_scheduled_end_after_start():
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    end = start + timedelta(hours=2)
    out = assert_scheduled_end_after_start(start.isoformat(), end.isoformat())
    assert parse_scheduled_at(out) > start
    with pytest.raises(ValueError, match="晚于开始时间"):
        assert_scheduled_end_after_start(end.isoformat(), start.isoformat())


def test_validate_state_accepts_queued_and_scheduled():
    ws = WorkflowService.__new__(WorkflowService)
    assert ws._validate_state(_state("queued")) is True
    assert ws._validate_state(_state("scheduled")) is True
    assert ws._validate_state(_state("bogus")) is False


def test_start_task_request_rejects_past_scheduled_at():
    from blog_writer.api.tasks import StartTaskRequest

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future_end = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    with pytest.raises(Exception):
        StartTaskRequest.model_validate(
            {
                "brandPath": "brands/sms-boosting",
                "keywords": "test",
                "scheduledAt": past,
                "scheduledEndAt": future_end,
            }
        )


def test_start_task_request_requires_end_with_start():
    from blog_writer.api.tasks import StartTaskRequest

    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    with pytest.raises(Exception):
        StartTaskRequest.model_validate(
            {
                "brandPath": "brands/sms-boosting",
                "keywords": "test",
                "scheduledAt": future,
            }
        )


def test_start_task_request_accepts_future_scheduled_window():
    from blog_writer.api.tasks import StartTaskRequest

    future = datetime.now(timezone.utc) + timedelta(hours=3)
    end = future + timedelta(hours=2)
    req = StartTaskRequest.model_validate(
        {
            "brandPath": "brands/sms-boosting",
            "keywords": "test",
            "scheduledAt": future.isoformat(),
            "scheduledEndAt": end.isoformat(),
        }
    )
    assert req.scheduled_at is not None
    assert req.scheduled_end_at is not None
    assert scheduled_at_is_due(req.scheduled_at) is False
    assert scheduled_at_is_due(req.scheduled_end_at) is False
