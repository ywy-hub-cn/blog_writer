"""
认证模块单元测试 - 明文密码 + 双角色（管理员/运营）
"""
import os
import json
import tempfile
from pathlib import Path

import pytest

from blog_writer.security.auth import (
    AuthManager,
    _load_config,
    _save_config,
    _CONFIG_CACHE_TTL,
    _invalidate_cache,
    _rate_limit,
    _active_tokens,
    ROLE_ADMIN,
    ROLE_OPERATOR,
)


@pytest.fixture(autouse=True)
def clear_auth_state():
    """在每个测试前后清理认证状态"""
    _active_tokens.clear()
    _rate_limit.clear()
    _invalidate_cache()
    yield
    _active_tokens.clear()
    _rate_limit.clear()
    _invalidate_cache()


@pytest.fixture
def temp_dir(tmp_path):
    """临时目录 fixture"""
    return str(tmp_path)


class TestPlaintextPassword:
    """测试明文密码验证逻辑"""

    def test_admin_password_verification(self, temp_dir, monkeypatch):
        """管理员密码可正确验证"""
        config_path = Path(temp_dir) / "admin_pwd.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        AuthManager.set_admin_password("my_admin_pwd")

        token = AuthManager.login("my_admin_pwd")
        assert token is not None

        info = AuthManager.get_token_info(token)
        assert info is not None
        assert info.get("role") == ROLE_ADMIN

        AuthManager.logout(token)

    def test_operator_password_verification(self, temp_dir, monkeypatch):
        """运营密码可正确验证并返回运营角色"""
        config_path = Path(temp_dir) / "operator_pwd.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        AuthManager.set_admin_password("admin_pwd")
        AuthManager.set_operator_password("operator_pwd")

        token = AuthManager.login("operator_pwd")
        assert token is not None

        info = AuthManager.get_token_info(token)
        assert info is not None
        assert info.get("role") == ROLE_OPERATOR

        AuthManager.logout(token)

    def test_wrong_password_rejected(self, temp_dir, monkeypatch):
        """错误密码被拒绝"""
        config_path = Path(temp_dir) / "wrong_pwd.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        AuthManager.set_admin_password("admin_pwd")

        token = AuthManager.login("wrong_pwd")
        assert token is None

    def test_default_admin_password(self, temp_dir, monkeypatch):
        """未配置密码时使用默认密码 admin123"""
        config_path = Path(temp_dir) / "default_pwd.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        token = AuthManager.login("admin123")
        assert token is not None

        AuthManager.logout(token)

    def test_both_roles_work_independently(self, temp_dir, monkeypatch):
        """管理员和运营角色独立工作"""
        config_path = Path(temp_dir) / "dual_role.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        AuthManager.set_admin_password("admin_pwd")
        AuthManager.set_operator_password("operator_pwd")

        admin_token = AuthManager.login("admin_pwd")
        operator_token = AuthManager.login("operator_pwd")

        assert admin_token is not None
        assert operator_token is not None
        assert admin_token != operator_token

        assert AuthManager.get_token_info(admin_token).get("role") == ROLE_ADMIN
        assert AuthManager.get_token_info(operator_token).get("role") == ROLE_OPERATOR

        AuthManager.logout(admin_token)
        AuthManager.logout(operator_token)


class TestConfigManagement:
    """测试配置管理"""

    def test_load_config_no_file(self, temp_dir, monkeypatch):
        """测试加载不存在的配置文件"""
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path",
            lambda: Path(temp_dir) / "nonexistent.json",
        )
        _invalidate_cache()
        config = _load_config()
        assert config == {}

    def test_save_and_load_config(self, temp_dir, monkeypatch):
        """测试保存和加载配置"""
        config_path = Path(temp_dir) / "test_config.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        test_config = {
            "security": {
                "admin_password_hash": "test_hash_placeholder",
                "operator_password_hash": "test_hash_placeholder",
                "token_expire_hours": 24,
            }
        }

        _save_config(test_config)
        _invalidate_cache()

        loaded = _load_config()
        assert loaded == test_config

    def test_config_cache(self, temp_dir, monkeypatch):
        """测试配置缓存"""
        config_path = Path(temp_dir) / "cache_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        test_config = {"test": "value"}
        _save_config(test_config)

        config1 = _load_config()
        assert config1 == test_config

        config2 = _load_config()
        assert config2 == test_config


class TestAuthLogin:
    """测试登录功能"""

    def test_login_without_password(self, temp_dir, monkeypatch):
        """测试无密码时的登录（使用默认 admin123）"""
        config_path = Path(temp_dir) / "login_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        token = AuthManager.login("admin123")
        assert token is not None
        assert len(token) > 0

        AuthManager.logout(token)

    def test_login_with_wrong_password(self, temp_dir, monkeypatch):
        """测试错误密码登录"""
        config_path = Path(temp_dir) / "wrong_pwd_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        AuthManager.set_admin_password("correct_password")

        token = AuthManager.login("wrong_password")
        assert token is None

    def test_login_success(self, temp_dir, monkeypatch):
        """测试成功登录"""
        config_path = Path(temp_dir) / "success_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        AuthManager.set_admin_password("my_password")

        token = AuthManager.login("my_password")
        assert token is not None

        info = AuthManager.get_token_info(token)
        assert info is not None
        assert "expire_at" in info
        assert info.get("role") == ROLE_ADMIN

        AuthManager.logout(token)

    def test_login_with_role_admin(self, temp_dir, monkeypatch):
        """测试 login_with_role 返回管理员角色"""
        config_path = Path(temp_dir) / "role_admin.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        AuthManager.set_admin_password("admin_pwd")
        AuthManager.set_operator_password("operator_pwd")

        result = AuthManager.login_with_role("admin_pwd")
        assert result is not None
        token, role = result
        assert role == ROLE_ADMIN
        assert token is not None

        AuthManager.logout(token)

    def test_login_with_role_operator(self, temp_dir, monkeypatch):
        """测试 login_with_role 返回运营角色"""
        config_path = Path(temp_dir) / "role_operator.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        AuthManager.set_admin_password("admin_pwd")
        AuthManager.set_operator_password("operator_pwd")

        result = AuthManager.login_with_role("operator_pwd")
        assert result is not None
        token, role = result
        assert role == ROLE_OPERATOR

        AuthManager.logout(token)


