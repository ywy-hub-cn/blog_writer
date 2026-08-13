"""
统一响应格式模块
所有 API 端点应返回标准结构: {code, message, data, timestamp}

code: 0 表示成功, 非0表示错误
message: 可读的消息描述
data: 响应数据
timestamp: 服务器时间戳
"""

from datetime import datetime
from typing import Any, Optional


def success(data: Any = None, message: str = "success") -> dict:
    """成功响应"""
    return {
        "code": 0,
        "message": message,
        "data": data,
        "timestamp": datetime.now().isoformat(),
    }


def error(code: int = 1, message: str = "error", data: Any = None) -> dict:
    """错误响应"""
    return {
        "code": code,
        "message": message,
        "data": data,
        "timestamp": datetime.now().isoformat(),
    }


# 标准错误码
class ErrorCode:
    OK = 0
    PARAM_ERROR = 1001
    AUTH_REQUIRED = 4001
    AUTH_FAILED = 4002
    PERMISSION_DENIED = 4003
    RATE_LIMITED = 4029
    NOT_FOUND = 4041
    TASK_NOT_FOUND = 4042
    INTERNAL_ERROR = 5001
    LLM_ERROR = 5002
    WEBHOOK_ERROR = 5003
    DB_ERROR = 5004
