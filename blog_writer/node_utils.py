"""节点工具函数 - 共享的节点查找与校验逻辑"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

REQUIRED_FIELDS = ["id", "name", "seq", "kind", "actions", "checks"]
VALID_KINDS = ["pure_code", "llm_completion", "agent_action", "human_review", "system_check"]

# 敏感内容检测模式 - 防止 API Key 等机密信息被写入节点 JSON
_SENSITIVE_PATTERNS = [
    (re.compile(r'sk-[a-zA-Z0-9]{16,}', re.I), 'API Key (sk-...)'),
    (re.compile(r'api[_-]?key[\s\'"]*[:=][\s\'"]*[a-zA-Z0-9_\-\.]{8,}', re.I), 'API Key 配置'),
    (re.compile(r'Bearer\s+[a-zA-Z0-9_\-\.]{20,}', re.I), 'Bearer Token'),
    (re.compile(r'password[\s\'"]*[:=][\s\'"]*[^\s\'",]{4,}', re.I), '密码'),
    (re.compile(r'secret[\s\'"]*[:=][\s\'"]*[^\s\'",]{4,}', re.I), '密钥'),
    (re.compile(r'authorization[\s\'"]*[:=][\s\'"]*[^\s\'",]{4,}', re.I), 'Authorization'),
]


def check_sensitive_content_in_node(node: Dict[str, Any]) -> List[str]:
    """递归检查节点 JSON 中是否包含敏感信息。

    Returns:
        匹配到的敏感内容描述列表（空列表表示无风险）。
    """
    warnings: List[str] = []

    def _scan(value: Any, path: str = ""):
        if isinstance(value, str):
            for pattern, desc in _SENSITIVE_PATTERNS:
                if pattern.search(value):
                    warnings.append(f"{path}: 检测到疑似 {desc}")
                    break  # 每个字段只报一次
        elif isinstance(value, dict):
            for k, v in value.items():
                _scan(v, f"{path}.{k}" if path else k)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                _scan(v, f"{path}[{i}]")

    _scan(node)
    return warnings


def find_node_file(nodes_dir: Path, node_id: str) -> Optional[Path]:
    """在 nodes_dir 内查找节点文件；拒绝路径穿越。"""
    if not node_id or not isinstance(node_id, str):
        return None
    try:
        base = Path(nodes_dir).resolve()
    except (ValueError, OSError):
        return None

    # 仅当 node_id 是安全 basename（无分隔符 / ..）时尝试直接文件匹配
    if "/" not in node_id and "\\" not in node_id and ".." not in node_id:
        try:
            direct_path = (base / node_id).resolve()
            direct_path.relative_to(base)
            if direct_path.exists() and direct_path.is_file():
                return direct_path
        except (ValueError, OSError):
            pass

    # 按节点 JSON 内 id 字段匹配（仅扫描 nodes_dir 下 *.json）
    for f in base.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                node_data = json.load(fh)
            if node_data.get("id") == node_id:
                return f
        except Exception:
            continue

    # 部分匹配（支持节点 ID 后缀/前缀）
    for f in base.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                node_data = json.load(fh)
            nid = node_data.get("id", "")
            if nid.endswith(node_id) or nid.startswith(node_id):
                return f
        except Exception:
            continue

    return None


def validate_node_schema(node: Dict[str, Any]) -> Dict[str, Any]:
    errors = []

    # 检查必填字段
    for field in REQUIRED_FIELDS:
        if field not in node:
            errors.append(f"缺少必填字段: {field}")

    # 检查kind/exec_type合法性
    kind = node.get("kind", "")
    exec_type = node.get("exec_type")
    check_type = exec_type or kind

    if check_type and check_type not in VALID_KINDS:
        errors.append(f"无效的执行类型: {check_type}，有效值: {VALID_KINDS}")

    # 检查id格式
    node_id = node.get("id", "")
    if node_id:
        if not isinstance(node_id, str) or "/" in node_id or "\\" in node_id or ".." in node_id:
            errors.append("节点ID不能包含路径分隔符或 '..'")
        else:
            parts = node_id.split(".")
            valid_prefixes = ["step", "batch", "cond", "loop", "review"]
            if parts and parts[0] not in valid_prefixes:
                errors.append(f"节点ID前缀必须是 {valid_prefixes} 之一")

    # 检查actions
    actions = node.get("actions", [])
    if not isinstance(actions, list):
        errors.append("actions必须是列表")
    elif kind in ["agent_action", "llm_completion"] and not actions:
        errors.append(f"{kind}类型节点必须定义actions")

    # 检查checks
    checks = node.get("checks", [])
    if not isinstance(checks, list):
        errors.append("checks必须是列表")
    else:
        import re
        for i, check in enumerate(checks):
            if not isinstance(check, dict):
                continue
            target = str(check.get("target") or "")
            if "::exec:" not in target:
                continue
            _, _, exec_cmd = target.partition("::exec:")
            exec_cmd = exec_cmd.strip()
            if not re.match(r"^python3?\s+-c\s+.+$", exec_cmd, re.S):
                errors.append(
                    f"checks[{i}].target ::exec: 仅允许 python/python3 -c（已禁用 shell）"
                )

    return {
        "valid": len(errors) == 0,
        "errors": errors
    }
