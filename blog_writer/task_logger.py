"""
blog_writer/task_logger.py - 任务日志管理器

提供统一的日志记录接口，支持节流保存和强制保存。
"""

import logging
import threading
from datetime import datetime
from typing import Callable, Optional, List

from blog_writer.constants import LOG_THROTTLE_INTERVAL, LOG_TIMESTAMP_FORMAT

logger = logging.getLogger(__name__)


class TaskLogger:
    """
    任务日志管理器
    
    特性：
    1. 日志节流：每 N 条日志自动保存一次状态
    2. 强制保存：关键状态变更时立即保存
    3. 日志回调：支持外部日志回调函数
    4. 线程安全：支持异步操作
    
    使用示例：
        logger = TaskLogger(task_id, task_state, state_saver)
        logger.info("Starting task")  # 自动节流保存
        logger.success("Step completed", force_save=True)  # 强制保存
    """
    
    def __init__(
        self,
        task_id: str,
        task_state: dict,
        state_saver: Callable[[str], None],
        log_storage: Optional[List[str]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        throttle_interval: int = LOG_THROTTLE_INTERVAL
    ):
        """
        初始化任务日志管理器
        
        Args:
            task_id: 任务ID
            task_state: 任务状态字典（引用）
            state_saver: 状态保存函数
            log_storage: 日志存储列表（引用）
            log_callback: 日志回调函数
            throttle_interval: 节流间隔（日志条数）
        """
        self._task_id = task_id
        self._task_state = task_state
        self._state_saver = state_saver
        self._log_storage = log_storage
        self._log_callback = log_callback
        self._throttle_interval = throttle_interval
        
        # 日志计数器（用于节流）
        self._log_count = 0
        self._lock = threading.Lock()
    
    def _format_log(self, msg: str) -> str:
        """格式化日志消息"""
        timestamp = datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
        return f"[{timestamp}] {msg}"
    
    def _save_log(self, entry: str, force_save: bool = False):
        """
        保存日志到所有存储位置
        
        Args:
            entry: 格式化后的日志条目
            force_save: 是否强制保存状态
        """
        with self._lock:
            # 保存到日志存储列表
            if self._log_storage is not None:
                self._log_storage.append(entry)
            
            # 保存到任务状态
            if "log" in self._task_state:
                log_list = self._task_state["log"]
                if isinstance(log_list, list):
                    log_list.append(entry)
            
            # 回调通知
            if self._log_callback:
                self._log_callback(f"[{self._task_id}] {entry}")
            
            # 节流保存
            self._log_count += 1
            should_save = force_save or self._log_count >= self._throttle_interval
            if should_save:
                self._log_count = 0
        
        if should_save:
            try:
                self._state_saver(self._task_id)
            except Exception as e:
                logger.error(f"保存任务状态失败 {self._task_id}: {e}")
    
    def log(self, msg: str, force_save: bool = False):
        """
        记录日志（通用方法）
        
        Args:
            msg: 日志消息
            force_save: 是否强制保存状态
        """
        entry = self._format_log(msg)
        self._save_log(entry, force_save)
    
    def info(self, msg: str, force_save: bool = False):
        """记录信息日志"""
        self.log(msg, force_save)
    
    def success(self, msg: str, force_save: bool = True):
        """记录成功日志（默认强制保存）"""
        self.log(msg, force_save)
    
    def warning(self, msg: str, force_save: bool = True):
        """记录警告日志（默认强制保存）"""
        self.log(f"⚠️ {msg}", force_save)
    
    def error(self, msg: str, force_save: bool = True):
        """记录错误日志（默认强制保存）"""
        self.log(f"❌ {msg}", force_save)
    
    def section(self, title: str, force_save: bool = False):
        """记录章节标题"""
        separator = "=" * 40
        self.log(f"\n{separator}", force_save)
        self.log(f"📋 {title}", force_save)
        self.log(separator, force_save)
    
    def step(self, step_idx: int, total_steps: int, step_name: str, force_save: bool = False):
        """记录步骤信息"""
        self.log(f"\n📝 Step {step_idx + 1}/{total_steps}: {step_name}", force_save)
    
    def complete(self, force_save: bool = True):
        """记录完成日志"""
        self.log("✅ Workflow completed!", force_save)
    
    def reset_counter(self):
        """重置日志计数器"""
        self._log_count = 0
    
    @property
    def log_count(self) -> int:
        """获取当前日志计数"""
        return self._log_count
    
    def create_log_function(self, force_save_default: bool = False) -> Callable[[str], None]:
        """
        创建一个简单的日志函数（用于向后兼容）
        
        Args:
            force_save_default: 默认是否强制保存
        
        Returns:
            日志函数
        """
        def log_func(msg: str, force_save: bool = force_save_default):
            self.log(msg, force_save)
        return log_func


def create_task_logger(
    task_id: str,
    task_state: dict,
    state_saver: Callable[[str], None],
    log_storage: Optional[List[str]] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    throttle_interval: int = LOG_THROTTLE_INTERVAL
) -> TaskLogger:
    """
    工厂函数：创建任务日志管理器
    
    Args:
        task_id: 任务ID
        task_state: 任务状态字典
        state_saver: 状态保存函数
        log_storage: 日志存储列表
        log_callback: 日志回调函数
        throttle_interval: 节流间隔
    
    Returns:
        TaskLogger 实例
    """
    return TaskLogger(
        task_id=task_id,
        task_state=task_state,
        state_saver=state_saver,
        log_storage=log_storage,
        log_callback=log_callback,
        throttle_interval=throttle_interval
    )
