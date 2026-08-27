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

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from brand_site_url import resolve_brand_site_url  # noqa: E402


SECTION_ORDER = [
    "Keyword",
    "Title",
    "SEO title",
    "Slug",
    "Meta description",
    "Excerpt",
    "Final article body",
]

PUBLISH_THEME_CSS = """
.tuoying-bw-article,.tuoying-bw-article *{box-sizing:border-box}
.tuoying-bw-article{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Oxygen-Sans,Ubuntu,Cantarell,"Helvetica Neue",sans-serif;color:#39433C;background:#fff;margin:0 auto;max-width:720px;padding:0 24px 80px;font-size:19px;line-height:1.74}
.tuoying-bw-article>p:first-of-type{font-size:21px;line-height:1.62;color:#2D3831}
.tuoying-bw-article h1{font-size:clamp(38px,4vw,52px);line-height:1.08;color:#132019;margin:0 0 32px}
.tuoying-bw-article h2{font-size:clamp(32px,3vw,44px);font-weight:600;line-height:1.12;color:#132019;margin:78px 0 32px}
.tuoying-bw-article h3{font-size:clamp(22px,1.8vw,27px);font-weight:600;line-height:1.28;color:#213027;margin:48px 0 16px}
.tuoying-bw-article p{margin:0 0 20px}
.tuoying-bw-article a{color:#5D765F;text-decoration:underline;overflow-wrap:anywhere}
.tuoying-bw-article ul,.tuoying-bw-article ol{background:#EEF3EC;border:1px solid #C9D5C5;border-radius:18px;padding:22px 26px 22px 36px;margin:22px 0 32px}
.tuoying-bw-article li{margin:9px 0}
.tuoying-bw-article figure{margin:40px 0;width:100%}
.tuoying-bw-article figure img{display:block;width:100%;height:auto;border-radius:22px}
.tuoying-bw-article figcaption{font-size:14px;color:#687268;margin-top:10px;text-align:center}
.tuoying-bw-article table{width:100%;border-collapse:collapse;margin:24px 0}
.tuoying-bw-article th,.tuoying-bw-article td{border:1px solid #DFE2DA;padding:12px;text-align:left}
.tuoying-bw-article blockquote{margin:24px 0;padding:16px 20px;border-left:4px solid #5D765F;background:#F5F8F3}
.tuoying-bw-article .faq-section,.tuoying-bw-article .references-section{background:#FBFCF8;border:1px solid #DFE2DA;border-radius:24px;padding:34px;margin-top:76px}
.tuoying-bw-article .faq-section h2,.tuoying-bw-article .references-section h2{font-size:clamp(30px,2.8vw,40px);margin:0 0 26px}
.tuoying-bw-article .faq-item{background:#F1F5EF;border:1px solid #C9D5C5;border-radius:18px;margin-bottom:14px;overflow:hidden}
.tuoying-bw-article .faq-item summary{font-size:19px;font-weight:600;color:#132019;padding:18px 48px 18px 20px;cursor:pointer}
.tuoying-bw-article .faq-answer{background:#F6F8F3;border-top:1px solid #C9D5C5;padding:18px 20px 20px}
.tuoying-bw-article .faq-answer p{font-size:17px;margin:0}
.tuoying-bw-article .references-section p{background:#F1F3ED;border:1px solid #DFE2DA;border-radius:14px;padding:14px 16px;font-size:14px;color:#687268}
@media(max-width:768px){.tuoying-bw-article{padding:0 16px 60px;font-size:17px}.tuoying-bw-article h2{font-size:31px;margin:58px 0 24px}.tuoying-bw-article h3{font-size:23px;margin:38px 0 16px}}
""".strip()


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
    return resolve_brand_site_url(startup, fallback)


def _extract_div_by_class(html: str, class_name: str) -> str:
    """Extract a div's complete inner HTML while respecting nested divs."""
    div_tag = re.compile(r"</?div\b[^>]*>", re.I)
    class_attr = re.compile(r"""class\s*=\s*["']([^"']*)["']""", re.I)
    start_end = None

    for match in div_tag.finditer(html):
        tag = match.group(0)
        if tag.startswith("</"):
            continue
        attr = class_attr.search(tag)
        classes = attr.group(1).split() if attr else []
        if class_name in classes:
            start_end = match.end()
            break

    if start_end is None:
        return ""

    depth = 1
    for match in div_tag.finditer(html, start_end):
        if match.group(0).startswith("</"):
            depth -= 1
            if depth == 0:
                return html[start_end:match.start()].strip()
        else:
            depth += 1
    return ""


def extract_article_html(out_dir: Path) -> str:
    html = _read_text(out_dir / "006 呈现文档.html")
    if not html:
        html = _read_text(out_dir / "005 字段化文档.html")
    if not html:
        return ""

    # 优先 blog-content 容器。不能用非贪婪正则匹配 </div>：
    # FAQ、图片等都包含嵌套 div，会导致正文从第一个嵌套闭合标签处截断。
    blog_content = _extract_div_by_class(html, "blog-content")
    if blog_content:
        body = blog_content
    else:
        m2 = re.search(r"<body[^>]*>([\s\S]*?)</body>", html, re.I)
        body = (m2.group(1) if m2 else html).strip()

    if "itemscope" in body and "<article" in body.lower():
        inner = body
    else:
        inner = (
            f'<style id="blog-writer-theme">{PUBLISH_THEME_CSS}</style>\n'
            '<article class="tuoying-bw-article" itemscope '
            'itemtype="https://schema.org/BlogPosting">\n'
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
        "schema_version": "1.0",
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
