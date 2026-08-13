"""路径安全模块 - 防止路径穿越，限制文件操作范围"""
import os
import re
from pathlib import Path
from typing import Optional, List

# 允许的根目录
_ALLOWED_ROOTS: List[Path] = []


def init_path_security(roots: List[Path]) -> None:
    """初始化允许的根目录"""
    global _ALLOWED_ROOTS
    _ALLOWED_ROOTS = [r.resolve() for r in roots]


def is_path_safe(path: str, base_dir: Optional[str] = None) -> bool:
    """
    检查路径是否安全（防止路径穿越）
    
    Args:
        path: 要检查的路径
        base_dir: 可选的基准目录，如果提供则检查路径是否在该目录下
    
    Returns:
        bool: 路径是否安全
    """
    # 检查空路径
    if not path:
        return False

    # 检查路径穿越模式
    dangerous_patterns = [
        r'\.\.[\\/]',           # ../ 或 ..\
        r'^[\\/]',              # 绝对路径（Unix）
        r'^[a-zA-Z]:[\\/]',    # Windows绝对路径
        r'~',                    # home目录
        r'\\x00',               # 空字节
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, path):
            return False

    try:
        # 如果有基准目录，先将路径相对于base_dir解析
        if base_dir:
            base = Path(base_dir).resolve()
            candidate = Path(path)
            if not candidate.is_absolute():
                resolved = (base / candidate).resolve()
            else:
                resolved = candidate.resolve()
            
            try:
                resolved.relative_to(base)
                return True
            except ValueError:
                return False

        resolved = Path(path).resolve()
        
        # 检查是否在允许的根目录内
        for root in _ALLOWED_ROOTS:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue

        # 如果没有配置允许的根目录，默认为不安全
        if _ALLOWED_ROOTS:
            return False
            
        # 没有配置根目录时，只检查路径穿越
        return True

    except (ValueError, OSError):
        return False


def sanitize_path(path: str, base_dir: str) -> Optional[str]:
    """
    清理并验证路径，返回安全的绝对路径
    
    Args:
        path: 要清理的路径
        base_dir: 基准目录
    
    Returns:
        str or None: 安全的绝对路径，失败返回None
    """
    if not path:
        return None

    # 使用路径解析来规范化路径，而不是简单的字符串替换
    try:
        base = Path(base_dir).resolve()
        full_path = (base / path).resolve()

        # 验证是否在基准目录内（防止路径穿越）
        try:
            full_path.relative_to(base)
            return str(full_path)
        except ValueError:
            return None

    except (ValueError, OSError):
        return None


_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_task_id(task_id: str) -> bool:
    """任务 ID 白名单：防路径穿越，禁止分隔符与 `..`。"""
    if not task_id or not isinstance(task_id, str):
        return False
    if "/" in task_id or "\\" in task_id or ".." in task_id:
        return False
    return bool(_TASK_ID_RE.match(task_id))


def safe_basename(filename: Optional[str], default: str = "file.json") -> Optional[str]:
    """提取安全文件名（仅 basename，拒绝穿越与空名）。"""
    if not filename:
        return default
    name = Path(str(filename)).name
    if not name or name in (".", "..") or ".." in name:
        return None
    if "/" in name or "\\" in name:
        return None
    return name


def validate_file_operation(
    file_path: str,
    operation: str = "read",
    task_dir: Optional[str] = None
) -> tuple[bool, str]:
    """
    验证文件操作是否安全
    
    Args:
        file_path: 目标文件路径
        operation: 操作类型 (read/write/delete)
        task_dir: 当前任务目录（用于限制写入范围）
    
    Returns:
        tuple[bool, str]: (是否安全, 错误信息)
    """
    # 检查路径
    if not is_path_safe(file_path, task_dir):
        return False, "路径不安全，禁止路径穿越和绝对路径"

    # 写入操作额外检查
    if operation in ("write", "delete"):
        if not task_dir:
            return False, "写入/删除操作需要指定任务目录"

        task_path = Path(task_dir).resolve()
        # 相对路径必须基于 task_dir 解析，与 is_path_safe 保持一致，
        # 否则 CWD 不同时会绕过任务目录约束
        candidate = Path(file_path)
        if not candidate.is_absolute():
            file_path_resolved = (task_path / candidate).resolve()
        else:
            file_path_resolved = candidate.resolve()

        try:
            file_path_resolved.relative_to(task_path)
        except ValueError:
            return False, f"写入/删除操作仅限任务目录: {task_dir}"

    return True, ""


def get_safe_task_dir(base_dir: str, task_id: str) -> str:
    """
    获取安全的任务目录路径
    
    Args:
        base_dir: 基础目录
        task_id: 任务ID
    
    Returns:
        str: 安全的任务目录路径
    """
    # 清理task_id中的危险字符
    safe_task_id = re.sub(r'[^\w\-]', '_', task_id)
    return str(Path(base_dir).resolve() / safe_task_id)
