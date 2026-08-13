#!/usr/bin/env python3
"""检测正文是否命中品牌禁用词（支持单次任务白名单豁免）。

用法:
  python check_forbidden.py --out-dir .
  python check_forbidden.py --out-dir . --body "004 正文.md"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Set


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _extract_section(text: str, heading: str) -> str:
    m = re.search(
        rf"##\s*{re.escape(heading)}\s*\n([\s\S]*?)(?=\n##\s|\Z)",
        text,
    )
    return m.group(1) if m else ""


def parse_word_lines(section: str) -> List[str]:
    words: List[str] = []
    for line in section.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # - word / * word / 1. word
        m = re.match(r"^(?:[-*+]|\d+[.)])\s+(.+)$", line)
        if m:
            w = m.group(1).strip().strip("`\"'")
            if w:
                words.append(w)
            continue
        # 纯词行（非标题）
        if len(line) > 1 and not line.startswith("|"):
            words.append(line.strip("`\"'"))
    # 去重保序
    seen: Set[str] = set()
    out: List[str] = []
    for w in words:
        key = w.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def load_whitelist(out_dir: Path, startup: str) -> List[str]:
    words: List[str] = []
    jl = out_dir / "forbidden_whitelist.json"
    if jl.exists():
        try:
            data = json.loads(jl.read_text(encoding="utf-8"))
            if isinstance(data, list):
                words.extend(str(x).strip() for x in data if str(x).strip())
            elif isinstance(data, dict) and isinstance(data.get("words"), list):
                words.extend(str(x).strip() for x in data["words"] if str(x).strip())
        except json.JSONDecodeError:
            pass
    section = _extract_section(startup, "本次禁用词白名单")
    words.extend(parse_word_lines(section))
    seen: Set[str] = set()
    out: List[str] = []
    for w in words:
        key = w.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def is_whitelisted(word: str, whitelist: List[str]) -> bool:
    w = word.casefold().strip()
    for a in whitelist:
        aa = a.casefold().strip()
        if not aa:
            continue
        if w == aa or aa in w or w in aa:
            return True
    return False


def find_hits(body: str, forbidden: List[str], whitelist: List[str]) -> List[str]:
    body_l = body.casefold()
    hits: List[str] = []
    for word in forbidden:
        if is_whitelisted(word, whitelist):
            continue
        if word.casefold() in body_l:
            hits.append(word)
    return hits


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="禁用词检测（含单次白名单）")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--body", default="004 正文.md")
    parser.add_argument("--startup", default="001 启动确认.md")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).resolve()
    startup = _read(out_dir / args.startup)
    body_path = out_dir / args.body
    if not body_path.exists():
        print(f"ERROR: 正文不存在: {body_path.name}", file=sys.stderr)
        return 1
    body = body_path.read_text(encoding="utf-8")

    forbidden_section = _extract_section(startup, "禁用词原文")
    forbidden = parse_word_lines(forbidden_section)
    whitelist = load_whitelist(out_dir, startup)
    effective = [w for w in forbidden if not is_whitelisted(w, whitelist)]
    hits = find_hits(body, effective, [])

    print(f"词库大小: {len(forbidden)} | 白名单: {len(whitelist)} | 生效: {len(effective)}")
    if whitelist:
        print("白名单:", ", ".join(whitelist))
    if hits:
        print("❌ 禁用词命中:", hits)
        return 1
    print("✅ 无禁用词命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())
