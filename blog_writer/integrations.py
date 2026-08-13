"""
blog_writer/integrations.py - 企业平台集成适配器

为系统提供对接公司已有平台的标准化接口层：
- 认证对接：SSO/OAuth2 企业统一认证
- 日志对接：结构化日志输出 + Webhook 回调
- 监控对接：Prometheus 格式指标 + 告警 Webhook
- 通知对接：企业微信/钉钉/飞书 Webhook 通知

设计原则：抽象而非删除，保留内置实现作为默认值，
企业部署时通过配置切换到公司平台组件。
"""

import json
import os
import time
import threading
import logging
import hashlib
import secrets
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime
from pathlib import Path

from blog_writer.security.auth import _check_password as _check_pwd_hash
from blog_writer.security.auth import _get_default_admin_hash, _hash_password

logger = logging.getLogger(__name__)

# 角色常量（与 security.auth 保持一致）
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"


# ==============================================================================
# 认证适配器
# ==============================================================================

class AuthProvider(ABC):
    """认证提供者抽象接口
    
    可对接：本地 JWT、SSO、OAuth2、LDAP、企业微信等
    """
    
    @abstractmethod
    def authenticate(self, credentials: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """验证凭据并返回用户信息
        
        Returns:
            用户信息 dict (含 token, user_id, roles 等) 或 None
        """
        pass
    
    @abstractmethod
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证 Token 并返回用户信息"""
        pass
    
    @abstractmethod
    def logout(self, token: str) -> bool:
        """注销 Token"""
        pass
    
    def get_provider_name(self) -> str:
        return self.__class__.__name__


class LocalAuthProvider(AuthProvider):
    """本地 JWT 认证（默认实现，保留用于独立部署）

    支持双角色：管理员(admin) 和 运营(operator)。
    密码通过 PBKDF2-SHA256 哈希存储（带随机盐），
    向后兼容配置文件中的明文密码。
    """

    def __init__(self, config_path: str = None):
        self._active_tokens: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._config_path = Path(config_path) if config_path else None
        self._config_cache: Optional[dict] = None
        self._config_cache_time: float = 0

    def _load_config(self) -> dict:
        if self._config_path is None:
            self._config_path = Path(__file__).parent / "config.json"

        now = time.time()
        if self._config_cache and (now - self._config_cache_time) < 5.0:
            return self._config_cache

        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    self._config_cache = json.load(f)
                    self._config_cache_time = now
            except Exception:
                self._config_cache = {}
        return self._config_cache or {}

    def authenticate(self, credentials: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """密码验证，支持管理员和运营双角色（所有凭据均为哈希格式）。"""
        password = credentials.get("password", "")
        if not password:
            return None

        with self._lock:
            config = self._load_config()
            security_cfg = config.get("security", {})

            # 管理员凭据：环境变量读入后立即哈希，配置文件仅读取哈希
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

            role = None
            if _check_pwd_hash(password, admin_cred):
                role = ROLE_ADMIN
            elif operator_cred and _check_pwd_hash(password, operator_cred):
                role = ROLE_OPERATOR

            if role is None:
                return None

            token = secrets.token_urlsafe(32)
            expire_hours = security_cfg.get("token_expire_hours", 24)
            now = time.time()
            self._active_tokens[token] = {
                "user_id": role,
                "role": role,
                "created_at": now,
                "expire_at": now + expire_hours * 3600,
            }
            return {"token": token, "user_id": role, "role": role}

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._active_tokens.get(token)
            if not data:
                return None
            if time.time() >= data["expire_at"]:
                del self._active_tokens[token]
                return None
            return {"token": token, **data}

    def logout(self, token: str) -> bool:
        with self._lock:
            if token in self._active_tokens:
                del self._active_tokens[token]
                return True
            return False

class SSOAuthProvider(AuthProvider):
    """SSO/OAuth2 企业统一认证适配器
    
    对接公司 SSO 系统（如 CAS、OAuth2、OIDC）。
    配置后自动将认证请求转发到公司认证服务。
    
    Session：内存 + StateStore 双写（REDIS_URL 时可跨进程恢复）。
    
    配置项（config.security.sso）：
        - enabled: true
        - auth_url: 公司SSO登录URL
        - token_url: 公司Token获取URL
        - client_id: OAuth2 Client ID
        - client_secret: OAuth2 Client Secret（或环境变量）
        - redirect_uri: 回调URL
        - scopes: ["openid", "profile"]
        - api_base_url: 公司API Base URL
    """
    
    _SESSION_PREFIX = "blog_writer:sso:session:"
    _SESSION_CLEANUP_INTERVAL = 600  # 10 分钟

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._session_tokens: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._last_session_cleanup = 0.0

    def _maybe_cleanup_sessions(self) -> None:
        now = time.time()
        if now - self._last_session_cleanup < self._SESSION_CLEANUP_INTERVAL:
            return
        self._last_session_cleanup = now
        expired = [
            tok for tok, data in self._session_tokens.items()
            if now >= float(data.get("expire_at") or 0)
        ]
        for tok in expired:
            self._session_tokens.pop(tok, None)
        if expired:
            logger.debug("SSO session cleanup: removed %s expired sessions", len(expired))

    def _session_key(self, token: str) -> str:
        return f"{self._SESSION_PREFIX}{token}"

    def _store_session(self, access_token: str, data: Dict[str, Any]) -> None:
        with self._lock:
            self._maybe_cleanup_sessions()
            self._session_tokens[access_token] = data
        ttl = max(int(data.get("expire_at", time.time() + 3600) - time.time()), 60)
        try:
            from blog_writer.state_store import get_state_store
            get_state_store().set_json(self._session_key(access_token), data, ttl_seconds=ttl)
        except Exception as e:
            logger.warning("SSO session external persist skipped: %s", e)

    def _load_session(self, token: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._maybe_cleanup_sessions()
            data = self._session_tokens.get(token)
            if data:
                return data
        try:
            from blog_writer.state_store import get_state_store
            data = get_state_store().get_json(self._session_key(token))
            if isinstance(data, dict):
                with self._lock:
                    self._session_tokens[token] = data
                return data
        except Exception:
            pass
        return None

    def _delete_session(self, token: str) -> bool:
        removed = False
        with self._lock:
            if token in self._session_tokens:
                del self._session_tokens[token]
                removed = True
        try:
            from blog_writer.state_store import get_state_store
            get_state_store().delete(self._session_key(token))
        except Exception:
            pass
        return removed
    
    def authenticate(self, credentials: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将认证请求转发到公司SSO
        
        支持两种模式：
        1. code模式：前端获取code后传给后端交换token
        2. password模式：直接转发密码到SSO（部分公司支持）
        """
        sso_cfg = self.config.get("security", {}).get("sso") or self.config.get("sso") or {}
        if not sso_cfg.get("enabled", False):
            logger.warning("SSO认证未启用")
            return None
        
        code = credentials.get("code", "")
        if code:
            return self._exchange_code(code, sso_cfg)
        
        username = credentials.get("username", "")
        password = credentials.get("password", "")
        if username and password:
            return self._forward_password(username, password, sso_cfg)
        
        return None
    
    def _exchange_code(self, code: str, sso_cfg: Dict) -> Optional[Dict[str, Any]]:
        """OAuth2 code 换取 token"""
        try:
            import urllib.request
            import urllib.parse
            
            token_url = sso_cfg.get("token_url", "")
            data = urllib.parse.urlencode({
                "grant_type": "authorization_code",
                "code": code,
                "client_id": sso_cfg.get("client_id", ""),
                "client_secret": sso_cfg.get("client_secret", ""),
                "redirect_uri": sso_cfg.get("redirect_uri", ""),
            }).encode()
            
            req = urllib.request.Request(token_url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
            
            access_token = result.get("access_token", "")
            user_info = self._fetch_user_info(access_token, sso_cfg)

            if not user_info:
                logger.error("SSO code交换成功但无法获取用户信息，拒绝登录")
                return None

            user_id = str(
                user_info.get("sub")
                or user_info.get("username")
                or user_info.get("user_id")
                or ""
            ).strip()
            if not user_id or user_id.lower() in ("unknown", "anonymous", "null", "none"):
                logger.error("SSO 用户身份无效: %r", user_id)
                return None

            self._store_session(access_token, {
                "user_id": user_id,
                "role": user_info.get("role", "user"),
                "created_at": time.time(),
                "expire_at": time.time() + result.get("expires_in", 3600),
            })
            return {"token": access_token, "user_id": user_id, **user_info}
        except Exception as e:
            logger.error(f"SSO code交换失败: {e}")
        return None
    
    def _forward_password(self, username: str, password: str, sso_cfg: Dict) -> Optional[Dict[str, Any]]:
        """转发密码到SSO"""
        try:
            import urllib.request
            import urllib.parse
            
            token_url = sso_cfg.get("token_url", "")
            data = urllib.parse.urlencode({
                "grant_type": "password",
                "username": username,
                "password": password,
                "client_id": sso_cfg.get("client_id", ""),
                "client_secret": sso_cfg.get("client_secret", ""),
            }).encode()
            
            req = urllib.request.Request(token_url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
            
            access_token = result.get("access_token", "")
            if access_token:
                self._store_session(access_token, {
                    "user_id": username,
                    "role": "user",
                    "created_at": time.time(),
                    "expire_at": time.time() + result.get("expires_in", 3600),
                })
                return {"token": access_token, "user_id": username, "role": "user"}
        except Exception as e:
            logger.error(f"SSO密码转发失败: {e}")
        return None
    
    def _fetch_user_info(self, access_token: str, sso_cfg: Dict) -> Optional[Dict]:
        """获取用户信息；失败返回 None（禁止塌缩为 unknown 破坏归属隔离）。"""
        try:
            import urllib.request

            userinfo_url = sso_cfg.get("userinfo_url", "")
            if not userinfo_url:
                logger.error("SSO userinfo_url 未配置")
                return None

            req = urllib.request.Request(userinfo_url)
            req.add_header("Authorization", f"Bearer {access_token}")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            if not isinstance(data, dict):
                return None
            return data
        except Exception as e:
            logger.error(f"SSO 获取用户信息失败: {e}")
            return None
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        data = self._load_session(token)
        if not data:
            return None
        if time.time() >= data.get("expire_at", 0):
            self._delete_session(token)
            return None
        return {"token": token, **data}
    
    def logout(self, token: str) -> bool:
        return self._delete_session(token)


def create_auth_provider(config: Dict[str, Any] = None) -> AuthProvider:
    """根据配置创建认证提供者"""
    config = config or {}
    security_cfg = config.get("security", {})
    # 兼容根级 sso 与 security.sso 两种写法
    sso_cfg = security_cfg.get("sso") or config.get("sso") or {}
    
    if sso_cfg.get("enabled", False):
        # 规范化到 security.sso，供 SSOAuthProvider 读取
        if "sso" not in security_cfg:
            merged = dict(config)
            merged["security"] = {**security_cfg, "sso": sso_cfg}
            config = merged
        logger.info("使用 SSO/OAuth2 认证提供者")
        return SSOAuthProvider(config)
    
    logger.info("使用本地 JWT 认证提供者")
    return LocalAuthProvider()


# ==============================================================================
# 日志适配器（结构化日志 + Webhook）
# ==============================================================================

class StructuredLogFormatter(logging.Formatter):
    """结构化日志格式化器
    
    输出 JSON 格式，包含 trace_id/task_id/level/timestamp 等字段。
    便于 Loki/ELK 直接采集和索引。
    """
    
    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        
        # 从 extra 中提取自定义字段
        extra_fields = {}
        if hasattr(record, "trace_id"):
            log_entry["trace_id"] = record.trace_id
        if hasattr(record, "task_id"):
            log_entry["task_id"] = record.task_id
        if hasattr(record, "user_id"):
            log_entry["user_id"] = record.user_id
        
        if record.exc_info and record.exc_info[0]:
            import traceback
            log_entry["exception"] = traceback.format_exception(
                *record.exc_info
            )
        
        return json.dumps(log_entry, ensure_ascii=False)


class WebhookLogHandler(logging.Handler):
    """Webhook 日志处理器
    
    将错误级别的日志推送到企业通知系统（企业微信/钉钉/飞书 Webhook）。
    用于关键告警场景（如任务失败、LLM调用异常等）。
    """
    
    def __init__(self, webhook_url: str, min_level: int = logging.ERROR, max_buffer: int = 1000):
        super().__init__(min_level)
        self.webhook_url = webhook_url
        self._buffer: List[Dict] = []
        self._lock = threading.Lock()
        self._flush_interval = 30  # 秒
        self._last_flush = time.time()
        self._max_buffer = max(100, int(max_buffer))
    
    def emit(self, record: logging.LogRecord):
        try:
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
            }
            
            with self._lock:
                self._buffer.append(log_entry)
                if len(self._buffer) > self._max_buffer:
                    overflow = len(self._buffer) - self._max_buffer
                    del self._buffer[:overflow]
            
            # 立即发送或批量发送
            if record.levelno >= logging.CRITICAL:
                self._flush()
            elif time.time() - self._last_flush >= self._flush_interval:
                self._flush()
        except Exception:
            pass
    
    def _flush(self):
        with self._lock:
            if not self._buffer:
                return
            entries = self._buffer[:]
        
        try:
            import urllib.request
            
            payload = {
                "msgtype": "text",
                "text": {
                    "content": json.dumps(entries, ensure_ascii=False, indent=2)
                }
            }
            
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
            with self._lock:
                self._buffer.clear()
                self._last_flush = time.time()
        except Exception as e:
            logger.warning(f"Webhook日志推送失败: {e}")


def setup_structured_logging(config: Dict[str, Any] = None):
    """初始化结构化日志配置
    
    配置项（config.logging）：
        - format: "json" 或 "text" (默认 text)
        - webhook_url: 企业通知 Webhook URL（可选）
        - webhook_level: 推送级别 (ERROR/CRITICAL)
    """
    config = config or {}
    logging_cfg = config.get("logging", {})
    log_format = logging_cfg.get("format", "text")
    
    if log_format == "json":
        # 为所有 logger 设置 JSON 格式化器
        formatter = StructuredLogFormatter()
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)
        logger.info("结构化日志已启用 (JSON 格式)")
    
    # Webhook 告警
    webhook_url = logging_cfg.get("webhook_url", "")
    if webhook_url:
        webhook_level = getattr(logging, logging_cfg.get("webhook_level", "ERROR"), logging.ERROR)
        webhook_handler = WebhookLogHandler(webhook_url, webhook_level)
        logging.getLogger().addHandler(webhook_handler)
        logger.info(f"Webhook 告警已配置: {webhook_url}")


# ==============================================================================
# 指标适配器（Prometheus 格式）
# ==============================================================================

class MetricsCollector:
    """指标收集器
    
    收集应用级指标，支持 Prometheus text exposition format 输出。
    便于公司 Prometheus 直接抓取，Grafana 直接可视化。
    """

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    
    def __init__(self, histogram_buckets: tuple = None):
        self._counters: Dict[str, Dict[str, float]] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._histogram_buckets = tuple(histogram_buckets or self.DEFAULT_BUCKETS)
        self._lock = threading.Lock()
    
    def increment_counter(self, name: str, labels: Dict[str, str] = None, value: float = 1):
        """递增计数器"""
        with self._lock:
            key = name
            if labels:
                key += "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"
            self._counters[key] = self._counters.get(key, 0) + value
    
    def set_gauge(self, name: str, value: float):
        """设置仪表值"""
        with self._lock:
            self._gauges[name] = value
    
    def observe_histogram(self, name: str, value: float):
        """记录直方图观测值（保留样本用于分桶导出；上限 10000 条防泄漏）"""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(float(value))
            if len(self._histograms[name]) > 10000:
                self._histograms[name] = self._histograms[name][-5000:]
    
    def generate_prometheus(self) -> str:
        """生成 Prometheus text exposition format（含标准 histogram buckets）"""
        with self._lock:
            lines = []
            
            for name, value in self._counters.items():
                base = name.split("{")[0]
                lines.append(f"# TYPE blog_writer_{base} counter")
                lines.append(f"blog_writer_{name} {value}")
            
            for name, value in self._gauges.items():
                lines.append(f"# TYPE blog_writer_{name} gauge")
                lines.append(f"blog_writer_{name} {value}")
            
            for name, values in self._histograms.items():
                metric = f"blog_writer_{name}_seconds"
                lines.append(f"# TYPE {metric} histogram")
                total = len(values)
                for bound in self._histogram_buckets:
                    cumulative = sum(1 for v in values if v <= bound)
                    lines.append(f'{metric}_bucket{{le="{bound}"}} {cumulative}')
                lines.append(f'{metric}_bucket{{le="+Inf"}} {total}')
                lines.append(f"{metric}_sum {sum(values) if values else 0.0}")
                lines.append(f"{metric}_count {total}")
            
            return "\n".join(lines) + "\n"
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计数据（JSON 格式）"""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histogram_counts": {k: len(v) for k, v in self._histograms.items()},
            }


# 全局指标收集器实例
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """获取全局指标收集器"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


# ==============================================================================
# 通知适配器
# ==============================================================================

class NotificationService:
    """企业通知服务
    
    支持多种通知渠道，便于对接公司IM系统：
    - 企业微信 Webhook
    - 钉钉 Webhook
    - 飞书 Webhook
    - 自定义 Webhook
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._channels: Dict[str, Dict] = {}
        self._init_channels()
    
    def _init_channels(self):
        """初始化通知渠道"""
        notify_cfg = self.config.get("notifications", {})
        channels_cfg = notify_cfg.get("channels", {})
        
        for name, cfg in channels_cfg.items():
            if cfg.get("enabled", False):
                self._channels[name] = {
                    "webhook_url": cfg.get("webhook_url", ""),
                    "type": cfg.get("type", "generic"),
                    "mention": cfg.get("mention", ""),
                }
    
    def send(self, message: str, channel: str = None, level: str = "info") -> bool:
        """发送通知
        
        Args:
            message: 通知内容
            channel: 渠道名称，None 表示发送到所有启用的渠道
            level: 级别 (info/warning/error/critical)
        """
        targets = {}
        if channel and channel in self._channels:
            targets[channel] = self._channels[channel]
        else:
            targets = self._channels
        
        if not targets:
            return False
        
        success = False
        for name, cfg in targets.items():
            try:
                self._send_to_channel(message, cfg, level)
                success = True
            except Exception as e:
                logger.warning(f"通知渠道 {name} 发送失败: {e}")
        
        return success
    
    def _send_to_channel(self, message: str, cfg: Dict, level: str):
        """发送到单个渠道"""
        import urllib.request
        
        webhook_url = cfg.get("webhook_url", "")
        channel_type = cfg.get("type", "generic")
        mention = cfg.get("mention", "")
        
        if not webhook_url:
            return
        
        if channel_type == "wecom":
            payload = {
                "msgtype": "text",
                "text": {"content": f"[{level.upper()}] {message}"}
            }
        elif channel_type == "dingtalk":
            payload = {
                "msgtype": "text",
                "text": {"content": f"[{level.upper()}] {message}"},
                "at": {"isAtAll": False}
            }
        elif channel_type == "feishu":
            payload = {
                "msg_type": "text",
                "content": {"text": f"[{level.upper()}] {message}"}
            }
        else:
            payload = {
                "level": level,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            }
        
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    
    def list_channels(self) -> List[str]:
        """列出所有启用的渠道"""
        return list(self._channels.keys())


def create_notification_service(config: Dict[str, Any] = None) -> NotificationService:
    """创建通知服务"""
    return NotificationService(config)
