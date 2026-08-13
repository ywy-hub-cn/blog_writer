from typing import Optional
import threading

from blog_writer.workflow_service import WorkflowService
from blog_writer.config_manager import ConfigManager

_service: Optional[WorkflowService] = None
_config: Optional[ConfigManager] = None
_lock = threading.RLock()


def get_config() -> ConfigManager:
    """进程内唯一配置实例（与 main / API / WorkflowService 共享）。"""
    global _config
    with _lock:
        if _config is None:
            _config = ConfigManager()
        return _config


def set_config(config: ConfigManager) -> ConfigManager:
    """注入配置实例（测试或启动时统一入口）。会重置已创建的 WorkflowService。"""
    global _config, _service
    with _lock:
        _config = config
        _service = None
        return _config


def get_service() -> WorkflowService:
    global _service
    with _lock:
        cfg = get_config()
        if _service is None:
            _service = WorkflowService(cfg)
        return _service


def reset_service():
    global _service
    with _lock:
        _service = None


def reset_for_tests():
    """测试用：清空配置与服务单例。"""
    global _service, _config
    with _lock:
        _service = None
        _config = None
