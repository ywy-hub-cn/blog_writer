"""鉴权模块 - 登录、Token管理、IP限流

密码采用 PBKDF2-SHA256 哈希存储（带随机盐），支持双角色（运营 operator / 管理员 admin）。
密码来源：环境变量优先，配置文件次之。
Token：默认内存；若配置 REDIS_URL / BLOG_WRITER_STATE_BACKEND=redis 则外置。
"""
import hashlib
import hmac
import json
import logging
import os
import secrets
import time 
import threading
from typing import Dict, Optional, Tuple
from pathlib import Path

from blog_writer.state_store import get_state_store

logger = logging.getLogger(__name__)

# === 密码哈希常量 ===
_PBKDF2_ITERATIONS = 600000  # OWASP 2023 推荐值
_PBKDF2_HASH_ALGO = "sha256"
_PBKDF2_SALT_BYTES = 16
_PBKDF2_DKLEN = 32
_PBKDF2_PREFIX = "$pbkdf2-sha256$"

# 默认密码 admin123 的预计算哈希（惰性加载）
_DEFAULT_ADMIN_HASH: Optional[str] = None


def _get_default_admin_hash() -> str:
    global _DEFAULT_ADMIN_HASH
    if _DEFAULT_ADMIN_HASH is None:
        _DEFAULT_ADMIN_HASH = _hash_password("admin123")
    return _DEFAULT_ADMIN_HASH


# === 密码哈希工具 ===

def _hash_password(password: str) -> str:
    """生成 PBKDF2-SHA256 哈希，格式：$pbkdf2-sha256$iterations$salt$hash"""
    salt = secrets.token_hex(_PBKDF2_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        _PBKDF2_HASH_ALGO,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
        dklen=_PBKDF2_DKLEN,
    )
    return f"{_PBKDF2_PREFIX}{_PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def _check_password(password: str, stored: str) -> bool:
    """验证密码是否匹配 PBKDF2-SHA256 哈希值。

    格式：$pbkdf2-sha256$iterations$salt$hash
    password 与 stored 均为明文，stored 是已存储的哈希值。
    """
    try:
        parts = stored[len(_PBKDF2_PREFIX):].split("$")
        if len(parts) != 3:
            return False
        iterations_str, salt, stored_hash_hex = parts
        iterations = int(iterations_str)
        dk = hashlib.pbkdf2_hmac(
            _PBKDF2_HASH_ALGO,
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
            dklen=_PBKDF2_DKLEN,
        )
        return hmac.compare_digest(dk.hex(), stored_hash_hex)
    except (ValueError, TypeError):
        return False


# Token 内存备份（与 StateStore 双写，保证同进程快速路径）
_active_tokens: Dict[str, Dict] = {}

# IP限流: {ip: [timestamp, ...]}
_rate_limit: Dict[str, list] = {}

_lock = threading.Lock()

_config_cache: Optional[dict] = None
_config_cache_time: float = 0
_CONFIG_CACHE_TTL: float = 1.0  # 降低缓存TTL确保配置变更即时生效

_TOKEN_KEY_PREFIX = "blog_writer:auth:token:"

# 角色定义
ROLE_ADMIN = "admin"      # 管理员：完整权限
ROLE_OPERATOR = "operator"  # 运营：运营相关权限


def _get_config_path() -> Path:
    """获取配置文件路径（与 ConfigManager 一致，支持 BLOG_WRITER_CONFIG）"""
    env_path = os.environ.get("BLOG_WRITER_CONFIG", "").strip()
    if env_path:
        return Path(env_path)
    return Path(__file__).parent.parent / "config.json"


def _load_config() -> dict:
    """加载配置（带缓存）"""
    global _config_cache, _config_cache_time

    now = time.time()
    if _config_cache is not None and (now - _config_cache_time) < _CONFIG_CACHE_TTL:
        return _config_cache

    config_path = _get_config_path()
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                _config_cache = json.load(f)
                _config_cache_time = now
                return _config_cache
        except Exception:
            pass
    return {}


def _invalidate_cache() -> None:
    """使配置缓存失效"""
    global _config_cache, _config_cache_time
    _config_cache = None
    _config_cache_time = 0


