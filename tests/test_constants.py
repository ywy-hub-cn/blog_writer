"""
constants 模块单元测试
"""
import pytest

from blog_writer.constants import (
    LOG_THROTTLE_INTERVAL,
    LOG_TIMESTAMP_FORMAT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY_SECONDS,
    STEP_CHECK_TIMEOUT,
    SCRIPT_EXECUTION_TIMEOUT,
    MAX_PATH_LENGTH,
    MAX_FILENAME_LENGTH,
    ALLOWED_FILE_EXTENSIONS,
    MIN_CONTENT_LENGTH,
    MAX_KEYWORDS_COUNT,
    MAX_TITLE_LENGTH,
    MAX_SUMMARY_LENGTH,
    TOKEN_EXPIRE_HOURS,
    RATE_LIMIT_PER_MINUTE,
    MAX_LOGIN_ATTEMPTS,
    ACCOUNT_LOCKOUT_MINUTES,
    MAX_TOKENS_LIMIT,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    MAX_TOOL_CALL_RETRIES,
    VALID_EXEC_TYPES,
    VALID_NODE_KINDS,
    HUMAN_REVIEW_TYPES,
    AUTO_EXECUTION_TYPES,
    SUPPORTED_OUTPUT_FORMATS,
    DEFAULT_OUTPUT_FORMAT,
    MAX_PATH_LENGTH as MAX_PATH,
    ALLOWED_FILE_EXTENSIONS as ALLOWED_EXT
)


class TestLogConstants:
    """测试日志相关常量"""
    
    def test_throttle_interval_positive(self):
        """测试节流间隔为正数"""
        assert LOG_THROTTLE_INTERVAL > 0
        assert isinstance(LOG_THROTTLE_INTERVAL, int)
    
    def test_timestamp_format_valid(self):
        """测试时间戳格式有效"""
        assert "%" in LOG_TIMESTAMP_FORMAT
        assert "H" in LOG_TIMESTAMP_FORMAT
        assert "M" in LOG_TIMESTAMP_FORMAT
        assert "S" in LOG_TIMESTAMP_FORMAT


class TestWorkflowConstants:
    """测试工作流相关常量"""
    
    def test_max_retries_positive(self):
        """测试最大重试次数为正数"""
        assert DEFAULT_MAX_RETRIES > 0
        assert isinstance(DEFAULT_MAX_RETRIES, int)
    
    def test_retry_delay_positive(self):
        """测试重试延迟为正数"""
        assert DEFAULT_RETRY_DELAY_SECONDS > 0
        assert isinstance(DEFAULT_RETRY_DELAY_SECONDS, (int, float))
    
    def test_step_check_timeout_positive(self):
        """测试步骤检查超时为正数"""
        assert STEP_CHECK_TIMEOUT > 0
    
    def test_script_execution_timeout_positive(self):
        """测试脚本执行超时为正数"""
        assert SCRIPT_EXECUTION_TIMEOUT > 0
        assert SCRIPT_EXECUTION_TIMEOUT > STEP_CHECK_TIMEOUT


class TestPathConstants:
    """测试路径相关常量"""
    
    def test_max_path_length_reasonable(self):
        """测试最大路径长度合理"""
        assert MAX_PATH_LENGTH > 0
        assert MAX_PATH_LENGTH < 1000  # 合理的上限
    
    def test_max_filename_length_positive(self):
        """测试最大文件名长度为正数"""
        assert MAX_FILENAME_LENGTH > 0
        assert MAX_FILENAME_LENGTH < MAX_PATH_LENGTH
    
    def test_allowed_extensions_not_empty(self):
        """测试允许的扩展名不为空"""
        assert len(ALLOWED_FILE_EXTENSIONS) > 0
    
    def test_allowed_extensions_have_common_types(self):
        """测试允许的扩展名包含常见类型"""
        common_types = {'.py', '.md', '.json', '.txt'}
        for ext in common_types:
            assert ext in ALLOWED_FILE_EXTENSIONS, f"缺少常见扩展名: {ext}"


class TestContentConstants:
    """测试内容相关常量"""
    
    def test_min_content_length_positive(self):
        """测试最小内容长度为正数"""
        assert MIN_CONTENT_LENGTH > 0
    
    def test_max_keywords_count_positive(self):
        """测试最大关键词数量为正数"""
        assert MAX_KEYWORDS_COUNT > 0
    
    def test_max_title_length_reasonable(self):
        """测试最大标题长度合理"""
        assert MAX_TITLE_LENGTH > 50
        assert MAX_TITLE_LENGTH < 500
    
    def test_max_summary_length_greater_than_title(self):
        """测试最大摘要长度大于标题长度"""
        assert MAX_SUMMARY_LENGTH > MAX_TITLE_LENGTH


