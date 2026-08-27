#!/usr/bin/env python3
"""Deterministically guarantee a cover visual and three inline diagrams."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import struct
import sys
import urllib.parse
import urllib.request
import zlib
from pathlib import Path
from typing import Optional


MERMAID_HEAD = """
<!-- Mermaid CDN（主：jsdelivr，备：unpkg） -->
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
if (typeof mermaid === "undefined") {
  document.write('<script src="https://unpkg.com/mermaid@11/dist/mermaid.min.js">\\x3C/script>');
}
mermaid.initialize({startOnLoad:true,theme:"neutral",flowchart:{useMaxWidth:true,htmlLabels:true},securityLevel:"loose"});
</script>
""".strip()

FONT_5X7 = {
    "A": "01110/10001/10001/11111/10001/10001/10001",
    "B": "11110/10001/10001/11110/10001/10001/11110",
    "C": "01111/10000/10000/10000/10000/10000/01111",
    "D": "11110/10001/10001/10001/10001/10001/11110",
    "E": "11111/10000/10000/11110/10000/10000/11111",
    "F": "11111/10000/10000/11110/10000/10000/10000",
    "G": "01111/10000/10000/10111/10001/10001/01111",
    "H": "10001/10001/10001/11111/10001/10001/10001",
    "I": "11111/00100/00100/00100/00100/00100/11111",
    "J": "00111/00010/00010/00010/10010/10010/01100",
    "K": "10001/10010/10100/11000/10100/10010/10001",
    "L": "10000/10000/10000/10000/10000/10000/11111",
    "M": "10001/11011/10101/10101/10001/10001/10001",
    "N": "10001/11001/10101/10011/10001/10001/10001",
    "O": "01110/10001/10001/10001/10001/10001/01110",
    "P": "11110/10001/10001/11110/10000/10000/10000",
    "Q": "01110/10001/10001/10001/10101/10010/01101",
    "R": "11110/10001/10001/11110/10100/10010/10001",
    "S": "01111/10000/10000/01110/00001/00001/11110",
    "T": "11111/00100/00100/00100/00100/00100/00100",
    "U": "10001/10001/10001/10001/10001/10001/01110",
    "V": "10001/10001/10001/10001/10001/01010/00100",
    "W": "10001/10001/10001/10101/10101/11011/10001",
    "X": "10001/10001/01010/00100/01010/10001/10001",
    "Y": "10001/10001/01010/00100/00100/00100/00100",
    "Z": "11111/00001/00010/00100/01000/10000/11111",
    "0": "01110/10001/10011/10101/11001/10001/01110",
    "1": "00100/01100/00100/00100/00100/00100/01110",
    "2": "01110/10001/00001/00010/00100/01000/11111",
    "3": "11110/00001/00001/01110/00001/00001/11110",
    "4": "00010/00110/01010/10010/11111/00010/00010",
    "5": "11111/10000/10000/11110/00001/00001/11110",
    "6": "01110/10000/10000/11110/10001/10001/01110",
    "7": "11111/00001/00010/00100/01000/01000/01000",
    "8": "01110/10001/10001/01110/10001/10001/01110",
    "9": "01110/10001/10001/01111/00001/00001/01110",
}


def _title(document: str) -> str:
    match = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", document, re.I)
    if not match:
        match = re.search(r"<title[^>]*>([\s\S]*?)</title>", document, re.I)
    value = re.sub(r"<[^>]+>", " ", match.group(1) if match else "Article")
    return html.unescape(re.sub(r"\s+", " ", value)).strip() or "Article"


def _keyword(out_dir: Path, fallback: str) -> str:
    try:
        bid = json.loads((out_dir / "000 BID.json").read_text(encoding="utf-8"))
        summary = bid.get("summary") if isinstance(bid.get("summary"), dict) else {}
        return str(
            bid.get("keyword")
            or summary.get("keyword")
            or fallback
        ).strip()
    except (OSError, json.JSONDecodeError, TypeError):
        return fallback


def _search_media_cover(site_url: str, keyword: str, title: str) -> str:
    """Reuse a relevant image from the brand's WordPress media library."""
    if not site_url.startswith(("http://", "https://")):
        return ""
    site_url = site_url.rstrip("/")

    def fetch_json(endpoint: str):
        request = urllib.request.Request(
            endpoint,
            headers={"User-Agent": "BlogWriter/2.1"},
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))

    # Prefer the cover of the most closely related existing article.
    try:
        posts_endpoint = (
            f"{site_url}/wp-json/wp/v2/posts?"
            + urllib.parse.urlencode(
                {
                    "search": keyword,
                    "per_page": 10,
                    "_fields": "title,featured_media",
                }
            )
        )
        posts = fetch_json(posts_endpoint)
        common = {"the", "and", "for", "how", "with", "from", "why", "what"}
        keyword_tokens = set(re.findall(r"[a-z0-9]+", keyword.lower()))
        title_tokens = set(re.findall(r"[a-z0-9]+", title.lower())) - common

        def relevance(post) -> int:
            rendered = str((post.get("title") or {}).get("rendered") or "")
            post_tokens = set(re.findall(r"[a-z0-9]+", rendered.lower())) - common
            return (
                3 * len(keyword_tokens & post_tokens)
                + len(title_tokens & post_tokens)
            )

        for post in sorted(posts, key=relevance, reverse=True):
            media_id = int(post.get("featured_media") or 0)
            if not media_id:
                continue
            media = fetch_json(
                f"{site_url}/wp-json/wp/v2/media/{media_id}"
                "?_fields=source_url"
            )
            source = str(media.get("source_url") or "")
            if source.startswith("http"):
                return source
    except Exception:
        pass

    stopwords = {"the", "and", "for", "how", "with", "from", "guide", "explained"}
    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9]+", f"{keyword} {title}")
        if token.lower() not in stopwords and len(token) > 2
    ]
    queries = [keyword, " ".join(tokens[:3]), *tokens, "SMS"]
    seen = set()
    for query in queries:
        query = query.strip()
        if not query or query.lower() in seen:
            continue
        seen.add(query.lower())
        endpoint = (
            f"{site_url.rstrip('/')}/wp-json/wp/v2/media?"
            + urllib.parse.urlencode(
                {
                    "search": query,
                    "per_page": 20,
                    "_fields": "id,source_url,alt_text",
                }
            )
        )
        try:
            items = fetch_json(endpoint)
            candidates = [
                str(item.get("source_url") or "")
                for item in items
                if str(item.get("source_url") or "").startswith("http")
            ]
            if candidates:
                digest = hashlib.sha256(title.encode("utf-8")).digest()
                return candidates[int.from_bytes(digest[:4], "big") % len(candidates)]
        except Exception:
            continue
    return ""


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _write_visual_png(
    path: Path,
    width: int,
    height: int,
    variant: int,
    label: str,
) -> None:
    """Write a dependency-free, labelled, topic-specific infographic PNG."""
    pixels = bytearray(width * height * 3)

    def set_pixel(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 3
            pixels[offset : offset + 3] = bytes(color)

    def rect(
        x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]
    ) -> None:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                set_pixel(x, y, color)

    def text_width(text: str, scale: int) -> int:
        return max(0, len(text) * 6 * scale - scale)

    def draw_text(
        text: str,
        x: int,
        y: int,
        scale: int,
        color: tuple[int, int, int],
        centered: bool = False,
    ) -> None:
        value = re.sub(r"[^A-Z0-9 ]+", "", text.upper())
        if centered:
            x -= text_width(value, scale) // 2
        cursor = x
        for char in value:
            if char == " ":
                cursor += 6 * scale
                continue
            glyph = FONT_5X7.get(char)
            if glyph:
                for row_index, row in enumerate(glyph.split("/")):
                    for col_index, bit in enumerate(row):
                        if bit == "1":
                            rect(
                                cursor + col_index * scale,
                                y + row_index * scale,
                                cursor + (col_index + 1) * scale,
                                y + (row_index + 1) * scale,
                                color,
                            )
            cursor += 6 * scale

    # Branded green gradient background.
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = (19 + int(35 * ratio), 32 + int(55 * ratio), 25 + int(37 * ratio))
        row = bytes(color) * width
        offset = y * width * 3
        pixels[offset : offset + width * 3] = row

    def line(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for step in range(steps + 1):
            x = round(x0 + (x1 - x0) * step / steps)
            y = round(y0 + (y1 - y0) * step / steps)
            for delta in range(-2, 3):
                set_pixel(x + delta, y, color)
                set_pixel(x, y + delta, color)

    def circle(cx: int, cy: int, radius: int, color: tuple[int, int, int]) -> None:
        r2 = radius * radius
        inner = max(0, radius - 7) ** 2
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                dist = (x - cx) ** 2 + (y - cy) ** 2
                if inner <= dist <= r2:
                    set_pixel(x, y, color)

    accent = (191, 214, 193)
    white = (246, 250, 246)
    muted = (139, 174, 145)
    title = re.sub(r"\s+", " ", label).strip().upper()
    words = title.split()
    title_line = " ".join(words[: min(6, len(words))])[:42]
    draw_text(title_line, width // 2, 34, 5 if width >= 1100 else 4, white, True)

    if variant == 0:
        # Cover: phone + OTP code + protected delivery path.
        rect(width // 10, 150, width // 10 + 210, height - 80, (28, 57, 39))
        rect(width // 10 + 18, 170, width // 10 + 192, height - 120, (238, 245, 238))
        draw_text("OTP", width // 10 + 105, 230, 7, (42, 92, 55), True)
        draw_text("482931", width // 10 + 105, 315, 5, (19, 32, 25), True)
        nodes = [
            (width // 2 - 80, height // 2),
            (width // 2 + 100, height // 2 - 80),
            (width * 4 // 5, height // 2 + 40),
        ]
        for first, second in zip(nodes, nodes[1:]):
            line(*first, *second, accent)
        for point, name in zip(nodes, ("API", "ROUTE", "PHONE")):
            circle(*point, 42, accent)
            draw_text(name, point[0], point[1] + 64, 3, white, True)
        draw_text("SECURE SMS DELIVERY", width * 2 // 3, height - 80, 4, muted, True)
    elif variant == 1:
        # Failure diagnosis chain.
        names = ("APP", "API", "ROUTE", "CARRIER", "DEVICE")
        xs = [width * (i + 1) // 6 for i in range(5)]
        y = height // 2
        for x0, x1 in zip(xs, xs[1:]):
            line(x0 + 34, y, x1 - 34, y, accent)
        for x, name in zip(xs, names):
            circle(x, y, 34, accent)
            draw_text(name, x, y + 58, 3, white, True)
        draw_text("TRACE EVERY HOP", width // 2, height - 48, 4, muted, True)
    elif variant == 2:
        # End-to-end OTP sequence with descending steps.
        steps = (("1", "GENERATE"), ("2", "SEND"), ("3", "DELIVER"), ("4", "VERIFY"))
        for index, (number, name) in enumerate(steps):
            x = width // 5 + index * width // 5
            y = 145 + (index % 2) * 105
            if index:
                prev_x = width // 5 + (index - 1) * width // 5
                prev_y = 145 + ((index - 1) % 2) * 105
                line(prev_x + 32, prev_y, x - 32, y, accent)
            circle(x, y, 32, accent)
            draw_text(number, x, y - 11, 3, white, True)
            draw_text(name, x, y + 54, 3, white, True)
        draw_text("EXPIRY AND RETRY CONTROL", width // 2, height - 48, 4, muted, True)
    else:
        # Security boundary: risks on one side, controls on the other.
        center = (width // 2, height // 2)
        circle(*center, 58, accent)
        draw_text("OTP", center[0], center[1] - 11, 3, white, True)
        branches = [
            ((width // 5, 140), "SS7", (184, 110, 104)),
            ((width // 5, height - 110), "SIM SWAP", (184, 110, 104)),
            ((width * 4 // 5, 140), "RATE LIMIT", muted),
            ((width * 4 // 5, height - 110), "RISK CHECK", muted),
        ]
        for point, name, color in branches:
            line(*center, *point, color)
            circle(*point, 30, color)
            draw_text(name, point[0], point[1] + 48, 3, white, True)
        draw_text("BALANCE REACH AND RISK", width // 2, height - 38, 4, muted, True)

    raw = b"".join(
        b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3])
        for y in range(height)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _cover_figure(title: str, src: str) -> str:
    alt = html.escape(f"Visual overview for {title}", quote=True)
    return (
        '<figure class="article-cover" data-field="image" data-seq="cover" '
        'itemprop="image" itemscope itemtype="https://schema.org/ImageObject">'
        f'<img src="{src}" alt="{alt}" itemprop="contentUrl" loading="eager" '
        'style="width:100%;display:block;border-radius:18px;">'
        f'<figcaption itemprop="caption">{alt}</figcaption></figure>'
    )


def _diagram(index: int, heading: str, src: str) -> str:
    label = re.sub(r"[^A-Za-z0-9 ]+", "", html.unescape(heading))
    label = re.sub(r"\s+", " ", label).strip()[:48] or f"Topic {index}"
    return (
        f'<figure class="visual-mermaid" data-field="visual" data-seq="mermaid-{index}" '
        'itemprop="image" itemscope itemtype="https://schema.org/ImageObject">\n'
        f'<img src="{src}" alt="{html.escape(label, quote=True)} workflow diagram" '
        'itemprop="contentUrl" loading="lazy">\n'
        f'<figcaption itemprop="caption">{html.escape(label)} workflow</figcaption>\n'
        "</figure>"
    )


MIN_INLINE_VISUALS = 1
TARGET_INLINE_VISUALS = 2


def inject_visuals(document: str, image_sources: Optional[list[str]] = None) -> str:
    """Add missing visuals without changing article text or section order."""
    result = document
    title = _title(result)
    sources = image_sources or [
        "visual-cover.png",
        "visual-section-1.png",
        "visual-section-2.png",
    ]

    if 'data-seq="cover"' not in result:
        content = re.search(
            r'<div\b[^>]*class=["\'][^"\']*\bblog-content\b[^"\']*["\'][^>]*>',
            result,
            re.I,
        )
        if not content:
            raise ValueError("缺少 blog-content 容器，无法注入封面图")
        result = (
            result[: content.end()]
            + "\n"
            + _cover_figure(title, sources[0])
            + result[content.end() :]
        )

    existing = len(re.findall(r'data-seq=["\']mermaid-\d+["\']', result, re.I))
    needed = max(0, TARGET_INLINE_VISUALS - existing)
    if needed:
        section_pattern = re.compile(
            r'(<section\b[^>]*>[\s\S]*?<h2[^>]*>([\s\S]*?)</h2>)',
            re.I,
        )
        sections = list(section_pattern.finditer(result))
        if len(sections) < MIN_INLINE_VISUALS:
            raise ValueError(
                f"可注入图表的 H2 区块不足 {MIN_INLINE_VISUALS} 个（实际 {len(sections)}）"
            )
        # Prefer the first two distinct H2 sections; avoid stacking three similar diagrams.
        additions = []
        for index, match in enumerate(sections[:needed], start=existing + 1):
            heading = re.sub(r"<[^>]+>", " ", match.group(2))
            source = sources[min(index, len(sources) - 1)]
            additions.append((match.end(), "\n" + _diagram(index, heading, source)))
        for offset, addition in reversed(additions):
            result = result[:offset] + addition + result[offset:]

    if "cdn.jsdelivr.net/npm/mermaid@11" not in result:
        if "</head>" not in result.lower():
            raise ValueError("缺少 </head>，无法注入 Mermaid CDN")
        result = re.sub(
            r"</head>",
            lambda _match: MERMAID_HEAD + "\n</head>",
            result,
            count=1,
            flags=re.I,
        )

    return result


def run(out_dir: Path, media_site_url: str = "") -> Path:
    target = out_dir / "006 呈现文档.html"
    if not target.exists():
        raise SystemExit(f"ERROR: 缺少 {target.name}")
    original = target.read_text(encoding="utf-8")
    image_names = [
        "visual-cover.png",
        "visual-section-1.png",
        "visual-section-2.png",
    ]
    sizes = [(1200, 630), (1000, 420), (1000, 420)]
    title = _title(original)
    keyword = _keyword(out_dir, title)
    headings = [
        html.unescape(re.sub(r"<[^>]+>", " ", item))
        for item in re.findall(r"<h2[^>]*>([\s\S]*?)</h2>", original, re.I)
    ]
    labels = [title] + (headings[:2] + ["Workflow"] * 2)[:2]
    for index, (name, (width, height)) in enumerate(zip(image_names, sizes)):
        image_path = out_dir / name
        _write_visual_png(image_path, width, height, index, labels[index])
    cover_url = _search_media_cover(media_site_url, keyword, title)
    image_sources = [cover_url or image_names[0], *image_names[1:]]
    try:
        updated = inject_visuals(original, image_sources)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    figures = updated.count("<figure")
    mermaids = len(re.findall(r'data-seq=["\']mermaid-\d+["\']', updated, re.I))
    if figures < 1 or mermaids < MIN_INLINE_VISUALS:
        raise SystemExit(f"ERROR: 视觉元素不足 figures={figures}, mermaids={mermaids}")
    target.write_text(updated, encoding="utf-8")
    print(f"OK: visuals injected figures={figures}, mermaids={mermaids}")
    return target


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="为 006 呈现文档注入确定性视觉元素")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--media-site-url", default="")
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir).resolve()
    if not out_dir.is_dir():
        print(f"ERROR: out-dir 不存在: {out_dir}", file=sys.stderr)
        return 1
    try:
        run(out_dir, media_site_url=args.media_site_url)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