def _save_config(config: dict) -> None:
    """保存配置（原子写入）"""
    config_path = _get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = config_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
        f.flush()
    os.replace(tmp_path, config_path)
    _invalidate_cache()


def _get_credentials() -> Tuple[str, str]:
    """获取凭据并返回 (admin_credential, operator_credential)。

    所有凭据均为 PBKDF2-SHA256 哈希格式：
    - 环境变量：读入后立即哈希（$pbkdf2-sha256$...）
    - 配置文件：读取 admin_password_hash / operator_password_hash
    - 默认值：admin123 的 PBKDF2 哈希
    """
    config = _load_config()
    security_cfg = config.get("security", {})
    
    # 管理员凭据
    env_admin = os.environ.get(
        security_cfg.get("admin_password_env", "BLOG_WRITER_ADMIN_PASSWORD"), ""
    ).strip()
    if env_admin:
        admin_cred = _hash_password(env_admin)
    else:
        admin_cred = str(security_cfg.get("admin_password_hash", "") or "").strip()
    if not admin_cred:
        admin_cred = _get_default_admin_hash()
    
    # 运营凭据（可选，不设置则运营登录不可用）
    env_operator = os.environ.get(
        security_cfg.get("operator_password_env", "BLOG_WRITER_OPERATOR_PASSWORD"), ""
    ).strip()
    if env_operator:
        operator_cred = _hash_password(env_operator)
    else:
        operator_cred = str(security_cfg.get("operator_password_hash", "") or "").strip()
    
    return admin_cred, operator_cred


def _verify_password(password: str) -> Optional[str]:
    """验证密码并返回角色（admin / operator），使用 _check_password 支持哈希和明文两种格式。"""
    admin_cred, operator_cred = _get_credentials()
    
    if _check_password(password, admin_cred):
        return ROLE_ADMIN
    if operator_cred and _check_password(password, operator_cred):
        return ROLE_OPERATOR
    return None


def _token_store_key(token: str) -> str:
    return f"{_TOKEN_KEY_PREFIX}{token}"


def _persist_token(token: str, data: dict, ttl_seconds: int) -> None:
    """写入 Token；若配置了 Redis 后端则写入失败时抛错（fail-closed）。"""
    _active_tokens[token] = data
    store = get_state_store()
    backend = os.environ.get("BLOG_WRITER_STATE_BACKEND", "").strip().lower()
    if not backend:
        backend = "redis" if os.environ.get("REDIS_URL", "").strip() else "memory"
    require_external = backend == "redis"
    try:
        store.set_json(_token_store_key(token), data, ttl_seconds=ttl_seconds)
        if require_external and not isinstance(store.get_json(_token_store_key(token)), dict):
            raise RuntimeError("token persist verify failed")
    except Exception as e:
        _active_tokens.pop(token, None)
        if require_external:
            raise RuntimeError(f"token store unavailable: {e}") from e
        logger.warning("token external persist skipped: %s", e)


def _load_token(token: str) -> Optional[dict]:
    data = _active_tokens.get(token)
    if data:
        return data
    try:
        data = get_state_store().get_json(_token_store_key(token))
        if isinstance(data, dict):
            _active_tokens[token] = data
            return data
    except Exception:
        pass
    return None


def _delete_token(token: str) -> None:
    _active_tokens.pop(token, None)
    try:
        get_state_store().delete(_token_store_key(token))
    except Exception:
        pass


def _cleanup_expired_tokens() -> None:
    """清理过期Token（内存）"""
    now = time.time()
    expired = [
        token for token, data in _active_tokens.items() if now >= data["expire_at"]
    ]
    for token in expired:
        _delete_token(token)


