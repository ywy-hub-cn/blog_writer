"""人工审核等待：内存 Event + StateStore/DB 轮询，降低跨进程死等。"""
from __future__ import annotations

from typing import Any, Dict, Optional

_REVIEW_KEY_PREFIX = "blog_writer:review:decision:"
_REVIEW_TTL_SECONDS = 86400


def review_decision_key(task_id: str) -> str:
    return f"{_REVIEW_KEY_PREFIX}{task_id}"


def publish_review_decision(
    task_id: str,
    decision: str,
    modifications: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = _REVIEW_TTL_SECONDS,
) -> None:
    """将审核决策写入 StateStore（Redis/memory），供等待协程跨进程发现。"""
    try:
        from blog_writer.state_store import get_state_store

        get_state_store().set_json(
            review_decision_key(task_id),
            {
                "decision": decision,
                "modifications": modifications or {},
            },
            ttl_seconds=ttl_seconds,
        )
    except Exception:
        pass


def load_external_review_decision(task_id: str) -> Optional[Dict[str, Any]]:
    try:
        from blog_writer.state_store import get_state_store

        data = get_state_store().get_json(review_decision_key(task_id))
        if isinstance(data, dict) and data.get("decision"):
            return data
    except Exception:
        pass
    return None


def clear_external_review_decision(task_id: str) -> None:
    try:
        from blog_writer.state_store import get_state_store

        get_state_store().delete(review_decision_key(task_id))
    except Exception:
        pass
