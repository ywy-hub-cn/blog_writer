import json
import os
import shutil
import copy
import time
import threading
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Callable, List

logger = logging.getLogger(__name__)

_ENV_LOADED = False


def _ensure_dotenv_loaded() -> None:
    """加载项目根目录 .env（若存在）。不覆盖已有环境变量。"""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)
    else:
        load_dotenv(override=False)


def _apply_env_overrides(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """解析配置中的 *_env 字段（如 api_key_env → 读取 LLM_API_KEY）。"""
    if not isinstance(cfg, dict):
        return cfg
    result = dict(cfg)
    for key, env_name in list(result.items()):
        if not isinstance(key, str) or not key.endswith("_env") or not env_name:
            continue
        field = key[:-4]
        env_value = os.environ.get(str(env_name), "")
        if env_value:
            result[field] = env_value
    return result


DEFAULT_CONFIG = {
    "security": {
        "admin_password_hash": "",
        "admin_password_env": "BLOG_WRITER_ADMIN_PASSWORD",
        "api_token": "",
        "api_token_env": "BLOG_WRITER_API_TOKEN",
        "token_expire_hours": 24,
        "rate_limit_per_minute": 10,
        "allowed_origins": ["http://localhost:8000", "http://127.0.0.1:8000"]
    },
    "database": {
        "backend": "sqlite",
        "sqlite_path": "./instance/blog_writer.db",
        "postgres": {
            "host_env": "DB_HOST",
            "port_env": "DB_PORT",
            "database_env": "DB_NAME",
            "user_env": "DB_USER",
            "password_env": "DB_PASSWORD",
            "host": "localhost",
            "port": 5432,
            "database": "blog_writer",
            "user": "blog_writer",
            "password": "",
            "pool_size": 5,
            "max_overflow": 10
        },
        "mysql": {
            "host_env": "MYSQL_HOST",
            "port_env": "MYSQL_PORT",
            "database_env": "MYSQL_DATABASE",
            "user_env": "MYSQL_USER",
            "password_env": "MYSQL_PASSWORD",
            "host": "localhost",
            "port": 3306,
            "database": "blog_writer",
            "user": "blog_writer",
            "password": ""
        }
    },
    "llm": {
        "default_model": "default",
        "models": {
            "default": {
                "provider": "openai_compatible",
                "base_url_env": "LLM_BASE_URL",
                "api_key_env": "LLM_API_KEY",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "",
                "model": "deepseek-v4-flash",
                "temperature": 0.7,
                "max_tokens": 8192,
                "timeout": 120,
                "thinking": False,
                "retry": {
                    "max_retries": 3,
                    "retry_delay": 2
                }
            }
        }
    },
    "workflow": {
        "max_iterations_per_step": 20,
        "step_timeout_minutes": 10,
        "default_mode": "supervised",
        "instance_root": "./instance",
        "nodes_dir": "./nodes",
        "backup_dir": "./nodes/.backup",
        "max_backup_versions": 10,
        "max_retries_per_step": 3,
        "retry_delay_seconds": 2,
        "max_tokens_per_task": 0,
        # 任务真相源为 DB；本地调试可开 use_file_fallback 镜像 task_state.json
        "enable_breakpoint_resume": True,
        "use_database": True,
        "use_file_fallback": False
    },
    "tools": {
        "web_search": {
            "enabled": True,
            "max_results": 5
        },
        "python_exec": {
            "timeout": 10
        }
    },
    "monitoring": {
        "enable_health_check": True,
        "enable_metrics": False,
        "health_check_interval": 30
    },
    "logging": {
        "format": "text",
        "webhook_url": "",
        "webhook_level": "ERROR"
    },
    "notifications": {
        "channels": {}
    },
    "sso": {
        "enabled": False
    }
}


class ConfigManager:
    """配置管理器 - 支持热更新和原子写入
    
    特性:
    - 自动检测配置文件变化并热加载
    - 原子写入（临时文件 + 重命名）
    - 支持配置变更回调
    - 线程安全
    """
    
    def __init__(self, config_path: str = None, auto_reload: bool = True):
        _ensure_dotenv_loaded()
        if config_path is None:
            env_path = os.environ.get("BLOG_WRITER_CONFIG", "").strip()
            if env_path:
                config_path = env_path
            else:
                # 默认与包内 nodes/registry 同级：blog_writer/config.json
                config_path = Path(__file__).parent / "config.json"
        
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._file_mtime: float = 0
        self._auto_reload = auto_reload
        self._change_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        
        self.load()
    
    def load(self) -> Dict[str, Any]:
        """加载配置（带文件修改时间检测）"""
        with self._lock:
            if self.config_path.exists():
                self._file_mtime = self.config_path.stat().st_mtime
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
            else:
                self._config = copy.deepcopy(DEFAULT_CONFIG)
                self.save()
            return self._config
    
    def reload_if_changed(self) -> bool:
        """检查配置文件是否已更改，如更改则热加载"""
        with self._lock:
            notify = self._reload_if_changed_locked()
        if notify is not None:
            self._fire_notify(*notify)
            logger.info("配置热更新完成")
            return True
        return False

    def _reload_if_changed_locked(self):
        """在已持有 _lock 时检查并加载；若有变更返回 (callbacks, payload)。"""
        if not self.config_path.exists():
            return None

        current_mtime = self.config_path.stat().st_mtime
        if current_mtime == self._file_mtime:
            return None

        logger.info(f"配置文件已更改，重新加载: {self.config_path}")
        self._file_mtime = current_mtime

        with open(self.config_path, 'r', encoding='utf-8') as f:
            new_config = json.load(f)

        self._config = new_config
        return list(self._change_callbacks), copy.deepcopy(new_config)

    def save(self):
        """保存配置（原子写入）"""
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.config_path.with_suffix('.json.tmp')
            try:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(self._config, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.config_path)
                self._file_mtime = self.config_path.stat().st_mtime
            except Exception:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                raise

    def _fire_notify(self, callbacks, payload):
        """在锁外触发回调，避免回调内读写配置死锁/递归阻塞。"""
        for callback in callbacks:
            try:
                callback(payload)
            except Exception as e:
                logger.error(f"配置变更回调执行失败: {e}")

    def on_change(self, callback: Callable[[Dict[str, Any]], None]):
        """注册配置变更回调"""
        with self._lock:
            self._change_callbacks.append(callback)

    def off_change(self, callback: Callable[[Dict[str, Any]], None]):
        """移除配置变更回调"""
        with self._lock:
            self._change_callbacks = [
                cb for cb in self._change_callbacks if cb != callback
            ]
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持点号分隔的嵌套键 + 环境变量覆盖）
        
        环境变量规则：如果配置项有对应的 _env 后缀键（如 api_key_env），
        且该环境变量存在且非空，则优先使用环境变量的值。
        """
        notify = None
        with self._lock:
            if self._auto_reload:
                notify = self._reload_if_changed_locked()
            
            keys = key.split(".")
            value = self._config
            found = True
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k)
                else:
                    found = False
                    break
                if value is None:
                    found = False
                    break
            
            if not found or value is None:
                result = default
            else:
                # 环境变量优先：只要存在 *_env 配置且环境变量非空，即覆盖配置文件值
                parent = self._config
                for k in keys[:-1]:
                    if isinstance(parent, dict):
                        parent = parent.get(k, {})
                    else:
                        parent = {}
                        break
                if isinstance(parent, dict):
                    env_key = f"{keys[-1]}_env"
                    env_name = parent.get(env_key, "")
                    if env_name:
                        env_value = os.environ.get(str(env_name), "")
                        if env_value:
                            result = env_value
                        else:
                            result = value
                    else:
                        result = value
                else:
                    result = value
        if notify is not None:
            self._fire_notify(*notify)
            logger.info("配置热更新完成")
        return result
    
    def set(self, key: str, value: Any):
        """设置配置值（支持点号分隔的嵌套键）"""
        with self._lock:
            keys = key.split(".")
            config = self._config
            for k in keys[:-1]:
                if k not in config or not isinstance(config[k], dict):
                    config[k] = {}
                config = config[k]
            config[keys[-1]] = value
            self.save()
            callbacks = list(self._change_callbacks)
            payload = copy.deepcopy(self._config)
        self._fire_notify(callbacks, payload)
    
    def update(self, updates: Dict[str, Any]):
        """批量更新配置（深度合并）"""
        with self._lock:
            self._config = self._deep_merge(self._config, updates)
            self.save()
            callbacks = list(self._change_callbacks)
            payload = copy.deepcopy(self._config)
        self._fire_notify(callbacks, payload)
    
    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """深度合并两个字典，override 中的值会覆盖 base 中的对应值"""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result
    
    def get_llm_config(self, model_name: Optional[str] = None) -> Dict[str, Any]:
        """获取LLM配置（环境变量优先于 config.json 中的明文值）"""
        _ensure_dotenv_loaded()
        notify = None
        with self._lock:
            if self._auto_reload:
                notify = self._reload_if_changed_locked()
            
            llm_cfg = self._config.get("llm", {})
            default_model = llm_cfg.get("default_model", "default")
            target_model = model_name or default_model
            
            models = llm_cfg.get("models", {})
            if target_model in models:
                result = copy.deepcopy(models[target_model])
            elif models:
                result = copy.deepcopy(next(iter(models.values())))
            else:
                result = {
                    "provider": "openai_compatible",
                    "base_url_env": "LLM_BASE_URL",
                    "api_key_env": "LLM_API_KEY",
                    "base_url": llm_cfg.get("base_url", "https://api.deepseek.com/v1"),
                    "api_key": llm_cfg.get("api_key", ""),
                    "model": llm_cfg.get("model", "deepseek-v4-flash"),
                    "temperature": llm_cfg.get("temperature", 0.7),
                    "max_tokens": llm_cfg.get("max_tokens", 8192),
                    "timeout": llm_cfg.get("timeout", 120),
                    "retry": llm_cfg.get("retry", {"max_retries": 3, "retry_delay": 2})
                }
        if notify is not None:
            self._fire_notify(*notify)
            logger.info("配置热更新完成")
        return _apply_env_overrides(result)

    def get_workflow_config(self) -> Dict[str, Any]:
        """获取工作流配置"""
        notify = None
        with self._lock:
            if self._auto_reload:
                notify = self._reload_if_changed_locked()
            result = copy.deepcopy(self._config.get("workflow", {}))
        if notify is not None:
            self._fire_notify(*notify)
            logger.info("配置热更新完成")
        return result

    def get_all(self) -> Dict[str, Any]:
        """获取完整配置"""
        notify = None
        with self._lock:
            if self._auto_reload:
                notify = self._reload_if_changed_locked()
            result = copy.deepcopy(self._config)
        if notify is not None:
            self._fire_notify(*notify)
            logger.info("配置热更新完成")
        return result

    def resolve_path(self, path: str) -> Path:
        """解析相对路径为绝对路径"""
        p = Path(path)
        if not p.is_absolute():
            return self.config_path.parent / p
        return p


class NodeBackupManager:
    def __init__(self, nodes_dir: str, backup_dir: str, max_versions: int = 10):
        self.nodes_dir = Path(nodes_dir)
        self.backup_dir = Path(backup_dir)
        self.max_versions = max_versions

    @staticmethod
    def _validate_node_id(node_id: str) -> str:
        """校验 node_id 安全性，防止路径穿越。"""
        if not node_id:
            raise ValueError("node_id 不能为空")
        if '/' in node_id or '\\' in node_id or '..' in node_id:
            raise ValueError(f"node_id 包含不安全字符: {node_id}")
        return node_id

    @staticmethod
    def _validate_version(version: str) -> str:
        """校验 version 安全性，防止路径穿越。"""
        if not version:
            raise ValueError("version 不能为空")
        if '/' in version or '\\' in version or '..' in version:
            raise ValueError(f"version 包含不安全字符: {version}")
        return version

    def backup_node(self, node_id: str):
        self._validate_node_id(node_id)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        node_file = None
        for f in self.nodes_dir.glob(f"{node_id}*.json"):
            node_file = f
            break
        
        if not node_file and not node_id.startswith("S"):
            for f in self.nodes_dir.glob(f"S*{node_id}*.json"):
                node_file = f
                break
        
        if not node_file:
            return None
        
        import re
        dirs = [d for d in os.listdir(self.backup_dir) if d.startswith(node_id)]
        max_ver = 0
        for d in dirs:
            m = re.search(r"_v(\d+)$", d)
            if m:
                try:
                    max_ver = max(max_ver, int(m.group(1)))
                except ValueError:
                    pass
        version = max_ver + 1
        version_dir = self.backup_dir / f"{node_id}_v{version}"
        version_dir.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(node_file, version_dir / node_file.name)
        
        self._cleanup_old_versions(node_id)
        
        return str(version_dir)

    def _cleanup_old_versions(self, node_id: str):
        import re as _re
        versions = sorted(
            [d for d in self.backup_dir.iterdir() if d.is_dir() and d.name.startswith(f"{node_id}_v")],
            key=lambda x: int(_re.search(r'_v(\d+)$', x.name).group(1)) if _re.search(r'_v(\d+)$', x.name) else 0
        )
        
        while len(versions) > self.max_versions:
            oldest = versions.pop(0)
            shutil.rmtree(oldest, ignore_errors=True)

    def list_backups(self, node_id: str = None) -> list:
        if not self.backup_dir.exists():
            return []
        
        backups = []
        for d in sorted(self.backup_dir.iterdir()):
            if d.is_dir():
                if node_id is None or d.name.startswith(node_id):
                    files = list(d.glob("*.json"))
                    backups.append({
                        "version": d.name,
                        "files": [f.name for f in files],
                        "path": str(d)
                    })
        return backups

    def restore_backup(self, version: str) -> bool:
        self._validate_version(version)
        version_dir = self.backup_dir / version
        if not version_dir.exists():
            return False
        
        for f in version_dir.glob("*.json"):
            shutil.copy2(f, self.nodes_dir / f.name)
        
        return True
