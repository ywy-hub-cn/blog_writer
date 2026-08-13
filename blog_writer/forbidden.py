"""单次任务禁用词白名单工具。"""
from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional


_MAX_ITEMS = 50
_MAX_ITEM_LEN = 100


def normalize_forbidden_whitelist(value: Any) -> List[str]:
    """将字符串/列表规范化为去重后的白名单词条（保序）。

    支持分隔符：英文逗号、中文逗号、分号、换行。
    """
    if value is None:
        return []

    raw: List[str] = []
    if isinstance(value, str):
        raw = [p.strip() for p in re.split(r"[,，\n;；]+", value) if p.strip()]
    elif isinstance(value, (list, tuple)):
        for item in value:
            if item is None:
                continue
            if isinstance(item, str) and re.search(r"[,，\n;；]", item):
                raw.extend(normalize_forbidden_whitelist(item))
            else:
                s = str(item).strip()
                if s:
                    raw.append(s)
    else:
        s = str(value).strip()
        if s:
            raw.append(s)

    seen = set()
    out: List[str] = []
    for w in raw:
        w = w[:_MAX_ITEM_LEN].strip()
        if not w:
            continue
        key = w.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
        if len(out) >= _MAX_ITEMS:
            break
    return out


def is_whitelisted(word: str, whitelist: Iterable[str]) -> bool:
    """大小写不敏感；白名单词可精确匹配，或以白名单词为子串豁免禁用词条。"""
    w = (word or "").casefold().strip()
    if not w:
        return False
    for allowed in whitelist:
        a = (allowed or "").casefold().strip()
        if not a:
            continue
        if w == a or a in w or w in a:
            return True
    return False


def filter_forbidden_words(
    forbidden: Iterable[str],
    whitelist: Optional[Iterable[str]] = None,
) -> List[str]:
    """从禁用词列表中剔除本次白名单词。"""
    wl = list(whitelist or [])
    return [w for w in forbidden if not is_whitelisted(w, wl)]
