"""Enrich task API responses with step progress and quality gate summaries."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_validation_log(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": None, "messages": []}
    if not text.strip():
        return out
    if "[FAIL]" in text or "❌" in text:
        out["ok"] = False
    elif "[OK]" in text or "✅" in text:
        out["ok"] = True
    for line in text.splitlines():
        line = line.strip()
        if line:
            out["messages"].append(line[:300])
    return out


def read_quality_gates(instance_dir: Path) -> Dict[str, Any]:
    gates: Dict[str, Any] = {
        "content": {"ok": None, "messages": []},
        "visuals": {"ok": None, "messages": []},
        "internal_link_count": None,
        "publish": {},
    }
    content_log = _parse_validation_log(_read_text(instance_dir / "004-validation.log"))
    gates["content"] = content_log
    for msg in content_log.get("messages", []):
        m = re.search(r"品牌内部链接:\s*(\d+)", msg)
        if m:
            gates["internal_link_count"] = int(m.group(1))

    visual_log = _parse_validation_log(_read_text(instance_dir / "007-visual-validation.log"))
    gates["visuals"] = visual_log

    publish_record_path = instance_dir / "发布记录.json"
    if publish_record_path.is_file():
        try:
            rec = json.loads(publish_record_path.read_text(encoding="utf-8"))
            gates["publish"] = {
                "status": rec.get("status"),
                "dry_run": rec.get("dry_run"),
                "post_id": rec.get("post_id"),
                "post_url": rec.get("post_url") or rec.get("link"),
                "images_ready": rec.get("images_ready"),
            }
        except json.JSONDecodeError:
            pass

    package_path = instance_dir / "007 发布包.json"
    if package_path.is_file():
        try:
            pkg = json.loads(package_path.read_text(encoding="utf-8"))
            gates["publish_package"] = {
                "schema_version": pkg.get("schema_version"),
                "title": pkg.get("title"),
                "slug": pkg.get("slug"),
                "keyword": pkg.get("keyword"),
                "brand_site_url": pkg.get("brand_site_url"),
            }
        except json.JSONDecodeError:
            pass

    return gates


def build_step_progress(task: Dict[str, Any]) -> Dict[str, Any]:
    step_files: List[str] = list(task.get("step_files") or [])
    current_idx = int(task.get("current_step") or 0)
    total = int(task.get("total_steps") or len(step_files) or 0)
    if total <= 0 and step_files:
        total = len(step_files)
    completed = len(task.get("completed_steps") or [])
    current_file = step_files[current_idx] if step_files and 0 <= current_idx < len(step_files) else ""
    percent = round((completed / total) * 100, 1) if total else 0.0
    return {
        "current": current_idx,
        "total": total,
        "completed_count": completed,
        "percent": percent,
        "current_step_file": current_file,
    }


def enrich_task(task: Dict[str, Any], instance_root: Path, full: bool = True) -> Dict[str, Any]:
    """Return a copy of task dict with integration-friendly fields."""
    if not task:
        return task
    enriched = dict(task)
    enriched["step_progress"] = build_step_progress(task)
    enriched["current_step_file"] = enriched["step_progress"]["current_step_file"]

    if not full:
        return enriched

    task_id = task.get("task_id") or ""
    if not task_id:
        return enriched

    instance_dir = instance_root / task_id
    if instance_dir.is_dir():
        enriched["quality_gates"] = read_quality_gates(instance_dir)
        publish = enriched["quality_gates"].get("publish") or {}
        if publish:
            enriched["publish_summary"] = publish

    return enriched
