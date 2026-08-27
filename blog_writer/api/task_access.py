"""任务访问控制：归属隔离（非 admin/service 只能操作自己的任务）。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException, status


PRIVILEGED_ROLES = frozenset({"admin", "service"})


def is_anonymous_user(user: Optional[Dict[str, Any]]) -> bool:
    """Web UI 免登录访客（非管理员）。"""
    if not user:
        return True
    if user.get("auth_type") == "anonymous":
        return True
    return str(user.get("role") or "") == "anonymous"


def has_open_task_access(user: Optional[Dict[str, Any]]) -> bool:
    """匿名或未隔离部署：任务读写不做归属过滤（与旧版 UI 行为一致）。"""
    return is_privileged(user) or is_anonymous_user(user)


def is_privileged(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    return str(user.get("role") or "") in PRIVILEGED_ROLES


def get_user_id(user: Optional[Dict[str, Any]]) -> str:
    if not user:
        return ""
    return str(user.get("user_id") or user.get("sub") or "").strip()


def get_task_owner_id(task: Optional[Dict[str, Any]]) -> str:
    if not task:
        return ""
    owner = task.get("owner_id")
    if owner:
        return str(owner)
    extra = task.get("extra") or {}
    if isinstance(extra, dict) and extra.get("owner_id"):
        return str(extra.get("owner_id"))
    return ""


def assert_task_access(
    user: Dict[str, Any],
    task: Optional[Dict[str, Any]],
    *,
    missing_as_404: bool = True,
) -> Dict[str, Any]:
    """校验当前用户可访问任务；失败抛 HTTPException。"""
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    if has_open_task_access(user):
        return task

    uid = get_user_id(user)
    owner = get_task_owner_id(task)
    # 无归属的历史任务：仅特权角色可访问（上面已放行）
    if not owner or not uid or owner != uid:
        # 对普通用户隐藏存在性
        if missing_as_404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="任务不存在",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问该任务",
        )
    return task


def filter_tasks_for_user(
    user: Dict[str, Any],
    tasks: list,
) -> list:
    if has_open_task_access(user):
        return tasks
    uid = get_user_id(user)
    if not uid:
        return []
    out = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if get_task_owner_id(t) == uid:
            out.append(t)
    return out
