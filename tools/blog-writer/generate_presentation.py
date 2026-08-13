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


CSS = """
:root {
  --green: #5D765F;
  --green-hover: #4D6350;
  --green-dark: #3F5242;
  --green-light-bg: #EEF3EC;
  --green-lighter-bg: #F5F8F3;
  --heading-primary: #132019;
  --heading-secondary: #213027;
  --text-body: #39433C;
  --text-muted: #687268;
  --section-bg: #FBFCF8;
  --faq-question-bg: #F1F5EF;
  --faq-answer-bg: #F6F8F3;
  --border-default: #DFE2DA;
  --border-green: #C9D5C5;
  --ref-bg: #F1F3ED;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: var(--font);
  color: var(--text-body);
  background: #fff;
  line-height: 1.74;
}
.article-shell {
  max-width: 760px;
  margin: 0 auto;
  padding: 48px 20px 80px;
}
.blog-meta {
  display: flex;
  gap: 16px;
  align-items: center;
  color: var(--text-muted);
  font-size: 14px;
  margin-bottom: 20px;
}
.read-time { font-weight: 500; }
.blog-content h1 {
  font-size: clamp(38px, 4vw, 52px);
  font-weight: 600;
  line-height: 1.08;
  letter-spacing: -0.02em;
  color: var(--heading-primary);
  margin: 0 0 32px;
}
.blog-content h2 {
  font-size: clamp(32px, 3vw, 44px);
  font-weight: 600;
  line-height: 1.12;
  letter-spacing: -0.035em;
  color: var(--heading-primary);
  margin: 78px 0 32px;
}
.blog-content h3 {
  font-size: clamp(22px, 1.8vw, 27px);
  font-weight: 600;
  line-height: 1.28;
  color: var(--heading-secondary);
  margin: 48px 0 16px;
}
.blog-content p {
  font-size: 19px;
  margin: 0 0 20px;
}
.blog-content p[data-field="hook"] {
  font-size: 20px;
  line-height: 1.62;
  color: #2D3831;
}
.blog-content ul, .blog-content ol {
  background: var(--green-light-bg);
  border: 1px solid var(--border-green);
  border-radius: 18px;
  padding: 22px 26px 22px 36px;
  margin: 22px 0 32px;
}
.blog-content li { margin: 0 0 9px; font-size: 19px; }
.blog-content a {
  color: #268C37;
  text-decoration: none;
  font-weight: 500;
}
.blog-content a:hover { color: #1F6F2C; }
.faq-section {
  background: var(--section-bg);
  border: 1px solid var(--border-default);
  border-radius: 24px;
  padding: 34px;
  margin-top: 76px;
}
.faq-item {
  background: var(--faq-question-bg);
  border: 1px solid var(--border-green);
  border-radius: 18px;
  padding: 18px 20px;
  margin: 0 0 14px;
}
.faq-answer {
  background: var(--faq-answer-bg);
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 12px;
}
.references-section {
  background: var(--ref-bg);
  border-radius: 18px;
  padding: 28px;
  margin-top: 56px;
}
.blog-content table {
  width: 100%;
  border-collapse: collapse;
  margin: 24px 0;
}
.blog-content th, .blog-content td {
  border: 1px solid var(--border-default);
  padding: 10px 12px;
  text-align: left;
}
blockquote {
  margin: 24px 0;
  padding: 16px 20px;
  border-left: 4px solid var(--green);
  background: var(--green-lighter-bg);
}
@media (max-width: 640px) {
  .blog-content p { font-size: 17px; }
  .blog-content h2 { font-size: 31px; margin-top: 58px; }
  .blog-content h3 { font-size: 23px; }
}
""".strip()


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
    title = (
        _dig(bid, "title")
        or _dig(seo, "title")
        or _dig(bid, "keyword")
        or "Untitled"
    )
    seo_title = _dig(bid, "seo_title") or _dig(seo, "seo_title") or title
    slug = _dig(bid, "slug") or _dig(seo, "slug") or "article"
    meta = (
        _dig(bid, "meta_description")
        or _dig(seo, "meta_description")
        or _dig(seo, "description")
        or title
    )
    if len(meta) > 160:
        meta = meta[:160]
    keyword = _dig(bid, "keyword") or _dig(seo, "keyword") or ""
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
    m = re.search(r"##\s*品牌官网\s*\n+([^\n#]+)", startup)
    if m:
        return m.group(1).strip()
    return (fallback or "").strip()


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
{CSS}
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
    html_doc = build_presentation(field_html, meta, minutes)

    out_path = out_dir / "006 呈现文档.html"
    out_path.write_text(html_doc, encoding="utf-8")
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