class AuthManager:
    """鉴权管理器（线程安全）"""

    @staticmethod
    def login(password: str) -> Optional[str]:
        """验证密码并生成Token（线程安全）。
        
        返回 Token 字符串；密码错误返回 None。
        """
        with _lock:
            role = _verify_password(password)
            if role is None:
                return None

            config = _load_config()
            security_cfg = config.get("security", {})
            expire_hours = security_cfg.get("token_expire_hours", 24)
            
            token = secrets.token_urlsafe(32)
            now = time.time()
            ttl = int(expire_hours * 3600)
            token_data = {
                "expire_at": now + ttl,
                "created_at": now,
                "role": role,
            }
            try:
                _persist_token(token, token_data, ttl_seconds=ttl)
            except RuntimeError:
                return None
            _cleanup_expired_tokens()
            return token

    @staticmethod
    def login_with_role(password: str) -> Optional[Tuple[str, str]]:
        """验证密码并返回 (token, role) 元组。"""
        with _lock:
            role = _verify_password(password)
            if role is None:
                return None

            config = _load_config()
            security_cfg = config.get("security", {})
            expire_hours = security_cfg.get("token_expire_hours", 24)
            
            token = secrets.token_urlsafe(32)
            now = time.time()
            ttl = int(expire_hours * 3600)
            token_data = {
                "expire_at": now + ttl,
                "created_at": now,
                "role": role,
            }
            try:
                _persist_token(token, token_data, ttl_seconds=ttl)
            except RuntimeError:
                return None
            _cleanup_expired_tokens()
            return token, role

    @staticmethod
    def verify_token(token: str) -> bool:
        """验证Token是否有效（线程安全）"""
        if not token:
            return False

        with _lock:
            _cleanup_expired_tokens()
            token_data = _load_token(token)
            if not token_data:
                return False
            if time.time() >= token_data["expire_at"]:
                _delete_token(token)
                return False
            return True

    @staticmethod
    def get_token_info(token: str) -> Optional[dict]:
        """获取Token信息（线程安全）"""
        with _lock:
            token_data = _load_token(token)
            if not token_data:
                return None
            return {
                "created_at": token_data.get("created_at"),
                "expire_at": token_data.get("expire_at"),
                "role": token_data.get("role", ROLE_ADMIN),
            }

    @staticmethod
    def logout(token: str) -> None:
        """注销Token（线程安全）"""
        with _lock:
            _delete_token(token)

    @staticmethod
    def set_admin_password(new_password: str) -> None:
        """设置管理员密码（哈希存储，线程安全）"""
        with _lock:
            config = _load_config()
            if "security" not in config:
                config["security"] = {}
            config["security"]["admin_password_hash"] = _hash_password(new_password)
            _save_config(config)

    @staticmethod
    def set_operator_password(new_password: str) -> None:
        """设置运营密码（哈希存储，线程安全）"""
        with _lock:
            config = _load_config()
            if "security" not in config:
                config["security"] = {}
            config["security"]["operator_password_hash"] = _hash_password(new_password)
            _save_config(config)

    @staticmethod
    def revoke_all_tokens() -> int:
        """吊销全部本地会话 Token（改密后调用）。"""
        with _lock:
            tokens = list(_active_tokens.keys())
            for token in tokens:
                _delete_token(token)
            try:
                store = get_state_store()
                for key in store.keys(_TOKEN_KEY_PREFIX):
                    store.delete(key)
            except Exception:
                pass
            return len(tokens)

    @staticmethod
    def check_rate_limit(ip: str) -> bool:
        """检查IP是否限流，返回True表示允许请求（线程安全）"""
        with _lock:
            now = time.time()
            config = _load_config()
            security_cfg = config.get("security", {})
            max_requests = security_cfg.get("rate_limit_per_minute", 10)
            window = 60

            if ip not in _rate_limit:
                _rate_limit[ip] = []

            _rate_limit[ip] = [ts for ts in _rate_limit[ip] if now - ts < window]

            if len(_rate_limit[ip]) >= max_requests:
                return False

            _rate_limit[ip].append(now)

            # 定期清理不活跃 IP（每 300 秒执行一次）
            if len(_rate_limit) > 1000:
                cutoff = now - window
                stale = [k for k, ts_list in _rate_limit.items()
                         if not ts_list or ts_list[-1] < cutoff]
                for k in stale:
                    del _rate_limit[k]

            return True

    @staticmethod
    def get_rate_limit_info(ip: str) -> dict:
        """获取限流信息（线程安全）"""
        with _lock:
            now = time.time()
            config = _load_config()
            security_cfg = config.get("security", {})
            max_requests = security_cfg.get("rate_limit_per_minute", 10)

            records = _rate_limit.get(ip, [])
            recent = [ts for ts in records if now - ts < 60]

            return {
                "current": len(recent),
                "max": max_requests,
                "reset_in": 60 - (now - recent[0]) if recent else 0,
            }
