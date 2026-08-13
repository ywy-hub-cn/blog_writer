"""工作流预算：单步超时解析、任务 Token 上限。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def resolve_step_timeout_seconds(
    *,
    global_minutes: Any,
    node_def: Optional[Dict[str, Any]] = None,
    min_seconds: float = 30.0,
    max_seconds: float = 7200.0,
) -> Tuple[float, float]:
    """解析单步超时秒数。

    优先级：节点 resources/constraints.step_timeout_minutes > 全局配置。
    返回 (step_timeout_seconds, timeout_minutes_used)。
    """
    timeout_min = None
    node_def = node_def or {}
    resources = node_def.get("resources") if isinstance(node_def.get("resources"), dict) else {}
    constraints = node_def.get("constraints") if isinstance(node_def.get("constraints"), dict) else {}
    for candidate in (
        node_def.get("step_timeout_minutes"),
        resources.get("step_timeout_minutes"),
        constraints.get("step_timeout_minutes"),
        constraints.get("timeout_minutes"),
        global_minutes,
        10,
    ):
        if candidate is None or candidate == "":
            continue
        try:
            timeout_min = float(candidate)
            break
        except (TypeError, ValueError):
            continue
    if timeout_min is None or timeout_min <= 0:
        timeout_min = 10.0
    seconds = max(min_seconds, min(timeout_min * 60.0, max_seconds))
    return seconds, timeout_min


def accumulate_tokens(node_results: List[Dict[str, Any]]) -> int:
    total = 0
    for r in node_results or []:
        usage = r.get("token_usage") or {}
        if not isinstance(usage, dict):
            continue
        try:
            total += int(
                usage.get("total_tokens_used")
                or usage.get("total_tokens")
                or 0
            )
        except (TypeError, ValueError):
            continue
    return total


def token_budget_exceeded(
    node_results: List[Dict[str, Any]],
    max_tokens: Any,
) -> Tuple[bool, int, int]:
    """若配置了正数 max_tokens，检查累计用量是否超限。

    返回 (exceeded, used, limit)；limit<=0 表示未启用。
    """
    try:
        limit = int(max_tokens or 0)
    except (TypeError, ValueError):
        limit = 0
    used = accumulate_tokens(node_results)
    if limit <= 0:
        return False, used, 0
    return used >= limit, used, limit
