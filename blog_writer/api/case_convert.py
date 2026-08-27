"""Shared snake_case ↔ camelCase helpers for API and webhook payloads."""
from __future__ import annotations

import os
import re
from typing import Any, Callable


def snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def convert_keys(obj: Any, converter: Callable[[str], str]) -> Any:
    if isinstance(obj, dict):
        return {
            converter(k) if isinstance(k, str) else k: convert_keys(v, converter)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [convert_keys(item, converter) for item in obj]
    return obj


def use_camel_case() -> bool:
    return os.environ.get("RESPONSE_CASE", "snake").lower() == "camel"


def maybe_camel(obj: Any) -> Any:
    if use_camel_case():
        return convert_keys(obj, snake_to_camel)
    return obj


def normalize_idempotency_key(raw: str) -> str:
    """Turn Idempotency-Key header into a safe task_id suffix."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", (raw or "").strip())[:64]
    if not cleaned:
        return ""
    if cleaned.startswith("task_"):
        return cleaned
    return f"task_{cleaned}"
