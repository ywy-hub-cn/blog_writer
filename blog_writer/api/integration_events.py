"""Webhook event filtering and Java-friendly payload shaping."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from blog_writer.api.case_convert import maybe_camel

# Default: terminal + lifecycle events Java integrators care about
DEFAULT_CALLBACK_EVENTS = [
    "task.created",
    "task.started",
    "task.step_completed",
    "task.waiting_review",
    "task.paused",
    "task.resumed",
    "task.completed",
    "task.completed_partial",
    "task.failed",
    "task.cancelled",
    "task.rejected",
]

TERMINAL_EVENTS = {
    "task.completed",
    "task.completed_partial",
    "task.failed",
    "task.cancelled",
    "task.rejected",
}


def normalize_callback_events(events: Optional[List[str]]) -> List[str]:
    if not events:
        return list(DEFAULT_CALLBACK_EVENTS)
    out: List[str] = []
    seen = set()
    for raw in events:
        name = (raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out or list(DEFAULT_CALLBACK_EVENTS)


def should_fire_event(registered_events: Optional[List[str]], event: str) -> bool:
    if not registered_events:
        return True
    return event in registered_events


def build_webhook_payload(
    event: str,
    task_id: str,
    data: Optional[Dict[str, Any]] = None,
    signature: str = "",
    timestamp: Optional[int] = None,
) -> Dict[str, Any]:
    """Flatten payload for Java consumers: event + task fields at top level."""
    import time

    payload: Dict[str, Any] = {
        "event": event,
        "task_id": task_id,
        "timestamp": timestamp or int(time.time()),
    }
    if data:
        for key, value in data.items():
            if key not in payload:
                payload[key] = value
    if signature:
        payload["signature"] = signature
    return maybe_camel(payload)


def collect_output_files(instance_dir) -> List[str]:
    from pathlib import Path

    root = Path(instance_dir)
    if not root.is_dir():
        return []
    names = [
        "004 正文.md",
        "006 呈现文档.html",
        "007 发布包.json",
        "007 发布包.md",
        "发布记录.json",
    ]
    return [name for name in names if (root / name).is_file()]