class TestTokenManagement:
    """测试Token管理"""

    def test_token_verify(self, temp_dir, monkeypatch):
        """测试Token验证"""
        config_path = Path(temp_dir) / "verify_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        token = AuthManager.login("admin123")
        assert token is not None

        result = AuthManager.verify_token(token)
        assert result is True

        result = AuthManager.verify_token("invalid_token")
        assert result is False

        AuthManager.logout(token)

    def test_token_logout(self, temp_dir, monkeypatch):
        """测试Token注销"""
        config_path = Path(temp_dir) / "logout_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        token = AuthManager.login("admin123")
        assert token is not None

        AuthManager.logout(token)

        result = AuthManager.verify_token(token)
        assert result is False

    def test_multiple_tokens(self, temp_dir, monkeypatch):
        """测试多个Token管理"""
        config_path = Path(temp_dir) / "multi_token_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        token1 = AuthManager.login("admin123")
        token2 = AuthManager.login("admin123")

        assert token1 is not None
        assert token2 is not None
        assert token1 != token2

        assert AuthManager.verify_token(token1) is True
        assert AuthManager.verify_token(token2) is True

        AuthManager.logout(token1)
        assert AuthManager.verify_token(token1) is False
        assert AuthManager.verify_token(token2) is True

        AuthManager.logout(token2)


class TestRateLimit:
    """测试IP限流"""

    def test_rate_limit_allows_first_request(self, temp_dir, monkeypatch):
        """测试首次请求允许通过"""
        config_path = Path(temp_dir) / "rate_limit_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        config = {
            "security": {
                "rate_limit_per_minute": 10,
            }
        }
        _save_config(config)
        _invalidate_cache()

        result = AuthManager.check_rate_limit("192.168.1.1")
        assert result is True

    def test_rate_limit_blocks_exceeding(self, temp_dir, monkeypatch):
        """测试超出限制时阻止请求"""
        config_path = Path(temp_dir) / "rate_limit_exceed_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        config = {
            "security": {
                "rate_limit_per_minute": 3,
            }
        }
        _save_config(config)
        _invalidate_cache()

        ip = "192.168.1.2"
        if ip in _rate_limit:
            del _rate_limit[ip]

        for i in range(3):
            result = AuthManager.check_rate_limit(ip)
            assert result is True, f"Request {i + 1} should be allowed"

        result = AuthManager.check_rate_limit(ip)
        assert result is False, "Request 4 should be blocked"

    def test_rate_limit_different_ips(self, temp_dir, monkeypatch):
        """测试不同IP独立限流"""
        config_path = Path(temp_dir) / "rate_limit_ips_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        config = {
            "security": {
                "rate_limit_per_minute": 1,
            }
        }
        _save_config(config)
        _invalidate_cache()

        ip1 = "192.168.1.3"
        ip2 = "192.168.1.4"

        for ip in [ip1, ip2]:
            if ip in _rate_limit:
                del _rate_limit[ip]

        AuthManager.check_rate_limit(ip1)
        result = AuthManager.check_rate_limit(ip1)
        assert result is False

        result = AuthManager.check_rate_limit(ip2)
        assert result is True


class TestSetAdminPassword:
    """测试设置管理员密码"""

    def test_set_password(self, temp_dir, monkeypatch):
        """测试设置密码"""
        config_path = Path(temp_dir) / "set_pwd_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        AuthManager.set_admin_password("new_secure_password")

        token = AuthManager.login("new_secure_password")
        assert token is not None

        token = AuthManager.login("admin123")
        assert token is None

        if token:
            AuthManager.logout(token)

    def test_set_operator_password(self, temp_dir, monkeypatch):
        """测试设置运营密码"""
        config_path = Path(temp_dir) / "set_op_pwd_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        AuthManager.set_admin_password("admin_pwd")
        AuthManager.set_operator_password("op_secure_pwd")

        token = AuthManager.login("op_secure_pwd")
        assert token is not None

        info = AuthManager.get_token_info(token)
        assert info.get("role") == ROLE_OPERATOR

        AuthManager.logout(token)


class TestRevokeAllTokens:
    """测试吊销全部Token"""

    def test_revoke_all(self, temp_dir, monkeypatch):
        """吊销全部Token后所有登录会话失效"""
        config_path = Path(temp_dir) / "revoke_test.json"
        monkeypatch.setattr(
            "blog_writer.security.auth._get_config_path", lambda: config_path
        )

        if config_path.exists():
            config_path.unlink()
        _invalidate_cache()

        token1 = AuthManager.login("admin123")
        token2 = AuthManager.login("admin123")
        assert token1 is not None
        assert token2 is not None

        revoked = AuthManager.revoke_all_tokens()
        assert revoked >= 2

        assert AuthManager.verify_token(token1) is False
        assert AuthManager.verify_token(token2) is False
