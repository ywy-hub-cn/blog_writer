"""
blog_writer/security/rate_limiter.py - API 限流中间件

实现双层限流机制：
1. 全局限流（GlobalTokenBucket）：保护服务整体不被过载
2. 客户端限流（PerClientThrottle）：按IP+用户维度限制单客户端请求
3. 端点限流：敏感接口（如登录、LLM调用）更严格的限制

支持：
- Token Bucket 算法
- 滑动窗口计数
- 突发流量容忍
- 限流审计日志（写入数据库）
"""
import time
import threading
import logging
from typing import Dict, Optional, Tuple
from collections import defaultdict
from datetime import datetime

from blog_writer.db import AuditLogRepository

logger = logging.getLogger(__name__)


class TokenBucket:
    """Token Bucket - 平滑限流
    
    Token 以固定速率添加，突发流量可以消耗积累的 Token。
    """
    
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()
    
    def acquire(self, tokens: int = 1) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens += elapsed * self.refill_rate
            if self.tokens > self.capacity:
                self.tokens = self.capacity
            self.last_refill = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def current_tokens(self) -> float:
        with self._lock:
            return self.tokens


class SlidingWindowCounter:
    """滑动窗口计数器 - 精确限流"""
    
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: list = []
        self._lock = threading.Lock()
    
    def acquire(self) -> bool:
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds
            self.requests = [t for t in self.requests if t > cutoff]
            
            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return True
            return False
    
    def current_count(self) -> int:
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds
            # 同时清理过期条目，防止内存泄漏
            self.requests = [t for t in self.requests if t > cutoff]
            return len(self.requests)


class RateLimiter:
    """双层层限流器
    
    层级1: 全局 Token Bucket（保护服务整体）
    层级2: 客户端滑动窗口（限制单客户端）
    
    自带内存管理：定期清理长期未活跃的客户端桶，防止内存泄漏。
    """
    
    # 清理间隔：每5分钟清理一次不活跃的客户端桶
    _cleanup_interval = 300  # seconds
    # 客户端桶最大闲置时间：10分钟无请求则清理
    _client_max_idle = 600  # seconds
    
    def __init__(
        self,
        global_rate: int = 100,
        global_burst: int = 200,
        per_client_rate: int = 10,
        per_client_burst: int = 20,
        per_client_window: int = 60,
        audit_enabled: bool = True
    ):
        self.global_bucket = TokenBucket(global_burst, global_rate)
        
        self.per_client_window = per_client_window
        self.per_client_rate = per_client_rate
        self.per_client_burst = per_client_burst
        self._client_buckets: Dict[str, SlidingWindowCounter] = {}
        self._client_last_access: Dict[str, float] = {}  # 跟踪每个桶的最后访问时间
        self._client_buckets_lock = threading.Lock()
        # 端点限流桶独立存放，不参与 idle 清理（配置静态）
        self._endpoint_buckets: Dict[str, SlidingWindowCounter] = {}
        self._endpoint_buckets_lock = threading.Lock()
        
        self._endpoint_limits: Dict[str, Tuple[int, int]] = {}
        
        self._last_cleanup = time.monotonic()
        
        self._audit_enabled = audit_enabled
        self._audit_repo: Optional[AuditLogRepository] = None
        if audit_enabled:
            try:
                from blog_writer.db import get_database
                db = get_database()
                self._audit_repo = AuditLogRepository(db)
            except Exception:
                logger.warning("Rate limit audit disabled: database not available")
                self._audit_enabled = False
    
    def set_endpoint_limit(self, endpoint: str, max_requests: int, window_seconds: int):
        self._endpoint_limits[endpoint] = (max_requests, window_seconds)
    
    def _get_client_bucket(self, client_id: str) -> SlidingWindowCounter:
        now = time.monotonic()
        with self._client_buckets_lock:
            if client_id not in self._client_buckets:
                self._client_buckets[client_id] = SlidingWindowCounter(
                    self.per_client_rate,
                    self.per_client_window
                )
            self._client_last_access[client_id] = now
            self._maybe_cleanup(now)
            return self._client_buckets[client_id]
    
    def _match_endpoint_limit(self, endpoint: str) -> Optional[Tuple[str, int, int]]:
        """精确匹配优先，其次最长前缀（支持 /api/admin/ 覆盖子路径）。"""
        if endpoint in self._endpoint_limits:
            max_req, window = self._endpoint_limits[endpoint]
            return endpoint, max_req, window
        best_key = None
        best_len = -1
        for ep, (max_req, window) in self._endpoint_limits.items():
            if not ep:
                continue
            if ep.endswith("/"):
                if endpoint.startswith(ep) and len(ep) > best_len:
                    best_key = ep
                    best_len = len(ep)
            elif endpoint.startswith(ep + "/") and len(ep) > best_len:
                best_key = ep
                best_len = len(ep)
        if best_key is None:
            return None
        max_req, window = self._endpoint_limits[best_key]
        return best_key, max_req, window

    def _check_endpoint_limit(self, endpoint: str) -> Optional[SlidingWindowCounter]:
        matched = self._match_endpoint_limit(endpoint)
        if not matched:
            return None
        ep_key, max_req, window = matched
        key = f"endpoint:{ep_key}"
        with self._endpoint_buckets_lock:
            if key not in self._endpoint_buckets:
                self._endpoint_buckets[key] = SlidingWindowCounter(max_req, window)
            return self._endpoint_buckets[key]
    
    def _maybe_cleanup(self, now: float):
        """定期清理不活跃的客户端桶，防止内存泄漏。端点桶不清理。"""
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        
        stale_keys = [
            k for k, last_access in self._client_last_access.items()
            if now - last_access > self._client_max_idle
        ]
        for key in stale_keys:
            self._client_buckets.pop(key, None)
            self._client_last_access.pop(key, None)
        
        if stale_keys:
            logger.debug(
                f"Rate limiter cleanup: removed {len(stale_keys)} stale client buckets, "
                f"active={len(self._client_buckets)}"
            )
    
    def is_allowed(self, client_id: str, endpoint: str = "/") -> Tuple[bool, str]:
        # 先查客户端/端点，避免被拒客户端仍消耗全局部额度
        client_bucket = self._get_client_bucket(client_id)
        if not client_bucket.acquire():
            self._log_violation("client", client_id, endpoint)
            return False, f"Per-client rate limit exceeded ({self.per_client_rate}/{self.per_client_window}s)"

        endpoint_bucket = self._check_endpoint_limit(endpoint)
        if endpoint_bucket and not endpoint_bucket.acquire():
            self._log_violation("endpoint", client_id, endpoint)
            return False, f"Endpoint rate limit exceeded for {endpoint}"

        if not self.global_bucket.acquire():
            self._log_violation("global", client_id, endpoint)
            return False, "Global rate limit exceeded"

        return True, ""
    
    def _log_violation(self, violation_type: str, client_id: str, endpoint: str):
        logger.warning(
            f"Rate limit violation: type={violation_type}, "
            f"client={client_id}, endpoint={endpoint}"
        )
        if self._audit_enabled and self._audit_repo:
            try:
                # 优先写入专用 rate_limit_audit 表
                if hasattr(self._audit_repo, "log_rate_limit"):
                    self._audit_repo.log_rate_limit(
                        client_id=client_id,
                        endpoint=endpoint,
                        violation_type=violation_type,
                    )
                else:
                    self._audit_repo.log_event(
                        event_type="rate_limit_exceeded",
                        event_source=endpoint,
                        details=f"violation_type={violation_type}",
                        actor=client_id
                    )
            except Exception:
                pass
    
    def get_stats(self) -> Dict:
        return {
            "global_tokens": self.global_bucket.current_tokens(),
            "active_clients": len(self._client_buckets),
            "endpoint_buckets": len(self._endpoint_buckets),
            "endpoint_limits": dict(self._endpoint_limits),
        }


