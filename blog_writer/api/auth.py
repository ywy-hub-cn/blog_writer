"""认证API - 登录、登出、验证

支持双模式：
- 本地JWT模式：使用 AuthManager（默认）
- SSO模式：使用 AuthProvider 适配器（对接公司SSO）
"""
import os
from fastapi import APIRouter, HTTPException, status, Header, Request
from pydantic import BaseModel, field_validator, ConfigDict, Field
from typing import Optional

from blog_writer.security.auth import AuthManager
from blog_writer.integrations import create_auth_provider

router = APIRouter(prefix="/auth", tags=["认证"])

# 延迟初始化，避免循环导入
_auth_provider = None

def _get_auth_provider():
    global _auth_provider
    if _auth_provider is None:
        from blog_writer.service_manager import get_config
        config = get_config().get_all()
        _auth_provider = create_auth_provider(config)
    return _auth_provider


def reset_auth_provider_cache() -> None:
    """配置热更新后清空 SSO/本地 AuthProvider 缓存。"""
    global _auth_provider
    _auth_provider = None


def _is_sso_enabled() -> bool:
    try:
        from blog_writer.service_manager import get_config
        cfg = get_config().get_all()
        security = cfg.get("security") or {}
        sso = security.get("sso") or cfg.get("sso") or {}
        return bool(sso.get("enabled"))
    except Exception:
        return False


def _allow_local_fallback() -> bool:
    """SSO 启用时是否仍允许本地 password-only 登录（默认否）。"""
    try:
        from blog_writer.service_manager import get_config
        cfg = get_config().get_all()
        security = cfg.get("security") or {}
        sso = security.get("sso") or cfg.get("sso") or {}
        return bool(sso.get("allow_local_fallback", False))
    except Exception:
        return False


