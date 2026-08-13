"""审核事件总线 - 可插拔的审核决策通知机制。

支持两种后端：
1. 内存模式（默认）：基于 asyncio.Event，单进程部署用
2. Redis 模式：基于 Redis Pub/Sub，多副本部署用

环境变量控制：
- REVIEW_EVENT_BACKEND=memory（默认）或 redis
- REDIS_URL=redis://localhost:6379/0（Redis模式必需）

设计原则：
- 接口统一，上层代码不感知具体后端
- Redis 不可用时自动降级为内存模式，不阻塞流程
- 所有方法都是异步的，兼容 asyncio
"""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ReviewEventBus(ABC):
    """审核事件总线抽象接口。"""

    @abstractmethod
    async def publish_decision(self, task_id: str, decision: str, modifications: Optional[Dict[str, Any]] = None) -> None:
        """发布审核决策。

        Args:
            task_id: 任务ID
            decision: 审核决策（approve/reject/modify）
            modifications: 修改内容（可选）
        """
        ...

    @abstractmethod
    async def wait_for_decision(self, task_id: str, timeout: float = 1.5) -> Optional[Dict[str, Any]]:
        """等待审核决策。

        Args:
            task_id: 任务ID
            timeout: 等待超时时间（秒）

        Returns:
            审核决策字典 {decision, modifications}，超时返回 None
        """
        ...

    @abstractmethod
    async def cancel_wait(self, task_id: str) -> None:
        """取消等待（任务被取消时调用）。"""
        ...

    async def close(self) -> None:
        """清理资源（关闭连接等）。"""
        pass


class MemoryReviewEventBus(ReviewEventBus):
    """内存模式事件总线（基于 asyncio.Event）。

    适用于单进程部署。审核决策和等待在同一个进程内。
    """

    def __init__(self):
        self._events: Dict[str, asyncio.Event] = {}
        self._decisions: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def publish_decision(self, task_id: str, decision: str, modifications: Optional[Dict[str, Any]] = None) -> None:
        async with self._lock:
            self._decisions[task_id] = {
                "decision": decision,
                "modifications": modifications or {},
            }
            event = self._events.get(task_id)
            if event:
                event.set()
        logger.info(f"[MemoryBus] 发布审核决策: task={task_id}, decision={decision}")

    async def wait_for_decision(self, task_id: str, timeout: float = 1.5) -> Optional[Dict[str, Any]]:
        # 先检查是否已有决策
        async with self._lock:
            if task_id in self._decisions:
                return self._decisions.pop(task_id)

        # 创建事件等待
        async with self._lock:
            event = self._events.get(task_id)
            if event is None:
                event = asyncio.Event()
                self._events[task_id] = event

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

        async with self._lock:
            return self._decisions.pop(task_id, None)

    async def cancel_wait(self, task_id: str) -> None:
        async with self._lock:
            event = self._events.pop(task_id, None)
            if event:
                event.set()
            self._decisions.pop(task_id, None)

    async def close(self) -> None:
        async with self._lock:
            for event in self._events.values():
                event.set()
            self._events.clear()
            self._decisions.clear()


