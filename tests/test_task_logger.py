"""
TaskLogger 单元测试
"""
import time
from typing import List, Dict, Any

import pytest

from blog_writer.task_logger import TaskLogger, create_task_logger
from blog_writer.constants import LOG_THROTTLE_INTERVAL


class TestTaskLogger:
    """测试 TaskLogger 类"""
    
    @pytest.fixture
    def setup(self):
        """设置测试环境"""
        task_id = "test_task"
        task_state: Dict[str, Any] = {
            "task_id": task_id,
            "status": "running",
            "log": []
        }
        log_storage: List[str] = []
        saved_state = []
        
        def state_saver(tid: str):
            saved_state.append(tid)
        
        callback_logs = []
        def log_callback(msg: str):
            callback_logs.append(msg)
        
        logger = TaskLogger(
            task_id=task_id,
            task_state=task_state,
            state_saver=state_saver,
            log_storage=log_storage,
            log_callback=log_callback,
            throttle_interval=5  # 测试用较小的间隔
        )
        
        return {
            "logger": logger,
            "task_id": task_id,
            "task_state": task_state,
            "log_storage": log_storage,
            "saved_state": saved_state,
            "callback_logs": callback_logs
        }
    
    def test_log_basic(self, setup):
        """测试基本日志记录"""
        logger = setup["logger"]
        log_storage = setup["log_storage"]
        
        logger.log("Test message")
        
        assert len(log_storage) == 1
        assert "Test message" in log_storage[0]
        assert "[" in log_storage[0]  # 包含时间戳
    
    def test_log_to_task_state(self, setup):
        """测试日志保存到任务状态"""
        logger = setup["logger"]
        task_state = setup["task_state"]
        
        logger.log("Test message")
        
        assert len(task_state["log"]) == 1
    
    def test_log_callback(self, setup):
        """测试日志回调"""
        logger = setup["logger"]
        callback_logs = setup["callback_logs"]
        task_id = setup["task_id"]
        
        logger.log("Test message")
        
        assert len(callback_logs) == 1
        assert f"[{task_id}]" in callback_logs[0]
    
    def test_throttle_save(self, setup):
        """测试节流保存"""
        logger = setup["logger"]
        saved_state = setup["saved_state"]
        
        # 记录4条日志（节流间隔为5）
        for i in range(4):
            logger.log(f"Message {i}")
        
        # 不应该保存
        assert len(saved_state) == 0
        
        # 第5条日志应该触发保存
        logger.log("Message 5")
        assert len(saved_state) == 1
    
    def test_force_save(self, setup):
        """测试强制保存"""
        logger = setup["logger"]
        saved_state = setup["saved_state"]
        
        # 记录1条日志并强制保存
        logger.log("Test message", force_save=True)
        
        # 应该立即保存
        assert len(saved_state) == 1
    
    def test_info_log(self, setup):
        """测试 info 方法"""
        logger = setup["logger"]
        log_storage = setup["log_storage"]
        
        logger.info("Info message")
        
        assert len(log_storage) == 1
        assert "Info message" in log_storage[0]
    
    def test_success_log(self, setup):
        """测试 success 方法（默认强制保存）"""
        logger = setup["logger"]
        saved_state = setup["saved_state"]
        log_storage = setup["log_storage"]
        
        logger.success("Success message")
        
        assert len(log_storage) == 1
        assert "Success message" in log_storage[0]
        assert len(saved_state) == 1  # 强制保存
    
    def test_warning_log(self, setup):
        """测试 warning 方法"""
        logger = setup["logger"]
        log_storage = setup["log_storage"]
        
        logger.warning("Warning message")
        
        assert len(log_storage) == 1
        assert "⚠️" in log_storage[0]
    
    def test_error_log(self, setup):
        """测试 error 方法"""
        logger = setup["logger"]
        log_storage = setup["log_storage"]
        
        logger.error("Error message")
        
        assert len(log_storage) == 1
        assert "❌" in log_storage[0]
    
    def test_section_log(self, setup):
        """测试 section 方法"""
        logger = setup["logger"]
        log_storage = setup["log_storage"]
        
        logger.section("Test Section")
        
        # 应该有3条日志（分隔线、标题、分隔线）
        assert len(log_storage) == 3
        assert "Test Section" in log_storage[1]
    
    def test_step_log(self, setup):
        """测试 step 方法"""
        logger = setup["logger"]
        log_storage = setup["log_storage"]
        
        logger.step(2, 5, "Step 3")
        
        assert len(log_storage) == 1
        assert "3/5" in log_storage[0]
        assert "Step 3" in log_storage[0]
    
    def test_complete_log(self, setup):
        """测试 complete 方法"""
        logger = setup["logger"]
        log_storage = setup["log_storage"]
        saved_state = setup["saved_state"]
        
        logger.complete()
        
        assert len(log_storage) == 1
        assert "Workflow completed" in log_storage[0]
        assert len(saved_state) == 1  # 强制保存
    
    def test_reset_counter(self, setup):
        """测试重置计数器"""
        logger = setup["logger"]
        saved_state = setup["saved_state"]
        
        # 记录4条日志
        for i in range(4):
            logger.log(f"Message {i}")
        
        assert len(saved_state) == 0
        
        # 重置计数器
        logger.reset_counter()
        
        # 再记录4条日志，应该不会保存
        for i in range(4):
            logger.log(f"Message {i}")
        
        assert len(saved_state) == 0
    
    def test_log_count_property(self, setup):
        """测试日志计数属性"""
        logger = setup["logger"]
        
        assert logger.log_count == 0
        
        logger.log("Message 1")
        assert logger.log_count == 1
        
        logger.log("Message 2")
        assert logger.log_count == 2


