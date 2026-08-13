"""敏感信息脱敏模块 - API密钥、密码等敏感信息保护"""
import re
from typing import Optional

# 敏感字段名
_SENSITIVE_FIELDS = {
    "api_key", "apikey", "api-key",
    "password", "passwd", "pwd",
    "secret", "secret_key", "secret-key",
    "token", "access_key", "access-key",
    "authorization",
    "base_url", "api_base_url", "api_base", "url", "endpoint",
    "host", "hostname", "server", "dsn",
    "connection_string", "connection_url",
    "webhook_url", "callback_url", "redirect_uri",
}

# 敏感值模式
_SENSITIVE_PATTERNS = [
    (re.compile(r'(api[_-]?key["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-\.]+)["\']?', re.IGNORECASE), r'\1[已脱敏]'),
    (re.compile(r'(password["\']?\s*[:=]\s*["\']?)([^"\',\n]+)["\']?', re.IGNORECASE), r'\1[已脱敏]'),
    (re.compile(r'(secret["\']?\s*[:=]\s*["\']?)([^"\',\n]+)["\']?', re.IGNORECASE), r'\1[已脱敏]'),
    (re.compile(r'(Bearer\s+)([a-zA-Z0-9_\-\.]+)', re.IGNORECASE), r'\1[已脱敏]'),
    (re.compile(r'(sk-)[a-zA-Z0-9]+', re.IGNORECASE), r'\1****'),
]


def mask_api_key(api_key: str, show_chars: int = 4) -> str:
    """
    脱敏API密钥，显示前3位和后N位
    
    Args:
        api_key: 原始API密钥
        show_chars: 末尾显示字符数
    
    Returns:
        str: 脱敏后的密钥
    """
    if not api_key:
        return ""

    if len(api_key) <= show_chars + 3:
        return "*" * len(api_key)

    prefix = api_key[:3]
    suffix = api_key[-show_chars:]
    masked = "*" * (len(api_key) - 3 - show_chars)

    return f"{prefix}{masked}{suffix}"


def mask_password(password: str) -> str:
    """
    脱敏密码
    
    Args:
        password: 原始密码
    
    Returns:
        str: 脱敏后的密码
    """
    if not password:
        return ""
    return "•" * min(len(password), 8)


def mask_sensitive_data(data: dict, depth: int = 0) -> dict:
    """
    递归脱敏字典中的敏感数据
    
    Args:
        data: 原始数据字典
        depth: 当前递归深度
    
    Returns:
        dict: 脱敏后的数据
    """
    if not isinstance(data, dict):
        return data

    if depth > 10:  # 防止无限递归
        return data

    masked_data = {}
    for key, value in data.items():
        key_lower = key.lower()

        if key_lower in _SENSITIVE_FIELDS:
            if isinstance(value, str):
                if "key" in key_lower or "secret" in key_lower or "token" in key_lower:
                    masked_data[key] = mask_api_key(value)
                elif "password" in key_lower or "pwd" in key_lower:
                    masked_data[key] = mask_password(value)
                else:
                    masked_data[key] = mask_api_key(value)
            elif isinstance(value, dict):
                masked_data[key] = mask_sensitive_data(value, depth + 1)
            else:
                masked_data[key] = "***已脱敏***"
        elif isinstance(value, dict):
            masked_data[key] = mask_sensitive_data(value, depth + 1)
        elif isinstance(value, list):
            masked_data[key] = [
                mask_sensitive_data(item, depth + 1) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            masked_data[key] = value

    return masked_data


def mask_log_content(content: str) -> str:
    """
    脱敏日志内容中的敏感信息
    
    Args:
        content: 原始日志内容
    
    Returns:
        str: 脱敏后的内容
    """
    if not content:
        return ""

    for pattern, replacement in _SENSITIVE_PATTERNS:
        content = pattern.sub(replacement, content)

    return content


def create_config_response(config: dict) -> dict:
    """
    创建用于前端展示的配置响应（敏感信息脱敏，不传输实际值）

    规则：
    - api_key / secret / token 等字段：完全移除实际值，替换为 configured: bool 状态
    - password_hash 字段：不返回
    - 其他字段正常返回
    """
    safe_config = _strip_sensitive_values(config)

    # 移除密码哈希
    if "security" in safe_config:
        security = safe_config["security"]
        security.pop("admin_password_hash", None)
        security.pop("operator_password_hash", None)

    return safe_config


def _strip_sensitive_values(data: dict, depth: int = 0) -> dict:
    """递归移除敏感字段的实际值，替换为 {configured: bool} 状态指示器。"""
    if not isinstance(data, dict):
        return data
    if depth > 10:
        return data

    result = {}
    for key, value in data.items():
        key_lower = key.lower()

        if isinstance(value, dict):
            result[key] = _strip_sensitive_values(value, depth + 1)
        elif isinstance(value, list):
            result[key] = [
                _strip_sensitive_values(item, depth + 1) if isinstance(item, dict) else item
                for item in value
            ]
        elif key_lower in _SENSITIVE_FIELDS:
            # 敏感字段：不传实际值，只传是否已配置
            is_configured = bool(value and str(value).strip())
            result[key] = {"configured": is_configured}
            # 保留字段名以便前端知道这个字段存在
            result[f"{key}_configured"] = is_configured
        else:
            result[key] = value

    return result


def is_sensitive_key(key: str) -> bool:
    """检查是否为敏感字段"""
    return key.lower() in _SENSITIVE_FIELDS