class LoginRequest(BaseModel):
    """登录请求 - 支持两种格式：
    1. 本地模式: {"password": "xxx"}
    2. SSO模式: {"username": "xxx", "password": "xxx"} 或 {"code": "xxx"}
    
    同时接受 camelCase 别名 (password/username/code)
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    password: Optional[str] = None
    username: Optional[str] = None
    code: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if v is not None and len(v) < 4:
            raise ValueError("密码至少4位")
        if v is not None and len(v) > 128:
            raise ValueError("密码过长")
        return v


class LoginResponse(BaseModel):
    """登录响应"""
    success: bool
    token: Optional[str] = None
    user_id: Optional[str] = None
    role: Optional[str] = None
    message: str = ""


@router.post("/login", response_model=LoginResponse)
async def login(request: Request, login_req: LoginRequest):
    """
    登录
    
    自动识别模式：
    - 传入 code → SSO OAuth2 授权码模式
    - 传入 username + password → SSO 密码模式 或 本地密码模式
    - 仅传入 password → 本地 JWT 模式
    """
    sso_enabled = _is_sso_enabled()
    
    # 仅当 SSO 启用时才使用 provider.authenticate()（SSO 或 username+password 场景）
    credentials = login_req.model_dump(exclude_none=True)
    if sso_enabled and credentials:
        provider = _get_auth_provider()
        result = provider.authenticate(credentials)
        if result and result.get("token"):
            return LoginResponse(
                success=True,
                token=result.get("token"),
                user_id=result.get("user_id", "admin"),
                role=result.get("role", "user"),
                message="SSO登录成功"
            )
    
    # 本地JWT：仅 password 且未启用 SSO（或显式允许本地降级）
    if login_req.password and not login_req.username and not login_req.code:
        if sso_enabled and not _allow_local_fallback():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="已启用 SSO，请使用企业统一登录（不接受本地密码登录）"
            )
        try:
            result = AuthManager.login_with_role(login_req.password)
        except RuntimeError as e:
            msg = str(e)
            if "token store" in msg.lower() or "redis" in msg.lower():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="登录会话存储不可用（请检查 Redis 或改用 BLOG_WRITER_STATE_BACKEND=memory）",
                ) from e
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"登录失败: {msg[:200]}",
            ) from e
        if result:
            token, role = result
            return LoginResponse(
                success=True,
                token=token,
                user_id=role,
                role=role,
                message=f"{'管理员' if role == 'admin' else '运营'}登录成功"
            )
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证失败，请检查凭据"
    )


@router.get("/debug")
async def auth_debug():
    """调试端点：返回当前认证状态"""
    from blog_writer.security.auth import _get_credentials, _verify_password, _get_default_admin_hash
    admin_cred, operator_cred = _get_credentials()
    return {
        "admin_cred_len": len(admin_cred) if admin_cred else 0,
        "admin_cred_prefix": (admin_cred[:30] + "...") if admin_cred else "empty",
        "operator_cred_len": len(operator_cred) if operator_cred else 0,
        "default_hash_prefix": _get_default_admin_hash()[:30] + "...",
        "admin123_verify": _verify_password("admin123"),
        "config_source": "env" if admin_cred == _get_default_admin_hash() else "file",
    }


@router.post("/logout")
async def logout(authorization: str = Header(default="")):
    """
    登出
    """
    token = _extract_token(authorization)
    if token:
        provider = _get_auth_provider()
        provider.logout(token)
        AuthManager.logout(token)
    return {"success": True, "message": "已登出"}


@router.get("/verify")
async def verify_token(authorization: str = Header(default="")):
    """
    验证Token有效性
    
    同时检查本地JWT和SSO Token
    """
    token = _extract_token(authorization)
    if not token:
        return {"valid": False, "message": "未登录"}
    
    # 先检查本地Token
    if AuthManager.verify_token(token):
        token_info = AuthManager.get_token_info(token)
        role = token_info.get("role", "admin") if token_info else "admin"
        return {
            "valid": True,
            "user_id": role,
            "role": role,
            "expire_at": token_info.get("expire_at") if token_info else None,
            "message": "Token有效"
        }
    
    # 再检查SSO Token
    provider = _get_auth_provider()
    sso_result = provider.verify_token(token)
    if sso_result:
        return {
            "valid": True,
            "user_id": sso_result.get("user_id"),
            "role": sso_result.get("role", "user"),
            "expire_at": sso_result.get("expire_at"),
            "message": "SSO Token有效"
        }
    
    return {"valid": False, "message": "Token无效或已过期"}


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v):
        if len(v) < 4:
            raise ValueError("新密码至少4位")
        if len(v) > 128:
            raise ValueError("密码过长")
        return v


@router.post("/change-password")
async def change_password(request: Request, req: ChangePasswordRequest):
    """
    修改管理员密码（仅本地模式有效，SSO模式由公司平台管理）
    """
    if _is_sso_enabled() and not _allow_local_fallback():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSO 模式下请在企业平台修改密码"
        )

    result = AuthManager.login_with_role(req.old_password)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="旧密码错误"
        )
    
    token, role = result
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可修改密码"
        )

    AuthManager.set_admin_password(req.new_password)
    # 改密后吊销全部本地会话（含刚用于校验的临时 token）
    AuthManager.revoke_all_tokens()
    return {"success": True, "message": "密码修改成功，请重新登录"}


class ChangeOperatorPasswordRequest(BaseModel):
    """修改运营密码请求"""
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v):
        if len(v) < 4:
            raise ValueError("新密码至少4位")
        if len(v) > 128:
            raise ValueError("密码过长")
        return v


@router.post("/change-operator-password")
async def change_operator_password(request: Request, req: ChangeOperatorPasswordRequest):
    """
    修改运营密码（仅管理员可操作）
    """
    if _is_sso_enabled() and not _allow_local_fallback():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSO 模式下请在企业平台修改密码"
        )

    result = AuthManager.login_with_role(req.old_password)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="旧密码错误"
        )
    
    token, role = result
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可修改运营密码"
        )

    AuthManager.set_operator_password(req.new_password)
    # 吊销所有现有运营会话，防止旧密码 Token 继续有效
    AuthManager.revoke_all_tokens()
    return {"success": True, "message": "运营密码修改成功"}


def _extract_token(authorization: str) -> str:
    """从Authorization header中提取Token"""
    if not authorization:
        return ""
    if authorization.startswith("Bearer "):
        return authorization[7:]
    return authorization