class TestTaskLoggerFactory:
    """测试工厂函数"""
    
    def test_create_task_logger(self):
        """测试创建日志管理器"""
        task_id = "factory_test"
        task_state = {"log": []}
        log_storage = []
        saved = []
        
        logger = create_task_logger(
            task_id=task_id,
            task_state=task_state,
            state_saver=lambda tid: saved.append(tid),
            log_storage=log_storage
        )
        
        assert isinstance(logger, TaskLogger)
        logger.info("Test")
        assert len(log_storage) == 1
    
    def test_create_log_function(self):
        """测试创建日志函数"""
        task_id = "func_test"
        task_state = {"log": []}
        log_storage = []
        
        logger = create_task_logger(
            task_id=task_id,
            task_state=task_state,
            state_saver=lambda tid: None,
            log_storage=log_storage,
            throttle_interval=3
        )
        
        # 创建日志函数
        log_func = logger.create_log_function(force_save_default=False)
        
        # 使用日志函数
        log_func("Test via function")
        
        assert len(log_storage) == 1
        assert "Test via function" in log_storage[0]
    
    def test_create_log_function_with_force_save(self):
        """测试创建带强制保存的日志函数"""
        task_id = "force_test"
        task_state = {"log": []}
        log_storage = []
        saved = []
        
        logger = create_task_logger(
            task_id=task_id,
            task_state=task_state,
            state_saver=lambda tid: saved.append(tid),
            log_storage=log_storage,
            throttle_interval=10
        )
        
        # 创建默认强制保存的日志函数
        log_func = logger.create_log_function(force_save_default=True)
        
        # 使用日志函数
        log_func("Force save test")
        
        assert len(saved) == 1  # 应该立即保存


class TestTaskLoggerEdgeCases:
    """测试边界情况"""
    
    def test_without_log_storage(self):
        """测试无日志存储"""
        task_id = "no_storage"
        task_state = {"log": []}
        saved = []
        
        logger = TaskLogger(
            task_id=task_id,
            task_state=task_state,
            state_saver=lambda tid: saved.append(tid),
            log_storage=None  # 无外部存储
        )
        
        # 应该不会崩溃
        logger.log("Test without storage")
        assert len(task_state["log"]) == 1
    
    def test_without_log_callback(self):
        """测试无日志回调"""
        task_id = "no_callback"
        task_state = {"log": []}
        log_storage = []
        saved = []
        
        logger = TaskLogger(
            task_id=task_id,
            task_state=task_state,
            state_saver=lambda tid: saved.append(tid),
            log_storage=log_storage,
            log_callback=None  # 无回调
        )
        
        # 应该不会崩溃
        logger.log("Test without callback")
        assert len(log_storage) == 1
    
    def test_state_saver_exception_handling(self):
        """测试状态保存异常处理"""
        task_id = "exception_test"
        task_state = {"log": []}
        log_storage = []
        
        def failing_saver(tid: str):
            raise Exception("Save failed!")
        
        logger = TaskLogger(
            task_id=task_id,
            task_state=task_state,
            state_saver=failing_saver,
            log_storage=log_storage,
            throttle_interval=1  # 每条都保存
        )
        
        # 即使保存失败，也应该继续工作
        logger.log("Test with failing saver")
        assert len(log_storage) == 1  # 日志应该仍然被记录
    
    def test_many_logs_throttling(self):
        """测试大量日志的节流"""
        task_id = "many_logs"
        task_state = {"log": []}
        log_storage = []
        saved = []
        
        logger = TaskLogger(
            task_id=task_id,
            task_state=task_state,
            state_saver=lambda tid: saved.append(tid),
            log_storage=log_storage,
            throttle_interval=10
        )
        
        # 记录100条日志
        for i in range(100):
            logger.log(f"Message {i}")
        
        # 应该保存10次（每10条保存一次）
        assert len(saved) == 10
        assert len(log_storage) == 100
    
    def test_throttle_interval_from_constants(self):
        """测试使用常量配置节流间隔"""
        task_id = "constant_test"
        task_state = {"log": []}
        log_storage = []
        saved = []
        
        logger = TaskLogger(
            task_id=task_id,
            task_state=task_state,
            state_saver=lambda tid: saved.append(tid),
            log_storage=log_storage,
            throttle_interval=LOG_THROTTLE_INTERVAL  # 使用常量
        )
        
        # 记录 LOG_THROTTLE_INTERVAL 条日志
        for i in range(LOG_THROTTLE_INTERVAL):
            logger.log(f"Message {i}")
        
        # 应该保存1次
        assert len(saved) == 1
