import json
import os
import time
import asyncio
import logging
import threading
import concurrent.futures
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime

from blog_writer.config_manager import ConfigManager
from blog_writer.llm.providers import OpenAICompatibleProvider
from blog_writer.agent.executor import AgentExecutor
from blog_writer.agent.hybrid_executor import NodeExecutorFactory
from blog_writer.llm.base import BaseLLMProvider, Message
from blog_writer.constants import (
    DEFAULT_MAX_RETRIES as MAX_RETRIES,
    DEFAULT_RETRY_DELAY_SECONDS as RETRY_DELAY,
    LOG_THROTTLE_INTERVAL
)
from blog_writer.task_logger import TaskLogger, create_task_logger
from blog_writer.db import DatabaseManager, TaskRepository, TaskLogRepository, create_database_manager
from blog_writer.api.webhooks import get_webhook_manager
from blog_writer.workflow.routing import WorkflowRouter
from blog_writer.workflow import helpers as wf_helpers
from blog_writer.workflow import review_wait as review_wait_mod
from blog_writer.review_event_bus import get_review_event_bus
from blog_writer.workflow.budgets import (
    resolve_step_timeout_seconds,
    token_budget_exceeded,
)
from blog_writer.workflow.task_control import TaskControlMixin
from blog_writer.security.path_security import validate_task_id

logger = logging.getLogger(__name__)

# 共享线程池（避免每次调用创建新实例）
_shared_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="webhook-sync")

# webhook fire-and-forget 任务引用集合：防止 asyncio.Task 被 GC 回收
_bg_tasks_webhook: set = set()

# 定时任务触发的后台启动协程引用集合：防止 asyncio.Task 被 GC 回收
_scheduled_futures: set = set()

# 向后兼容别名（外部模块可能引用这些常量）
DEFAULT_MAX_RETRIES = MAX_RETRIES
DEFAULT_RETRY_DELAY_SECONDS = RETRY_DELAY


def priority_label(priority: int) -> str:
    """优先级数字转中文标签。"""
    return {3: "高", 2: "中", 1: "低"}.get(priority, "中")


def parse_scheduled_at(value) -> datetime:
    """解析定时时间字符串为 UTC aware datetime。

    支持 ISO 格式，可带时区偏移或 'Z' 后缀；无时区时视为服务器本地时间。
    用于前端/API 传入的 scheduledAt 与调度器到期比较，统一在 UTC 下判断。
    """
    from datetime import timezone

    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            raise ValueError("定时时间为空")
        s = s.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise ValueError(f"无法解析定时时间: {value!r}") from e
    if dt.tzinfo is None:
        # 无时区信息：视为服务器本地时间，附加本地时区
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc)


def scheduled_at_is_due(value) -> bool:
    """判断定时时间是否已到期（<= 当前 UTC 时间）。"""
    from datetime import timezone

    try:
        target = parse_scheduled_at(value)
    except ValueError:
        return False
    return target <= datetime.now(timezone.utc)


def assert_scheduled_at_is_future(value, *, grace_seconds: float = 5.0) -> str:
    """校验定时时间必须晚于当前时间（允许极小时钟偏差）。

    返回规范化后的 ISO UTC 字符串，便于落库一致。
    """
    from datetime import timezone, timedelta

    target = parse_scheduled_at(value)
    now = datetime.now(timezone.utc)
    if target <= now - timedelta(seconds=max(0.0, grace_seconds)):
        raise ValueError(
            f"定时时间必须晚于当前时间（已过期: {target.isoformat()}）"
        )
    return target.isoformat().replace("+00:00", "Z")


def assert_scheduled_end_after_start(start_value, end_value) -> str:
    """校验结束时间晚于开始时间，返回规范化 ISO UTC 结束时间。"""
    start = parse_scheduled_at(start_value)
    end = parse_scheduled_at(end_value)
    if end <= start:
        raise ValueError(
            f"定时结束时间必须晚于开始时间（start={start.isoformat()}, end={end.isoformat()}）"
        )
    return end.isoformat().replace("+00:00", "Z")


