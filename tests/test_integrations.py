"""
集成适配器测试 - 认证/日志/指标/通知
"""
import json
import os
import tempfile
import pytest
from blog_writer.security.auth import _hash_password


class TestLocalAuthProvider:
    """测试本地 JWT 认证提供者"""
    
    def test_authenticate_success(self, temp_dir):
        from blog_writer.integrations import LocalAuthProvider
        
        config_path = os.path.join(temp_dir, "config.json")
        config = {
            "security": {
                "admin_password_hash": _hash_password("testpass"),
                "token_expire_hours": 24
            }
        }
        with open(config_path, "w") as f:
            json.dump(config, f)
        
        provider = LocalAuthProvider(config_path=config_path)
        result = provider.authenticate({"password": "testpass"})
        
        assert result is not None
        assert "token" in result
        assert result["user_id"] == "admin"
        assert result["role"] == "admin"
    
    def test_authenticate_wrong_password(self, temp_dir):
        from blog_writer.integrations import LocalAuthProvider
        
        config_path = os.path.join(temp_dir, "config.json")
        config = {
            "security": {
                "admin_password_hash": _hash_password("correctpass")
            }
        }
        with open(config_path, "w") as f:
            json.dump(config, f)
        
        provider = LocalAuthProvider(config_path=config_path)
        result = provider.authenticate({"password": "wrongpass"})
        assert result is None
    
    def test_verify_token(self, temp_dir):
        from blog_writer.integrations import LocalAuthProvider
        
        config_path = os.path.join(temp_dir, "config.json")
        config = {"security": {"admin_password_hash": _hash_password("test")}}
        with open(config_path, "w") as f:
            json.dump(config, f)
        
        provider = LocalAuthProvider(config_path=config_path)
        auth_result = provider.authenticate({"password": "test"})
        token = auth_result["token"]
        
        verify_result = provider.verify_token(token)
        assert verify_result is not None
        assert verify_result["user_id"] == "admin"
    
    def test_verify_invalid_token(self, temp_dir):
        from blog_writer.integrations import LocalAuthProvider
        
        config_path = os.path.join(temp_dir, "config.json")
        config = {"security": {"admin_password_hash": _hash_password("test")}}
        with open(config_path, "w") as f:
            json.dump(config, f)
        
        provider = LocalAuthProvider(config_path=config_path)
        result = provider.verify_token("invalid-token")
        assert result is None
    
    def test_logout(self, temp_dir):
        from blog_writer.integrations import LocalAuthProvider
        
        config_path = os.path.join(temp_dir, "config.json")
        config = {"security": {"admin_password_hash": _hash_password("test")}}
        with open(config_path, "w") as f:
            json.dump(config, f)
        
        provider = LocalAuthProvider(config_path=config_path)
        auth_result = provider.authenticate({"password": "test"})
        token = auth_result["token"]
        
        assert provider.logout(token) is True
        assert provider.verify_token(token) is None


class TestSSOAuthProvider:
    """测试 SSO/OAuth2 认证提供者"""
    
    def test_sso_disabled_returns_none(self):
        from blog_writer.integrations import SSOAuthProvider
        
        config = {"security": {"sso": {"enabled": False}}}
        provider = SSOAuthProvider(config)
        
        result = provider.authenticate({"username": "test", "password": "test"})
        assert result is None
    
    def test_sso_enabled_but_no_endpoint(self):
        from blog_writer.integrations import SSOAuthProvider
        
        config = {"security": {"sso": {"enabled": True, "token_url": ""}}}
        provider = SSOAuthProvider(config)
        
        result = provider.authenticate({"code": "fake-code"})
        assert result is None  # 无法连接，返回None


class TestAuthProviderFactory:
    """测试认证提供者工厂"""
    
    def test_create_local_provider(self):
        from blog_writer.integrations import create_auth_provider, LocalAuthProvider
        
        config = {}
        provider = create_auth_provider(config)
        assert isinstance(provider, LocalAuthProvider)
    
    def test_create_sso_provider(self):
        from blog_writer.integrations import create_auth_provider, SSOAuthProvider
        
        config = {"security": {"sso": {"enabled": True}}}
        provider = create_auth_provider(config)
        assert isinstance(provider, SSOAuthProvider)


class TestMetricsCollector:
    """测试指标收集器"""
    
    def test_counter(self):
        from blog_writer.integrations import MetricsCollector
        
        mc = MetricsCollector()
        mc.increment_counter("requests_total", {"method": "GET"})
        mc.increment_counter("requests_total", {"method": "GET"})
        mc.increment_counter("requests_total", {"method": "POST"})
        
        stats = mc.get_stats()
        assert len(stats["counters"]) == 2
    
    def test_gauge(self):
        from blog_writer.integrations import MetricsCollector
        
        mc = MetricsCollector()
        mc.set_gauge("active_connections", 42.5)
        
        stats = mc.get_stats()
        assert stats["gauges"]["active_connections"] == 42.5
    
    def test_prometheus_output(self):
        from blog_writer.integrations import MetricsCollector
        
        mc = MetricsCollector()
        mc.increment_counter("http_requests_total", {"method": "GET", "status": "200"})
        mc.set_gauge("system_uptime", 3600)
        
        output = mc.generate_prometheus()
        assert "blog_writer_http_requests_total" in output
        assert "blog_writer_system_uptime" in output
        assert "counter" in output
        assert "gauge" in output
    
    def test_histogram(self):
        from blog_writer.integrations import MetricsCollector
        
        mc = MetricsCollector()
        mc.observe_histogram("response_time", 0.1)
        mc.observe_histogram("response_time", 0.5)
        mc.observe_histogram("response_time", 1.2)
        
        stats = mc.get_stats()
        assert stats["histogram_counts"]["response_time"] == 3
        
        output = mc.generate_prometheus()
        assert "blog_writer_response_time_seconds_bucket" in output
        assert "blog_writer_response_time_seconds_count 3" in output
        assert 'le="+Inf"' in output


class TestStructuredLogFormatter:
    """测试结构化日志格式化"""
    
    def test_json_format(self):
        from blog_writer.integrations import StructuredLogFormatter
        import logging
        
        formatter = StructuredLogFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="test.py", lineno=1,
            msg="Test message", args=(), exc_info=None
        )
        
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test message"
        assert parsed["logger"] == "test"
        assert "timestamp" in parsed


class TestNotificationService:
    """测试通知服务"""
    
    def test_no_channels(self):
        from blog_writer.integrations import NotificationService
        
        svc = NotificationService()
        channels = svc.list_channels()
        assert len(channels) == 0
    
    def test_send_without_channels(self):
        from blog_writer.integrations import NotificationService
        
        svc = NotificationService()
        result = svc.send("Test message")
        assert result is False
    
    def test_list_channels(self):
        from blog_writer.integrations import NotificationService
        
        config = {
            "notifications": {
                "channels": {
                    "wecom": {
                        "enabled": True,
                        "webhook_url": "https://example.com/wecom",
                        "type": "wecom"
                    }
                }
            }
        }
        svc = NotificationService(config)
        channels = svc.list_channels()
        assert "wecom" in channels


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td
