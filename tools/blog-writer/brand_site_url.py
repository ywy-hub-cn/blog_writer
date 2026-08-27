"""Shared brand site URL normalize / resolve / auto-pick helpers."""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlparse

_PLACEHOLDERS = {
    "",
    "未提供",
    "n/a",
    "na",
    "none",
    "null",
    "-",
    "无",
    "暂无",
    "待定",
}


def normalize_brand_site_url(value: str | None) -> str:
    raw = (value or "").strip().rstrip("/.,;")
    if not raw:
        return ""
    lowered = raw.casefold()
    if lowered in _PLACEHOLDERS:
        return ""
    if not raw.startswith(("http://", "https://")):
        return ""
    return raw.rstrip("/")


def resolve_brand_site_url(startup_text: str, fallback: str = "") -> str:
    """Resolve brand site URL from 001 启动确认.md body (multiple formats)."""
    text = startup_text or ""

    heading = re.search(r"##\s*品牌官网\s*\n+([^\n#]+)", text)
    if heading:
        found = normalize_brand_site_url(heading.group(1))
        if found:
            return found

    inline = re.search(
        r"(?:\*\*)?品牌官网(?:\*\*)?[^\n]*?(https?://[^\s<>\"')\]]+)",
        text,
        re.I,
    )
    if inline:
        found = normalize_brand_site_url(inline.group(1))
        if found:
            return found

    keyed = re.search(
        r"brand[_ ]site[_ ]url[^\n]*?(https?://[^\s<>\"')\]]+)",
        text,
        re.I,
    )
    if keyed:
        found = normalize_brand_site_url(keyed.group(1))
        if found:
            return found

    return normalize_brand_site_url(fallback)


def pick_brand_site_url(
    explicit: str = "",
    urls: Iterable[str] | None = None,
    brand_text: str = "",
) -> str:
    """Prefer explicit URL; else 官网附近 URL; else shortest homepage-like candidate."""
    found = normalize_brand_site_url(explicit)
    if found:
        return found

    near = re.search(
        r"(?:品牌官网|官方网站|官网地址|官网)[^\n]*?(https?://[^\s<>\"')\]]+)",
        brand_text or "",
        re.I,
    )
    if near:
        found = normalize_brand_site_url(near.group(1))
        if found:
            return found

    candidates: list[tuple[int, int, str]] = []
    for raw in urls or []:
        url = normalize_brand_site_url(raw)
        if not url:
            continue
        parsed = urlparse(url)
        if not parsed.netloc:
            continue
        path = (parsed.path or "/").rstrip("/")
        depth = 0 if path in ("", "/") else path.count("/")
        # Prefer bare homepage over deep article links.
        candidates.append((depth, len(url), url))
    if not candidates:
        return ""
    candidates.sort()
    return candidates[0][2]