class WorkflowService(TaskControlMixin):
    """工作流服务 - 支持状态持久化、断点续跑、自动重试、指定节点重跑"""
    
    def __init__(self, config: Optional[ConfigManager] = None):
        self.config = config or ConfigManager()
        self.nodes_dir = self.config.resolve_path(self.config.get("workflow.nodes_dir", "./nodes"))
        self.instance_root = self.config.resolve_path(self.config.get("workflow.instance_root", "./instance"))
        self.instance_root.mkdir(parents=True, exist_ok=True)
        self.nodes_dir.mkdir(parents=True, exist_ok=True)
        
        self._llm_providers: Dict[str, OpenAICompatibleProvider] = {}
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._task_logs: Dict[str, List[str]] = {}
        self._flushed_log_counts: Dict[str, int] = {}
        self._pause_events: Dict[str, asyncio.Event] = {}
        # 终态任务精简缓存（清理完整内存态后仍可快速查 status）
        self._task_cache: Dict[str, Dict[str, Any]] = {}
        self._task_cleanup_delay_seconds = float(
            os.environ.get("BLOG_WRITER_TASK_MEMORY_TTL_SECONDS", "300") or 300
        )
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        # 定时任务调度器（scheduled tasks）
        self._scheduler_task: Optional[asyncio.Task] = None
        self._scheduler_running = False
        self._scheduler_interval_seconds = float(
            os.environ.get("BLOG_WRITER_SCHEDULER_INTERVAL_SECONDS", "15") or 15
        )
        # 防止同一 scheduled 任务被重复 create_task 启动
        self._scheduled_launching: set = set()
        # 防止同一 task 并发执行多个编排协程
        self._running_tasks: set = set()
        self._running_tasks_lock = threading.Lock()
        self._task_locks: Dict[str, asyncio.Lock] = {}
        # 同步控制面（approve/cancel/pause/...）串行化，避免竞态覆盖状态
        self._task_sync_locks: Dict[str, threading.Lock] = {}
        self._task_sync_locks_guard = threading.Lock()
        # 并发任务数限制 + 优先级调度
        self.max_concurrent_tasks = int(os.environ.get("MAX_CONCURRENT_TASKS", "5") or 5)
        self._available_slots = self.max_concurrent_tasks
        self._priority_queue: List[tuple] = []  # (priority, timestamp, task_id, event)
        self._queue_lock = asyncio.Lock()
        self._queue_counter = 0  # 同优先级时FIFO
        # 并发统计
        self._concurrency_stats = {
            "total_started": 0,
            "total_completed": 0,
            "total_wait_time": 0.0,
            "total_exec_time": 0.0,
        }
        
        # 数据库持久化：sqlite 路径相对 config 目录解析，避免 CWD 分裂出多套库
        db_cfg = self.config.get_all()
        sqlite_path = db_cfg.get("database", {}).get("sqlite_path", "./instance/blog_writer.db")
        if db_cfg.get("database", {}).get("backend", "sqlite") == "sqlite" and sqlite_path:
            resolved_db = self.config.resolve_path(sqlite_path)
            resolved_db.parent.mkdir(parents=True, exist_ok=True)
            db_cfg = {**db_cfg, "database": {**db_cfg.get("database", {}), "sqlite_path": str(resolved_db)}}
        self._db = create_database_manager(db_cfg)
        self._task_repo = TaskRepository(self._db)
        self._log_repo = TaskLogRepository(self._db)
        self._use_db = self.config.get("workflow.use_database", True)
        self._use_file_fallback = self.config.get("workflow.use_file_fallback", False)
    
    def _get_state_path(self, task_id: str) -> Path:
        """获取任务状态文件路径"""
        return self.instance_root / task_id / "task_state.json"
    
    def _save_state(self, task_id: str):
        """持久化任务状态
        
        企业级部署：仅使用数据库作为唯一事实源（Single Source of Truth）。
        本地开发：可启用 use_file_fallback 作为调试辅助。
        """
        task = self._tasks.get(task_id)
        if not task:
            return
        
        # 审核决策 / 归属写入 extra（表无独立列），避免重启后丢失
        extra = dict(task.get("extra") or {})
        if task.get("review_decision"):
            extra["review_decision"] = task.get("review_decision")
            extra["review_modifications"] = task.get("review_modifications") or {}
        else:
            extra.pop("review_decision", None)
            extra.pop("review_modifications", None)
        owner_id = task.get("owner_id") or extra.get("owner_id")
        if owner_id:
            extra["owner_id"] = owner_id
            task["owner_id"] = owner_id

        # 同步回内存态，避免 task["extra"] 与持久化态不一致
        # （否则 _hydrate_review_fields 可能从陈旧 extra 重新恢复已消费的 review_decision）
        task["extra"] = extra

        state_to_save = {
            "task_id": task_id,
            "status": task["status"],
            "mode": task.get("mode", ""),
            "current_step": task.get("current_step", 0),
            "total_steps": task.get("total_steps", 0),
            "start_time": task.get("start_time", ""),
            "brand_path": task.get("brand_path", ""),
            "keywords": task.get("keywords", ""),
            "user_note": task.get("user_note", ""),
            "brand_site_url": task.get("brand_site_url", ""),
            "step_files": task.get("step_files", []),
            "completed_steps": task.get("completed_steps", []),
            "results": task.get("results", []),
            "outputs": task.get("outputs", {}),
            "retry_counts": task.get("retry_counts", {}),
            "end_time": task.get("end_time", ""),
            "review_node": task.get("review_node", ""),
            "review_node_name": task.get("review_node_name", ""),
            "extra": extra,
        }
        
        # 写入数据库（主要持久化层）
        if self._use_db:
            try:
                self._task_repo.save_task(state_to_save)
                self._flush_logs_to_db(task_id)
            except Exception as e:
                logger.error(f"数据库保存失败: {e}")
                if not self._use_file_fallback:
                    raise
        
        # 文件系统持久化（可选降级/调试模式）
        if self._use_file_fallback:
            try:
                state_path = self._get_state_path(task_id)
                state_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = state_path.with_suffix('.json.tmp')
                try:
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        json.dump(state_to_save, f, ensure_ascii=False, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, state_path)
                except Exception:
                    if tmp_path.exists():
                        try:
                            tmp_path.unlink()
                        except Exception:
                            pass
                    raise
            except Exception as e:
                logger.error(f"文件系统保存失败 {task_id}: {e}")
                raise
    
    def _validate_state(self, state: Dict[str, Any]) -> bool:
        """验证任务状态数据的完整性和有效性"""
        if not isinstance(state, dict):
            return False
        
        # 必需字段检查
        required_fields = ['task_id', 'status']
        for field in required_fields:
            if field not in state:
                logger.warning(f"状态数据缺少必需字段: {field}")
                return False
        
        # 状态值检查
        valid_statuses = {
            'pending',
            'running',
            'queued',  # 并发排队 / 定时到期后启动前的中间态，必须可落库与恢复
            'paused',
            'completed',
            'failed',
            'cancelled',
            'waiting_review',
            'rejected',
            'completed_partial',
            'scheduled',
        }
        if state['status'] not in valid_statuses:
            logger.warning(f"状态值无效: {state['status']}, 有效值: {valid_statuses}")
            return False
        
        # 类型检查
        if not isinstance(state.get('current_step', 0), int):
            return False
        if not isinstance(state.get('total_steps', 0), int):
            return False
        if not isinstance(state.get('step_files', []), list):
            return False
        if not isinstance(state.get('completed_steps', []), list):
            return False
        
        return True
    
    def _flush_logs_to_db(self, task_id: str):
        """将内存中尚未落库的日志增量写入数据库（避免重复全量写入）"""
        if not self._use_db:
            return
        logs = self._task_logs.get(task_id, [])
        if not logs:
            return
        flushed = self._flushed_log_counts.get(task_id, 0)
        if flushed >= len(logs):
            return
        try:
            for log_entry in logs[flushed:]:
                self._log_repo.add_log(task_id, log_entry)
            self._flushed_log_counts[task_id] = len(logs)
        except Exception as e:
            logger.warning(f"日志写入数据库失败 {task_id}: {e}")

    def _should_skip_human_review(
        self,
        mode: str,
        step_file: str,
        outputs: Dict[str, Any],
        instance_dir: Optional[Path] = None,
    ) -> bool:
        """按 registry.mode_config 决定是否跳过人工审核节点。"""
        if mode == "auto":
            return True
        registry = self.load_registry()
        mode_cfg = (registry.get("mode_config") or {}).get(mode) or {}
        required = set(mode_cfg.get("required_review") or [])
        if step_file in required:
            return False
        conditional = mode_cfg.get("conditional_review") or {}
        rule = conditional.get(step_file)
        if not rule:
            # supervised/manual 未声明的审核节点：manual 不跳过；supervised 默认需要审核
            return False
        # 支持 "risk_level >= 03" 形式
        risk = self._extract_risk_level(outputs)
        if risk is None and instance_dir is not None:
            risk = wf_helpers.load_bid_risk_level(instance_dir)
        try:
            import re
            m = re.match(r"risk_level\s*>=\s*0?(\d+)", str(rule).strip(), re.I)
            if m:
                threshold = int(m.group(1))
                # risk 为空时保守：不跳过（需要审核）
                if risk is None:
                    return False
                return risk < threshold
        except Exception:
            pass
        return False

    def _extract_risk_level(self, outputs: Dict[str, Any]) -> Optional[int]:
        """从产出/BID 中解析 RK 等级数字，失败返回 None。"""
        candidates = []
        if isinstance(outputs, dict):
            for key in ("risk_level", "RK", "rk", "bid"):
                if key in outputs:
                    candidates.append(outputs[key])
            bid = outputs.get("bid") or outputs.get("000_BID") or outputs.get("BID")
            if isinstance(bid, dict):
                candidates.extend([bid.get("risk_level"), bid.get("RK"), bid.get("risk")])
                meta = bid.get("meta") or bid.get("metadata") or {}
                if isinstance(meta, dict):
                    candidates.extend([meta.get("risk_level"), meta.get("RK")])
        for c in candidates:
            if c is None:
                continue
            s = str(c).upper().strip()
            digits = "".join(ch for ch in s if ch.isdigit())
            if digits:
                try:
                    return int(digits[-2:] if len(digits) > 2 else digits)
                except ValueError:
                    continue
        # 尝试从实例目录读取 BID 文件
        return None

    def _ensure_task_loaded(self, task_id: str) -> Optional[Dict[str, Any]]:
        """确保任务在内存中；必要时从 DB/文件恢复。"""
        task = self._tasks.get(task_id)
        if task:
            self._hydrate_review_fields(task)
            return task
        state = self._load_state(task_id)
        if state:
            self._hydrate_review_fields(state)
            self._tasks[task_id] = state
            return state
        return None

    @staticmethod
    def _hydrate_review_fields(task: Dict[str, Any]) -> None:
        """从 extra 恢复审核决策 / 归属字段到顶层。"""
        extra = task.get("extra") or {}
        if isinstance(extra, dict):
            if not task.get("owner_id") and extra.get("owner_id"):
                task["owner_id"] = extra.get("owner_id")
            if not task.get("review_decision") and extra.get("review_decision"):
                task["review_decision"] = extra.get("review_decision")
                task["review_modifications"] = extra.get("review_modifications") or {}

    def _pull_external_review_decision(self, task_id: str) -> bool:
        """从 StateStore / DB 拉取外部写入的审核决策到内存任务。"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.get("review_decision"):
            return True

        external = review_wait_mod.load_external_review_decision(task_id)
        if external and external.get("decision"):
            task["review_decision"] = external["decision"]
            task["review_modifications"] = external.get("modifications") or {}
            return True

        # DB 可能被另一进程更新
        if self._use_db:
            try:
                db_task = self._task_repo.load_task(task_id)
                if db_task:
                    self._hydrate_review_fields(db_task)
                    if db_task.get("review_decision"):
                        task["review_decision"] = db_task["review_decision"]
                        task["review_modifications"] = db_task.get("review_modifications") or {}
                        if db_task.get("status") == "cancelled":
                            task["status"] = "cancelled"
                        return True
                    if db_task.get("status") == "cancelled":
                        task["status"] = "cancelled"
                        return True
            except Exception:
                pass
        return bool(task.get("review_decision"))

    async def _await_human_review(
        self,
        task_id: str,
        *,
        node_id: str,
        node_name: str,
        step_file: str,
        mode: str,
        outputs: Dict[str, Any],
        node_results: List[Dict[str, Any]],
        task_log: Callable[[str], None],
        reason: str = "human_review",
        poll_seconds: float = 1.5,
    ) -> tuple:
        """等待人工审核决策。

        Returns:
            (cancelled: bool, decision: str, modifications: dict)
        """
        pending = self._tasks[task_id].get("review_decision")
        if not pending:
            self._pull_external_review_decision(task_id)
            pending = self._tasks[task_id].get("review_decision")
        if pending:
            mods = self._tasks[task_id].get("review_modifications") or {}
            task_log(f"   ✅ Using persisted review decision: {pending}")
            return False, str(pending), mods

        event = asyncio.Event()
        self._pause_events[task_id] = event
        self._tasks[task_id]["status"] = "waiting_review"
        self._tasks[task_id]["review_node"] = node_id
        self._tasks[task_id]["review_node_name"] = node_name
        self._sync_runtime_state(task_id, outputs, node_results)
        self._save_state(task_id)
        self._fire_task_webhook(task_id, "task.waiting_review", {
            "task_id": task_id,
            "node_id": node_id,
            "node_name": node_name,
            "step_file": step_file,
            "keywords": self._tasks[task_id].get("keywords", ""),
            "mode": mode,
            "reason": reason,
        })

        try:
            while True:
                if self._tasks[task_id].get("status") in ("cancelled", "paused"):
                    break
                if self._tasks[task_id].get("review_decision"):
                    break
                if self._pull_external_review_decision(task_id):
                    if self._tasks[task_id].get("review_decision") or (
                        self._tasks[task_id].get("status") in ("cancelled", "paused")
                    ):
                        _ev = self._pause_events.get(task_id)
                        if _ev is not None:
                            _ev.set()
                        break

                # 同时等待内存事件和事件总线（Redis Pub/Sub）
                bus = await get_review_event_bus()
                bus_task = asyncio.create_task(
                    bus.wait_for_decision(task_id, timeout=max(0.5, poll_seconds))
                )
                mem_task = asyncio.create_task(
                    asyncio.wait_for(event.wait(), timeout=max(0.5, poll_seconds))
                )

                done, pending = await asyncio.wait(
                    [bus_task, mem_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # 取消未完成的任务
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass

                # 检查事件总线是否返回了决策
                if bus_task in done:
                    try:
                        bus_result = bus_task.result()
                        if bus_result and isinstance(bus_result, dict):
                            decision = bus_result.get("decision")
                            if decision:
                                self._tasks[task_id]["review_decision"] = decision
                                self._tasks[task_id]["review_modifications"] = bus_result.get("modifications", {})
                                task_log(f"   ✅ Review decision via event bus: {decision}")
                                break
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        pass

                # 检查内存事件是否被触发
                if mem_task in done:
                    try:
                        await mem_task
                        break  # 内存事件被触发，退出循环
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        continue
        finally:
            if task_id in self._pause_events:
                del self._pause_events[task_id]

        if self._tasks[task_id].get("status") == "cancelled":
            task_log("   🛑 Task cancelled during review")
            return True, "reject", {}

        if self._tasks[task_id].get("status") == "paused":
            task_log("   ⏸️ Task paused during review")
            return True, "pause", {}

        decision = str(self._tasks[task_id].get("review_decision", "approve"))
        mods = self._tasks[task_id].get("review_modifications") or {}
        task_log(f"   ✅ Review decision: {decision}")
        return False, decision, mods

    def _get_task_lock(self, task_id: str) -> asyncio.Lock:
        # 使用同步锁保护 _task_locks 字典的 check-then-create 操作
        with self._task_sync_locks_guard:
            lock = self._task_locks.get(task_id)
            if lock is None:
                lock = asyncio.Lock()
                self._task_locks[task_id] = lock
            return lock

    def _get_task_sync_lock(self, task_id: str) -> threading.Lock:
        with self._task_sync_locks_guard:
            lock = self._task_sync_locks.get(task_id)
            if lock is None:
                lock = threading.Lock()
                self._task_sync_locks[task_id] = lock
            return lock

    def is_task_executing(self, task_id: str) -> bool:
        with self._running_tasks_lock:
            return task_id in self._running_tasks

    async def _acquire_slot(self, task_id: str, priority: int = 2):
        """获取执行槽位，支持优先级调度。

        Returns:
            (wait_seconds, held_slot)
            held_slot=True 表示调用方持有一个并发槽（立即获得或由 _release_slot 转让）。
            held_slot=False 表示排队期间被取消/定时暂停唤醒，未持有槽，禁止再调用 _release_slot。
        """
        import time
        wait_start = time.time()

        async with self._queue_lock:
            if self._available_slots > 0:
                self._available_slots -= 1
                return 0.0, True
            # 无空闲槽位，进入优先级队列等待
            self._queue_counter += 1
            event = asyncio.Event()
            entry = (-priority, self._queue_counter, task_id, event)
            self._priority_queue.append(entry)
            self._priority_queue.sort()  # 按优先级降序，同优先级FIFO

        await event.wait()
        task = self._tasks.get(task_id)
        aborted = bool(task and task.pop("_queue_aborted", False))
        return time.time() - wait_start, (not aborted)

    def _abort_queued_waiter(self, task_id: str) -> bool:
        """从优先级队列移除任务并唤醒等待协程（不转让并发槽）。"""
        for i, entry in enumerate(self._priority_queue):
            if entry[2] == task_id:
                _, _, _, event = self._priority_queue.pop(i)
                task = self._tasks.get(task_id)
                if task is not None:
                    task["_queue_aborted"] = True
                event.set()
                return True
        return False

    def _release_slot(self):
        """释放槽位，唤醒队列中最高优先级任务。"""
        # 先尝试直接释放槽位
        if self._priority_queue:
            # 有排队任务，唤醒最高优先级的（槽位转让，被唤醒方 held_slot=True）
            entry = self._priority_queue.pop(0)
            _, _, _task_id, event = entry
            event.set()
        else:
            self._available_slots += 1

    def get_concurrency_info(self) -> Dict[str, Any]:
        """获取并发和排队信息（用于前端展示）。"""
        # 从 _tasks 中统计真实运行状态，比 _running_tasks 执行标记更可靠
        running_from_tasks = sum(
            1 for t in self._tasks.values()
            if t.get("status") in ("running", "waiting_review", "pending")
        )
        running = max(len(self._running_tasks), running_from_tasks)
        queued = len(self._priority_queue)
        stats = self._concurrency_stats
        avg_wait = stats["total_wait_time"] / stats["total_completed"] if stats["total_completed"] > 0 else 0
        avg_exec = stats["total_exec_time"] / stats["total_completed"] if stats["total_completed"] > 0 else 0
        return {
            "max_concurrent": self.max_concurrent_tasks,
            "running": running,
            "queued": queued,
            "available": max(0, self.max_concurrent_tasks - running),
            "stats": {
                "total_started": stats["total_started"],
                "total_completed": stats["total_completed"],
                "avg_wait_seconds": round(avg_wait, 1),
                "avg_exec_seconds": round(avg_exec, 1),
            }
        }

    def get_queued_tasks(self) -> List[Dict[str, Any]]:
        """获取排队任务列表（按优先级排序）。"""
        result = []
        for neg_pri, counter, task_id, event in self._priority_queue:
            task = self._tasks.get(task_id, {})
            result.append({
                "task_id": task_id,
                "priority": -neg_pri,
                "priority_label": {3: "高", 2: "中", 1: "低"}.get(-neg_pri, "中"),
                "keywords": task.get("keywords", ""),
                "queued_at": task.get("start_time", ""),
                "position": len(result) + 1,
            })
        return result

    def cancel_queued_task(self, task_id: str) -> bool:
        """取消排队中的任务。"""
        if not self._abort_queued_waiter(task_id):
            return False
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = "cancelled"
            self._save_state(task_id)
        return True

    # ============ 定时任务调度器 ============
    def start_scheduler(self) -> None:
        """启动定时任务调度器（幂等）。须在 event loop 中调用。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._scheduler_running:
            return
        self._scheduler_running = True
        self._main_loop = loop
        self._scheduler_task = loop.create_task(self._schedule_loop())
        logger.info(
            "定时任务调度器已启动（间隔 %.0fs）", self._scheduler_interval_seconds
        )

    def stop_scheduler(self) -> None:
        """停止调度器循环。"""
        self._scheduler_running = False
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            self._scheduler_task = None

    async def _schedule_loop(self) -> None:
        """调度器主循环：周期性扫描到期启动与到期自动暂停。"""
        # 启动时先立即清扫一次（处理服务器重启后遗留的到期任务）
        try:
            await self._dispatch_due_scheduled_tasks()
            await self._dispatch_due_schedule_ends()
        except Exception as e:
            logger.warning("定时任务初始清扫失败: %s", e)
        while self._scheduler_running:
            await asyncio.sleep(self._scheduler_interval_seconds)
            try:
                await self._dispatch_due_scheduled_tasks()
                await self._dispatch_due_schedule_ends()
            except Exception as e:
                logger.warning("定时任务清扫失败: %s", e)

    async def _dispatch_due_scheduled_tasks(self) -> None:
        """扫描内存与 DB 中到期的 scheduled 任务，并触发启动。"""
        due_ids: List[str] = []

        # 1. 内存中的 scheduled 任务
        for tid, t in list(self._tasks.items()):
            extra = t.get("extra") or {}
            sat = extra.get("scheduled_at")
            if t.get("status") == "scheduled" and sat and scheduled_at_is_due(sat):
                due_ids.append(tid)

        # 2. DB 中的 scheduled 任务（服务器重启后内存未加载）
        if self._use_db:
            try:
                for db_task in self._task_repo.list_tasks(status="scheduled", limit=1000):
                    tid = db_task.get("task_id", "")
                    if not tid or tid in due_ids:
                        continue
                    extra = db_task.get("extra") or {}
                    sat = extra.get("scheduled_at")
                    if sat and scheduled_at_is_due(sat):
                        self._hydrate_review_fields(db_task)
                        if tid not in self._tasks:
                            self._tasks[tid] = db_task
                            self._task_logs.setdefault(tid, [])
                        due_ids.append(tid)
            except Exception as e:
                logger.warning("扫描 DB 定时任务失败: %s", e)

        # 3. 触发启动
        for tid in due_ids:
            try:
                self._launch_scheduled_task(tid)
            except Exception as e:
                logger.error("触发定时任务 %s 失败: %s", tid, e)

    async def _dispatch_due_schedule_ends(self) -> None:
        """扫描带 scheduled_end_at 且已到期的活动任务，自动暂停。"""
        pause_ids: List[str] = []
        active = ("scheduled", "queued", "running", "waiting_review", "pending")
        active_set = set(active)

        def _end_due(tid: str, end_at: str) -> bool:
            try:
                parse_scheduled_at(end_at)
            except ValueError:
                logger.warning(
                    "任务 %s 的 scheduled_end_at 无法解析，跳过自动暂停: %r",
                    tid,
                    end_at,
                )
                return False
            return scheduled_at_is_due(end_at)

        for tid, t in list(self._tasks.items()):
            if t.get("status") not in active_set:
                continue
            end_at = (t.get("extra") or {}).get("scheduled_end_at")
            if end_at and _end_due(tid, end_at):
                pause_ids.append(tid)

        if self._use_db:
            try:
                for db_task in self._task_repo.list_tasks(
                    statuses=list(active), limit=2000
                ):
                    tid = db_task.get("task_id", "")
                    if not tid or tid in pause_ids:
                        continue
                    end_at = (db_task.get("extra") or {}).get("scheduled_end_at")
                    if not end_at or not _end_due(tid, end_at):
                        continue
                    self._hydrate_review_fields(db_task)
                    if tid not in self._tasks:
                        self._tasks[tid] = db_task
                        self._task_logs.setdefault(tid, [])
                    pause_ids.append(tid)
            except Exception as e:
                logger.warning("扫描定时结束任务失败: %s", e)

        for tid in pause_ids:
            try:
                self._pause_for_schedule_end(tid)
            except Exception as e:
                logger.error("定时结束自动暂停 %s 失败: %s", tid, e)

    def _pause_for_schedule_end(self, task_id: str) -> bool:
        """结束时间到期：运行中暂停；排队中移出队列并暂停；未启动则取消。"""
        # 注意：running/waiting_review 走 pause_task（自带锁），不可在本方法持锁时嵌套调用
        with self._get_task_sync_lock(task_id):
            task = self._tasks.get(task_id) or self._ensure_task_loaded(task_id)
            if not task:
                return False
            status = task.get("status")
            if status in (
                "completed",
                "failed",
                "cancelled",
                "rejected",
                "completed_partial",
                "paused",
            ):
                return False

            extra = dict(task.get("extra") or {})
            end_at = extra.get("scheduled_end_at", "")

            if status == "scheduled":
                task["status"] = "cancelled"
                task["end_time"] = datetime.now().isoformat()
                extra["last_error"] = f"已到定时结束时间（{end_at}），任务未启动即取消"
                extra["paused_by_schedule_end"] = True
                task["extra"] = extra
                self._save_state(task_id)
                self._fire_task_webhook(
                    task_id,
                    "task.cancelled",
                    {"task_id": task_id, "reason": "schedule_end", "status": "cancelled"},
                )
                logger.info("定时任务 %s 结束窗口已过且未启动，已取消", task_id)
                return True

            if status == "queued":
                self._abort_queued_waiter(task_id)
                task["_prev_status"] = "queued"
                task["status"] = "paused"
                extra["paused_by_schedule_end"] = True
                extra["last_error"] = f"已到定时结束时间（{end_at}），排队任务已自动暂停"
                task["extra"] = extra
                self._save_state(task_id)
                self._fire_task_webhook(
                    task_id, "task.paused", {"task_id": task_id, "reason": "schedule_end"}
                )
                logger.info("定时任务 %s 结束时间到期，已从排队暂停", task_id)
                return True

            if status not in ("running", "waiting_review", "pending"):
                return False
            end_at_for_running = end_at

        # 锁外调用 pause_task，避免与 TaskControlMixin 嵌套死锁
        ok = self.pause_task(task_id, reason="schedule_end")
        if ok:
            with self._get_task_sync_lock(task_id):
                task = self._tasks.get(task_id) or self._ensure_task_loaded(task_id)
                if task:
                    extra = dict(task.get("extra") or {})
                    extra["paused_by_schedule_end"] = True
                    extra["last_error"] = (
                        f"已到定时结束时间（{end_at_for_running}），任务已自动暂停"
                    )
                    task["extra"] = extra
                    self._save_state(task_id)
            logger.info("定时任务 %s 结束时间到期，已自动暂停", task_id)
        return ok

    def _launch_scheduled_task(self, task_id: str) -> None:
        """将到期的 scheduled 任务转为排队执行（fire-and-forget）。"""
        if task_id in self._scheduled_launching:
            return
        task = self._tasks.get(task_id) or self._ensure_task_loaded(task_id)
        if not task:
            return
        if task.get("status") == "cancelled":
            return
        extra = dict(task.get("extra") or {})

        # 已过结束时间：不再启动
        end_at = extra.get("scheduled_end_at")
        if end_at and scheduled_at_is_due(end_at):
            self._pause_for_schedule_end(task_id)
            return

        # 标记为 queued，避免 start_workflow 复用 scheduled 状态导致进度异常
        if task.get("status") == "scheduled":
            task["status"] = "queued"
            self._save_state(task_id)

        params = extra.get("scheduled_params")
        if not isinstance(params, dict) or not params.get("keywords"):
            params = self._rebuild_start_params(task_id, task)
        if not params or not params.get("keywords"):
            self._mark_scheduled_failed(task_id, "缺少启动参数，无法定时启动")
            return
        params["task_id"] = task_id
        params.pop("resume_from", None)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 理论上调度循环内不会发生；回退 scheduled 以免卡在 queued
            if task.get("status") == "queued" and extra.get("scheduled_at"):
                task["status"] = "scheduled"
                self._save_state(task_id)
            logger.warning("定时任务 %s 启动失败：无运行中的事件循环", task_id)
            return

        self._scheduled_launching.add(task_id)
        coro = self.start_workflow(**params)
        t = loop.create_task(coro)
        _scheduled_futures.add(t)

        def _done(fut, tid=task_id):
            _scheduled_futures.discard(fut)
            self._scheduled_launching.discard(tid)
            try:
                exc = fut.exception()
            except asyncio.CancelledError:
                return
            if exc:
                logger.error("定时任务 %s 启动协程异常: %s", tid, exc)

        t.add_done_callback(_done)
        # 通知 Java/对接方：定时窗口已到，任务进入排队执行
        self._fire_task_webhook(
            task_id,
            "task.started",
            {
                "task_id": task_id,
                "status": "queued",
                "reason": "schedule_due",
                "scheduled_at": extra.get("scheduled_at", ""),
                "scheduled_end_at": extra.get("scheduled_end_at", ""),
            },
        )
        logger.info("定时任务 %s 已到期，触发启动", task_id)

    def _rebuild_start_params(self, task_id: str, task: Dict[str, Any]) -> Dict[str, Any]:
        """从任务自身字段重建 start_workflow 参数（旧数据兜底）。"""
        from pathlib import Path as _Path
        extra = task.get("extra") or {}
        # 兜底路径存的是相对路径（./brands/...），start_workflow 期望绝对路径，
        # 与 scheduled_params（API 层已 resolve）保持语义一致，避免实例目录下找不到品牌。
        brand_path = task.get("brand_path", "") or ""
        if brand_path:
            p = _Path(brand_path)
            if not p.is_absolute():
                project_root = self.instance_root.resolve().parent.parent
                brand_path = str((project_root / p).resolve())
        return {
            "brand_path": brand_path,
            "keywords": task.get("keywords", ""),
            "user_note": task.get("user_note", ""),
            "mode": task.get("mode", "auto"),
            "brand_site_url": task.get("brand_site_url", ""),
            "forbidden_whitelist": extra.get("forbidden_whitelist")
            or task.get("forbidden_whitelist")
            or [],
            "step_files": task.get("step_files") or None,
            "task_id": task_id,
            "model": extra.get("model", "default"),
            "temperature": extra.get("temperature"),
            "max_tokens": extra.get("max_tokens"),
            "priority": extra.get("priority", 2),
            "skip_visual_check": extra.get("skip_visual_check", False),
            "visual_mode": extra.get("visual_mode", "relaxed"),
        }

    def _mark_scheduled_failed(self, task_id: str, msg: str) -> None:
        """将无法启动的定时任务标记为失败。"""
        try:
            task = self._ensure_task_loaded(task_id)
            if not task:
                return
            if task.get("status") in ("completed", "failed", "cancelled", "rejected", "completed_partial"):
                return
            task["status"] = "failed"
            task["end_time"] = datetime.now().isoformat()
            extra = dict(task.get("extra") or {})
            extra["last_error"] = str(msg)[:500]
            task["extra"] = extra
            self._save_state(task_id)
        except Exception as e:
            logger.error("标记定时任务失败 %s 出错: %s", task_id, e)

    def list_scheduled_tasks(self) -> List[Dict[str, Any]]:
        """列出所有 scheduled 任务（含 DB）。"""
        result: List[Dict[str, Any]] = []
        seen: set = set()
        for tid, t in self._tasks.items():
            if t.get("status") == "scheduled":
                seen.add(tid)
                result.append(self._scheduled_summary(tid, t))
        if self._use_db:
            try:
                for db_task in self._task_repo.list_tasks(status="scheduled", limit=1000):
                    tid = db_task.get("task_id", "")
                    if tid and tid not in seen:
                        seen.add(tid)
                        result.append(self._scheduled_summary(tid, db_task))
            except Exception:
                pass
        return result

    @staticmethod
    def _scheduled_summary(task_id: str, task: Dict[str, Any]) -> Dict[str, Any]:
        extra = task.get("extra") or {}
        return {
            "task_id": task_id,
            "status": "scheduled",
            "keywords": task.get("keywords", ""),
            "scheduled_at": extra.get("scheduled_at", ""),
            "scheduled_end_at": extra.get("scheduled_end_at", ""),
            "created_at": task.get("start_time", ""),
        }

    def set_task_priority(self, task_id: str, priority: int) -> bool:
        """修改排队任务的优先级（1=低, 2=中, 3=高）。"""
        priority = max(1, min(3, priority))
        for i, entry in enumerate(self._priority_queue):
            if entry[2] == task_id:
                neg_pri, counter, tid, event = entry
                self._priority_queue[i] = (-priority, counter, tid, event)
                self._priority_queue.sort()
                return True
        return False

    def set_max_concurrent(self, n: int) -> Dict[str, Any]:
        """动态调整最大并发数（运行时生效）。"""
        n = max(1, min(20, n))
        old = self.max_concurrent_tasks
        self.max_concurrent_tasks = n
        # 如果增加了并发数，释放相应槽位
        if n > old:
            for _ in range(n - old):
                self._release_slot()
        # 如果减少了，已运行的任务不受影响，_available_slots会自然减少
        return {"old": old, "new": n, "running": len(self._running_tasks), "queued": len(self._priority_queue)}

    def _try_begin_execution(self, task_id: str) -> bool:
        """标记任务开始执行；若已在跑则返回 False。"""
        with self._running_tasks_lock:
            if task_id in self._running_tasks:
                return False
            self._running_tasks.add(task_id)
            return True

    def _end_execution(self, task_id: str) -> None:
        with self._running_tasks_lock:
            self._running_tasks.discard(task_id)

    def _schedule_resume_from_current(self, task_id: str, task: Dict[str, Any]) -> bool:
        """无内存 waiter 时（重启后），按当前步骤重新调度执行循环。"""
        if self.is_task_executing(task_id):
            logger.warning("task %s already executing, skip duplicate resume", task_id)
            return False
        step_files = task.get("step_files", [])
        current_step = task.get("current_step", 0)
        if not step_files or current_step >= len(step_files):
            return True
        resume_from = step_files[current_step]
        task["status"] = "running"
        self._save_state(task_id)
        try:
            loop = asyncio.get_running_loop()
            self._main_loop = loop
            loop.create_task(
                self._safe_resume_workflow(
                    task_id=task_id,
                    resume_from=resume_from,
                    brand_path=task.get("brand_path", ""),
                    keywords=task.get("keywords", ""),
                    mode=task.get("mode", "auto"),
                    user_note=task.get("user_note", ""),
                    brand_site_url=task.get("brand_site_url", ""),
                    step_files=step_files,
                )
            )
        except RuntimeError:
            # 无运行中的事件循环：优先提交到已知主循环，避免 asyncio.run 绑定错误循环
            main = self._main_loop
            if main is not None and main.is_running():
                coro = self._safe_resume_workflow(
                    task_id=task_id,
                    resume_from=resume_from,
                    brand_path=task.get("brand_path", ""),
                    keywords=task.get("keywords", ""),
                    mode=task.get("mode", "auto"),
                    user_note=task.get("user_note", ""),
                    brand_site_url=task.get("brand_site_url", ""),
                    step_files=step_files,
                )
                asyncio.run_coroutine_threadsafe(coro, main)
                return True

            def _bg_resume(
                tid=task_id,
                rf=resume_from,
                bp=task.get("brand_path", ""),
                kw=task.get("keywords", ""),
                md=task.get("mode", "auto"),
                un=task.get("user_note", ""),
                bsu=task.get("brand_site_url", ""),
                sfs=list(step_files),
            ):
                try:
                    asyncio.run(
                        self._safe_resume_workflow(
                            task_id=tid,
                            resume_from=rf,
                            brand_path=bp,
                            keywords=kw,
                            mode=md,
                            user_note=un,
                            brand_site_url=bsu,
                            step_files=sfs,
                        )
                    )
                except Exception as e:
                    logger.error("background resume failed for %s: %s", tid, e)

            try:
                _shared_executor.submit(_bg_resume)
            except RuntimeError:
                threading.Thread(
                    target=_bg_resume, name=f"resume-{task_id}", daemon=True
                ).start()
        return True

    async def _safe_resume_workflow(
        self,
        task_id: str,
        resume_from: str,
        brand_path: str,
        keywords: str,
        mode: str,
        user_note: str,
        brand_site_url: str,
        step_files: Optional[List[str]],
    ) -> Optional[Dict[str, Any]]:
        """续跑包装：异常时标记 failed，避免任务永久卡在 running。"""
        try:
            return await self._resume_workflow(
                task_id=task_id,
                resume_from=resume_from,
                brand_path=brand_path,
                keywords=keywords,
                mode=mode,
                user_note=user_note,
                brand_site_url=brand_site_url,
                step_files=step_files,
                log_func=lambda x: None,
            )
        except Exception as e:
            logger.error("resume workflow failed for %s: %s", task_id, e, exc_info=True)
            task = self._tasks.get(task_id) or self._ensure_task_loaded(task_id)
            if task and task.get("status") not in (
                "completed", "failed", "cancelled", "rejected", "completed_partial"
            ):
                task["status"] = "failed"
                task["end_time"] = datetime.now().isoformat()
                extra = dict(task.get("extra") or {})
                extra["last_error"] = str(e)[:500]
                task["extra"] = extra
                self._save_state(task_id)
                self._fire_task_webhook(
                    task_id,
                    "task.failed",
                    {"task_id": task_id, "status": "failed", "error": str(e)[:200]},
                )
            return None
    
    def _load_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        """加载任务状态（数据库优先，文件系统降级）"""
        # 优先从数据库加载
        if self._use_db:
            try:
                state = self._task_repo.load_task(task_id)
                if state:
                    return self._validate_and_return(state, task_id, "database")
            except Exception:
                pass
        
        # 文件系统降级加载
        state_path = self._get_state_path(task_id)
        if not state_path.exists():
            return None
        
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            return self._validate_and_return(state, task_id, "filesystem")
        except json.JSONDecodeError as e:
            logger.error(f"任务状态文件格式错误 {task_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"加载任务状态失败 {task_id}: {e}")
            return None
    
    def _fire_task_webhook(self, task_id: str, event: str, data: Dict[str, Any]):
        """触发任务相关的 webhook 通知（如果已注册）
        
        同时兼容异步上下文（asyncio事件循环）和同步上下文。
        """
        try:
            webhook_mgr = get_webhook_manager()
            if not webhook_mgr.has_callback(task_id):
                return
            payload = dict(data or {})
            payload.setdefault("task_id", task_id)
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(webhook_mgr.fire(task_id, event, payload))
                # 持有引用防止 GC 回收，并在异常时记录
                _bg_tasks_webhook.add(task)
                task.add_done_callback(_bg_tasks_webhook.discard)
            except RuntimeError:
                # 同步上下文：使用共享线程池执行
                _shared_executor.submit(
                    asyncio.run,
                    webhook_mgr.fire(task_id, event, payload),
                )
        except Exception as e:
            logger.warning(f"Webhook 触发失败 {task_id}/{event}: {e}")

    def _webhook_payload_extra(self, task_id: str) -> Dict[str, Any]:
        from blog_writer.api.integration_events import collect_output_files
        from blog_writer.api.task_enrichment import read_quality_gates

        instance_dir = self.instance_root / task_id
        if not instance_dir.is_dir():
            return {}
        extra: Dict[str, Any] = {
            "output_files": collect_output_files(instance_dir),
        }
        gates = read_quality_gates(instance_dir)
        publish = gates.get("publish") or {}
        if publish:
            extra["post_id"] = publish.get("post_id")
            extra["post_url"] = publish.get("post_url")
            extra["images_ready"] = publish.get("images_ready")
            extra["dry_run"] = publish.get("dry_run")
            extra["publish_status"] = publish.get("status")
        return extra
    
    def _validate_and_return(self, state: Dict[str, Any], task_id: str, source: str) -> Optional[Dict[str, Any]]:
        """验证状态数据完整性"""
        if not self._validate_state(state):
            logger.error(f"任务状态数据无效 {task_id} (source={source}): 验证失败")
            if source == "filesystem":
                state_path = self._get_state_path(task_id)
                backup_path = state_path.with_suffix('.corrupted')
                try:
                    os.rename(state_path, backup_path)
                    logger.info(f"已将损坏的状态文件重命名为 {backup_path}")
                except Exception:
                    pass
            return None
        return state
    
    def _recover_task(self, task_id: str) -> bool:
        """从磁盘恢复任务状态到内存"""
        state = self._load_state(task_id)
        if not state:
            return False
        
        # 恢复到内存
        self._tasks[task_id] = state
        if task_id not in self._task_logs:
            self._task_logs[task_id] = []
        
        logger.info(f"任务 {task_id} 已从磁盘恢复，状态: {state['status']}")
        return True
    
    def get_llm_provider(self, model_name: Optional[str] = None) -> BaseLLMProvider:
        """按节点 llm_model 取提供者；未指定则用配置 default_model。"""
        key = (model_name or "").strip() or "default"
        if key not in self._llm_providers:
            llm_config = self.config.get_llm_config(
                None if key == "default" else key
            )
            self._llm_providers[key] = OpenAICompatibleProvider(llm_config)
        return self._llm_providers[key]

    def has_llm_provider(self) -> bool:
        """是否已实例化过 LLM 提供者（用于 stats，避免无调用时强行建连）。"""
        return bool(self._llm_providers)

    def get_llm_stats(self) -> Dict[str, Any]:
        """汇总全部已缓存模型的调用统计。"""
        total_tokens = 0
        total_calls = 0
        by_model: Dict[str, Any] = {}
        for name, provider in self._llm_providers.items():
            stats = provider.get_stats() if hasattr(provider, "get_stats") else {}
            by_model[name] = stats
            total_tokens += int(stats.get("total_tokens_used") or 0)
            total_calls += int(stats.get("total_calls") or 0)
        return {
            "total_tokens_used": total_tokens,
            "total_calls": total_calls,
            "by_model": by_model,
        }

    def reload_llm(self):
        self._llm_providers.clear()

    def apply_runtime_config(self) -> None:
        """配置热更新后刷新可热切换的运行时开关（不重建 DB 连接）。"""
        self.reload_llm()
        self._use_db = self.config.get("workflow.use_database", True)
        self._use_file_fallback = self.config.get("workflow.use_file_fallback", False)
    
    def get_all_tasks(self) -> Dict[str, Dict[str, Any]]:
        """获取所有内存中的任务（用于统计等）"""
        return self._tasks
    
    def load_node_definition(self, node_file: str) -> Dict[str, Any]:
        file_path = (self.nodes_dir / node_file).resolve()
        try:
            file_path.relative_to(self.nodes_dir)
        except ValueError:
            raise ValueError(f"节点文件路径越界被拒绝: {node_file!r}")
        if not file_path.exists():
            raise FileNotFoundError(f"Node file not found: {node_file}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def list_nodes(self) -> List[Dict[str, Any]]:
        nodes = []
        if self.nodes_dir.exists():
            for f in sorted(self.nodes_dir.glob("*.json")):
                try:
                    with open(f, 'r', encoding='utf-8') as fh:
                        node = json.load(fh)
                    exec_type = node.get("exec_type", node.get("kind", ""))
                    nodes.append({
                        "file": f.name,
                        "id": node.get("id", ""),
                        "name": node.get("name", ""),
                        "seq": node.get("seq", 0),
                        "exec_type": exec_type,
                        "kind": node.get("kind", "")
                    })
                except Exception as e:
                    logger.error(f"Error loading node {f.name}: {e}")
        return nodes
    
    def load_registry(self) -> Dict[str, Any]:
        registry_path = self.nodes_dir.parent / "registry.json"
        if registry_path.exists():
            try:
                with open(registry_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"registry.json 解析失败，使用空注册表: {e}")
                return {}
        return {}

    def pre_register_task(
        self,
        task_id: str,
        brand_path: str,
        keywords: str,
        user_note: str = "",
        mode: str = "auto",
        brand_site_url: str = "",
        forbidden_whitelist: Optional[List[str]] = None,
        step_files: Optional[List[str]] = None,
        owner_id: str = "",
        model: str = "default",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        scheduled_at: Optional[str] = None,
        scheduled_end_at: Optional[str] = None,
        priority: int = 2,
        skip_visual_check: bool = False,
        visual_mode: str = "relaxed",
    ) -> None:
        """同步预注册任务，避免后台协程启动前 GET /tasks/{task_id} 返回 404。

        start_workflow 是 async 函数，通过 asyncio.create_task 调度后不会立即执行；
        若不预注册，客户端在收到 "started" 响应后立即查询会得到 404。
        """
        if not validate_task_id(task_id):
            raise ValueError(f"非法 task_id: {task_id!r}")

        if task_id in self._tasks:
            raise ValueError(f"task_id 已存在: {task_id}")
        existing = self._load_state(task_id)
        if existing:
            raise ValueError(f"task_id 已存在: {task_id}")

        instance_dir = self.instance_root / task_id
        resolved = instance_dir.resolve()
        try:
            resolved.relative_to(self.instance_root.resolve())
        except ValueError as e:
            raise ValueError(f"task_id 路径越界: {task_id!r}") from e
        instance_dir.mkdir(parents=True, exist_ok=True)

        from blog_writer.forbidden import normalize_forbidden_whitelist
        whitelist = normalize_forbidden_whitelist(forbidden_whitelist)

        if step_files is None:
            registry = self.load_registry()
            step_files = registry.get("step_order", [])
        else:
            step_files = self.normalize_step_files(step_files)

        extra = {"owner_id": owner_id} if owner_id else {}
        if whitelist:
            extra["forbidden_whitelist"] = whitelist
        if model and model != "default":
            extra["model"] = model
        if temperature is not None:
            extra["temperature"] = temperature
        if max_tokens is not None:
            extra["max_tokens"] = max_tokens
        if scheduled_at:
            extra["scheduled_at"] = scheduled_at
        if scheduled_end_at:
            extra["scheduled_end_at"] = scheduled_end_at
        # 统一写入启动配置，_rebuild_start_params / rerun_from_node 等路径从 extra 读取
        extra["priority"] = priority
        extra["skip_visual_check"] = skip_visual_check
        extra["visual_mode"] = visual_mode or "relaxed"

        self._tasks[task_id] = {
            "task_id": task_id,
            "status": "scheduled" if scheduled_at else "running",
            "mode": mode,
            "current_step": 0,
            "total_steps": len(step_files),
            "start_time": datetime.now().isoformat(),
            "brand_path": brand_path,
            "keywords": keywords,
            "user_note": user_note,
            "brand_site_url": brand_site_url,
            "forbidden_whitelist": whitelist,
            "owner_id": owner_id or "",
            "log": [],
            "step_files": step_files,
            "completed_steps": [],
            "results": [],
            "outputs": {},
            "retry_counts": {},
            "extra": extra,
        }
        self._task_logs[task_id] = []
        self._save_state(task_id)

    def normalize_step_files(self, step_files: List[str]) -> List[str]:
        """校验并规范化 step_files：必须是 registry.step_order 的子集，且保持 registry 顺序。"""
        import re

        registry = self.load_registry()
        order = list(registry.get("step_order") or [])
        allowed = set(order)
        if not step_files:
            return order
        for sf in step_files:
            if not isinstance(sf, str) or not sf.endswith(".json"):
                raise ValueError(f"非法 step_file: {sf!r}")
            if "/" in sf or "\\" in sf or ".." in sf:
                raise ValueError(f"step_file 路径不安全: {sf!r}")
            if not re.match(r"^[A-Za-z0-9._\-]+\.json$", sf):
                raise ValueError(f"step_file 非法字符: {sf!r}")
            if sf not in allowed:
                raise ValueError(f"step_file 不在 registry.step_order 中: {sf}")
        requested = set(step_files)
        # 保持 canonical 顺序，禁止调用方重排绕过门禁语义
        normalized = [s for s in order if s in requested]
        if not normalized:
            raise ValueError("step_files 为空或无效")
        return normalized

    async def start_workflow(
        self,
        brand_path: str,
        keywords: str,
        user_note: str = "",
        mode: str = "auto",
        brand_site_url: str = "",
        forbidden_whitelist: Optional[List[str]] = None,
        step_files: Optional[List[str]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        task_id: Optional[str] = None,
        resume_from: Optional[str] = None,
        model: str = "default",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        priority: int = 2,
        skip_visual_check: bool = False,
        visual_mode: str = "relaxed",
    ) -> Dict[str, Any]:
        """启动工作流
        
        Args:
            brand_path: 品牌路径
            keywords: 关键词
            user_note: 用户备注
            mode: 运行模式 (auto/supervised/manual)
            brand_site_url: 品牌网站URL
            forbidden_whitelist: 本次任务禁用词白名单（仅本任务豁免）
            step_files: 步骤文件列表，None则从registry加载
            log_callback: 日志回调函数
            task_id: 指定任务ID（用于断点续跑）
            resume_from: 从指定节点文件开始续跑（断点续跑）
            model: 使用的模型key ("default" 或 "pro")
            temperature: 单次任务温度覆盖
            max_tokens: 单次任务 max_tokens 覆盖
            priority: 任务优先级 (1=低, 2=中, 3=高)，排队时高优先级先执行
            visual_mode: 视觉校验模式 ("relaxed"|"strict"|"placeholder")
        """
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        if task_id is None:
            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if not validate_task_id(task_id):
            raise ValueError(f"非法 task_id: {task_id!r}")

        from blog_writer.forbidden import normalize_forbidden_whitelist
        whitelist = normalize_forbidden_whitelist(forbidden_whitelist)
        if not whitelist and task_id in self._tasks:
            whitelist = normalize_forbidden_whitelist(
                self._tasks[task_id].get("forbidden_whitelist")
                or (self._tasks[task_id].get("extra") or {}).get("forbidden_whitelist")
            )

        instance_dir = self.instance_root / task_id
        resolved = instance_dir.resolve()
        try:
            resolved.relative_to(self.instance_root.resolve())
        except ValueError as e:
            raise ValueError(f"task_id 路径越界: {task_id!r}") from e
        instance_dir.mkdir(parents=True, exist_ok=True)
        
        log_func = log_callback or (lambda x: None)
        
        # 检查是否为断点续跑
        if resume_from:
            return await self._resume_workflow(
                task_id=task_id,
                resume_from=resume_from,
                brand_path=brand_path,
                keywords=keywords,
                mode=mode,
                user_note=user_note,
                brand_site_url=brand_site_url,
                forbidden_whitelist=whitelist,
                step_files=step_files,
                log_callback=log_func
            )
        
        # 全新任务（若已由 pre_register_task 预注册则复用，避免覆盖状态）
        if task_id not in self._tasks:
            extra = {}
            if whitelist:
                extra["forbidden_whitelist"] = whitelist
            if model and model != "default":
                extra["model"] = model
            if temperature is not None:
                extra["temperature"] = temperature
            if max_tokens is not None:
                extra["max_tokens"] = max_tokens
            extra["priority"] = priority
            extra["skip_visual_check"] = skip_visual_check
            extra["visual_mode"] = visual_mode
            self._tasks[task_id] = {
                "task_id": task_id,
                "status": "queued",
                "mode": mode,
                "current_step": 0,
                "total_steps": 0,
                "start_time": datetime.now().isoformat(),
                "brand_path": brand_path,
                "keywords": keywords,
                "user_note": user_note,
                "brand_site_url": brand_site_url,
                "forbidden_whitelist": whitelist,
                "log": [],
                "step_files": [],
                "completed_steps": [],
                "results": [],
                "outputs": {},
                "retry_counts": {},
                "extra": extra,
            }
        else:
            self._tasks[task_id]["forbidden_whitelist"] = whitelist
            extra = dict(self._tasks[task_id].get("extra") or {})
            if whitelist:
                extra["forbidden_whitelist"] = whitelist
            if model and model != "default":
                extra["model"] = model
            if temperature is not None:
                extra["temperature"] = temperature
            if max_tokens is not None:
                extra["max_tokens"] = max_tokens
            self._tasks[task_id]["extra"] = extra
        if task_id not in self._task_logs:
            self._task_logs[task_id] = []
        
        # 创建任务日志管理器（带节流保存）
        task_logger = create_task_logger(
            task_id=task_id,
            task_state=self._tasks[task_id],
            state_saver=self._save_state,
            log_storage=self._task_logs[task_id],
            log_callback=log_func,
            throttle_interval=LOG_THROTTLE_INTERVAL
        )
        
        # 向后兼容的日志函数
        task_log = task_logger.create_log_function(force_save_default=False)
        
        task_logger.info(f"🚀 Starting workflow task: {task_id}")
        task_logger.info(f"   Brand: {brand_path}")
        task_logger.info(f"   Keywords: {keywords}")
        task_logger.info(f"   Mode: {mode}")
        if whitelist:
            task_logger.info(f"   Forbidden whitelist ({len(whitelist)}): {', '.join(whitelist)}")
        
        params = {
            "brand_path": brand_path,
            "keywords": keywords,
            "user_note": user_note,
            "brand_site_url": brand_site_url,
            "forbidden_whitelist": whitelist,
            "forbidden_whitelist_csv": ",".join(whitelist),
            "mode": mode,
            "task_id": task_id,
            "instance_dir": str(instance_dir),
            "skip_visual_check": skip_visual_check,
            "skip_visual_flag": " --skip-visual" if skip_visual_check else "",
            "visual_mode": visual_mode,
            "strict_flag": " --strict" if visual_mode == "strict" else "",
        }

        if step_files is None:
            registry = self.load_registry()
            step_files = registry.get("step_order", [])
        else:
            step_files = self.normalize_step_files(step_files)

        self._tasks[task_id]["step_files"] = step_files
        self._tasks[task_id]["total_steps"] = len(step_files)
        
        outputs = {}
        node_results = []
        
        # 并发控制：优先级调度，超过最大并发数时排队等待
        priority = (self._tasks.get(task_id, {}).get("extra") or {}).get("priority", 2)
        self._concurrency_stats["total_started"] += 1
        task_logger.info(f"📋 任务排队中（优先级: {priority_label(priority)}，当前并发 {len(self._running_tasks)}/{self.max_concurrent_tasks}）")
        wait_time, held_slot = await self._acquire_slot(task_id, priority)
        
        # 检查是否在排队期间被取消或定时结束暂停
        status_after_wait = self._tasks.get(task_id, {}).get("status")
        if status_after_wait in ("cancelled", "paused"):
            task_logger.info(
                "❌ 任务已%s，退出执行",
                "取消" if status_after_wait == "cancelled" else "暂停",
            )
            # 仅在真正持有槽位时释放，避免排队中止导致 available_slots 虚增
            if held_slot:
                self._release_slot()
            return {
                "task_id": task_id,
                "status": status_after_wait,
                "message": "任务已取消" if status_after_wait == "cancelled" else "任务已暂停",
            }
        
        try:
            # 获取到槽位后，标记为运行中
            if self._tasks.get(task_id, {}).get("status") == "queued":
                self._tasks[task_id]["status"] = "running"
                self._save_state(task_id)
            if wait_time > 0:
                task_logger.info(f"🚀 任务开始执行（排队等待 {wait_time:.1f}s）")
            else:
                task_logger.info(f"🚀 任务开始执行")
            exec_start = time.time()
            
            await self._execute_steps(
                task_id=task_id,
                step_files=step_files,
                params=params,
                outputs=outputs,
                node_results=node_results,
                instance_dir=instance_dir,
                mode=mode,
                task_log=task_log,
                start_step_idx=0
            )
            
            result = self._finalize_task(task_id, node_results, outputs, step_files, task_log)
            # 记录统计
            self._concurrency_stats["total_completed"] += 1
            self._concurrency_stats["total_wait_time"] += wait_time
            self._concurrency_stats["total_exec_time"] += time.time() - exec_start
            return result
        finally:
            if held_slot:
                self._release_slot()
    
    async def _resume_workflow(
        self,
        task_id: str,
        resume_from: str,
        brand_path: str,
        keywords: str,
        mode: str,
        user_note: str,
        brand_site_url: str,
        step_files: Optional[List[str]],
        log_callback: Optional[Callable[[str], None]] = None,
        log_func: Optional[Callable[[str], None]] = None,
        forbidden_whitelist: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """断点续跑 - 从指定节点继续，复用前序结果"""
        from blog_writer.forbidden import normalize_forbidden_whitelist

        # 加载之前的状态
        state = self._load_state(task_id)
        if not state:
            raise ValueError(f"任务 {task_id} 不存在，无法续跑")
        
        # 只拒绝已完成的任务；cancelled/failed/paused 允许续跑
        if state.get("status") == "completed":
            raise ValueError(f"任务 {task_id} 已完成，无法续跑")

        # 清理可能残留的执行标记（上次异常退出未清理）
        with self._running_tasks_lock:
            self._running_tasks.discard(task_id)

        log_fn = log_callback or log_func or (lambda x: None)
        whitelist = normalize_forbidden_whitelist(
            forbidden_whitelist
            if forbidden_whitelist is not None
            else state.get("forbidden_whitelist")
            or (state.get("extra") or {}).get("forbidden_whitelist")
        )
        
        instance_dir = self.instance_root / task_id
        
        # 恢复状态
        self._tasks[task_id] = state
        self._tasks[task_id]["forbidden_whitelist"] = whitelist
        
        # 确保 log 字段存在，并与 _task_logs 共享同一个列表引用
        # （从数据库加载的 state 没有 log 字段，会导致 task_logger 不写入 task["log"]）
        if "log" not in self._tasks[task_id] or not isinstance(self._tasks[task_id]["log"], list):
            self._tasks[task_id]["log"] = []
        # 从数据库补充历史日志到内存
        if self._use_db:
            try:
                db_logs = self._log_repo.get_logs(task_id, limit=500)
                for log_entry in db_logs:
                    entry_text = log_entry.get("log_entry", "")
                    if entry_text and entry_text not in self._tasks[task_id]["log"]:
                        self._tasks[task_id]["log"].append(entry_text)
            except Exception:
                pass
        self._task_logs[task_id] = self._tasks[task_id]["log"]
        self._flushed_log_counts[task_id] = len(self._tasks[task_id]["log"])
        
        completed_steps = state.get("completed_steps", [])
        node_results = state.get("results", [])
        outputs = state.get("outputs", {})
        
        # 创建任务日志管理器（带节流保存）
        task_logger = create_task_logger(
            task_id=task_id,
            task_state=self._tasks[task_id],
            state_saver=self._save_state,
            log_storage=self._tasks[task_id]["log"],
            log_callback=log_fn,
            throttle_interval=LOG_THROTTLE_INTERVAL
        )
        
        # 向后兼容的日志函数（默认强制保存）
        task_log = task_logger.create_log_function(force_save_default=True)
        
        task_logger.info(f"🔄 断点续跑: {task_id}")
        task_logger.info(f"   从节点 {resume_from} 开始")
        task_logger.info(f"   已完成: {completed_steps}")
        
        # 确定起始步骤索引
        step_files = step_files or state.get("step_files", [])
        if resume_from not in step_files:
            raise ValueError(f"节点 {resume_from} 不在步骤列表中")
        
        start_idx = step_files.index(resume_from)
        
        # 已完成的步骤结果复用
        params = {
            "brand_path": brand_path or state.get("brand_path", ""),
            "keywords": keywords or state.get("keywords", ""),
            "user_note": user_note or state.get("user_note", ""),
            "brand_site_url": brand_site_url or state.get("brand_site_url", ""),
            "forbidden_whitelist": whitelist,
            "forbidden_whitelist_csv": ",".join(whitelist),
            "mode": mode,
            "task_id": task_id,
            "instance_dir": str(instance_dir)
        }
        
        self._tasks[task_id]["status"] = "running"
        self._save_state(task_id)
        
        await self._execute_steps(
            task_id=task_id,
            step_files=step_files,
            params=params,
            outputs=outputs,
            node_results=node_results,
            instance_dir=instance_dir,
            mode=mode,
            task_log=task_log,
            start_step_idx=start_idx,
            skip_steps=set(completed_steps)
        )
        
        return self._finalize_task(task_id, node_results, outputs, step_files, task_log)
    
    def _sync_runtime_state(
        self,
        task_id: str,
        outputs: Dict[str, Any],
        node_results: List[Dict[str, Any]],
    ) -> None:
        """将执行循环中的 outputs/results 写回任务态，供落盘与重启恢复。"""
        task = self._tasks.get(task_id)
        if not task:
            return
        task["outputs"] = dict(outputs or {})
        task["results"] = list(node_results or [])

    def _risk_code_from_outputs(self, outputs: Dict[str, Any], instance_dir: Path) -> Optional[str]:
        """解析 RK01..RK05 代码，供 gate 风险路由使用。"""
        level = self._extract_risk_level(outputs)
        if level is None:
            level = wf_helpers.load_bid_risk_level(instance_dir)
        return wf_helpers.risk_code_from_level(level)

    def _apply_route_jump(
        self,
        task_id: str,
        router: WorkflowRouter,
        from_file: str,
        decision,
        node_results: List[Dict[str, Any]],
        task_log: Callable[[str], None],
        outputs: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """应用路由决策，回跳时清理后续完成记录与 outputs。返回下一 step_file 或 None。"""
        if decision.action == "finish":
            return None
        if decision.action == "fail_closed":
            return None
        nxt = decision.next_step_file
        if not nxt:
            return None
        if decision.action == "jump":
            completed = list(self._tasks[task_id].get("completed_steps", []))
            kept, filtered, removed = wf_helpers.apply_invalidate(
                router, completed, nxt, node_results
            )
            self._tasks[task_id]["completed_steps"] = kept
            node_results[:] = filtered
            if removed:
                task_log(f"   ↩️ 路由回跳 {from_file} → {nxt}，已清除后续完成态")
                # 同步清理 outputs（内存参数 + 任务态）
                target_outputs = outputs if outputs is not None else self._tasks[task_id].setdefault("outputs", {})
                pruned = wf_helpers.prune_outputs_for_steps(
                    target_outputs, removed, self.load_node_definition
                )
                target_outputs.clear()
                target_outputs.update(pruned)
                self._tasks[task_id]["outputs"] = dict(target_outputs)
                retries = self._tasks[task_id].setdefault("retry_counts", {})
                for sf in removed:
                    retries.pop(sf, None)
            retries = self._tasks[task_id].setdefault("retry_counts", {})
            retries.pop(nxt, None)
            self._save_state(task_id)
        return nxt

    async def _execute_steps(
        self,
        task_id: str,
        step_files: List[str],
        params: Dict[str, Any],
        outputs: Dict[str, Any],
        node_results: List[Dict[str, Any]],
        instance_dir: Path,
        mode: str,
        task_log: Callable[[str], None],
        start_step_idx: int = 0,
        skip_steps: Optional[set] = None
    ):
        """执行工作流步骤（registry routing + 自动重试 + fail-closed + 断点续跑）"""
        if not self._try_begin_execution(task_id):
            task_log(f"   ⚠️ 任务 {task_id} 已在执行中，拒绝并发编排")
            raise RuntimeError(f"task {task_id} already executing")
        try:
            await self._execute_steps_inner(
                task_id=task_id,
                step_files=step_files,
                params=params,
                outputs=outputs,
                node_results=node_results,
                instance_dir=instance_dir,
                mode=mode,
                task_log=task_log,
                start_step_idx=start_step_idx,
                skip_steps=skip_steps,
            )
        finally:
            self._end_execution(task_id)

    async def _execute_steps_inner(
        self,
        task_id: str,
        step_files: List[str],
        params: Dict[str, Any],
        outputs: Dict[str, Any],
        node_results: List[Dict[str, Any]],
        instance_dir: Path,
        mode: str,
        task_log: Callable[[str], None],
        start_step_idx: int = 0,
        skip_steps: Optional[set] = None
    ):
        """执行工作流步骤（registry routing + 自动重试 + fail-closed + 断点续跑）"""
        skip_steps = set(skip_steps or set())
        default_retries = self.config.get("workflow.max_retries_per_step", MAX_RETRIES)
        retry_delay_raw = self.config.get("workflow.retry_delay_seconds", RETRY_DELAY)
        try:
            retry_delay = float(retry_delay_raw)
        except (TypeError, ValueError):
            retry_delay = float(RETRY_DELAY)
        # 限制重试等待，避免负值报错或超大配置拖死编排
        retry_delay = max(0.0, min(retry_delay, 60.0))
        registry = self.load_registry()
        router = WorkflowRouter(registry, step_files, self.load_node_definition)
        max_loop = int(registry.get("max_steps", 30)) * 4
        jump_budget: Dict[str, int] = {}

        if not step_files:
            return

        if start_step_idx >= len(step_files):
            return
        current_file: Optional[str] = step_files[start_step_idx]
        loops = 0

        while current_file and loops < max_loop:
            loops += 1
            if current_file not in step_files:
                task_log(f"   ❌ 未知步骤文件: {current_file}")
                self._tasks[task_id]["status"] = "failed"
                self._save_state(task_id)
                break

            step_idx = step_files.index(current_file)
            self._tasks[task_id]["current_step"] = step_idx

            if self._tasks[task_id]["status"] in ["cancelled", "paused", "rejected", "failed"]:
                task_log(f"   ⏸️ 任务{self._tasks[task_id]['status']}，停止执行")
                break

            # 断点续跑：已完成步骤按 on_pass 前进
            if current_file in skip_steps:
                task_log(f"\n{'='*60}")
                task_log(f"📋 Step {step_idx + 1}/{len(step_files)}: {current_file} (已完成，跳过)")
                task_log(f"{'='*60}")
                node_id = router.node_id_for_file(current_file)
                risk_code = self._risk_code_from_outputs(outputs, instance_dir)
                decision = router.resolve_next(
                    node_id, passed=True, mode=mode, risk_code=risk_code
                ) if node_id else router._linear_next_file(current_file)
                current_file = self._apply_route_jump(
                    task_id, router, current_file, decision, node_results, task_log, outputs
                )
                continue

            task_log(f"\n{'='*60}")
            task_log(f"📋 Step {step_idx + 1}/{len(step_files)}: {current_file}")
            task_log(f"{'='*60}")

            try:
                node_def = self.load_node_definition(current_file)
            except FileNotFoundError:
                task_log(f"   ❌ Node file not found: {current_file}")
                self._tasks[task_id]["status"] = "failed"
                self._save_state(task_id)
                break

            exec_type = NodeExecutorFactory.get_exec_type(node_def)
            node_id = node_def.get("id", "") or router.node_id_for_file(current_file)
            node_name = node_def.get("name", current_file)
            step_file = current_file
            risk_code = self._risk_code_from_outputs(outputs, instance_dir)
            max_retries = router.max_retries_for(node_id, default_retries)

            # ---- 人工审核 ----
            if exec_type == "human_review":
                if self._should_skip_human_review(mode, step_file, outputs, instance_dir):
                    task_log(f"   ⚡ Mode={mode}: skipping human review node {step_file}")
                    if step_file not in self._tasks[task_id]["completed_steps"]:
                        self._tasks[task_id]["completed_steps"].append(step_file)
                    self._save_state(task_id)
                    decision = router.resolve_skip_target(
                        step_file, mode=mode, risk_code=risk_code
                    )
                    current_file = self._apply_route_jump(
                        task_id, router, step_file, decision, node_results, task_log, outputs
                    )
                    continue

                task_log(f"   ⏸️ Human review required: {node_name}")

                cancelled, review_decision, review_modifications = await self._await_human_review(
                    task_id,
                    node_id=node_id,
                    node_name=node_name,
                    step_file=step_file,
                    mode=mode,
                    outputs=outputs,
                    node_results=node_results,
                    task_log=task_log,
                    reason="human_review",
                )
                if cancelled:
                    break

                # 消费后清除，避免后续节点误用；同步落盘清掉 extra 中的决策
                self._tasks[task_id].pop("review_decision", None)
                self._tasks[task_id].pop("review_modifications", None)
                review_wait_mod.clear_external_review_decision(task_id)
                self._save_state(task_id)

                if review_decision == "reject":
                    # 按 on_fail 回跳；无目标则 rejected 终态
                    decision = router.resolve_next(
                        node_id, passed=False, mode=mode, risk_code=risk_code
                    )
                    if decision.next_step_file and decision.action in ("jump", "continue"):
                        jump_key = f"{step_file}->{decision.next_step_file}"
                        jump_budget[jump_key] = jump_budget.get(jump_key, 0) + 1
                        if jump_budget[jump_key] > max_retries + 1:
                            task_log(f"   ❌ 回跳预算耗尽，任务 rejected")
                            self._tasks[task_id]["status"] = "rejected"
                            self._save_state(task_id)
                            break
                        current_file = self._apply_route_jump(
                            task_id, router, step_file, decision, node_results, task_log, outputs
                        )
                        self._tasks[task_id]["status"] = "running"
                        self._save_state(task_id)
                        continue
                    task_log(f"   ❌ Task rejected by reviewer")
                    self._tasks[task_id]["status"] = "rejected"
                    self._save_state(task_id)
                    break
                elif review_decision == "modify":
                    params.update(review_modifications)
                elif review_decision == "retry":
                    task_log(f"   🔄 Retrying current step")
                    continue

                if step_file not in self._tasks[task_id]["completed_steps"]:
                    self._tasks[task_id]["completed_steps"].append(step_file)
                self._tasks[task_id]["status"] = "running"
                self._save_state(task_id)
                decision = router.resolve_next(
                    node_id, passed=True, mode=mode, risk_code=risk_code
                )
                current_file = self._apply_route_jump(
                    task_id, router, step_file, decision, node_results, task_log, outputs
                )
                continue

            # ---- 普通节点执行 ----
            node_params = params.copy()
            node_params.update(outputs)
            retry_count = self._tasks[task_id].get("retry_counts", {}).get(step_file, 0)
            success = False
            exhausted = False

            while retry_count <= max_retries:
                if retry_count > 0:
                    task_log(f"   🔄 重试 #{retry_count}/{max_retries}: {step_file}")
                    await asyncio.sleep(retry_delay * retry_count)

                try:
                    model_name = (
                        node_def.get("llm_model")
                        or (node_def.get("resources") or {}).get("llm_model")
                        or (self._tasks.get(task_id, {}).get("extra") or {}).get("model")
                    )
                    executor = NodeExecutorFactory.create_executor(
                        node_definition=node_def,
                        llm_provider=(
                            self.get_llm_provider(model_name)
                            if exec_type != "pure_code"
                            else None
                        ),
                        instance_dir=str(instance_dir),
                        max_iterations=self.config.get("workflow.max_iterations_per_step", 20),
                        log_callback=task_log
                    )
                except ValueError as e:
                    task_log(f"   ❌ 执行器配置错误: {e}")
                    node_results.append({
                        "step": step_file,
                        "node_id": node_id,
                        "exec_type": exec_type,
                        "status": "error",
                        "error": str(e),
                        "retry_count": retry_count
                    })
                    exhausted = True
                    break

                if executor is None:
                    task_log(f"   ℹ️ 执行器类型 {exec_type} 无需创建，按通过处理")
                    success = True
                    break

                step_timeout, timeout_min = resolve_step_timeout_seconds(
                    global_minutes=self.config.get("workflow.step_timeout_minutes", 10),
                    node_def=node_def,
                )
                try:
                    result = await asyncio.wait_for(
                        executor.execute(node_params),
                        timeout=step_timeout,
                    )
                    node_results.append({
                        "step": step_file,
                        "node_id": node_id,
                        "exec_type": exec_type,
                        "status": result.get("status", "unknown"),
                        "iterations": result.get("iterations", 0),
                        "checks_passed": result.get("checks_passed", False),
                        "token_usage": result.get("token_usage", {}),
                        "tool_calls": result.get("tool_calls", [])
                    })

                    if result.get("status") == "success" or result.get("checks_passed"):
                        task_log(f"   ✅ Step completed successfully (exec_type={exec_type})")
                        success = True
                        for action in node_def.get("actions", []):
                            output_info = action.get("output", {})
                            if output_info:
                                output_path = output_info.get("path", "")
                                output_id = output_info.get("id", "")
                                if output_path:
                                    outputs[output_id] = output_path
                                    outputs[output_path.replace(" ", "_")] = output_path
                        break

                    task_log(f"   ⚠️ Step completed with warnings (checks failed)")
                    if mode == "manual":
                        cancelled, review_decision, _mods = await self._await_human_review(
                            task_id,
                            node_id=node_id,
                            node_name=node_name,
                            step_file=step_file,
                            mode=mode,
                            outputs=outputs,
                            node_results=node_results,
                            task_log=task_log,
                            reason="manual_check_failed",
                        )
                        self._tasks[task_id].pop("review_decision", None)
                        self._tasks[task_id].pop("review_modifications", None)
                        review_wait_mod.clear_external_review_decision(task_id)
                        self._save_state(task_id)
                        if cancelled:
                            return
                        if review_decision == "retry":
                            retry_count += 1
                            self._tasks[task_id].setdefault("retry_counts", {})[step_file] = retry_count
                            self._tasks[task_id]["status"] = "running"
                            self._save_state(task_id)
                            continue
                        if review_decision == "reject":
                            self._tasks[task_id]["status"] = "rejected"
                            self._save_state(task_id)
                            return
                        # approve：视为通过
                        success = True
                        break

                    if retry_count < max_retries:
                        retry_count += 1
                        self._tasks[task_id].setdefault("retry_counts", {})[step_file] = retry_count
                        self._save_state(task_id)
                        continue
                    task_log(f"   ❌ 达到最大重试次数 ({max_retries})，fail-closed / 按 on_fail 路由")
                    exhausted = True
                    break

                except asyncio.TimeoutError:
                    task_log(
                        f"   ❌ Step timed out after {step_timeout:.0f}s "
                        f"(step_timeout_minutes={timeout_min})"
                    )
                    node_results.append({
                        "step": step_file,
                        "node_id": node_id,
                        "exec_type": exec_type,
                        "status": "error",
                        "error": f"step timeout after {step_timeout:.0f}s",
                        "retry_count": retry_count,
                    })
                    if retry_count < max_retries:
                        retry_count += 1
                        self._tasks[task_id].setdefault("retry_counts", {})[step_file] = retry_count
                        self._save_state(task_id)
                        continue
                    exhausted = True
                    break

                except Exception as e:
                    task_log(f"   ❌ Step failed: {e}")
                    node_results.append({
                        "step": step_file,
                        "node_id": node_id,
                        "exec_type": exec_type,
                        "status": "error",
                        "error": str(e),
                        "retry_count": retry_count
                    })
                    if retry_count < max_retries:
                        retry_count += 1
                        self._tasks[task_id].setdefault("retry_counts", {})[step_file] = retry_count
                        self._save_state(task_id)
                        continue
                    if mode == "manual":
                        cancelled, review_decision, _mods = await self._await_human_review(
                            task_id,
                            node_id=node_id,
                            node_name=node_name,
                            step_file=step_file,
                            mode=mode,
                            outputs=outputs,
                            node_results=node_results,
                            task_log=task_log,
                            reason="manual_retry_exhausted",
                        )
                        self._tasks[task_id].pop("review_decision", None)
                        self._tasks[task_id].pop("review_modifications", None)
                        review_wait_mod.clear_external_review_decision(task_id)
                        self._save_state(task_id)
                        if cancelled:
                            return
                        if review_decision == "retry":
                            retry_count += 1
                            self._tasks[task_id].setdefault("retry_counts", {})[step_file] = retry_count
                            self._tasks[task_id]["status"] = "running"
                            self._save_state(task_id)
                            continue
                        if review_decision == "reject":
                            self._tasks[task_id]["status"] = "rejected"
                            self._save_state(task_id)
                            return
                        success = True
                        break
                    task_log(f"   ❌ Auto/supervised：重试耗尽，fail-closed")
                    exhausted = True
                    break

            if success:
                if step_file not in self._tasks[task_id]["completed_steps"]:
                    self._tasks[task_id]["completed_steps"].append(step_file)
                # 增量落盘：审核等待/重启前不能只存 completed_steps
                self._sync_runtime_state(task_id, outputs, node_results)
                self._save_state(task_id)
                self._fire_task_webhook(
                    task_id,
                    "task.step_completed",
                    {
                        "task_id": task_id,
                        "status": self._tasks[task_id].get("status", "running"),
                        "step_file": step_file,
                        "node_id": node_id,
                        "step_index": step_idx + 1,
                        "total_steps": len(step_files),
                        "keywords": self._tasks[task_id].get("keywords", ""),
                    },
                )

                exceeded, used, limit = token_budget_exceeded(
                    node_results,
                    self.config.get("workflow.max_tokens_per_task", 0),
                )
                if exceeded:
                    task_log(
                        f"   🛑 Token 预算耗尽：已用 {used} / 上限 {limit}，fail-closed"
                    )
                    self._tasks[task_id]["status"] = "failed"
                    extra = dict(self._tasks[task_id].get("extra") or {})
                    extra["last_error"] = f"token budget exceeded: {used}/{limit}"
                    self._tasks[task_id]["extra"] = extra
                    self._save_state(task_id)
                    break

                decision = router.resolve_next(
                    node_id, passed=True, mode=mode, risk_code=risk_code
                )
                current_file = self._apply_route_jump(
                    task_id, router, step_file, decision, node_results, task_log, outputs
                )
                continue

            # 失败：优先 on_fail 回跳，否则 fail-closed 终止
            decision = router.resolve_next(
                node_id, passed=False, mode=mode, risk_code=risk_code
            )
            if decision.next_step_file and decision.action in ("jump", "continue"):
                jump_key = f"{step_file}->{decision.next_step_file}:fail"
                jump_budget[jump_key] = jump_budget.get(jump_key, 0) + 1
                if jump_budget[jump_key] <= max_retries + 1:
                    task_log(
                        f"   ↪️ on_fail 路由 → {decision.next_step_file} "
                        f"(budget {jump_budget[jump_key]}/{max_retries + 1})"
                    )
                    current_file = self._apply_route_jump(
                        task_id, router, step_file, decision, node_results, task_log, outputs
                    )
                    continue

            task_log(f"   🛑 Fail-closed：步骤失败且无法继续路由 ({step_file})")
            self._tasks[task_id]["status"] = "failed"
            self._sync_runtime_state(task_id, outputs, node_results)
            self._save_state(task_id)
            break

        if loops >= max_loop:
            task_log(f"   🛑 达到最大循环次数 ({max_loop})，停止以防死循环")
            if self._tasks[task_id]["status"] == "running":
                self._tasks[task_id]["status"] = "failed"
                self._save_state(task_id)
    
    def _finalize_task(
        self,
        task_id: str,
        node_results: List[Dict[str, Any]],
        outputs: Dict[str, Any],
        step_files: List[str],
        task_log: Callable[[str], None]
    ) -> Dict[str, Any]:
        """完成任务，汇总结果"""
        current_status = self._tasks[task_id].get("status", "completed")
        
        # 根据当前状态和结果决定最终状态
        # failed 必须保留：fail-closed / 缺节点 / 循环上限会先写入 failed，
        # 但 node_results 里常见 partial（检查未过），旧逻辑会误标 completed。
        if current_status in ["cancelled", "paused", "rejected", "failed"]:
            final_status = current_status
        elif current_status == "waiting_review":
            # 如果任务还在等待审核，保持该状态
            final_status = "waiting_review"
        else:
            # 每个 step 只保留最后一次结果（重试成功后忽略早期 error）
            latest_by_step: Dict[str, Dict[str, Any]] = {}
            order: List[str] = []
            for r in node_results:
                step = r.get("step") or r.get("node_id") or ""
                if step not in latest_by_step:
                    order.append(step)
                latest_by_step[step] = r
            effective = [latest_by_step[s] for s in order if s in latest_by_step]

            has_failures = any(r.get("status") == "error" for r in effective)
            all_success = all(
                r.get("status") == "success" for r in effective
            ) if effective else False
            has_partial = any(r.get("status") == "partial" for r in effective)

            if all_success and effective and not has_partial:
                final_status = "completed"
            elif has_failures:
                final_status = "failed"
            elif not effective:
                final_status = "failed"
            else:
                final_status = "completed_partial"

            # 持久化时也写折叠后的结果，避免 API 展示误导
            node_results = effective
        
        self._tasks[task_id]["status"] = final_status
        self._tasks[task_id]["end_time"] = datetime.now().isoformat()
        self._tasks[task_id]["results"] = node_results
        self._tasks[task_id]["outputs"] = outputs

        # token / 步骤数按"每个 step 仅最后一次结果"统计，
        # 避免重试或失败分支下对同一 step 的多次结果重复累计 token
        latest_for_stats: Dict[str, Dict[str, Any]] = {}
        for r in node_results:
            step = r.get("step") or r.get("node_id") or ""
            latest_for_stats[step] = r
        stats_results = list(latest_for_stats.values())

        # token按累积值取最大值（每个步骤的token_usage是累积的，不能求和）
        total_tokens = self._calc_task_token_usage(stats_results)
        total_steps_completed = len([r for r in stats_results if r.get("status") in ["success", "partial"]])
        
        task_log(f"\n{'='*60}")
        task_log(f"📊 Workflow {final_status}!")
        task_log(f"   Task ID: {task_id}")
        task_log(f"   Steps completed: {total_steps_completed}/{len(step_files)}")
        task_log(f"   Total tokens used: {total_tokens}")
        task_log(f"   Status: {final_status}")
        task_log(f"{'='*60}")
        
        self._save_state(task_id)
        
        # 控制面 pause/cancel 已发过 webhook；此处再发会导致对接方重复计数
        if final_status not in ("paused", "cancelled"):
            webhook_data = {
                "task_id": task_id,
                "status": final_status,
                "steps_completed": total_steps_completed,
                "total_steps": len(step_files),
                "total_tokens": total_tokens,
                "token_usage": total_tokens,
                "keywords": self._tasks[task_id].get("keywords", ""),
            }
            webhook_data.update(self._webhook_payload_extra(task_id))
            self._fire_task_webhook(task_id, f"task.{final_status}", webhook_data)

        # 终态后延迟清理内存字典，降低长期运行 OOM 风险（DB 仍为真相源）
        if final_status in (
            "completed",
            "failed",
            "cancelled",
            "rejected",
            "completed_partial",
        ):
            self._schedule_task_memory_cleanup(task_id)
        
        return {
            "task_id": task_id,
            "status": final_status,
            "steps_completed": total_steps_completed,
            "total_steps": len(step_files),
            "total_tokens": total_tokens,
            "outputs": outputs,
            "results": node_results
        }

    def _schedule_task_memory_cleanup(self, task_id: str) -> None:
        delay = max(30.0, float(self._task_cleanup_delay_seconds or 300))

        def _job(tid=task_id):
            try:
                self._cleanup_task_memory(tid)
            except Exception as e:
                logger.debug("task memory cleanup failed for %s: %s", tid, e)

        # 使用独立 Timer 线程，避免占用共享线程池导致 Webhook/续跑任务饥饿
        timer = threading.Timer(delay, _job)
        timer.name = f"cleanup-{task_id}"
        timer.daemon = True
        timer.start()

    def _cleanup_task_memory(self, task_id: str) -> None:
        """终态任务：保留最小缓存，释放完整内存态。"""
        terminal = {
            "completed",
            "failed",
            "cancelled",
            "rejected",
            "completed_partial",
        }
        if self.is_task_executing(task_id):
            return
        if task_id in self._pause_events:
            return
        task = self._tasks.get(task_id)
        if not task:
            return
        status = task.get("status")
        if status not in terminal:
            return
        self._task_cache[task_id] = {
            "task_id": task_id,
            "status": status,
            "end_time": task.get("end_time"),
            "owner_id": task.get("owner_id")
            or (task.get("extra") or {}).get("owner_id", ""),
        }
        self._tasks.pop(task_id, None)
        self._task_logs.pop(task_id, None)
        self._flushed_log_counts.pop(task_id, None)
        self._task_locks.pop(task_id, None)
        with self._task_sync_locks_guard:
            self._task_sync_locks.pop(task_id, None)
        logger.debug("cleaned in-memory state for terminal task %s (%s)", task_id, status)
    
    async def rerun_from_node(
        self,
        task_id: str,
        node_file: str,
        brand_path: str = "",
        keywords: str = "",
        mode: str = "auto",
        user_note: str = "",
        brand_site_url: str = "",
        skip_visual_check: bool = False,
        visual_mode: str = "relaxed",
        log_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """从指定节点重新运行（忽略之前的结果）"""
        state = self._load_state(task_id)
        if not state:
            raise ValueError(f"任务 {task_id} 不存在")
        
        # 清理可能残留的执行标记（上次异常退出未清理）
        with self._running_tasks_lock:
            self._running_tasks.discard(task_id)

        log_func = log_callback or (lambda x: None)
        instance_dir = self.instance_root / task_id
        
        # 找到节点索引
        step_files = state.get("step_files", [])
        if node_file not in step_files:
            raise ValueError(f"节点 {node_file} 不在任务步骤中")
        
        start_idx = step_files.index(node_file)
        
        # 清除该节点及之后的结果
        completed_steps = list(state.get("completed_steps", []))
        results = list(state.get("results", []))
        outputs = dict(state.get("outputs", {}))
        
        # 清除残留的审核决策，防止 _await_human_review 误用旧决策
        state.pop("review_decision", None)
        state.pop("review_modifications", None)
        state.pop("review_node", None)
        state.pop("review_node_name", None)
        
        # 移除从指定节点开始的完成记录和结果
        nodes_to_remove = set(step_files[start_idx:])
        completed_steps = [s for s in completed_steps if s not in nodes_to_remove]
        results = [r for r in results if r.get("step") not in nodes_to_remove]
        outputs = wf_helpers.prune_outputs_for_steps(
            outputs, nodes_to_remove, self.load_node_definition
        )
        retries = dict(state.get("retry_counts", {}))
        for sf in nodes_to_remove:
            retries.pop(sf, None)
        state["retry_counts"] = retries
        
        # 确保 log 字段存在，并与 _task_logs 共享同一个列表引用
        if "log" not in state or not isinstance(state["log"], list):
            state["log"] = []
        if self._use_db:
            try:
                db_logs = self._log_repo.get_logs(task_id, limit=500)
                for log_entry in db_logs:
                    entry_text = log_entry.get("log_entry", "")
                    if entry_text and entry_text not in state["log"]:
                        state["log"].append(entry_text)
            except Exception:
                pass
        self._task_logs[task_id] = state["log"]
        self._flushed_log_counts[task_id] = len(state["log"])
        
        # 创建任务日志管理器（带节流保存）
        task_logger = create_task_logger(
            task_id=task_id,
            task_state=state,
            state_saver=self._save_state,
            log_storage=state["log"],
            log_callback=log_func,
            throttle_interval=LOG_THROTTLE_INTERVAL
        )
        
        # 向后兼容的日志函数（默认强制保存）
        task_log = task_logger.create_log_function(force_save_default=True)
        
        task_logger.info(f"🔄 重新运行任务 {task_id}，从节点 {node_file} 开始")
        task_logger.info(f"   将清除该节点及之后的所有结果")
        
        # 构建参数
        from blog_writer.forbidden import normalize_forbidden_whitelist
        whitelist = normalize_forbidden_whitelist(
            state.get("forbidden_whitelist")
            or (state.get("extra") or {}).get("forbidden_whitelist")
        )
        params = {
            "brand_path": brand_path or state.get("brand_path", ""),
            "keywords": keywords or state.get("keywords", ""),
            "user_note": user_note or state.get("user_note", ""),
            "brand_site_url": brand_site_url or state.get("brand_site_url", ""),
            "forbidden_whitelist": whitelist,
            "forbidden_whitelist_csv": ",".join(whitelist),
            "mode": mode,
            "task_id": task_id,
            "instance_dir": str(instance_dir),
            "skip_visual_check": skip_visual_check,
            "skip_visual_flag": " --skip-visual" if skip_visual_check else "",
            "visual_mode": visual_mode,
            "strict_flag": " --strict" if visual_mode == "strict" else "",
        }
        
        self._tasks[task_id] = state
        self._tasks[task_id]["status"] = "running"
        self._tasks[task_id]["completed_steps"] = completed_steps
        self._tasks[task_id]["results"] = results
        self._tasks[task_id]["outputs"] = outputs
        self._tasks[task_id]["brand_site_url"] = params["brand_site_url"]
        self._save_state(task_id)
        
        await self._execute_steps(
            task_id=task_id,
            step_files=step_files,
            params=params,
            outputs=outputs,
            node_results=results,
            instance_dir=instance_dir,
            mode=mode,
            task_log=task_log,
            start_step_idx=start_idx,
            skip_steps=set(completed_steps)
        )
        
        return self._finalize_task(task_id, results, outputs, step_files, task_log)
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self._tasks.get(task_id)
        if task:
            task["token_usage"] = self._calc_task_token_usage(task.get("results", []))
            return task
        # 尝试从数据库恢复
        if self._use_db:
            db_task = self._task_repo.load_task(task_id)
            if db_task:
                db_task["token_usage"] = self._calc_task_token_usage(db_task.get("results", []))
                self._tasks[task_id] = db_task
                self._task_cache.pop(task_id, None)
                return db_task
        # 尝试从磁盘恢复
        state = self._load_state(task_id)
        if state:
            state["token_usage"] = self._calc_task_token_usage(state.get("results", []))
            self._tasks[task_id] = state
            self._task_cache.pop(task_id, None)
            return state
        # 内存已清理时返回最小缓存（避免误报不存在）
        cached = self._task_cache.get(task_id)
        if cached:
            result = dict(cached)
            result["token_usage"] = self._calc_task_token_usage(result.get("results", []))
            return result
        return None
    
    def get_task_logs(self, task_id: str) -> List[str]:
        logs = list(self._task_logs.get(task_id, []))
        # 补充数据库中的历史日志
        if self._use_db:
            try:
                db_logs = self._log_repo.get_logs(task_id, limit=500)
                for log_entry in db_logs:
                    entry_text = log_entry.get("log_entry", "")
                    if entry_text and entry_text not in logs:
                        logs.append(entry_text)
            except Exception:
                pass
        return logs
    
    @staticmethod
    def _calc_task_token_usage(results: List[Dict[str, Any]]) -> int:
        """计算任务总Token消耗。
        
        注意：每个步骤的token_usage.total_tokens_used是累积值（整个任务复用
        同一个LLM实例），因此取所有步骤中的最大值即为任务总消耗，不能求和。
        """
        if not results:
            return 0
        max_tokens = 0
        for r in results:
            if not isinstance(r, dict):
                continue
            tokens = (r.get("token_usage") or {}).get("total_tokens_used", 0)
            if tokens and tokens > max_tokens:
                max_tokens = tokens
        return max_tokens
    
    @staticmethod
    def _list_extra_fields(extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """列表接口只回传前端卡片需要的 extra 子集（避免带上 scheduled_params 等大字段）。"""
        extra = extra or {}
        out: Dict[str, Any] = {
            "priority": extra.get("priority", 2),
        }
        if extra.get("scheduled_at"):
            out["scheduled_at"] = extra["scheduled_at"]
        if extra.get("scheduled_end_at"):
            out["scheduled_end_at"] = extra["scheduled_end_at"]
        if extra.get("paused_by_schedule_end"):
            out["paused_by_schedule_end"] = True
        last_error = extra.get("last_error")
        if last_error:
            out["last_error"] = str(last_error)[:300]
        return out

    def list_tasks(self) -> List[Dict[str, Any]]:
        tasks = []
        seen_ids = set()

        def _row(task_id: str, task: Dict[str, Any]) -> Dict[str, Any]:
            results = task.get("results", [])
            extra = task.get("extra") or {}
            return {
                "task_id": task_id,
                "status": task.get("status", "unknown"),
                "mode": task.get("mode", ""),
                "keywords": task.get("keywords", ""),
                "start_time": task.get("start_time", ""),
                "current_step": task.get("current_step", 0),
                "total_steps": task.get("total_steps", 0),
                "token_usage": self._calc_task_token_usage(results),
                "owner_id": task.get("owner_id") or extra.get("owner_id", ""),
                "extra": self._list_extra_fields(extra),
                "scheduled_at": extra.get("scheduled_at") or None,
                "scheduled_end_at": extra.get("scheduled_end_at") or None,
            }
        
        # 内存中的任务
        for task_id, task in self._tasks.items():
            seen_ids.add(task_id)
            tasks.append(_row(task_id, task))
        
        # 数据库中的任务
        if self._use_db:
            try:
                db_tasks = self._task_repo.list_tasks(limit=200)
                for db_task in db_tasks:
                    task_id = db_task.get("task_id", "")
                    if task_id and task_id not in seen_ids:
                        seen_ids.add(task_id)
                        tasks.append(_row(task_id, db_task))
            except Exception:
                pass
        
        # 磁盘中未加载的任务
        if self.instance_root.exists():
            for task_dir in self.instance_root.iterdir():
                if task_dir.is_dir() and task_dir.name not in seen_ids:
                    state = self._load_state(task_dir.name)
                    if state:
                        seen_ids.add(task_dir.name)
                        tasks.append(_row(task_dir.name, state))
        
        return sorted(tasks, key=lambda x: x["start_time"], reverse=True)
    
