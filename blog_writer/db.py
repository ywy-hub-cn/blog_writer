"""
blog_writer/db.py - SQLite 数据库管理器

提供任务状态持久化、日志存储、配置管理等功能。
支持 WAL 模式提升并发性能，自动迁移 schema。
"""
import json
import sqlite3
import hashlib
import threading
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

CREATE_TABLES_SQL = {
    "schema_version": """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """,
    "tasks": """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            mode TEXT NOT NULL DEFAULT 'auto',
            current_step INTEGER NOT NULL DEFAULT 0,
            total_steps INTEGER NOT NULL DEFAULT 0,
            start_time TEXT,
            end_time TEXT,
            brand_path TEXT,
            keywords TEXT,
            user_note TEXT,
            brand_site_url TEXT,
            step_files TEXT,
            completed_steps TEXT,
            results TEXT,
            outputs TEXT,
            retry_counts TEXT,
            review_node TEXT,
            review_node_name TEXT,
            extra TEXT,
            updated_at TEXT NOT NULL
        )
    """,
    "task_logs": """
        CREATE TABLE IF NOT EXISTS task_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            log_entry TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        )
    """,
    "node_definitions": """
        CREATE TABLE IF NOT EXISTS node_definitions (
            node_id TEXT PRIMARY KEY,
            name TEXT,
            exec_type TEXT NOT NULL,
            seq INTEGER DEFAULT 0,
            definition TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "audit_log": """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            event_source TEXT NOT NULL,
            details TEXT,
            actor TEXT,
            ip_address TEXT,
            created_at TEXT NOT NULL
        )
    """,
    "rate_limit_audit": """
        CREATE TABLE IF NOT EXISTS rate_limit_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            request_count INTEGER DEFAULT 0,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "brands": """
        CREATE TABLE IF NOT EXISTS brands (
            brand_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            inner_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
}

CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_task_logs_task_id ON task_logs(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
]


class DatabaseManager:
    """SQLite 数据库管理器 - 单例模式，线程安全"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path: str = None):
        with DatabaseManager._lock:
            if self._initialized:
                return
            self._initialized = True
        
        if db_path is None:
            # 与 create_database_from_config 默认一致：项目根 instance/
            base_dir = Path(__file__).parent.parent
            db_dir = base_dir / "instance"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(db_dir / "blog_writer.db")

        else:
            db_file = Path(db_path)
            if not db_file.parent.exists():
                db_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.db_path = db_path
        self._local = threading.local()
        # 跟踪所有线程的连接，以便 close_all() 能全部关闭
        self._all_conns: Dict[int, sqlite3.Connection] = {}
        self._conns_lock = threading.Lock()
        self._init_connection()
        self._init_schema()
    
    def _init_connection(self):
        if not hasattr(self._local, 'conn'):
            conn = sqlite3.connect(
                self.db_path,
                timeout=30,
                isolation_level=None
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
            # 注册到全局跟踪表
            with self._conns_lock:
                self._all_conns[threading.get_ident()] = conn
        return self._local.conn
    
    @property
    def conn(self) -> sqlite3.Connection:
        return self._init_connection()
    
    def _init_schema(self):
        cursor = self.conn.cursor()
        for name, sql in CREATE_TABLES_SQL.items():
            cursor.execute(sql)
        
        for sql in CREATE_INDEXES_SQL:
            cursor.execute(sql)

        # 迁移：为旧数据库添加新字段
        self._migrate_schema(cursor)
        
        cursor.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, datetime.now().isoformat())
        )
        logger.info(f"Database initialized: {self.db_path} (schema v{SCHEMA_VERSION})")

    def _migrate_schema(self, cursor):
        """轻量迁移：添加新列而不破坏现有数据"""
        migrations = [
            # v2: 添加 user_note 和 brand_site_url
            ("PRAGMA table_info(tasks)", "user_note", "ALTER TABLE tasks ADD COLUMN user_note TEXT DEFAULT ''"),
            ("PRAGMA table_info(tasks)", "brand_site_url", "ALTER TABLE tasks ADD COLUMN brand_site_url TEXT DEFAULT ''"),
        ]
        for check_sql, col_name, alter_sql in migrations:
            try:
                cursor.execute(check_sql)
                existing_cols = [row[1] for row in cursor.fetchall()]
                if col_name not in existing_cols:
                    cursor.execute(alter_sql)
                    logger.info(f"Migrated: added column '{col_name}' to tasks table")
            except Exception as e:
                logger.debug(f"Migration skipped for {col_name}: {e}")
    
    def close(self):
        """关闭当前线程的数据库连接"""
        thread_id = threading.get_ident()
        if hasattr(self._local, 'conn'):
            try:
                self._local.conn.close()
            except Exception:
                pass
            del self._local.conn
        with self._conns_lock:
            self._all_conns.pop(thread_id, None)

    def close_all(self):
        """关闭所有线程的数据库连接（用于程序退出或单例重置时）"""
        with self._conns_lock:
            conns = list(self._all_conns.values())
            self._all_conns.clear()
        for conn in conns:
            try:
                conn.close()
            except Exception:
                pass
        # 清理当前线程的 local 引用
        if hasattr(self._local, 'conn'):
            try:
                self._local.conn.close()
            except Exception:
                pass
            del self._local.conn

    def __del__(self):
        self.close_all()


