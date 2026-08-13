"""
Webhook 回调机制
用于任务状态变更时主动通知公司平台

使用场景:
1. 任务创建时，调用方可传入 callback_url
2. 任务状态变更（完成/失败/等待审核）时，系统自动 POST 回调
3. 支持签名验证，确保回调来源可信

回调注册默认内存；若 StateStore 可用（含 Redis）则持久化，重启可恢复。
"""

import json
import time
import hmac
import hashlib
import logging
import socket
import http.client
import threading
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger("blog-writer.webhook")

_WEBHOOK_KEY_PREFIX = "blog_writer:webhook:callback:"


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS 连接：TCP 连接到固定 IP（防 DNS rebinding），
    但 TLS 握手使用原始域名作为 SNI 和证书验证主机名。

    这样既能防止 DNS rebinding 攻击，又能正确完成 TLS 证书验证。
    """

    def __init__(self, host, port, *, pinned_ip, timeout=None, **kwargs):
        super().__init__(host, port, timeout=timeout, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self):
        sock = socket.create_connection(
            (self._pinned_ip, self.port), timeout=self.timeout
        )
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
        else:
            self.sock = self._context.wrap_socket(
                sock, server_hostname=self.host
            )


class WebhookManager:
    """Webhook 回调管理器 - 线程安全的单例"""
    
    _instance = None
    _instance_lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._callbacks = {}
                    instance._history = []
                    instance._max_history = 500
                    instance._lock = threading.Lock()
                    cls._instance = instance
        return cls._instance

    def _persist_callback(self, task_id: str, data: Dict[str, Any]) -> None:
        try:
            from blog_writer.state_store import get_state_store
            # 保留 7 天，任务结束后可显式 unregister
            get_state_store().set_json(
                f"{_WEBHOOK_KEY_PREFIX}{task_id}",
                data,
                ttl_seconds=7 * 24 * 3600,
            )
        except Exception as e:
            logger.debug("webhook persist skipped: %s", e)

    def _delete_persisted(self, task_id: str) -> None:
        try:
            from blog_writer.state_store import get_state_store
            get_state_store().delete(f"{_WEBHOOK_KEY_PREFIX}{task_id}")
        except Exception:
            pass

    def _load_persisted(self, task_id: str) -> Optional[Dict[str, Any]]:
        try:
            from blog_writer.state_store import get_state_store
            data = get_state_store().get_json(f"{_WEBHOOK_KEY_PREFIX}{task_id}")
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    
    def register(self, task_id: str, callback_url: str, secret: str = ""):
        """注册任务回调"""
        from blog_writer.security.url_safety import is_safe_webhook_url

        ok, reason = is_safe_webhook_url(callback_url, resolve_dns=True)
        if not ok:
            raise ValueError(f"不安全的 callback_url ({reason}): {callback_url}")

        payload = {
            "url": callback_url,
            "secret": secret,
            "created_at": datetime.now().isoformat(),
            "events": [],
        }
        with self._lock:
            self._callbacks[task_id] = payload
        self._persist_callback(task_id, payload)
        logger.info(f"Webhook registered for task {task_id} -> {callback_url}")
    
    def unregister(self, task_id: str):
        """注销任务回调"""
        with self._lock:
            if task_id in self._callbacks:
                del self._callbacks[task_id]
        self._delete_persisted(task_id)
    
    def has_callback(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._callbacks:
                return True
        restored = self._load_persisted(task_id)
        if restored:
            with self._lock:
                self._callbacks[task_id] = restored
            return True
        return False
    
    def get_callback(self, task_id: str) -> Optional[Dict]:
        with self._lock:
            cb = self._callbacks.get(task_id)
            if cb:
                return cb
        restored = self._load_persisted(task_id)
        if restored:
            with self._lock:
                self._callbacks[task_id] = restored
            return restored
        return None
    
    async def fire(self, task_id: str, event: str, data: Dict[str, Any] = None) -> bool:
        """
        触发回调（异步安全，不阻塞事件循环）；失败最多重试 3 次。
        """
        callback = self.get_callback(task_id)
        if not callback:
            return False
        
        payload = {
            "event": event,
            "task_id": task_id,
            "data": data or {},
            "timestamp": int(time.time()),
            "signature": "",
        }
        
        if callback["secret"]:
            payload["signature"] = self._sign(payload, callback["secret"])
        
        with self._lock:
            if task_id in self._callbacks:
                cb = self._callbacks[task_id]
                cb["events"].append({
                    "event": event,
                    "timestamp": payload["timestamp"],
                    "data_preview": str(data)[:200] if data else "",
                })
                if len(cb["events"]) > 100:
                    cb["events"] = cb["events"][-100:]
                # 同步事件历史到 StateStore（重启可恢复 event_count）
                self._persist_callback(task_id, cb)
        
        last_error = None
        for attempt in range(1, 4):
            try:
                success = await asyncio.to_thread(
                    self._send_http_request,
                    callback["url"],
                    payload,
                    task_id,
                    event
                )
                if success:
                    return True
                last_error = "non-2xx"
            except Exception as e:
                last_error = str(e)
                logger.error(f"Webhook error: {task_id} -> {event} attempt={attempt}: {e}")
            if attempt < 3:
                # 指数退避：0.5s, 1s, 2s ...
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        self._record_history(task_id, event, callback["url"], False, f"retries_exhausted:{last_error}")
        return False
    
    def _send_http_request(self, url: str, payload: Dict, task_id: str, event: str) -> bool:
        """发送HTTP请求（在独立线程中执行，不阻塞事件循环）

        防 DNS rebinding：解析阶段校验 IP 后，用解析到的 IP 建立 TCP 连接，
        但 TLS 握手仍使用原始域名作为 SNI / 证书验证主机名，
        避免 urlopen 二次解析 DNS 被重绑定到内网。
        """
        import ssl
        from urllib.parse import urlparse
        from blog_writer.security.url_safety import is_safe_webhook_url

        ok, reason = is_safe_webhook_url(url, resolve_dns=True)
        if not ok:
            logger.error(f"Webhook blocked SSRF: {task_id} -> {event} ({reason})")
            self._record_history(task_id, event, url, False, f"ssrf_blocked:{reason}")
            return False

        parsed = urlparse(url.strip())
        scheme = (parsed.scheme or "https").lower()
        host = parsed.hostname or ""
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        # 解析 DNS 获取 IP，用 IP 建 TCP 连接防止 DNS rebinding
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            self._record_history(task_id, event, url, False, "dns_resolve_failed")
            return False

        resolved_ip = None
        for info in infos:
            raw_ip = info[4][0]
            try:
                import ipaddress
                ip = ipaddress.ip_address(raw_ip)
                if not (ip.is_private or ip.is_loopback or ip.is_link_local
                        or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                    resolved_ip = raw_ip
                    break
            except ValueError:
                continue

        if not resolved_ip:
            self._record_history(task_id, event, url, False, "no_safe_ip")
            return False

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": payload.get("signature", ""),
            "X-Webhook-Event": event,
            "X-Task-ID": task_id,
            "Host": host,
        }

        conn = None
        try:
            if scheme == "https":
                # 自定义 HTTPS 连接：TCP 连接到 resolved_ip（防 DNS rebinding），
                # 但 TLS 握手使用原始 host 作为 SNI 和证书验证主机名
                ctx = ssl.create_default_context()
                conn = _PinnedHTTPSConnection(
                    host, port, pinned_ip=resolved_ip, timeout=10, context=ctx
                )
            else:
                conn = http.client.HTTPConnection(resolved_ip, port, timeout=10)

            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            resp.read()

            if 200 <= status < 300:
                logger.info(f"Webhook fired: {task_id} -> {event} (status={status})")
                self._record_history(task_id, event, url, True, status)
                return True
            else:
                logger.warning(f"Webhook failed: {task_id} -> {event} (status={status})")
                self._record_history(task_id, event, url, False, status)
                return False
        except Exception as e:
            logger.error(f"Webhook error: {task_id} -> {event}: {e}")
            self._record_history(task_id, event, url, False, str(e))
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    
    def _sign(self, payload: Dict, secret: str) -> str:
        """HMAC 签名：覆盖 event/task_id/timestamp 与 data 内容，防篡改。"""
        data_raw = json.dumps(payload.get("data") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content = f"{payload['event']}.{payload['task_id']}.{payload['timestamp']}.{data_raw}"
        signature = hmac.new(
            secret.encode("utf-8"),
            content.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _record_history(self, task_id: str, event: str, url: str, success: bool, detail: str):
        """记录回调历史（线程安全）"""
        with self._lock:
            self._history.append({
                "task_id": task_id,
                "event": event,
                "url": url,
                "success": success,
                "detail": detail,
                "timestamp": datetime.now().isoformat(),
            })
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
    
    def get_history(self, task_id: str = None, limit: int = 20) -> List[Dict]:
        """获取回调历史（线程安全副本）"""
        with self._lock:
            history = list(self._history)
        if task_id:
            history = [h for h in history if h["task_id"] == task_id]
        limit = max(1, min(limit, 500))
        return history[-limit:]
    
    def get_callbacks(self) -> Dict[str, Dict]:
        """获取所有已注册的回调（线程安全副本）"""
        with self._lock:
            result = {}
            for tid, cb in self._callbacks.items():
                result[tid] = {
                    "url": cb["url"],
                    "created_at": cb["created_at"],
                    "event_count": len(cb["events"]),
                    "last_event": cb["events"][-1]["event"] if cb["events"] else None,
                }
            return result


def get_webhook_manager() -> WebhookManager:
    """获取 Webhook 管理器实例"""
    return WebhookManager()