class TestAuthConstants:
    """测试认证相关常量"""
    
    def test_token_expire_hours_positive(self):
        """测试Token有效期为正数"""
        assert TOKEN_EXPIRE_HOURS > 0
        assert isinstance(TOKEN_EXPIRE_HOURS, (int, float))
    
    def test_rate_limit_positive(self):
        """测试限流为正数"""
        assert RATE_LIMIT_PER_MINUTE > 0
    
    def test_max_login_attempts_positive(self):
        """测试最大登录尝试次数为正数"""
        assert MAX_LOGIN_ATTEMPTS > 0
        assert MAX_LOGIN_ATTEMPTS < 20  # 合理范围
    
    def test_account_lockout_minutes_positive(self):
        """测试账户锁定时间为正数"""
        assert ACCOUNT_LOCKOUT_MINUTES > 0


class TestLLMConstants:
    """测试LLM相关常量"""
    
    def test_max_tokens_positive(self):
        """测试最大Token数为正数"""
        assert MAX_TOKENS_LIMIT > 0
    
    def test_temperature_valid_range(self):
        """测试温度在有效范围内"""
        assert 0.0 <= DEFAULT_TEMPERATURE <= 2.0
    
    def test_top_p_valid_range(self):
        """测试top_p在有效范围内"""
        assert 0.0 < DEFAULT_TOP_P <= 1.0
    
    def test_max_tool_call_retries_positive(self):
        """测试工具调用重试次数为正数"""
        assert MAX_TOOL_CALL_RETRIES > 0


class TestNodeTypeConstants:
    """测试节点类型常量"""
    
    def test_valid_exec_types_not_empty(self):
        """测试有效执行类型不为空"""
        assert len(VALID_EXEC_TYPES) > 0
    
    def test_valid_exec_types_has_core_types(self):
        """测试有效执行类型包含核心类型"""
        core_types = {'pure_code', 'llm_completion', 'agent_action', 'human_review', 'system_check'}
        for t in core_types:
            assert t in VALID_EXEC_TYPES, f"缺少核心类型: {t}"
    
    def test_valid_node_kinds_superset_of_exec_types(self):
        """测试有效节点类型是执行类型的超集"""
        for t in VALID_EXEC_TYPES:
            assert t in VALID_NODE_KINDS, f"执行类型 {t} 应在节点类型中"
    
    def test_human_review_types_not_empty(self):
        """测试人工审核类型不为空"""
        assert len(HUMAN_REVIEW_TYPES) > 0
        assert 'human_review' in HUMAN_REVIEW_TYPES
    
    def test_auto_execution_types_not_empty(self):
        """测试自动执行类型不为空"""
        assert len(AUTO_EXECUTION_TYPES) > 0
    
    def test_no_overlap_between_review_and_auto(self):
        """测试审核类型和自动类型没有重叠"""
        overlap = HUMAN_REVIEW_TYPES & AUTO_EXECUTION_TYPES
        assert len(overlap) == 0, f"审核类型和自动类型有重叠: {overlap}"


class TestOutputFormatConstants:
    """测试输出格式常量"""
    
    def test_supported_formats_not_empty(self):
        """测试支持的输出格式不为空"""
        assert len(SUPPORTED_OUTPUT_FORMATS) > 0
    
    def test_default_format_exists(self):
        """测试默认格式在支持列表中"""
        assert DEFAULT_OUTPUT_FORMAT in SUPPORTED_OUTPUT_FORMATS
    
    def test_format_extensions_are_valid(self):
        """测试格式扩展名为有效形式"""
        for name, ext in SUPPORTED_OUTPUT_FORMATS.items():
            assert ext.startswith('.'), f"扩展名应以点号开头: {ext}"
            assert len(ext) > 1, f"扩展名长度应大于1: {ext}"


class TestConstantsAreImmutable:
    """测试常量模块的基本特性"""
    
    def test_all_constants_are_readable(self):
        """测试所有常量可读取"""
        # 常量应该都能正常读取
        assert LOG_THROTTLE_INTERVAL is not None
        assert DEFAULT_MAX_RETRIES is not None
        assert MAX_PATH_LENGTH is not None
        assert TOKEN_EXPIRE_HOURS is not None
