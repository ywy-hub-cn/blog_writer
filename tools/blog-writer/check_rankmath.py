#!/usr/bin/env python3
"""校验 007 发布包的 Rank Math / SEO 基本合规性。"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def parse_sections(md_text: str) -> dict:
    sections = {}
    pattern = re.compile(r"###\s*(.+?)\s*\n+```(?:text|html)?\n([\s\S]*?)\n```", re.I)
    for m in pattern.finditer(md_text):
        sections[m.group(1).strip()] = m.group(2).strip()
    return sections


def check(out_dir: Path) -> int:
    md_path = out_dir / "007 发布包.md"
    if not md_path.exists():
        print("ERROR: 缺少 007 发布包.md")
        return 1
    sections = parse_sections(md_path.read_text(encoding="utf-8"))
    issues = []
    seo_title = sections.get("SEO title", "")
    meta = sections.get("Meta description", "")
    slug = sections.get("Slug", "")
    keyword = sections.get("Keyword", "")

    if len(seo_title) > 60:
        issues.append(f"SEO title 超长 ({len(seo_title)}>60)，建议缩短")
    if len(meta) > 160:
        issues.append(f"Meta description 超长 ({len(meta)}>160)")
    if meta.endswith("..."):
        issues.append("Meta description 以 ... 结尾，建议写完整句")
    if keyword and keyword.lower() not in meta.lower():
        issues.append("Meta description 未包含 focus keyword")
    if keyword:
        kw_slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
        if kw_slug and kw_slug not in slug.lower() and keyword.lower().replace(" ", "-") not in slug.lower():
            # 宽松：关键词任一单词出现在 slug
            words = [w for w in re.split(r"\W+", keyword.lower()) if len(w) > 2]
            if words and not any(w in slug.lower() for w in words):
                issues.append("Slug 未包含 focus keyword")

    if issues:
        print("Rank Math 校验发现问题:")
        for i, msg in enumerate(issues, 1):
            print(f"  {i}. {msg}")
        return 1

    print("OK: Rank Math 基本合规")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    return check(Path(args.out_dir).resolve())


if __name__ == "__main__":
    sys.exit(main())
