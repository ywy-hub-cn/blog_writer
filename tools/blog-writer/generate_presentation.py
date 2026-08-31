#!/usr/bin/env python3
"""将字段化 HTML 包裹为完整呈现页 006 呈现文档.html。

供 S006 调用。保留所有 data-field / data-seq，注入 SEO meta 与设计系统 CSS。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from html import escape

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from brand_site_url import resolve_brand_site_url  # noqa: E402
from brand_css import resolve_presentation_css  # noqa: E402


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


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


def extract_meta(bid: Dict[str, Any], brand_site_url: str = "") -> Dict[str, str]:
    seo = bid.get("seo") if isinstance(bid.get("seo"), dict) else {}
    summary = bid.get("summary") if isinstance(bid.get("summary"), dict) else {}
    title = (
        _dig(bid, "title")
        or _dig(seo, "title")
        or _dig(summary, "title")
        or _dig(bid, "keyword")
        or "Untitled"
    )
    seo_title = (
        _dig(bid, "seo_title")
        or _dig(seo, "seo_title")
        or _dig(summary, "seo_title")
        or title
    )
    slug = _dig(bid, "slug") or _dig(seo, "slug") or _dig(summary, "slug") or "article"
    meta = (
        _dig(bid, "meta_description")
        or _dig(seo, "meta_description")
        or _dig(summary, "meta_description")
        or _dig(seo, "description")
        or title
    )
    if len(meta) > 160:
        meta = meta[:160]
    keyword = (
        _dig(bid, "keyword")
        or _dig(seo, "keyword")
        or _dig(summary, "keyword")
        or ""
    )
    site = brand_site_url.rstrip("/")
    url = f"{site}/{slug}" if site else ""
    return {
        "title": title,
        "seo_title": seo_title[:60],
        "slug": slug,
        "meta_description": meta,
        "keyword": keyword,
        "canonical": url,
        "og_url": url,
    }


def extract_brand_site_url(out_dir: Path, fallback: str = "") -> str:
    startup = _read(out_dir / "001 启动确认.md")
    return resolve_brand_site_url(startup, fallback)


def estimate_read_time(html_body: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html_body)
    words = len(re.findall(r"[A-Za-z0-9']+|[\u4e00-\u9fff]", text))
    # 中英混合：约 200 词/分钟
    minutes = max(1, math.ceil(words / 200))
    return minutes


def ensure_h1(body: str, title: str) -> str:
    if re.search(r"<h1[\s>]", body, re.I):
        return body
    return f"<h1>{escape(title)}</h1>\n{body}"


def build_presentation(
    field_html: str,
    meta: Dict[str, str],
    read_minutes: int,
    css: str,
) -> str:
    body = ensure_h1(field_html.strip(), meta["title"])
    # 若字段化结果已是完整文档，只做校验性包装时抽出 body
    if re.search(r"<!DOCTYPE\s+html>", body, re.I):
        m = re.search(r"<body[^>]*>([\s\S]*)</body>", body, re.I)
        if m:
            body = m.group(1).strip()

    canonical = meta.get("canonical") or ""
    og_url = meta.get("og_url") or canonical
    title = meta["seo_title"] or meta["title"]
    desc = meta["meta_description"]
    kw = meta.get("keyword") or ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
<meta name="keywords" content="{escape(kw)}">
<meta name="robots" content="index,follow">
{f'<link rel="canonical" href="{escape(canonical)}">' if canonical else ''}
<meta property="og:type" content="article">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(desc)}">
{f'<meta property="og:url" content="{escape(og_url)}">' if og_url else ''}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{escape(title)}">
<meta name="twitter:description" content="{escape(desc)}">
<style>
{css}
</style>
</head>
<body>
<article class="article-shell">
  <div class="blog-meta">
    <span class="read-time">{read_minutes} min read</span>
  </div>
  <div class="blog-content">
{body}
  </div>
</article>
</body>
</html>
"""


def generate(out_dir: Path, brand_site_url: str = "") -> Path:
    field_path = out_dir / "005 字段化文档.html"
    if not field_path.exists():
        raise SystemExit(f"ERROR: 缺少 {field_path.name}")

    field_html = field_path.read_text(encoding="utf-8")
    if "data-field=" not in field_html:
        raise SystemExit("ERROR: 字段化文档缺少 data-field 属性")

    site = extract_brand_site_url(out_dir, brand_site_url)
    bid = _load_bid(out_dir)
    meta = extract_meta(bid, site)
    minutes = estimate_read_time(field_html)
    css = resolve_presentation_css(out_dir)
    html_doc = build_presentation(field_html, meta, minutes, css)

    out_path = out_dir / "006 呈现文档.html"
    out_path.write_text(html_doc, encoding="utf-8")
    # S007 曾依赖仓库中不存在的 Unsplash/Pexels 脚本，导致流水线只有告警、
    # 没有任何图片。呈现阶段确定性注入可用视觉元素，确保后续发布包始终带图。
    import importlib.util

    visual_script = Path(__file__).resolve().parent / "inject_visuals.py"
    spec = importlib.util.spec_from_file_location("inject_visuals", visual_script)
    if not spec or not spec.loader:
        raise SystemExit("ERROR: 无法加载 inject_visuals.py")
    visual_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(visual_mod)
    visual_mod.run(out_dir, media_site_url=site)
    print(f"OK: wrote {out_path.name} (read-time={minutes}min)", file=sys.stderr)
    print(f"OK: {out_path}")
    return out_path


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="生成 006 呈现文档.html")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--brand-site-url", default="")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).resolve()
    if not out_dir.is_dir():
        print(f"ERROR: out-dir 不存在: {out_dir}", file=sys.stderr)
        return 1
    try:
        generate(out_dir, brand_site_url=args.brand_site_url)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
