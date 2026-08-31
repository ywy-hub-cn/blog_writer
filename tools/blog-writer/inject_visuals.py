#!/usr/bin/env python3
"""Deterministically guarantee a cover visual and inline diagrams using Mermaid."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


MERMAID_HEAD_SMS = """
<!-- Mermaid CDN（主：jsdelivr，备：unpkg） -->
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
if (typeof mermaid === "undefined") {
  document.write('<script src="https://unpkg.com/mermaid@11/dist/mermaid.min.js">\\x3C/script>');
}
mermaid.initialize({
  startOnLoad:true,
  theme:"base",
  themeVariables:{
    primaryColor:"#EEF3EC",
    primaryTextColor:"#132019",
    primaryBorderColor:"#5D765F",
    lineColor:"#5D765F",
    secondaryColor:"#F5F8F3",
    tertiaryColor:"#FBFCF8",
    fontFamily:"Georgia, Times New Roman, serif"
  },
  flowchart:{useMaxWidth:true,htmlLabels:true,curve:"basis"},
  securityLevel:"loose"
});
</script>
""".strip()

MERMAID_HEAD_TRAFFIC = """
<!-- Mermaid CDN（主：jsdelivr，备：unpkg） -->
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
if (typeof mermaid === "undefined") {
  document.write('<script src="https://unpkg.com/mermaid@11/dist/mermaid.min.js">\\x3C/script>');
}
mermaid.initialize({
  startOnLoad:true,
  theme:"base",
  themeVariables:{
    primaryColor:"#F5F5F5",
    primaryTextColor:"#18181B",
    primaryBorderColor:"#B22222",
    lineColor:"#52525B",
    secondaryColor:"#FFFFFF",
    tertiaryColor:"#F4F4F6",
    fontFamily:"Inter, system-ui, sans-serif"
  },
  flowchart:{useMaxWidth:true,htmlLabels:true,curve:"basis"},
  securityLevel:"loose"
});
</script>
""".strip()

# Backward-compatible alias used by older tests / callers
MERMAID_HEAD = MERMAID_HEAD_SMS

PALETTES = [
    {
        "name": "sms-green",
        "bg_start": (19, 32, 25),
        "bg_end": (54, 87, 62),
        "accent": (191, 214, 193),
        "muted": (139, 174, 145),
        "title": (246, 250, 246),
        "deco": (93, 118, 95),
    },
    {
        "name": "sms-blue",
        "bg_start": (18, 28, 48),
        "bg_end": (42, 72, 120),
        "accent": (158, 198, 255),
        "muted": (110, 145, 198),
        "title": (246, 248, 255),
        "deco": (63, 93, 142),
    },
    {
        "name": "sms-purple",
        "bg_start": (36, 22, 44),
        "bg_end": (88, 48, 102),
        "accent": (230, 180, 255),
        "muted": (170, 120, 188),
        "title": (250, 246, 255),
        "deco": (118, 65, 142),
    },
    {
        "name": "sms-orange",
        "bg_start": (40, 28, 18),
        "bg_end": (110, 72, 38),
        "accent": (255, 210, 150),
        "muted": (188, 140, 90),
        "title": (255, 250, 244),
        "deco": (135, 95, 55),
    },
    {
        "name": "sms-teal",
        "bg_start": (16, 36, 36),
        "bg_end": (38, 92, 92),
        "accent": (150, 230, 220),
        "muted": (96, 160, 154),
        "title": (244, 252, 251),
        "deco": (58, 108, 108),
    },
    {
        "name": "sms-red",
        "bg_start": (44, 18, 22),
        "bg_end": (120, 42, 52),
        "accent": (255, 170, 170),
        "muted": (190, 110, 118),
        "title": (255, 246, 247),
        "deco": (155, 60, 75),
    },
]


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


def _extract_h2_headings(document: str) -> List[str]:
    """Extract H2 headings from the document."""
    headings = []
    for match in re.finditer(r"<h2[^>]*>([\s\S]*?)</h2>", document, re.I):
        text = re.sub(r"<[^>]+>", " ", match.group(1))
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        if text:
            headings.append(text)
    return headings


def _search_media_cover(site_url: str, keyword: str, title: str) -> str:
    """Reuse a relevant image from the brand's WordPress media library.

    Fail-fast: short timeouts and a hard cap on HTTP calls, so unreachable
    brand sites cannot stall S006/S007 for tens of seconds.
    """
    if not site_url.startswith(("http://", "https://")):
        return ""
    site_url = site_url.rstrip("/")
    attempts = {"n": 0}
    max_attempts = 3

    def fetch_json(endpoint: str):
        if attempts["n"] >= max_attempts:
            raise TimeoutError("media cover search attempt budget exhausted")
        attempts["n"] += 1
        request = urllib.request.Request(
            endpoint,
            headers={"User-Agent": "BlogWriter/2.1"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    # Prefer the cover of the most closely related existing article.
    try:
        posts_endpoint = (
            f"{site_url}/wp-json/wp/v2/posts?"
            + urllib.parse.urlencode(
                {
                    "search": keyword,
                    "per_page": 5,
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

        for post in sorted(posts, key=relevance, reverse=True)[:2]:
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
        return ""

    if attempts["n"] >= max_attempts:
        return ""

    stopwords = {"the", "and", "for", "how", "with", "from", "guide", "explained"}
    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9]+", f"{keyword} {title}")
        if token.lower() not in stopwords and len(token) > 2
    ]
    queries = [keyword, " ".join(tokens[:3])]
    seen = set()
    for query in queries:
        if attempts["n"] >= max_attempts:
            break
        query = query.strip()
        if not query or query.lower() in seen:
            continue
        seen.add(query.lower())
        endpoint = (
            f"{site_url.rstrip('/')}/wp-json/wp/v2/media?"
            + urllib.parse.urlencode(
                {
                    "search": query,
                    "per_page": 10,
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
            return ""
    return ""


def _variant_for(label: str, salt: str = "") -> int:
    digest = hashlib.sha256(f"{label}:{salt}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 6


def _generate_cover_svg(
    title: str,
    keyword: str,
    output_path: Path,
    palette_index: int,
) -> None:
    """Generate a high-quality SVG cover image with gradient + title."""
    p = PALETTES[palette_index % len(PALETTES)]
    w, h = 1200, 630

    def rgb(c):
        return f"rgb({c[0]},{c[1]},{c[2]})"

    bg_id = f"bg_{palette_index}"
    deco_id = f"deco_{palette_index}"

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
  <defs>
    <linearGradient id="{bg_id}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{rgb(p['bg_start'])}"/>
      <stop offset="100%" stop-color="{rgb(p['bg_end'])}"/>
    </linearGradient>
    <linearGradient id="{deco_id}" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="{rgb(p['accent'])}" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="{rgb(p['accent'])}" stop-opacity="0"/>
    </linearGradient>
    <radialGradient id="glow_{palette_index}" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{rgb(p['accent'])}" stop-opacity="0.15"/>
      <stop offset="100%" stop-color="{rgb(p['accent'])}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#{bg_id})"/>
  <circle cx="850" cy="200" r="350" fill="url(#glow_{palette_index})"/>
  <rect x="0" y="{h-180}" width="{w}" height="3" fill="url(#{deco_id})"/>
'''

    # Decorative geometric elements
    shape_type = _variant_for(title, "cover_shape")
    if shape_type == 0:
        # Circles cluster
        svg += f'''  <circle cx="1050" cy="120" r="80" fill="{rgb(p['accent'])}" fill-opacity="0.15"/>
  <circle cx="1080" cy="160" r="50" fill="{rgb(p['accent'])}" fill-opacity="0.1"/>
  <circle cx="950" cy="100" r="30" fill="{rgb(p['title'])}" fill-opacity="0.2"/>
'''
    elif shape_type == 1:
        # Triangles
        svg += f'''  <polygon points="1000,80 1100,180 900,180" fill="{rgb(p['accent'])}" fill-opacity="0.12"/>
  <polygon points="1050,40 1120,140 980,140" fill="{rgb(p['muted'])}" fill-opacity="0.1"/>
'''
    elif shape_type == 2:
        # Rectangles / bars
        svg += f'''  <rect x="900" y="60" width="15" height="150" fill="{rgb(p['accent'])}" fill-opacity="0.15"/>
  <rect x="930" y="40" width="15" height="170" fill="{rgb(p['accent'])}" fill-opacity="0.1"/>
  <rect x="960" y="80" width="15" height="130" fill="{rgb(p['muted'])}" fill-opacity="0.12"/>
'''
    elif shape_type == 3:
        # Wave / arc
        svg += f'''  <path d="M 800 550 Q 900 450 1000 500 T 1200 480" stroke="{rgb(p['accent'])}" stroke-width="2" fill="none" fill-opacity="0.2"/>
  <path d="M 800 570 Q 900 470 1000 520 T 1200 500" stroke="{rgb(p['muted'])}" stroke-width="1.5" fill="none" fill-opacity="0.15"/>
'''
    elif shape_type == 4:
        # Dots / grid
        dot_rows, dot_cols = 4, 8
        dots = []
        for r in range(dot_rows):
            for c in range(dot_cols):
                cx = 880 + c * 40
                cy = 80 + r * 40
                dots.append(f'<circle cx="{cx}" cy="{cy}" r="4" fill="{rgb(p["accent"])}" fill-opacity="{0.15 + (r*dot_cols+c)*0.02}"/>')
        svg += "  " + "\n  ".join(dots) + "\n"
    else:
        # Diagonal lines
        svg += f'''  <line x1="800" y1="0" x2="1200" y2="400" stroke="{rgb(p['accent'])}" stroke-width="1" stroke-opacity="0.1"/>
  <line x1="850" y1="0" x2="1200" y2="350" stroke="{rgb(p['muted'])}" stroke-width="1" stroke-opacity="0.08"/>
  <line x1="900" y1="0" x2="1200" y2="300" stroke="{rgb(p['accent'])}" stroke-width="1" stroke-opacity="0.06"/>
'''

    # Title text
    display_title = title[:90] if len(title) > 90 else title
    title_lines = _wrap_text(display_title, max_chars=28)
    line_height = 68
    start_y = 280 - (len(title_lines) * line_height) // 2
    for i, line in enumerate(title_lines):
        svg += f'  <text x="80" y="{start_y + i * line_height}" font-family="Georgia, Times New Roman, serif" font-size="52" font-weight="600" fill="{rgb(p["title"])}">{html.escape(line)}</text>\n'

    # Keyword/tagline
    if keyword:
        kw_display = keyword[:50]
        svg += f'  <text x="80" y="{start_y + len(title_lines) * line_height + 60}" font-family="Georgia, Times New Roman, serif" font-size="24" fill="{rgb(p["accent"])}" fill-opacity="0.85">{html.escape(kw_display)}</text>\n'

    svg += "</svg>"
    output_path.write_text(svg, encoding="utf-8")


def _wrap_text(text: str, max_chars: int = 28) -> List[str]:
    """Simple word-wrap for SVG text."""
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


# Mermaid flowchart node with left-aligned text content (HTML labels)
TEXT_LEFT_ALIGN = '["<div style=\'text-align:left\'>Key Points<br/>• Core concept<br/>• Main idea<br/>• Important detail</div>"]'


_SKIP_SECTION_HINTS = (
    "faq", "frequently asked", "references", "reference", "conclusion",
    "summary", "about the author", "related", "disclaimer", "sources",
    "常见问题", "参考", "结论", "总结", "作者",
)

_PROCESS_HINTS = (
    "how", "step", "process", "pipeline", "workflow", "guide", "setup",
    "implement", "deploy", "install", "deliver", "send", "route", "flow",
    "流程", "步骤", "如何", "实现", "部署",
)

_DECISION_HINTS = (
    "when", "whether", "should", "choose", "decision", "vs", "versus",
    "compare", "pros", "cons", "trade", "risk", "retry", "fail", "error",
    "判断", "对比", "选择", "还是", "风险", "失败",
)

_SEQUENCE_HINTS = (
    "api", "request", "response", "call", "handshake", "otp", "verify",
    "auth", "session", "webhook", "callback", "sequence", "latency",
    "调用", "验证", "请求", "响应", "时序",
)

_ARCH_HINTS = (
    "architecture", "system", "stack", "component", "infra", "network",
    "carrier", "gateway", "platform", "structure", "layer",
    "架构", "系统", "组件", "网络", "网关",
)


def _heading_blob(heading: str) -> str:
    return re.sub(r"\s+", " ", (heading or "").lower()).strip()


def _should_skip_section(heading: str) -> bool:
    blob = _heading_blob(heading)
    return any(h in blob for h in _SKIP_SECTION_HINTS)


def _classify_diagram(heading: str, points: List[str], index: int) -> str:
    """Pick a diagram family from heading semantics (not just section index)."""
    blob = _heading_blob(heading)
    point_blob = " ".join(points).lower()
    combined = f"{blob} {point_blob}"

    scores = {
        "process": sum(1 for h in _PROCESS_HINTS if h in combined),
        "decision": sum(1 for h in _DECISION_HINTS if h in combined),
        "sequence": sum(1 for h in _SEQUENCE_HINTS if h in combined),
        "architecture": sum(1 for h in _ARCH_HINTS if h in combined),
        "overview": 1 if index == 0 else 0,
    }
    # Numbered steps in extracted points strongly suggest a process chart.
    if sum(1 for p in points if re.match(r"^\d+[\).\s]", p)) >= 2:
        scores["process"] += 2
    if len(points) >= 2 and any(x in combined for x in (" vs ", "versus", "compare", "对比")):
        scores["decision"] += 2

    best = max(scores, key=scores.get)
    if scores[best] <= 0:
        # Stable fallback by index: overview → process → concept map
        return ("overview", "process", "concept")[min(index, 2)]
    return best


def _short_label(text: str, limit: int = 36) -> str:
    cleaned = _clean_for_mermaid(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip(" -–,;") + "…"


def _extract_section_points(document: str, heading: str, limit: int = 6) -> List[str]:
    """Pull concrete bullets / lead sentences from the H2 section body."""
    if not document or not heading:
        return []
    # Locate the H2, then read until next H2 / end of section.
    h2_re = re.compile(
        r"<h2\b[^>]*>\s*" + re.escape(heading) + r"\s*</h2>([\s\S]*?)(?=<h2\b|</section>|$)",
        re.I,
    )
    # Heading in HTML may contain nested tags — fall back to looser search.
    match = h2_re.search(document)
    if not match:
        loose = re.compile(
            r"<h2\b[^>]*>([\s\S]*?)</h2>([\s\S]*?)(?=<h2\b|</section>|$)",
            re.I,
        )
        for m in loose.finditer(document):
            plain = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
            plain = re.sub(r"\s+", " ", plain).strip()
            if plain.lower() == heading.lower() or heading.lower() in plain.lower():
                match = m
                body = m.group(2)
                break
        else:
            body = ""
    else:
        body = match.group(1)

    if not body:
        return []

    points: List[str] = []
    seen = set()

    def _add(raw: str) -> None:
        text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
        text = re.sub(r"\s+", " ", text).strip(" \t\r\n•·-–—:")
        text = re.sub(r"^[\d]+[\).\s]+", "", text).strip()
        if len(text) < 4 or len(text) > 90:
            return
        key = text.lower()
        if key in seen:
            return
        # Skip pure navigation / CTA fluff
        low = key
        if any(x in low for x in ("click here", "read more", "learn more", "photo by")):
            return
        seen.add(key)
        points.append(text)

    for li in re.findall(r"<li\b[^>]*>([\s\S]*?)</li>", body, re.I):
        _add(li)
        if len(points) >= limit:
            return points[:limit]

    for strong in re.findall(r"<(?:strong|b)\b[^>]*>([\s\S]*?)</(?:strong|b)>", body, re.I):
        _add(strong)
        if len(points) >= limit:
            return points[:limit]

    for p in re.findall(r"<p\b[^>]*>([\s\S]*?)</p>", body, re.I):
        plain = html.unescape(re.sub(r"<[^>]+>", " ", p))
        plain = re.sub(r"\s+", " ", plain).strip()
        # Prefer the first clause / sentence as a diagram node
        clause = re.split(r"(?<=[.!?])\s+|;\s+| — | – ", plain)[0].strip()
        _add(clause)
        if len(points) >= limit:
            return points[:limit]

    return points[:limit]


def _fallback_points(heading: str, keyword: str) -> List[str]:
    """Topic-specific fallbacks when section text is too thin to mine."""
    topic = _short_label(keyword or heading, 28)
    head = _short_label(heading, 28)
    blob = _heading_blob(f"{heading} {keyword}")
    if any(h in blob for h in _SEQUENCE_HINTS):
        return [
            f"App requests {topic}",
            "Provider routes message",
            "Carrier delivers",
            "User verifies code",
        ]
    if any(h in blob for h in _DECISION_HINTS):
        return [
            f"Evaluate {head}",
            "Check constraints",
            "Choose path A or B",
            "Apply controls",
        ]
    if any(h in blob for h in _ARCH_HINTS):
        return ["Client", "API gateway", topic or "Core service", "Downstream"]
    return [
        f"Define {head}",
        f"Apply {topic}",
        "Validate outcome",
        "Iterate and improve",
    ]


def _generate_mermaid_code(
    heading: str,
    keyword: str,
    heading_index: int,
    total_sections: int,
    all_headings: List[str],
    points: Optional[List[str]] = None,
) -> str:
    """Generate content-aware Mermaid diagram code for a section."""
    label = _short_label(heading, 40)
    kw = _short_label(keyword, 28) if keyword else "Topic"
    nodes = [ _short_label(p, 40) for p in (points or []) if p ]
    if len(nodes) < 2:
        nodes = _fallback_points(heading, keyword)

    kind = _classify_diagram(heading, nodes, heading_index)

    if kind == "overview":
        mindmap = "mindmap\n"
        mindmap += f"  root(({kw}))\n"
        mindmap += f"    {label}\n"
        for node in (all_headings[:5] or nodes[:5]):
            clean = _short_label(node, 28)
            if clean.lower() == label.lower():
                continue
            mindmap += f"      {clean}\n"
        for node in nodes[:4]:
            mindmap += f"    {node}\n"
        return mindmap

    if kind == "sequence":
        actors = nodes[:4]
        while len(actors) < 3:
            actors.append(f"Step {len(actors)+1}")
        a, b, c = actors[0], actors[1], actors[2]
        d = actors[3] if len(actors) > 3 else "Result"
        return (
            "sequenceDiagram\n"
            f"    participant A as {a}\n"
            f"    participant B as {b}\n"
            f"    participant C as {c}\n"
            f"    A->>B: Initiate {kw}\n"
            f"    B->>C: Process request\n"
            f"    C-->>B: Return status\n"
            f"    B-->>A: Confirm {d}\n"
        )

    if kind == "decision":
        left = nodes[0]
        right = nodes[1] if len(nodes) > 1 else "Alternative"
        yes = nodes[2] if len(nodes) > 2 else "Proceed"
        no = nodes[3] if len(nodes) > 3 else "Adjust"
        return (
            "flowchart TD\n"
            f'    Start["{label}"] --> Q{{"Decision point"}}\n'
            f'    Q -->|Yes| Y["{yes}"]\n'
            f'    Q -->|No| N["{no}"]\n'
            f'    Y --> Out["{left}"]\n'
            f'    N --> Alt["{right}"]\n'
        )

    if kind == "architecture":
        parts = nodes[:4]
        while len(parts) < 3:
            parts.append(f"Component {len(parts)+1}")
        lines = ["flowchart LR", f'    subgraph System["{label}"]']
        ids = []
        for i, part in enumerate(parts):
            nid = chr(ord("A") + i)
            ids.append(nid)
            lines.append(f'      {nid}["{part}"]')
        lines.append("    end")
        for left, right in zip(ids, ids[1:]):
            lines.append(f"    {left} --> {right}")
        return "\n".join(lines)

    if kind == "process":
        lines = ["flowchart TD", f'    S0["{label}"]']
        prev = "S0"
        for i, step in enumerate(nodes[:5], start=1):
            nid = f"S{i}"
            lines.append(f'    {nid}["{i}. {step}"]')
            lines.append(f"    {prev} --> {nid}")
            prev = nid
        lines.append(f'    Done["Outcome: {kw}"]')
        lines.append(f"    {prev} --> Done")
        return "\n".join(lines)

    # concept map default
    lines = ["flowchart TD", f'    Root["{label}"]']
    for i, point in enumerate(nodes[:5], start=1):
        nid = f"N{i}"
        lines.append(f'    {nid}["{point}"]')
        lines.append(f"    Root --> {nid}")
    return "\n".join(lines)


def _clean_for_mermaid(text: str) -> str:
    """Clean text for safe use in Mermaid node labels."""
    # Remove characters that cause Mermaid parse errors
    cleaned = re.sub(r'[<>{}|\[\]]', '', text)
    cleaned = re.sub(r'"', "'", cleaned)
    cleaned = re.sub(r'\\\\n', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Limit length
    if len(cleaned) > 50:
        cleaned = cleaned[:48] + '…'
    return cleaned or 'Topic'


def _pick_visual_sections(
    document: str,
    headings: List[str],
    needed: int,
) -> List[tuple]:
    """Choose the most diagram-worthy H2 sections (skip FAQ/References)."""
    section_pattern = re.compile(
        r'(<section\b[^>]*>[\s\S]*?<h2[^>]*>([\s\S]*?)</h2>)',
        re.I,
    )
    matches = list(section_pattern.finditer(document))
    if len(matches) < MIN_INLINE_VISUALS:
        matches = list(re.compile(r'(<h2[^>]*>([\s\S]*?)</h2>)', re.I).finditer(document))

    scored = []
    for match in matches:
        heading = html.unescape(re.sub(r"<[^>]+>", " ", match.group(2)))
        heading = re.sub(r"\s+", " ", heading).strip()
        if not heading or _should_skip_section(heading):
            continue
        points = _extract_section_points(document, heading)
        kind = _classify_diagram(heading, points, len(scored))
        score = {
            "process": 5,
            "decision": 5,
            "sequence": 4,
            "architecture": 4,
            "overview": 2,
            "concept": 1,
        }.get(kind, 1)
        score += min(len(points), 4)
        # Prefer earlier content sections slightly
        score += max(0, 3 - len(scored))
        scored.append((score, match, heading, points, kind))

    scored.sort(key=lambda item: item[0], reverse=True)
    chosen = scored[:needed]
    # Keep document order for insertion stability
    chosen.sort(key=lambda item: item[1].start())
    return chosen


def _mermaid_figure(index: int, heading: str, keyword: str, diagram_code: str, kind: str = "") -> str:
    """Build a figure containing a Mermaid diagram block."""
    label = _short_label(heading, 48)
    kind_label = {
        "process": "process flow",
        "decision": "decision tree",
        "sequence": "sequence diagram",
        "architecture": "architecture map",
        "overview": "topic overview",
        "concept": "concept map",
    }.get(kind, "concept diagram")
    alt = html.escape(f"{label} {kind_label}", quote=True)
    caption = html.escape(f"{label} — {kind_label} for {keyword or 'this section'}", quote=True)
    return (
        f'<figure class="visual-mermaid" data-field="visual" data-seq="mermaid-{index}" '
        'itemprop="image" itemscope itemtype="https://schema.org/ImageObject">\n'
        f'<figcaption itemprop="caption">{caption}</figcaption>\n'
        '<div class="mermaid-container">\n'
        f'<pre class="mermaid" itemprop="contentUrl">{html.escape(diagram_code)}</pre>\n'
        '</div>\n'
        "</figure>"
    )


def _cover_figure(title: str, src: str, keyword: str) -> str:
    """Build the cover figure element."""
    alt = html.escape(f"{title} article cover overview", quote=True)
    caption = html.escape(f"{title} — article overview and key themes", quote=True)
    is_svg = src.endswith(".svg") or "visual-cover" in src
    if is_svg:
        # SVG covers use an <img> tag with proper dimensions
        return (
            '<figure class="article-cover" data-field="image" data-seq="cover" '
            'itemprop="image" itemscope itemtype="https://schema.org/ImageObject">'
            f'<img src="{src}" alt="{alt}" itemprop="contentUrl" loading="eager" '
            'style="width:100%;display:block;border-radius:18px;">'
            f'<figcaption itemprop="caption">{caption}</figcaption></figure>'
        )
    else:
        return (
            '<figure class="article-cover" data-field="image" data-seq="cover" '
            'itemprop="image" itemscope itemtype="https://schema.org/ImageObject">'
            f'<img src="{src}" alt="{alt}" itemprop="contentUrl" loading="eager" '
            'style="width:100%;display:block;border-radius:18px;">'
            f'<figcaption itemprop="caption">{caption}</figcaption></figure>'
        )


def _strip_visuals(document: str) -> str:
    """Remove previously injected cover / inline visuals so we can re-inject cleanly."""
    result = re.sub(
        r'<figure\b[^>]*\bdata-seq=["\']cover["\'][^>]*>[\s\S]*?</figure>\s*',
        "",
        document,
        flags=re.I,
    )
    result = re.sub(
        r'<figure\b[^>]*\bdata-seq=["\']mermaid-\d+["\'][^>]*>[\s\S]*?</figure>\s*',
        "",
        result,
        flags=re.I,
    )
    # Also strip old-style pixel image references
    result = re.sub(
        r'<figure\b[^>]*>\s*<img[^>]*src=["\'][^"\']*visual-(cover|section)[^"\']*["\'][^>]*>\s*</figure>\s*',
        "",
        result,
        flags=re.I,
    )
    return result


MIN_INLINE_VISUALS = 1
TARGET_INLINE_VISUALS = 2


def inject_visuals(
    document: str,
    image_sources: Optional[List[str]] = None,
    keyword: str = "",
    headings: Optional[List[str]] = None,
    brand_theme: str = "sms",
) -> str:
    """Add missing visuals without changing article text or section order."""
    result = document
    title = _title(result)

    if headings is None:
        headings = _extract_h2_headings(result)

    if 'data-seq="cover"' not in result:
        content = re.search(
            r'<div\b[^>]*class=["\'][^"\']*\bblog-content\b[^"\']*["\'][^>]*>',
            result,
            re.I,
        )
        if not content:
            raise ValueError("缺少 blog-content 容器，无法注入封面图")
        cover_src = image_sources[0] if image_sources and image_sources[0] else "visual-cover.svg"
        result = (
            result[: content.end()]
            + "\n"
            + _cover_figure(title, cover_src, keyword)
            + result[content.end() :]
        )

    existing = len(re.findall(r'data-seq=["\']mermaid-\d+["\']', result, re.I))
    needed = max(0, TARGET_INLINE_VISUALS - existing)
    if needed:
        chosen = _pick_visual_sections(result, headings, needed)
        if len(chosen) < MIN_INLINE_VISUALS:
            raise ValueError(
                f"可注入图表的区块不足 {MIN_INLINE_VISUALS} 个（实际 {len(chosen)}）"
            )

        additions = []
        for offset_i, (_score, match, heading_text, points, kind) in enumerate(chosen):
            idx = existing + offset_i + 1
            diagram_code = _generate_mermaid_code(
                heading_text,
                keyword,
                offset_i,
                len(chosen),
                headings,
                points=points,
            )
            # Re-classify with the same points for caption accuracy
            kind = _classify_diagram(heading_text, points or [], offset_i)
            additions.append(
                (
                    match.end(),
                    "\n"
                    + _mermaid_figure(
                        idx, heading_text, keyword, diagram_code, kind=kind
                    ),
                )
            )
        for offset, addition in reversed(additions):
            result = result[:offset] + addition + result[offset:]

    head = MERMAID_HEAD_TRAFFIC if brand_theme == "traffic" else MERMAID_HEAD_SMS
    # Always refresh Mermaid init so brand themeVariables stay current.
    result = re.sub(
        r"<!--\s*Mermaid CDN[\s\S]*?</script>\s*(?:</script>\s*)?",
        "",
        result,
        count=1,
        flags=re.I,
    )
    # Fallback: remove bare mermaid CDN + init scripts if comment marker missing
    if "cdn.jsdelivr.net/npm/mermaid@11" in result:
        result = re.sub(
            r'<script[^>]+cdn\.jsdelivr\.net/npm/mermaid@11[^>]*>\s*</script>\s*'
            r'<script>[\s\S]*?mermaid\.initialize\([\s\S]*?</script>\s*',
            "",
            result,
            count=1,
            flags=re.I,
        )
    if "</head>" not in result.lower():
        raise ValueError("缺少 </head>，无法注入 Mermaid CDN")
    result = re.sub(
        r"</head>",
        lambda _match: head + "\n</head>",
        result,
        count=1,
        flags=re.I,
    )

    return result


def run(out_dir: Path, media_site_url: str = "", strict: bool = False) -> Path:
    target = out_dir / "006 呈现文档.html"
    if not target.exists():
        raise SystemExit(f"ERROR: 缺少 {target.name}")
    original = target.read_text(encoding="utf-8")

    title = _title(original)
    keyword = _keyword(out_dir, title)
    headings = _extract_h2_headings(original)

    brand_theme = "sms"
    try:
        from brand_css import resolve_brand_theme

        brand_theme, _ = resolve_brand_theme(out_dir)
    except Exception:
        brand_theme = "sms"

    # 1. Generate SVG cover image (palette biased by brand)
    palette_index = _variant_for(keyword or title, f"palette-{brand_theme}")
    if brand_theme == "traffic":
        # Prefer red / purple / orange family for TraffiClimb
        palette_index = (palette_index % 3) + 3
    cover_svg_path = out_dir / "visual-cover.svg"
    _generate_cover_svg(title, keyword, cover_svg_path, palette_index)

    # 2. Try WordPress cover, fall back to SVG
    cover_url = _search_media_cover(media_site_url, keyword, title)
    cover_src = cover_url or "visual-cover.svg"

    image_sources = [cover_src]

    # 3. Always strip old visuals before reinjecting (ensures fresh SVG/Mermaid)
    original = _strip_visuals(original)
    print("   [visual] stripped old visuals for fresh injection", file=sys.stderr)

    try:
        updated = inject_visuals(
            original,
            image_sources,
            keyword=keyword,
            headings=headings,
            brand_theme=brand_theme,
        )
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    figures = updated.count("<figure")
    mermaid_blocks = len(re.findall(r'<pre class="mermaid"', updated, re.I))

    if figures < 1:
        raise SystemExit(f"ERROR: 视觉元素不足 figures={figures}（至少封面 1 个）")

    target.write_text(updated, encoding="utf-8")

    # 4. Validate (strict mode blocks, relaxed mode only warns)
    import importlib.util

    validator_path = Path(__file__).resolve().parent / "validate_visuals.py"
    validator_spec = importlib.util.spec_from_file_location("validate_visuals", validator_path)
    if validator_spec and validator_spec.loader:
        validator = importlib.util.module_from_spec(validator_spec)
        validator_spec.loader.exec_module(validator)
        errors = validator.validate_visuals(out_dir, strict=strict)
        if errors:
            if strict:
                raise SystemExit(
                    f"ERROR: 视觉校验失败（严格模式）: {'; '.join(errors[:5])}"
                )
            print(f"   [visual] validation warnings (non-blocking): {'; '.join(errors[:3])}", file=sys.stderr)
        else:
            mode_label = "严格模式" if strict else "宽松模式"
            print(f"   [visual] validation passed ({mode_label})", file=sys.stderr)

    print(
        f"OK: visuals injected figures={figures}, mermaid_diagrams={mermaid_blocks}, theme={brand_theme}"
    )
    return target


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="为 006 呈现文档注入高质量视觉元素（Mermaid 图表 + SVG 封面）")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--media-site-url", default="")
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="严格模式：图片校验失败时 hard fail（默认宽松模式，仅警告）",
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir).resolve()
    if not out_dir.is_dir():
        print(f"ERROR: out-dir 不存在: {out_dir}", file=sys.stderr)
        return 1
    try:
        run(out_dir, media_site_url=args.media_site_url, strict=args.strict)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