# ---------------------------------------------------------------------------
# PostgreSQL / MySQL 支持
# ---------------------------------------------------------------------------

# DDL: 与 SQLite 版本字段对齐，仅翻译 SQLite 特有语法
_POSTGRES_CREATE_TABLES_SQL = [
    """CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'pending',
        mode TEXT NOT NULL DEFAULT 'auto',
        current_step INTEGER NOT NULL DEFAULT 0,
        total_steps INTEGER NOT NULL DEFAULT 0,
        start_time TEXT,
        end_time TEXT,
        brand_path TEXT,
        keywords TEXT,
        user_note TEXT,
        brand_site_url TEXT,
        step_files TEXT,
        completed_steps TEXT,
        results TEXT,
        outputs TEXT,
        retry_counts TEXT,
        review_node TEXT,
        review_node_name TEXT,
        extra TEXT,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS task_logs (
        id SERIAL PRIMARY KEY,
        task_id TEXT NOT NULL,
        log_entry TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS node_definitions (
        node_id TEXT PRIMARY KEY,
        name TEXT,
        exec_type TEXT NOT NULL,
        seq INTEGER DEFAULT 0,
        definition TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id SERIAL PRIMARY KEY,
        event_type TEXT NOT NULL,
        event_source TEXT NOT NULL,
        details TEXT,
        actor TEXT,
        ip_address TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS rate_limit_audit (
        id SERIAL PRIMARY KEY,
        client_id TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        request_count INTEGER DEFAULT 0,
        window_start TEXT NOT NULL,
        window_end TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS brands (
        brand_id VARCHAR(64) PRIMARY KEY,
        display_name TEXT NOT NULL,
        inner_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_task_logs_task_id ON task_logs(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
]

_MYSQL_CREATE_TABLES_SQL = [
    """CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS tasks (
        task_id VARCHAR(255) PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'pending',
        mode TEXT NOT NULL DEFAULT 'auto',
        current_step INTEGER NOT NULL DEFAULT 0,
        total_steps INTEGER NOT NULL DEFAULT 0,
        start_time TEXT,
        end_time TEXT,
        brand_path TEXT,
        keywords TEXT,
        user_note TEXT,
        brand_site_url TEXT,
        step_files LONGTEXT,
        completed_steps LONGTEXT,
        results LONGTEXT,
        outputs LONGTEXT,
        retry_counts LONGTEXT,
        review_node TEXT,
        review_node_name TEXT,
        extra LONGTEXT,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS task_logs (
        id INTEGER AUTO_INCREMENT PRIMARY KEY,
        task_id VARCHAR(255) NOT NULL,
        log_entry LONGTEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS node_definitions (
        node_id VARCHAR(255) PRIMARY KEY,
        name TEXT,
        exec_type TEXT NOT NULL,
        seq INTEGER DEFAULT 0,
        definition LONGTEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER AUTO_INCREMENT PRIMARY KEY,
        event_type TEXT NOT NULL,
        event_source TEXT NOT NULL,
        details LONGTEXT,
        actor TEXT,
        ip_address TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS rate_limit_audit (
        id INTEGER AUTO_INCREMENT PRIMARY KEY,
        client_id TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        request_count INTEGER DEFAULT 0,
        window_start TEXT NOT NULL,
        window_end TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS brands (
        brand_id VARCHAR(64) PRIMARY KEY,
        display_name TEXT NOT NULL,
        inner_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX idx_task_logs_task_id ON task_logs(task_id)",
    "CREATE INDEX idx_audit_log_event_type ON audit_log(event_type)",
    "CREATE INDEX idx_audit_log_created_at ON audit_log(created_at)",
    "CREATE INDEX idx_tasks_status ON tasks(status)",
]

# 已知主键映射，用于将 INSERT OR REPLACE 翻译为各后端的 upsert 语法
_UPSERT_PK = {
    "tasks": "task_id",
    "node_definitions": "node_id",
    "schema_version": "version",
    "brands": "brand_id",
}

# tasks 表的非主键列（用于生成 ON CONFLICT DO UPDATE / ON DUPLICATE KEY UPDATE）
_UPSERT_COLUMNS = {
    "tasks": [
        "status", "mode", "current_step", "total_steps", "start_time", "end_time",
        "brand_path", "keywords", "user_note", "brand_site_url", "step_files",
        "completed_steps", "results", "outputs", "retry_counts", "review_node",
        "review_node_name", "extra", "updated_at",
    ],
    "node_definitions": ["name", "exec_type", "seq", "definition", "updated_at"],
    "brands": ["display_name", "inner_path", "updated_at"],
}


def _replace_sql_placeholders(sql: str) -> str:
    """将 ? 占位符替换为 %s，跳过单/双引号字符串字面量内的问号。"""
    out = []
    i = 0
    n = len(sql)
    in_single = False
    in_double = False
    while i < n:
        ch = sql[i]
        if ch == "'" and not in_double:
            # 处理 SQL 转义 ''
            if in_single and i + 1 < n and sql[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_single = not in_single
            out.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
            i += 1
            continue
        if ch == "?" and not in_single and not in_double:
            out.append("%s")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class ConnectionAdapter:
    """适配 PostgreSQL/MySQL 连接，提供与 sqlite3.Connection 兼容的接口。

    sqlite3.Connection.execute(sql, params) 会返回 cursor，
    psycopg2 / pymysql 需要先 cursor() 再 execute。
    本适配器统一为 execute(sql, params) → cursor，并翻译 SQLite 特有 SQL。
    """

    def __init__(self, raw_conn, backend: str):
        self._raw_conn = raw_conn
        self._backend = backend  # "postgres" or "mysql"

    @property
    def raw(self):
        return self._raw_conn

    def execute(self, sql: str, params=None):
        translated = self._translate_sql(sql)
        # postgres 需要指定 cursor_factory 以获得 dict-like 行
        cursor_factory = getattr(self._raw_conn, "_blog_writer_cursor_factory", None)
        if cursor_factory is not None:
            cursor = self._raw_conn.cursor(cursor_factory=cursor_factory)
        else:
            cursor = self._raw_conn.cursor()
        cursor.execute(translated, params or ())
        return cursor

    def close(self):
        try:
            self._raw_conn.close()
        except Exception:
            pass

    def _translate_sql(self, sql: str) -> str:
        # 占位符：仅替换 SQL 中非字符串字面量的 ?
        translated = _replace_sql_placeholders(sql)

        # 2. INSERT OR IGNORE
        if "INSERT OR IGNORE INTO" in translated:
            if self._backend == "postgres":
                # INSERT INTO ... ON CONFLICT DO NOTHING
                translated = translated.replace("INSERT OR IGNORE INTO", "INSERT INTO")
                translated = translated.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
            else:  # mysql
                translated = translated.replace("INSERT OR IGNORE INTO", "INSERT IGNORE INTO")

        # 3. INSERT OR REPLACE（需要按表生成 upsert 子句）
        if "INSERT OR REPLACE INTO" in translated:
            for table, pk in _UPSERT_PK.items():
                marker = f"INSERT OR REPLACE INTO {table}"
                if marker in translated:
                    translated = translated.replace(marker, f"INSERT INTO {table}")
                    if "ON CONFLICT" in translated or "ON DUPLICATE" in translated:
                        break
                    cols = _UPSERT_COLUMNS.get(table, [])
                    if self._backend == "postgres":
                        set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols)
                        translated = translated.rstrip().rstrip(";") + \
                            f" ON CONFLICT ({pk}) DO UPDATE SET {set_clause}"
                    else:  # mysql
                        # MySQL 8.0.20+ 废弃 VALUES() 函数引用，改用别名语法
                        set_clause = ", ".join(f"{c}=new_row.{c}" for c in cols)
                        translated = translated.rstrip().rstrip(";") + \
                            f" AS new_row ON DUPLICATE KEY UPDATE {set_clause}"
                    break

        return translated


class SQLDatabaseManager:
    """PostgreSQL/MySQL 数据库管理器 - 单例模式，线程安全。

    提供与 DatabaseManager 相同的接口（conn 属性、close 方法），
    内部通过 ConnectionAdapter 翻译 SQLite 方言 SQL。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, backend: str = "postgres", **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, backend: str = "postgres", **kwargs):
        with SQLDatabaseManager._lock:
            if self._initialized:
                return
            self._initialized = True

            self.backend = backend
            self._connection_kwargs = kwargs
            self._local = threading.local()
            self._all_conns: Dict[int, Any] = {}
            self._conns_lock = threading.Lock()
            self.db_path = f"{backend}://{kwargs.get('host', 'localhost')}:{kwargs.get('port', '')}/{kwargs.get('database', '')}"
            self._init_connection()
            self._init_schema()

    def _init_connection(self):
        if not hasattr(self._local, 'conn'):
            raw_conn = create_connection(self.backend, **self._connection_kwargs)
            self._local.conn = ConnectionAdapter(raw_conn, self.backend)
            with self._conns_lock:
                self._all_conns[threading.get_ident()] = self._local.conn
        return self._local.conn

    @property
    def conn(self):
        return self._init_connection()

    def _init_schema(self):
        adapter = self.conn
        ddl = _POSTGRES_CREATE_TABLES_SQL if self.backend == "postgres" else _MYSQL_CREATE_TABLES_SQL
        for sql_stmt in ddl:
            try:
                adapter.execute(sql_stmt)
            except Exception as e:
                # 索引已存在等非致命错误，记录后继续
                logger.debug(f"DDL skipped: {e}")

        # 为 PostgreSQL/MySQL 旧库执行轻量迁移
        self._migrate_schema(adapter)

        # 记录 schema 版本（使用适配器翻译 INSERT OR IGNORE）
        adapter.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, datetime.now().isoformat())
        )
        logger.info(f"Database initialized: {self.db_path} (backend={self.backend}, schema v{SCHEMA_VERSION})")

    def _migrate_schema(self, adapter):
        """PostgreSQL/MySQL 轻量迁移：添加新列"""
        if self.backend == "postgres":
            migrations = [
                ("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS user_note TEXT DEFAULT ''",),
                ("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS brand_site_url TEXT DEFAULT ''",),
            ]
        else:  # mysql
            migrations = [
                ("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS user_note TEXT DEFAULT ''",),
                ("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS brand_site_url TEXT DEFAULT ''",),
                # 历史 DDL 曾用 TEXT 作 FK，与 tasks.task_id VARCHAR(255) 不兼容
                ("ALTER TABLE task_logs MODIFY COLUMN task_id VARCHAR(255) NOT NULL",),
            ]
        for (alter_sql,) in migrations:
            try:
                adapter.execute(alter_sql)
            except Exception as e:
                logger.debug(f"Migration skipped: {e}")

    def close(self):
        if hasattr(self._local, 'conn'):
            self._local.conn.close()
            del self._local.conn

    def close_all(self):
        """关闭所有线程的数据库连接（用于程序退出或单例重置时）"""
        with self._conns_lock:
            conns = list(self._all_conns.values())
            self._all_conns.clear()
        for conn in conns:
            try:
                conn.close()
            except Exception:
                pass
        if hasattr(self._local, 'conn'):
            try:
                self._local.conn.close()
            except Exception:
                pass
            if hasattr(self._local, 'conn'):
                del self._local.conn

    def __del__(self):
        self.close()


class TaskRepository:
    """任务数据访问层"""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def save_task(self, task: Dict[str, Any]):
        now = datetime.now().isoformat()
        conn = self.db.conn
        # 使用 UPSERT 而非 INSERT OR REPLACE：
        # SQLite 的 OR REPLACE 会先 DELETE 父行，触发 task_logs ON DELETE CASCADE，导致日志被清空。
        backend = getattr(self.db, "backend", "sqlite") or "sqlite"
        values = (
            task.get("task_id", ""),
            task.get("status", "pending"),
            task.get("mode", "auto"),
            task.get("current_step", 0),
            task.get("total_steps", 0),
            task.get("start_time", ""),
            task.get("end_time", ""),
            task.get("brand_path", ""),
            task.get("keywords", ""),
            task.get("user_note", ""),
            task.get("brand_site_url", ""),
            json.dumps(task.get("step_files", []), ensure_ascii=False),
            json.dumps(task.get("completed_steps", []), ensure_ascii=False),
            json.dumps(task.get("results", []), ensure_ascii=False),
            json.dumps(task.get("outputs", {}), ensure_ascii=False),
            json.dumps(task.get("retry_counts", {}), ensure_ascii=False),
            task.get("review_node", ""),
            task.get("review_node_name", ""),
            json.dumps(task.get("extra", {}), ensure_ascii=False),
            now,
        )
        columns = (
            "task_id, status, mode, current_step, total_steps, start_time, end_time, "
            "brand_path, keywords, user_note, brand_site_url, step_files, completed_steps, "
            "results, outputs, retry_counts, review_node, review_node_name, extra, updated_at"
        )
        placeholders = ", ".join(["?"] * 20)
        update_cols = [
            "status", "mode", "current_step", "total_steps", "start_time", "end_time",
            "brand_path", "keywords", "user_note", "brand_site_url", "step_files",
            "completed_steps", "results", "outputs", "retry_counts", "review_node",
            "review_node_name", "extra", "updated_at",
        ]
        if backend == "mysql":
            # MySQL 8.0.20+ 废弃 VALUES() 函数引用，改用别名语法
            set_clause = ", ".join(f"{c}=new_row.{c}" for c in update_cols)
            sql = (
                f"INSERT INTO tasks ({columns}) VALUES ({placeholders}) "
                f"AS new_row ON DUPLICATE KEY UPDATE {set_clause}"
            )
        else:
            # sqlite / postgres
            set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
            sql = (
                f"INSERT INTO tasks ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(task_id) DO UPDATE SET {set_clause}"
            )
        conn.execute(sql, values)
    
    def load_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        conn = self.db.conn
        row = conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        
        return self._row_to_dict(row)
    
    def list_tasks(
        self,
        status: str = None,
        statuses: List[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        conn = self.db.conn
        if statuses:
            clean = [s for s in statuses if s]
            if not clean:
                return []
            placeholders = ",".join("?" * len(clean))
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE status IN ({placeholders}) "
                "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (*clean, limit, offset),
            ).fetchall()
        elif status:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]
    
    def delete_task(self, task_id: str):
        conn = self.db.conn
        # 使用显式事务保证原子性
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    
    def _row_to_dict(self, row) -> Dict[str, Any]:
        result = {}
        for key in row.keys():
            val = row[key]
            if key in ('step_files', 'completed_steps', 'results', 'outputs', 'retry_counts', 'extra'):
                if val:
                    try:
                        result[key] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        result[key] = [] if key in ('step_files', 'completed_steps', 'results') else {}
                else:
                    result[key] = [] if key in ('step_files', 'completed_steps', 'results') else {}
            else:
                result[key] = val
        return result


class TaskLogRepository:
    """任务日志数据访问层"""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def add_log(self, task_id: str, log_entry: str):
        now = datetime.now().isoformat()
        conn = self.db.conn
        conn.execute(
            "INSERT INTO task_logs (task_id, log_entry, created_at) VALUES (?, ?, ?)",
            (task_id, log_entry, now)
        )
    
    def get_logs(self, task_id: str, limit: int = 500, offset: int = 0) -> List[Dict[str, Any]]:
        conn = self.db.conn
        rows = conn.execute(
            "SELECT * FROM task_logs WHERE task_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?",
            (task_id, limit, offset)
        ).fetchall()
        return [dict(r) for r in rows]
    
    def delete_logs(self, task_id: str):
        conn = self.db.conn
        conn.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
    
    def count_logs(self, task_id: str) -> int:
        conn = self.db.conn
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM task_logs WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row["cnt"] if row else 0


class NodeDefinitionRepository:
    """节点定义数据访问层"""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def save_node(self, node_id: str, definition: Dict[str, Any]):
        now = datetime.now().isoformat()
        conn = self.db.conn
        conn.execute("""
            INSERT OR REPLACE INTO node_definitions 
            (node_id, name, exec_type, seq, definition, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            node_id,
            definition.get("name", ""),
            definition.get("exec_type", definition.get("kind", "pure_code")),
            definition.get("seq", 0),
            json.dumps(definition, ensure_ascii=False),
            now,
        ))
    
    def load_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        conn = self.db.conn
        row = conn.execute(
            "SELECT * FROM node_definitions WHERE node_id = ?", (node_id,)
        ).fetchone()
        if not row:
            return None
        return json.loads(row["definition"]) if row["definition"] else {}
    
    def list_nodes(self) -> List[Dict[str, Any]]:
        conn = self.db.conn
        rows = conn.execute(
            "SELECT * FROM node_definitions ORDER BY seq ASC, node_id ASC"
        ).fetchall()
        return [{"node_id": r["node_id"], "name": r["name"], "exec_type": r["exec_type"], "seq": r["seq"]} for r in rows]
    
    def delete_node(self, node_id: str):
        conn = self.db.conn
        conn.execute("DELETE FROM node_definitions WHERE node_id = ?", (node_id,))


class AuditLogRepository:
    """审计日志数据访问层"""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def log_event(self, event_type: str, event_source: str, details: str = None, 
                  actor: str = None, ip_address: str = None):
        now = datetime.now().isoformat()
        conn = self.db.conn
        conn.execute("""
            INSERT INTO audit_log (event_type, event_source, details, actor, ip_address, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (event_type, event_source, details, actor, ip_address, now))

    def log_rate_limit(
        self,
        client_id: str,
        endpoint: str,
        violation_type: str,
        request_count: int = 0,
    ) -> None:
        """写入 rate_limit_audit 表（限流专用审计）。"""
        now = datetime.now().isoformat()
        conn = self.db.conn
        try:
            conn.execute(
                """
                INSERT INTO rate_limit_audit
                (client_id, endpoint, request_count, window_start, window_end, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id or "",
                    f"{endpoint or ''}|{violation_type or ''}",
                    int(request_count or 0),
                    now,
                    now,
                    now,
                ),
            )
        except Exception:
            # 表结构差异时回退到通用审计
            self.log_event(
                event_type="rate_limit_exceeded",
                event_source=endpoint,
                details=f"violation_type={violation_type}",
                actor=client_id,
            )
    
    def query_events(self, event_type: str = None, start_time: str = None, 
                     end_time: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self.db.conn
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if start_time:
            query += " AND created_at >= ?"
            params.append(start_time)
        if end_time:
            query += " AND created_at <= ?"
            params.append(end_time)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


"""
blog_writer/db.py - 多后端数据库管理器

提供任务状态持久化、日志存储、配置管理等功能。
支持 SQLite (默认)、PostgreSQL、MySQL 三种后端。

企业级部署：优先使用 PostgreSQL/MySQL，通过配置或环境变量切换。
本地开发：使用 SQLite 即可，无需外部数据库。
"""
import os
from enum import Enum


class DatabaseBackend(str, Enum):
    """数据库后端类型"""
    SQLITE = "sqlite"
    POSTGRESQL = "postgres"
    MYSQL = "mysql"


def create_connection(backend: str, **kwargs) -> Any:
    """创建数据库连接（工厂函数）
    
    Args:
        backend: 数据库后端类型 (sqlite/postgres/mysql)
        **kwargs: 连接参数
            - sqlite: db_path
            - postgres: host, port, database, user, password
            - mysql: host, port, database, user, password
    
    Returns:
        数据库连接对象
    """
    backend = backend.lower()
    
    if backend == DatabaseBackend.SQLITE:
        db_path = kwargs.get("db_path", ":memory:")
        conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn
    
    elif backend == DatabaseBackend.POSTGRESQL:
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise ImportError(
                "PostgreSQL backend requires psycopg2. "
                "Install with: pip install psycopg2-binary"
            )

        conn = psycopg2.connect(
            host=kwargs.get("host", "localhost"),
            port=kwargs.get("port", 5432),
            database=kwargs.get("database", "blog_writer"),
            user=kwargs.get("user", "blog_writer"),
            password=kwargs.get("password", ""),
        )
        conn.autocommit = True
        # 标记默认游标工厂，供 ConnectionAdapter 使用
        conn._blog_writer_cursor_factory = psycopg2.extras.RealDictCursor
        return conn

    elif backend == DatabaseBackend.MYSQL:
        try:
            import pymysql
            import pymysql.cursors
        except ImportError:
            raise ImportError(
                "MySQL backend requires pymysql. "
                "Install with: pip install pymysql"
            )

        conn = pymysql.connect(
            host=kwargs.get("host", "localhost"),
            port=kwargs.get("port", 3306),
            database=kwargs.get("database", "blog_writer"),
            user=kwargs.get("user", "blog_writer"),
            password=kwargs.get("password", ""),
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )
        return conn
    
    else:
        raise ValueError(f"Unknown database backend: {backend}. Use: sqlite, postgres, mysql")


def get_backend_from_config(config: Dict[str, Any] = None) -> Dict[str, Any]:
    """从配置和环境变量中解析数据库后端参数
    
    优先级：环境变量 > config > 默认值
    
    Returns:
        dict with keys: backend, connection_kwargs
    """
    if config is None:
        config = {}
    
    db_config = config.get("database", {})
    backend = os.environ.get("DB_BACKEND", "").strip() or db_config.get("backend", "sqlite")
    if backend == "postgresql":
        backend = "postgres"
    
    # 环境变量覆盖
    env_mapping = {
        "postgres": {
            "host": ("DB_HOST", "localhost"),
            "port": ("DB_PORT", 5432),
            "database": ("DB_NAME", "blog_writer"),
            "user": ("DB_USER", "blog_writer"),
            "password": ("DB_PASSWORD", ""),
        },
        "mysql": {
            "host": ("MYSQL_HOST", "localhost"),
            "port": ("MYSQL_PORT", 3306),
            "database": ("MYSQL_DATABASE", "blog_writer"),
            "user": ("MYSQL_USER", "blog_writer"),
            "password": ("MYSQL_PASSWORD", ""),
        },
    }
    
    connection_kwargs = {}
    
    if backend == "sqlite":
        connection_kwargs["db_path"] = db_config.get("sqlite_path", "./instance/blog_writer.db")
    elif backend in env_mapping:
        mapping = env_mapping[backend]
        backend_config = db_config.get(backend, {})
        for param, (env_var, default) in mapping.items():
            env_val = os.environ.get(env_var, "")
            config_val = backend_config.get(param, "")
            if env_val:
                connection_kwargs[param] = env_val
            elif config_val:
                connection_kwargs[param] = config_val
            else:
                connection_kwargs[param] = default
    
    return {"backend": backend, "connection_kwargs": connection_kwargs}


def get_database(db_path: str = None) -> DatabaseManager:
    """获取数据库单例（兼容旧接口，默认使用 SQLite）"""
    return DatabaseManager(db_path)


def create_database_manager(config: Dict[str, Any] = None):
    """根据配置创建数据库管理器（支持多后端）

    当 backend=sqlite 时，返回标准 DatabaseManager。
    当 backend=postgres/mysql 时，返回 SQLDatabaseManager（通过 ConnectionAdapter 翻译方言）。
    """
    backend_info = get_backend_from_config(config)
    backend = backend_info["backend"]
    kwargs = backend_info["connection_kwargs"]

    # 重置单例以支持不同后端（在类锁保护下，避免多线程竞态）
    # 先关闭旧实例的所有连接，防止 ResourceWarning: unclosed database
    with DatabaseManager._lock:
        if DatabaseManager._instance is not None:
            try:
                DatabaseManager._instance.close_all()
            except Exception:
                pass
            DatabaseManager._instance = None
    with SQLDatabaseManager._lock:
        if SQLDatabaseManager._instance is not None:
            try:
                SQLDatabaseManager._instance.close_all()
            except Exception:
                pass
            SQLDatabaseManager._instance = None

    if backend == "sqlite":
        db_path = kwargs.get("db_path")
        if db_path:
            return DatabaseManager(db_path=db_path)
        return DatabaseManager()

    # PostgreSQL/MySQL: 使用 SQLDatabaseManager 真正连接到目标数据库
    # （此前实现静默回退到 :memory: SQLite，会导致数据全部丢失）
    logger.info(f"Creating {backend} database manager with kwargs: { {k: v for k, v in kwargs.items() if k != 'password'} }")
    return SQLDatabaseManager(backend=backend, **kwargs)


class BrandRepository:
    """品牌数据访问层"""

    def __init__(self, db=None):
        self.db = db or DatabaseManager()

    def save_brand(self, brand_id: str, display_name: str, inner_path: str):
        now = datetime.now().isoformat()
        conn = self.db.conn
        conn.execute("""
            INSERT OR REPLACE INTO brands (brand_id, display_name, inner_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (brand_id, display_name, inner_path, now, now))

    def list_brands(self) -> List[Dict[str, Any]]:
        conn = self.db.conn
        rows = conn.execute(
            "SELECT brand_id, display_name, inner_path, created_at, updated_at FROM brands ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_brand(self, brand_id: str) -> Optional[Dict[str, Any]]:
        conn = self.db.conn
        row = conn.execute(
            "SELECT * FROM brands WHERE brand_id = ?", (brand_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_brand(self, brand_id: str) -> bool:
        """删除品牌记录。

        Returns:
            True 如果删除了记录，False 如果记录不存在
        """
        conn = self.db.conn
        cursor = conn.execute("DELETE FROM brands WHERE brand_id = ?", (brand_id,))
        return cursor.rowcount > 0
