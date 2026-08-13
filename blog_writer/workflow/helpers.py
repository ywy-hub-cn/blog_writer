"""工作流辅助：风险码与回跳清理（从 WorkflowService 拆出，便于单测）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from blog_writer.workflow.routing import WorkflowRouter


def risk_code_from_level(level: Optional[int]) -> Optional[str]:
    if level is None:
        return None
    try:
        return f"RK{int(level):02d}"
    except (TypeError, ValueError):
        return None


def load_bid_risk_level(instance_dir: Path) -> Optional[int]:
    bid_path = instance_dir / "000 BID.json"
    if not bid_path.exists():
        return None
    try:
        bid = json.loads(bid_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    for key in ("risk_level", "RK", "rk", "risk"):
        val = bid.get(key) if isinstance(bid, dict) else None
        if val is None and isinstance(bid, dict):
            meta = bid.get("meta") or bid.get("metadata") or {}
            if isinstance(meta, dict):
                val = meta.get(key)
        if val is None:
            continue
        digits = "".join(ch for ch in str(val) if ch.isdigit())
        if digits:
            try:
                return int(digits[-2:] if len(digits) > 2 else digits)
            except ValueError:
                continue
    return None


def apply_invalidate(
    router: WorkflowRouter,
    completed_steps: List[str],
    from_file: str,
    results: List[Dict[str, Any]],
) -> Tuple[List[str], List[Dict[str, Any]], set]:
    kept, removed = router.invalidate_from(completed_steps, from_file)
    filtered = [r for r in results if r.get("step") not in removed]
    return kept, filtered, removed


def collect_output_keys(node_def: Dict[str, Any]) -> set:
    """从节点定义收集可能写入 outputs 的键。"""
    keys: set = set()
    if not isinstance(node_def, dict):
        return keys
    for action in node_def.get("actions") or []:
        if not isinstance(action, dict):
            continue
        name = action.get("name")
        if name:
            keys.add(str(name))
        output = action.get("output") or {}
        if isinstance(output, dict):
            oid = output.get("id")
            path = output.get("path")
            if oid:
                keys.add(str(oid))
            if path:
                keys.add(str(path))
                keys.add(str(path).replace(" ", "_"))
    return keys


def prune_outputs_for_steps(
    outputs: Dict[str, Any],
    step_files: set,
    load_node,
) -> Dict[str, Any]:
    """移除失效步骤对应的 outputs 条目。"""
    if not outputs or not step_files:
        return dict(outputs or {})
    drop: set = set()
    for sf in step_files:
        try:
            node_def = load_node(sf)
        except Exception:
            continue
        drop |= collect_output_keys(node_def)
    if not drop:
        return dict(outputs)
    return {k: v for k, v in outputs.items() if k not in drop}