class RedisReviewEventBus(ReviewEventBus):
    """Redis 模式事件总线（基于 Redis Pub/Sub）。

    适用于多副本部署。审核决策通过 Redis 广播，任何副本都能收到。
    Redis 不可用时自动降级为内存模式。
    """

    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._redis = None
        self._pubsub = None
        self._listeners: Dict[str, asyncio.Future] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self._fallback: Optional[MemoryReviewEventBus] = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_connected(self) -> bool:
        """确保 Redis 连接已建立。失败则降级为内存模式。"""
        if self._initialized:
            return self._redis is not None

        async with self._init_lock:
            if self._initialized:
                return self._redis is not None

            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
                # 测试连接
                await self._redis.ping()
                self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe("review_decisions")
                self._listener_task = asyncio.create_task(self._listen_loop())
                logger.info(f"[RedisBus] 连接成功: {self._redis_url}")
                self._initialized = True
                return True
            except Exception as e:
                logger.warning(f"[RedisBus] 连接失败，降级为内存模式: {e}")
                self._fallback = MemoryReviewEventBus()
                self._redis = None
                self._initialized = True
                return False

    async def _listen_loop(self):
        """监听 Redis 消息的后台任务。"""
        try:
            async for message in self._pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    data = json.loads(message.get("data", "{}"))
                    task_id = data.get("task_id")
                    if task_id and task_id in self._listeners:
                        future = self._listeners.pop(task_id)
                        if not future.done():
                            future.set_result(data)
                except Exception as e:
                    logger.warning(f"[RedisBus] 消息处理失败: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[RedisBus] 监听循环异常: {e}")

    async def publish_decision(self, task_id: str, decision: str, modifications: Optional[Dict[str, Any]] = None) -> None:
        if not await self._ensure_connected():
            await self._fallback.publish_decision(task_id, decision, modifications)
            return

        try:
            payload = json.dumps({
                "task_id": task_id,
                "decision": decision,
                "modifications": modifications or {},
            })
            await self._redis.publish("review_decisions", payload)
            logger.info(f"[RedisBus] 发布审核决策: task={task_id}, decision={decision}")
        except Exception as e:
            logger.warning(f"[RedisBus] 发布失败，降级内存: {e}")
            await self._fallback.publish_decision(task_id, decision, modifications)

    async def wait_for_decision(self, task_id: str, timeout: float = 1.5) -> Optional[Dict[str, Any]]:
        if not await self._ensure_connected():
            return await self._fallback.wait_for_decision(task_id, timeout)

        # 创建 future 等待消息
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._listeners[task_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return {
                "decision": result.get("decision"),
                "modifications": result.get("modifications", {}),
            }
        except asyncio.TimeoutError:
            self._listeners.pop(task_id, None)
            return None
        except Exception as e:
            logger.warning(f"[RedisBus] 等待失败: {e}")
            self._listeners.pop(task_id, None)
            return None

    async def cancel_wait(self, task_id: str) -> None:
        future = self._listeners.pop(task_id, None)
        if future and not future.done():
            future.cancel()

    async def close(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe("review_decisions")
                await self._pubsub.close()
            except Exception:
                pass
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass
        if self._fallback:
            await self._fallback.close()


# 全局单例
_event_bus: Optional[ReviewEventBus] = None
_event_bus_lock = asyncio.Lock()


async def get_review_event_bus() -> ReviewEventBus:
    """获取审核事件总线单例。

    根据环境变量 REVIEW_EVENT_BACKEND 选择后端：
    - memory（默认）：内存模式
    - redis：Redis 模式（需配置 REDIS_URL）
    """
    global _event_bus
    if _event_bus is not None:
        return _event_bus

    async with _event_bus_lock:
        if _event_bus is not None:
            return _event_bus

        backend = os.environ.get("REVIEW_EVENT_BACKEND", "memory").lower()

        if backend == "redis":
            redis_url = os.environ.get("REDIS_URL", "")
            if redis_url:
                _event_bus = RedisReviewEventBus(redis_url)
                logger.info("审核事件总线: Redis 模式")
            else:
                logger.warning("REVIEW_EVENT_BACKEND=redis 但未配置 REDIS_URL，降级为内存模式")
                _event_bus = MemoryReviewEventBus()
        else:
            _event_bus = MemoryReviewEventBus()
            logger.info("审核事件总线: 内存模式")

        return _event_bus


def get_review_event_bus_sync() -> ReviewEventBus:
    """同步获取事件总线（用于非异步上下文，返回内存模式实例）。

    注意：此方法仅用于初始化或测试，生产环境请用异步版本。
    """
    global _event_bus
    if _event_bus is None:
        _event_bus = MemoryReviewEventBus()
    return _event_bus


def publish_review_decision_sync(task_id: str, decision: str, modifications: Optional[Dict[str, Any]] = None) -> None:
    """同步发布审核决策（用于同步上下文，如 API 处理函数）。

    内部使用 asyncio.create_task 调度异步发布，不阻塞当前调用。
    如果事件总线是内存模式，直接同步发布。
    """
    global _event_bus
    if _event_bus is None:
        _event_bus = MemoryReviewEventBus()

    bus = _event_bus

    # 内存模式可以直接同步发布
    if isinstance(bus, MemoryReviewEventBus):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(bus.publish_decision(task_id, decision, modifications))
            else:
                loop.run_until_complete(bus.publish_decision(task_id, decision, modifications))
        except RuntimeError:
            # 没有事件循环，直接设置内存状态
            bus._decisions[task_id] = {"decision": decision, "modifications": modifications or {}}
            event = bus._events.get(task_id)
            if event:
                event.set()
    else:
        # Redis 模式，调度异步发布
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(bus.publish_decision(task_id, decision, modifications))
            else:
                loop.run_until_complete(bus.publish_decision(task_id, decision, modifications))
        except RuntimeError:
            logger.warning("无法发布审核决策到事件总线：没有运行中的事件循环")
