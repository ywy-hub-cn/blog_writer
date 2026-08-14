#!/usr/bin/env python3
"""组装 007 发布包.md / 007 发布包.json。

从 BID、呈现 HTML、启动确认等产物确定性生成发布包，供 S010 调用。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


SECTION_ORDER = [
    "Keyword",
    "Title",
    "SEO title",
    "Slug",
    "Meta description",
    "Excerpt",
    "Final article body",
]


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _load_bid(out_dir: Path) -> Dict[str, Any]:
    for name in ("000 BID.json", "000_BID.json", "BID.json"):
        p = out_dir / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
    return {}


def _dig(bid: Dict[str, Any], *keys: str, default: str = "") -> str:
    cur: Any = bid
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    if cur is None:
        return default
    return str(cur).strip()


def extract_fields(
    bid: Dict[str, Any],
    *,
    keyword: str = "",
    title: str = "",
    slug: str = "",
    meta_description: str = "",
) -> Dict[str, str]:
    seo = bid.get("seo") if isinstance(bid.get("seo"), dict) else {}
    content = bid.get("content") if isinstance(bid.get("content"), dict) else {}
    summary = bid.get("summary") if isinstance(bid.get("summary"), dict) else {}
    bid_core = _dig(bid, "bid", "core", default="") if isinstance(bid.get("bid"), dict) else ""

    kw = (
        keyword
        or _dig(bid, "keyword")
        or _dig(bid, "focus_keyword")
        or _dig(seo, "keyword")
        or _dig(content, "keyword")
        or _dig(summary, "keyword")
        or (bid_core.get("th") if isinstance(bid_core, dict) else "")
    )
    ttl = (
        title
        or _dig(bid, "title")
        or _dig(seo, "title")
        or _dig(content, "title")
        or _dig(summary, "title")
        or kw
    )
    seo_title = (
        _dig(bid, "seo_title")
        or _dig(seo, "seo_title")
        or _dig(summary, "seo_title")
        or _dig(seo, "title")
        or ttl
    )
    sl = (
        slug
        or _dig(bid, "slug")
        or _dig(seo, "slug")
        or _dig(summary, "slug")
        or re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-")
    )
    meta = (
        meta_description
        or _dig(bid, "meta_description")
        or _dig(seo, "meta_description")
        or _dig(summary, "meta_description")
        or _dig(seo, "description")
        or ""
    )
    if len(meta) > 160:
        meta = meta[:157].rstrip() + "..."
        # 规范要求不以 ... 结尾时，改为硬截断到 160
        if meta.endswith("..."):
            meta = meta[:160]

    excerpt = (
        _dig(bid, "excerpt")
        or _dig(content, "excerpt")
        or _dig(summary, "excerpt")
        or meta[:120]
    )

    return {
        "keyword": kw,
        "title": ttl,
        "seo_title": seo_title[:60] if seo_title else "",
        "slug": sl,
        "meta_description": meta[:160],
        "excerpt": excerpt,
    }


def extract_brand_site_url(out_dir: Path, fallback: str = "") -> str:
    startup = _read_text(out_dir / "001 启动确认.md")
    m = re.search(r"##\s*品牌官网\s*\n+([^\n#]+)", startup)
    if m:
        url = m.group(1).strip()
        if url.startswith("http"):
            return url
    m2 = re.search(r"https?://[^\s)]+", startup)
    if m2:
        return m2.group(0).rstrip(".,;")
    return fallback.strip()


def extract_article_html(out_dir: Path) -> str:
    html = _read_text(out_dir / "006 呈现文档.html")
    if not html:
        html = _read_text(out_dir / "005 字段化文档.html")
    if not html:
        return ""

    # 优先 blog-content 容器
    m = re.search(
        r'<div[^>]*class=["\'][^"\']*blog-content[^"\']*["\'][^>]*>([\s\S]*?)</div>',
        html,
        re.I,
    )
    if m:
        body = m.group(1).strip()
    else:
        m2 = re.search(r"<body[^>]*>([\s\S]*?)</body>", html, re.I)
        body = (m2.group(1) if m2 else html).strip()

    if "itemscope" in body and "<article" in body.lower():
        inner = body
    else:
        inner = (
            '<article itemscope itemtype="https://schema.org/BlogPosting">\n'
            f"{body}\n"
            "</article>"
        )

    if re.search(r"```mermaid|class=\"mermaid\"|<div class=\"mermaid\">", inner, re.I):
        cdn = (
            '<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js">'
            "</script>\n<script>mermaid.initialize({startOnLoad:true});</script>\n"
        )
        if "mermaid.min.js" not in inner:
            inner = cdn + inner

    return inner.strip()


def find_cover_image(html: str) -> str:
    m = re.search(
        r'<img[^>]+src=["\']([^"\']+)["\'][^>]*(?:data-seq=["\']cover["\']|data-field=["\']image["\'])',
        html,
        re.I,
    )
    if m:
        return m.group(1)
    m2 = re.search(
        r'data-seq=["\']cover["\'][^>]*>[\s\S]*?<img[^>]+src=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if m2:
        return m2.group(1)
    m3 = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I)
    return m3.group(1) if m3 else ""


def render_publish_md(fields: Dict[str, str], article_html: str) -> str:
    blocks = {
        "Keyword": ("text", fields["keyword"]),
        "Title": ("text", fields["title"]),
        "SEO title": ("text", fields["seo_title"]),
        "Slug": ("text", fields["slug"]),
        "Meta description": ("text", fields["meta_description"]),
        "Excerpt": ("text", fields["excerpt"]),
        "Final article body": ("html", article_html),
    }
    parts = []
    for name in SECTION_ORDER:
        lang, content = blocks[name]
        parts.append(f"### {name}\n\n```{lang}\n{content}\n```\n")
    return "\n".join(parts).rstrip() + "\n"


def assemble(
    out_dir: Path,
    *,
    brand_site_url: str = "",
    keyword: str = "",
    title: str = "",
    slug: str = "",
    meta_description: str = "",
) -> Tuple[Path, Path]:
    bid = _load_bid(out_dir)
    fields = extract_fields(
        bid,
        keyword=keyword,
        title=title,
        slug=slug,
        meta_description=meta_description,
    )
    site = extract_brand_site_url(out_dir, brand_site_url)
    article_html = extract_article_html(out_dir)
    if not article_html:
        raise SystemExit("ERROR: 未找到 006 呈现文档.html / 005 字段化文档.html 可用正文")

    md_path = out_dir / "007 发布包.md"
    json_path = out_dir / "007 发布包.json"

    for p in (md_path, json_path):
        if p.exists():
            p.unlink()

    md_path.write_text(render_publish_md(fields, article_html), encoding="utf-8")

    payload = {
        "keyword": fields["keyword"],
        "title": fields["title"],
        "seo_title": fields["seo_title"],
        "slug": fields["slug"],
        "meta_description": fields["meta_description"],
        "excerpt": fields["excerpt"],
        "cover_image": find_cover_image(article_html),
        "brand_site_url": site,
        "body_html": article_html,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 格式自检
    first = md_path.read_text(encoding="utf-8").splitlines()[:1]
    if not first or first[0].strip() != "### Keyword":
        raise SystemExit("ERROR: 发布包格式校验失败：第一行必须是 '### Keyword'")
    heading_count = sum(
        1
        for line in md_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("### ")
    )
    if heading_count != 7:
        raise SystemExit(f"ERROR: 期望 7 个 ### 标题，实际 {heading_count}")

    print(f"OK: 已写入 {md_path.name} 与 {json_path.name}")
    return md_path, json_path


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="组装 WordPress 发布包")
    parser.add_argument("--out-dir", required=True, help="实例输出目录")
    parser.add_argument("--brand-site-url", default="", help="品牌官网 URL")
    parser.add_argument("--keyword", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--slug", default="")
    parser.add_argument("--meta-description", default="")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).resolve()
    if not out_dir.is_dir():
        print(f"ERROR: out-dir 不存在: {out_dir}", file=sys.stderr)
        return 1

    try:
        assemble(
            out_dir,
            brand_site_url=args.brand_site_url,
            keyword=args.keyword,
            title=args.title,
            slug=args.slug,
            meta_description=args.meta_description,
        )
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