# 全局限流器实例（带线程安全锁）
_rate_limiter: Optional[RateLimiter] = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter() -> RateLimiter:
    """获取全局限流器（线程安全懒加载）"""
    global _rate_limiter
    if _rate_limiter is None:
        with _rate_limiter_lock:
            if _rate_limiter is None:
                _rate_limiter = RateLimiter(
                    global_rate=2.0,  # ≈120/min
                    global_burst=240,
                    per_client_rate=120,
                    per_client_burst=240,
                    per_client_window=60
                )
    return _rate_limiter


def init_rate_limiter(config: Dict, *, force: bool = False):
    """根据配置初始化限流器（线程安全）。

    force=True 时按新配置重建（配置热更新用）。
    """
    global _rate_limiter
    
    with _rate_limiter_lock:
        if _rate_limiter is not None and not force:
            logger.info("Rate limiter already initialized, skipping re-init")
            return
        
        security_cfg = config.get("security", {})
        
        rate = security_cfg.get("rate_limit_per_minute", 120)
        burst = security_cfg.get("rate_limit_burst", 240)
        window = security_cfg.get("rate_limit_window_seconds", 60)

        # TokenBucket.refill_rate 单位为「每秒」；配置项为「每分钟」
        # global_rate_multiplier 默认 1.0（可用配置放宽全局限流）
        try:
            multiplier = float(security_cfg.get("global_rate_multiplier", 1.0) or 1.0)
        except (TypeError, ValueError):
            multiplier = 1.0
        multiplier = max(0.1, min(multiplier, 10.0))
        global_per_sec = max(float(rate) / 60.0, 0.1) * multiplier
        
        _rate_limiter = RateLimiter(
            global_rate=global_per_sec,
            global_burst=burst * 4,
            per_client_rate=rate,
            per_client_burst=burst,
            per_client_window=window
        )
        
        _rate_limiter.set_endpoint_limit("/api/v1/auth/login", 20, 60)
        _rate_limiter.set_endpoint_limit("/api/auth/login", 20, 60)
        _rate_limiter.set_endpoint_limit("/api/v1/auth/token", 20, 60)
        _rate_limiter.set_endpoint_limit("/api/auth/token", 20, 60)
        _rate_limiter.set_endpoint_limit("/api/v1/tasks/start", rate, window)
        _rate_limiter.set_endpoint_limit("/api/tasks/start", rate, window)
        _rate_limiter.set_endpoint_limit("/api/v1/tasks/execute", rate, window)
        _rate_limiter.set_endpoint_limit("/api/tasks/execute", rate, window)
        _rate_limiter.set_endpoint_limit("/api/v1/admin/", 30, 60)
        _rate_limiter.set_endpoint_limit("/api/admin/", 30, 60)
        logger.info(
            "Rate limiter %s: global=%.2f/s client=%s/%ss multiplier=%.2f",
            "reinitialized" if force else "initialized",
            global_per_sec,
            rate,
            window,
            multiplier,
        )


def reinit_rate_limiter(config: Dict):
    """配置热更新：强制按新配置重建限流器。"""
    init_rate_limiter(config, force=True)

