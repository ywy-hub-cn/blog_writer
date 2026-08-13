"""
blog_writer/constants.py - 集中管理魔法数字和配置常量

所有硬编码的数字和限制都应在此处定义，便于维护和发现。
"""

# === 日志系统常量 ===
# 日志节流：每 N 条日志自动保存一次状态
LOG_THROTTLE_INTERVAL = 10

# 日志时间戳格式
LOG_TIMESTAMP_FORMAT = "%H:%M:%S"


# === 工作流执行常量 ===
# 默认最大重试次数
DEFAULT_MAX_RETRIES = 3

# 默认重试延迟（秒）
DEFAULT_RETRY_DELAY_SECONDS = 2

# 步骤结果检查超时时间（秒）
STEP_CHECK_TIMEOUT = 10

# 脚本执行超时时间（秒）
SCRIPT_EXECUTION_TIMEOUT = 60


# === 路径安全常量 ===
# 路径最大长度限制（Windows路径限制为260，但保留余量）
MAX_PATH_LENGTH = 255

# 文件名最大长度
MAX_FILENAME_LENGTH = 128

# 允许的文件扩展名白名单（安全考虑）
ALLOWED_FILE_EXTENSIONS = {
    '.py', '.md', '.json', '.txt', '.html', '.css', '.js', '.xml', '.csv'
}


# === 内容验证常量 ===
# 内容最小字符数（空内容检查）
MIN_CONTENT_LENGTH = 10

# 关键词提取最大数量
MAX_KEYWORDS_COUNT = 50

# 标题最大字符数
MAX_TITLE_LENGTH = 200

# 摘要最大字符数
MAX_SUMMARY_LENGTH = 500


# === 认证安全常量 ===
# Token 有效期（小时）
TOKEN_EXPIRE_HOURS = 24

# IP 限流（每分钟最大请求数）
RATE_LIMIT_PER_MINUTE = 20

# 登录最大尝试次数
MAX_LOGIN_ATTEMPTS = 5

# 账户锁定时间（分钟）
ACCOUNT_LOCKOUT_MINUTES = 15


# === LLM 调用常量 ===
# 最大 token 限制
MAX_TOKENS_LIMIT = 4096

# 温度参数
DEFAULT_TEMPERATURE = 0.7

# 顶部P参数
DEFAULT_TOP_P = 0.9

# 工具调用最大重试次数
MAX_TOOL_CALL_RETRIES = 3


# === 节点定义常量 ===
# 支持的执行类型
VALID_EXEC_TYPES = {
    'pure_code', 'llm_completion', 'agent_action', 'human_review', 'system_check'
}

# 支持的节点类型（兼容旧版）
VALID_NODE_KINDS = VALID_EXEC_TYPES | {'agent', 'code', 'review', 'system'}

# 需要人工审核的执行类型
HUMAN_REVIEW_TYPES = {'human_review'}

# 自动化执行类型
AUTO_EXECUTION_TYPES = {'pure_code', 'llm_completion', 'agent_action', 'system_check'}


# === 输出格式常量 ===
# 支持的输出格式
SUPPORTED_OUTPUT_FORMATS = {
    'markdown': '.md',
    'html': '.html',
    'json': '.json',
    'text': '.txt',
}

# 默认输出格式
DEFAULT_OUTPUT_FORMAT = 'markdown'
