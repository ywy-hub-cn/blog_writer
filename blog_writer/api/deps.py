"""API依赖 - 鉴权、限流等"""
import os
import secrets
from fastapi import Request, HTTPException, Depends, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from blog_writer.security.auth import AuthManager


def is_task_auth_required() -> bool:
    """任务 API 是否强制鉴权。

    仅当显式设置 BLOG_WRITER_TASK_AUTH=required 时启用。
    Web UI 默认可匿名使用；Java 对接生产环境再按需开启。
    """
    explicit = os.environ.get("BLOG_WRITER_TASK_AUTH", "").strip().lower()
    return explicit in ("required", "true", "1", "yes")


# Bearer认证
security = HTTPBearer(auto_error=False)

# SSO 认证提供者缓存（与 api/auth.py 保持一致的懒初始化策略）
_cached_auth_provider = None


def _get_auth_provider():
    """延迟初始化 SSO 认证提供者（与 api/auth.py 保持一致）"""
    global _cached_auth_provider
    if _cached_auth_provider is None:
        from blog_writer.integrations import create_auth_provider
        from blog_writer.service_manager import get_config
        _cached_auth_provider = create_auth_provider(get_config().get_all())
    return _cached_auth_provider


def reset_auth_provider_cache() -> None:
    """配置热更新后清空缓存的 AuthProvider。"""
    global _cached_auth_provider
    _cached_auth_provider = None


def _get_configured_api_token() -> str:
    """平台服务间调用 Token（环境变量优先）"""
    env_token = os.environ.get("BLOG_WRITER_API_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        from blog_writer.service_manager import get_config
        return str(get_config().get("security.api_token", "") or "").strip()
    except Exception:
        return ""


def _verify_service_token(token: str) -> Optional[dict]:
    expected = _get_configured_api_token()
    if not expected or not token:
        return None
    if secrets.compare_digest(token, expected):
        return {
            "user_id": "service",
            "role": "service",
            "auth_type": "api_token",
            "token_created_at": None,
        }
    return None


def _verify_token_both(token: str) -> Optional[dict]:
    """同时验证本地 JWT、服务 Token 和 SSO Token。

    返回用户信息 dict（含 user_id / role）或 None。
    与 /auth/verify 端点行为一致，确保 SSO 用户也能访问管理接口。
    """
    # 0. 平台服务间 API Token
    service_user = _verify_service_token(token)
    if service_user:
        return service_user

    # 1. 本地 JWT
    if AuthManager.verify_token(token):
        info = AuthManager.get_token_info(token)
        role = info.get("role", "admin") if info else "admin"
        return {
            "user_id": role,
            "role": role,
            "auth_type": "local_jwt",
            "token_created_at": info["created_at"] if info else None,
        }

    # 2. SSO Token
    try:
        provider = _get_auth_provider()
        sso_result = provider.verify_token(token)
        if sso_result:
            # 缺失 role 时默认 user，避免格式异常的 SSO 响应误授 admin
            return {
                "user_id": sso_result.get("user_id", "sso_user"),
                "role": sso_result.get("role", "user"),
                "auth_type": "sso",
                "token_created_at": None,
            }
    except Exception:
        pass

    return None


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> dict:
    """
    获取当前用户信息（任务/管理类接口使用）。

    支持：
    - Authorization: Bearer <jwt|sso|api_token>
    - X-API-Key: <api_token>（公司平台服务间调用）
    """
    token = credentials.credentials if credentials else None
    if not token and x_api_key:
        token = x_api_key

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证Token"
        )

    user_info = _verify_token_both(token)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token无效或已过期"
        )

    return {
        "is_admin": user_info.get("role") in ("admin", "service"),
        "user_id": user_info.get("user_id"),
        "role": user_info.get("role"),
        "auth_type": user_info.get("auth_type"),
        "token_created_at": user_info.get("token_created_at"),
    }


async def verify_admin_access(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> dict:
    """
    验证管理员访问权限（用于管理接口）

    支持本地 JWT、SSO Token、以及平台服务 Token（Bearer 或 X-API-Key）。
    """
    # 限流检查
    client_ip = resolve_client_ip(request)
    if not AuthManager.check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试"
        )

    token = credentials.credentials if credentials else None
    if not token and x_api_key:
        token = x_api_key

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要管理员权限"
        )

    user_info = _verify_token_both(token)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录"
        )

    role = user_info.get("role", "")
    if role not in ("admin", "service"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足"
        )

    return {
        "is_admin": True,
        "ip": client_ip,
        "user_id": user_info.get("user_id"),
        "role": role,
        "auth_type": user_info.get("auth_type"),
        "token_created_at": user_info.get("token_created_at"),
    }


async def check_rate_limit(request: Request) -> None:
    """
    检查请求频率限制
    
    用于公开接口的限流
    """
    client_ip = resolve_client_ip(request)
    if not AuthManager.check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试"
        )


async def get_client_ip(request: Request) -> str:
    """获取客户端 IP；仅当直连来自可信代理时才信任 X-Forwarded-For。"""
    return resolve_client_ip(request)


def resolve_client_ip(request: Request) -> str:
    """同步解析客户端 IP（中间件可用）。

    环境变量 TRUSTED_PROXIES：逗号分隔，默认 127.0.0.1,::1。
    仅当 request.client.host 命中可信代理时，才取 X-Forwarded-For 最左侧。
    """
    peer = request.client.host if request.client else "unknown"
    trusted_raw = os.environ.get("TRUSTED_PROXIES", "127.0.0.1,::1")
    trusted = {p.strip() for p in trusted_raw.split(",") if p.strip()}
    if peer in trusted:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or peer
    return peer
