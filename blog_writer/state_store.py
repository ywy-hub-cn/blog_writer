"""进程外状态存储：Token / Webhook 等可外置到 Redis，默认内存。

环境变量：
  REDIS_URL=redis://localhost:6379/0
  BLOG_WRITER_STATE_BACKEND=memory|redis
"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class StateStore:
    """键值状态存储抽象。"""

    def set_json(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        raise NotImplementedError

    def get_json(self, key: str) -> Optional[Any]:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def keys(self, prefix: str) -> List[str]:
        raise NotImplementedError


class MemoryStateStore(StateStore):
    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _purge(self, key: str) -> None:
        exp = self._expiry.get(key)
        if exp is not None and time.time() >= exp:
            self._data.pop(key, None)
            self._expiry.pop(key, None)

    def set_json(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        with self._lock:
            self._data[key] = copy.deepcopy(value)
            if ttl_seconds:
                self._expiry[key] = time.time() + ttl_seconds
            else:
                self._expiry.pop(key, None)

    def get_json(self, key: str) -> Optional[Any]:
        with self._lock:
            self._purge(key)
            val = self._data.get(key)
            return copy.deepcopy(val) if val is not None else None

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)
            self._expiry.pop(key, None)

    def keys(self, prefix: str) -> List[str]:
        with self._lock:
            for k in list(self._expiry.keys()):
                self._purge(k)
            return [k for k in self._data if k.startswith(prefix)]


class RedisStateStore(StateStore):
    def __init__(self, url: str) -> None:
        try:
            import redis  # type: ignore
        except ImportError as e:
            raise ImportError(
                "Redis backend requires redis package. pip install redis"
            ) from e
        self._client = redis.Redis.from_url(url, decode_responses=True)

    def set_json(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        if ttl_seconds:
            self._client.setex(key, int(ttl_seconds), payload)
        else:
            self._client.set(key, payload)

    def get_json(self, key: str) -> Optional[Any]:
        raw = self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def keys(self, prefix: str) -> List[str]:
        # SCAN 更安全；前缀规模通常很小
        return list(self._client.scan_iter(match=f"{prefix}*"))


_store: Optional[StateStore] = None
_store_lock = threading.Lock()


def get_state_store() -> StateStore:
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is not None:
            return _store
        backend = os.environ.get("BLOG_WRITER_STATE_BACKEND", "").strip().lower()
        redis_url = os.environ.get("REDIS_URL", "").strip()
        # 默认 memory；不因环境里存在 REDIS_URL（其他 Java 服务共用）而自动切 Redis
        if not backend:
            backend = "memory"
        if backend == "redis":
            url = redis_url or "redis://localhost:6379/0"
            try:
                store = RedisStateStore(url)
                store.set_json("_blog_writer_ping", {"ok": True}, ttl_seconds=10)
                store.delete("_blog_writer_ping")
                logger.info("StateStore: redis (%s)", url.split("@")[-1])
                _store = store
                return _store
            except Exception as e:
                logger.warning("Redis unavailable (%s), falling back to memory", e)
        _store = MemoryStateStore()
        logger.info("StateStore: memory")
        return _store


def reset_state_store_for_tests() -> None:
    global _store
    with _store_lock:
        _store = MemoryStateStore()
