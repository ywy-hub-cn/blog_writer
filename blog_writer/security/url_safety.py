"""URL 安全校验：Webhook 回调防 SSRF。"""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional, Tuple
from urllib.parse import urlparse


_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}


def is_safe_webhook_url(
    url: str,
    *,
    allow_http: bool = True,
    resolve_dns: bool = True,
) -> Tuple[bool, str]:
    """校验回调 URL，拒绝私网/回环/链路本地等目标。

    Args:
        resolve_dns: True 时解析主机名并检查全部 A/AAAA；
            False 时仅做语法与字面量 IP / 已知危险主机名检查（供请求体校验，避免依赖外网）。

    Returns:
        (ok, reason) reason 为空表示通过。
    """
    if not url or not isinstance(url, str):
        return False, "empty"
    if len(url) > 500:
        return False, "too_long"

    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    allowed = {"https", "http"} if allow_http else {"https"}
    if scheme not in allowed:
        return False, "scheme"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False, "host"
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        return False, "localhost"
    if host == "0.0.0.0":
        return False, "any"

    # 字面量 IP
    try:
        ip = ipaddress.ip_address(host)
        if _is_blocked_ip(ip):
            return False, "private_ip"
        return True, ""
    except ValueError:
        pass

    if not resolve_dns:
        return True, ""

    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False, "dns"
    except Exception:
        return False, "resolve"

    if not infos:
        return False, "dns"

    for info in infos:
        raw = info[4][0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            return False, "private_ip"
    return True, ""


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_webhook_url_or_raise(url: Optional[str], *, allow_http: bool = True) -> Optional[str]:
    """供 pydantic / API 使用；非法时抛 ValueError（不强制 DNS，避免离线失败）。"""
    if url is None or url == "":
        return url
    ok, reason = is_safe_webhook_url(url, allow_http=allow_http, resolve_dns=False)
    if not ok:
        raise ValueError(f"回调URL不安全或不允许 ({reason})")
    return url
