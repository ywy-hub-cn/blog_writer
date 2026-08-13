"""
限流模块测试
"""
import time
import threading
import pytest


class TestTokenBucket:
    """测试令牌桶"""
    
    def test_acquire_within_capacity(self):
        from blog_writer.security.rate_limiter import TokenBucket
        
        bucket = TokenBucket(capacity=100, refill_rate=10)
        
        for _ in range(50):
            assert bucket.acquire() is True
        
        tokens = bucket.current_tokens()
        assert 49.0 <= tokens <= 51.0
    
    def test_acquire_exhausts_tokens(self):
        from blog_writer.security.rate_limiter import TokenBucket
        
        bucket = TokenBucket(capacity=10, refill_rate=1)
        
        for _ in range(10):
            assert bucket.acquire() is True
        
        # 令牌耗尽
        assert bucket.acquire() is False
    
    def test_refill_over_time(self):
        from blog_writer.security.rate_limiter import TokenBucket
        
        bucket = TokenBucket(capacity=5, refill_rate=100)
        
        # 消耗所有令牌
        for _ in range(5):
            bucket.acquire()
        
        # 短暂等待令牌补充
        time.sleep(0.1)
        
        # 应该能再次获取
        assert bucket.acquire() is True
    
    def test_thread_safety(self):
        from blog_writer.security.rate_limiter import TokenBucket
        
        bucket = TokenBucket(capacity=200, refill_rate=100)
        success_count = []
        lock = threading.Lock()
        
        def acquire_tokens(n):
            local_success = 0
            for _ in range(n):
                if bucket.acquire():
                    local_success += 1
            with lock:
                success_count.append(local_success)
        
        threads = []
        for _ in range(4):
            t = threading.Thread(target=acquire_tokens, args=(50,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        total_success = sum(success_count)
        # 总共获取的令牌数不超过容量
        assert total_success <= 200


class TestSlidingWindowCounter:
    """测试滑动窗口计数器"""
    
    def test_acquire_within_window(self):
        from blog_writer.security.rate_limiter import SlidingWindowCounter
        
        counter = SlidingWindowCounter(max_requests=5, window_seconds=1)
        
        for _ in range(5):
            assert counter.acquire() is True
        
        assert counter.acquire() is False
    
    def test_window_expires(self):
        from blog_writer.security.rate_limiter import SlidingWindowCounter
        
        counter = SlidingWindowCounter(max_requests=3, window_seconds=1)
        
        for _ in range(3):
            counter.acquire()
        
        # 窗口过期后应允许新请求
        time.sleep(1.1)
        
        assert counter.acquire() is True
    
    def test_current_count(self):
        from blog_writer.security.rate_limiter import SlidingWindowCounter
        
        counter = SlidingWindowCounter(max_requests=10, window_seconds=5)
        
        assert counter.current_count() == 0
        
        counter.acquire()
        counter.acquire()
        
        assert counter.current_count() == 2


class TestRateLimiter:
    """测试双层层限流器"""
    
    def test_global_rate_limit(self):
        from blog_writer.security.rate_limiter import RateLimiter
        
        limiter = RateLimiter(
            global_rate=1000,
            global_burst=5,
            per_client_rate=100,
            per_client_window=60,
            audit_enabled=False
        )
        
        client_ip = "10.0.0.1"
        
        for _ in range(5):
            allowed, reason = limiter.is_allowed(client_ip, "/test")
            assert allowed is True
        
        # 第6个请求应被全局限制
        allowed, reason = limiter.is_allowed(client_ip, "/test")
        assert allowed is False
        assert "Global" in reason
    
    def test_per_client_limit(self):
        from blog_writer.security.rate_limiter import RateLimiter
        
        limiter = RateLimiter(
            global_rate=1000,
            global_burst=500,
            per_client_rate=3,
            per_client_window=60,
            audit_enabled=False
        )
        
        client_ip1 = "10.0.0.1"
        client_ip2 = "10.0.0.2"
        
        # client1 超过限制
        for _ in range(3):
            limiter.is_allowed(client_ip1, "/test")
        
        allowed, reason = limiter.is_allowed(client_ip1, "/test")
        assert allowed is False
        assert "Per-client" in reason
        
        # client2 仍应被允许
        allowed2, _ = limiter.is_allowed(client_ip2, "/test")
        assert allowed2 is True
    
    def test_endpoint_specific_limit(self):
        from blog_writer.security.rate_limiter import RateLimiter
        
        limiter = RateLimiter(
            global_rate=1000,
            global_burst=500,
            per_client_rate=100,
            per_client_window=60,
            audit_enabled=False
        )
        
        # 设置严格的端点限制
        limiter.set_endpoint_limit("/api/auth/login", 2, 60)
        
        client_ip = "10.0.0.1"
        
        # 登录端点只允许2次
        for _ in range(2):
            allowed, _ = limiter.is_allowed(client_ip, "/api/auth/login")
            assert allowed is True
        
        allowed, reason = limiter.is_allowed(client_ip, "/api/auth/login")
        assert allowed is False
        assert "Endpoint" in reason
    
    def test_get_stats(self):
        from blog_writer.security.rate_limiter import RateLimiter
        
        limiter = RateLimiter(
            global_rate=100,
            global_burst=200,
            per_client_rate=10,
            per_client_window=60,
            audit_enabled=False
        )
        
        limiter.is_allowed("client-1", "/test")
        limiter.is_allowed("client-1", "/test")
        limiter.is_allowed("client-2", "/test")
        
        stats = limiter.get_stats()
        assert "global_tokens" in stats
        assert stats["active_clients"] == 2


class TestRateLimiterIntegration:
    """限流集成测试"""
    
    def test_concurrent_requests(self):
        from blog_writer.security.rate_limiter import RateLimiter
        
        limiter = RateLimiter(
            global_rate=1000,
            global_burst=100,
            per_client_rate=100,
            per_client_window=60,
            audit_enabled=False
        )
        
        results = {"allowed": 0, "blocked": 0}
        lock = threading.Lock()
        
        def make_requests(client_id, n):
            local_allowed = 0
            local_blocked = 0
            for _ in range(n):
                allowed, _ = limiter.is_allowed(client_id, "/api/test")
                if allowed:
                    local_allowed += 1
                else:
                    local_blocked += 1
            with lock:
                results["allowed"] += local_allowed
                results["blocked"] += local_blocked
        
        threads = []
        for i in range(10):
            t = threading.Thread(
                target=make_requests,
                args=(f"client-{i}", 10)
            )
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        total = results["allowed"] + results["blocked"]
        assert total == 100  # 10 clients * 10 requests
        
        # 不应超过全局限制
        assert results["allowed"] <= 100
    
    def test_different_endpoints_isolated(self):
        from blog_writer.security.rate_limiter import RateLimiter
        
        limiter = RateLimiter(
            global_rate=1000,
            global_burst=500,
            per_client_rate=100,
            per_client_window=60,
            audit_enabled=False
        )
        
        limiter.set_endpoint_limit("/api/auth/login", 3, 60)
        
        client_id = "client-1"
        
        # 登录端点消耗限制
        for _ in range(3):
            limiter.is_allowed(client_id, "/api/auth/login")
        
        # 工作端点不受影响
        for _ in range(5):
            allowed, _ = limiter.is_allowed(client_id, "/api/tasks/execute")
            assert allowed is True
