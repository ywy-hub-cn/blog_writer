#!/usr/bin/env python3
"""Load presentation / publish CSS from task instance brand files."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

VISUAL_FILE_HINTS = (
    "visual",
    "guideline",
    "guidelines",
    "css",
    "视觉",
    "规范",
    "template",
    "模板",
    "trafficlimb",
    "trafficclimb",
)

DEFAULT_SMS_PRESENTATION_CSS = """
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
  --font: Georgia, "Times New Roman", serif;
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

TRAFFIC_PRESENTATION_CSS = """
:root {
  --tc-red: #B22222;
  --tc-red-dark: #7f1d1d;
  --tc-red-light: #DC3545;
  --tc-gray-900: #18181b;
  --tc-gray-800: #2d2d2d;
  --tc-gray-700: #52525b;
  --tc-gray-500: #888888;
  --tc-gray-300: #cccccc;
  --tc-gray-200: #e8e8e8;
  --tc-gray-100: #f5f5f5;
  --tc-white: #ffffff;
  --tc-bg: #f4f4f6;
  --tc-font: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --tc-radius: 22px;
  --tc-radius-lg: 28px;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: var(--tc-font);
  color: var(--tc-gray-900);
  background: var(--tc-bg);
  line-height: 1.75;
}
.article-shell {
  max-width: 1120px;
  margin: 0 auto;
  padding: 48px 24px 80px;
}
.blog-meta {
  display: flex;
  gap: 16px;
  align-items: center;
  color: var(--tc-gray-500);
  font-size: 14px;
  margin-bottom: 20px;
}
.read-time { font-weight: 500; }
.blog-content h1 {
  font-size: clamp(38px, 4vw, 52px);
  font-weight: 700;
  line-height: 1.08;
  letter-spacing: -0.02em;
  color: var(--tc-gray-900);
  margin: 0 0 32px;
}
.blog-content h2 {
  font-size: clamp(32px, 3vw, 44px);
  font-weight: 700;
  line-height: 1.12;
  letter-spacing: -0.035em;
  color: var(--tc-gray-900);
  margin: 78px 0 32px;
}
.blog-content h3 {
  font-size: clamp(22px, 1.8vw, 27px);
  font-weight: 600;
  line-height: 1.28;
  color: var(--tc-gray-800);
  margin: 48px 0 16px;
}
.blog-content p {
  font-size: 19px;
  margin: 0 0 20px;
  color: var(--tc-gray-900);
}
.blog-content p[data-field="hook"],
.blog-content .lead {
  font-size: 20px;
  line-height: 1.62;
  color: var(--tc-gray-800);
}
.blog-content ul, .blog-content ol {
  background: var(--tc-gray-100);
  border: 1px solid var(--tc-gray-200);
  border-radius: var(--tc-radius);
  padding: 22px 26px 22px 36px;
  margin: 22px 0 32px;
}
.blog-content li { margin: 0 0 9px; font-size: 19px; }
.blog-content li::marker { color: var(--tc-red); }
.blog-content a {
  color: var(--tc-red);
  text-decoration: none;
  font-weight: 500;
}
.blog-content a:hover { color: var(--tc-red-dark); }
.faq-section {
  background: var(--tc-white);
  border: 1px solid var(--tc-gray-200);
  border-radius: var(--tc-radius-lg);
  padding: 34px;
  margin-top: 76px;
  box-shadow: 0 1px 3px rgba(15,23,42,0.06);
}
.faq-item {
  background: var(--tc-gray-100);
  border: 1px solid var(--tc-gray-200);
  border-radius: var(--tc-radius);
  padding: 18px 20px;
  margin: 0 0 14px;
}
.faq-answer {
  background: var(--tc-white);
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: calc(var(--tc-radius) - 6px);
  color: var(--tc-gray-700);
}
.references-section {
  background: var(--tc-gray-100);
  border-radius: var(--tc-radius);
  padding: 28px;
  margin-top: 56px;
}
.blog-content table {
  width: 100%;
  border-collapse: collapse;
  margin: 24px 0;
}
.blog-content th, .blog-content td {
  border: 1px solid var(--tc-gray-200);
  padding: 10px 12px;
  text-align: left;
}
.blog-content th {
  background: var(--tc-gray-100);
  color: var(--tc-gray-900);
}
blockquote {
  margin: 24px 0;
  padding: 16px 20px;
  border-left: 4px solid var(--tc-red);
  background: var(--tc-gray-100);
  color: var(--tc-gray-700);
}
.blog-content figure img {
  border-radius: var(--tc-radius);
}
.blog-content figcaption {
  color: var(--tc-gray-500);
  font-size: 14px;
}
@media (max-width: 640px) {
  .blog-content p { font-size: 17px; }
  .blog-content h2 { font-size: 31px; margin-top: 58px; }
  .blog-content h3 { font-size: 23px; }
}
""".strip()

DEFAULT_SMS_PUBLISH_CSS = """
.tuoying-bw-article,.tuoying-bw-article *{box-sizing:border-box}
.tuoying-bw-article{font-family:Georgia,"Times New Roman",serif;color:#39433C;background:#fff;margin:0 auto;max-width:720px;padding:0 24px 80px;font-size:19px;line-height:1.74}
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

TRAFFIC_PUBLISH_CSS = """
.tuoying-bw-article,.tuoying-bw-article *{box-sizing:border-box}
.tuoying-bw-article{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#18181b;background:#fff;margin:0 auto;max-width:1120px;padding:0 24px 80px;font-size:19px;line-height:1.75}
.tuoying-bw-article>p:first-of-type,.tuoying-bw-article .lead{font-size:21px;line-height:1.62;color:#2d2d2d}
.tuoying-bw-article h1{font-size:clamp(38px,4vw,52px);line-height:1.08;color:#18181b;margin:0 0 32px;font-weight:700}
.tuoying-bw-article h2{font-size:clamp(32px,3vw,44px);font-weight:700;line-height:1.12;color:#18181b;margin:78px 0 32px}
.tuoying-bw-article h3{font-size:clamp(22px,1.8vw,27px);font-weight:600;line-height:1.28;color:#2d2d2d;margin:48px 0 16px}
.tuoying-bw-article p{margin:0 0 20px}
.tuoying-bw-article a{color:#B22222;text-decoration:underline;overflow-wrap:anywhere}
.tuoying-bw-article a:hover{color:#7f1d1d}
.tuoying-bw-article ul,.tuoying-bw-article ol{background:#f5f5f5;border:1px solid #e8e8e8;border-radius:22px;padding:22px 26px 22px 36px;margin:22px 0 32px}
.tuoying-bw-article li{margin:9px 0}
.tuoying-bw-article li::marker{color:#B22222}
.tuoying-bw-article figure{margin:40px 0;width:100%}
.tuoying-bw-article figure img{display:block;width:100%;height:auto;border-radius:22px}
.tuoying-bw-article figcaption{font-size:14px;color:#888888;margin-top:10px;text-align:center}
.tuoying-bw-article table{width:100%;border-collapse:collapse;margin:24px 0}
.tuoying-bw-article th,.tuoying-bw-article td{border:1px solid #e8e8e8;padding:12px;text-align:left}
.tuoying-bw-article th{background:#f5f5f5}
.tuoying-bw-article blockquote{margin:24px 0;padding:16px 20px;border-left:4px solid #B22222;background:#f5f5f5;color:#52525b}
.tuoying-bw-article .faq-section,.tuoying-bw-article .references-section{background:#fff;border:1px solid #e8e8e8;border-radius:28px;padding:34px;margin-top:76px;box-shadow:0 1px 3px rgba(15,23,42,0.06)}
.tuoying-bw-article .faq-section h2,.tuoying-bw-article .references-section h2{font-size:clamp(30px,2.8vw,40px);margin:0 0 26px}
.tuoying-bw-article .faq-item{background:#f5f5f5;border:1px solid #e8e8e8;border-radius:22px;margin-bottom:14px;overflow:hidden}
.tuoying-bw-article .faq-item summary{font-size:19px;font-weight:600;color:#18181b;padding:18px 48px 18px 20px;cursor:pointer}
.tuoying-bw-article .faq-answer{background:#fff;border-top:1px solid #e8e8e8;padding:18px 20px 20px;color:#52525b}
.tuoying-bw-article .faq-answer p{font-size:17px;margin:0}
.tuoying-bw-article .references-section p{background:#f5f5f5;border:1px solid #e8e8e8;border-radius:14px;padding:14px 16px;font-size:14px;color:#888888}
@media(max-width:768px){.tuoying-bw-article{padding:0 16px 60px;font-size:17px}.tuoying-bw-article h2{font-size:31px;margin:58px 0 24px}.tuoying-bw-article h3{font-size:23px;margin:38px 0 16px}}
""".strip()


def _score_visual_file(path: Path) -> int:
    name = path.name.lower()
    score = 0
    for hint in VISUAL_FILE_HINTS:
        if hint in name:
            score += 10
    if name.endswith(".md"):
        score += 1
    return score


def extract_css_blocks(markdown: str) -> List[str]:
    return [
        block.strip()
        for block in re.findall(r"```css\s*\n(.*?)```", markdown, flags=re.I | re.S)
        if block.strip()
    ]


def detect_theme(css_text: str, *, filename: str = "") -> str:
    lower = css_text.lower()
    name = filename.lower()
    if "--tc-red" in lower or "--tc-gray-900" in lower or "trafficclimb" in name:
        return "traffic"
    if "--green" in lower or "#5d765f" in lower or "sms-blog" in lower:
        return "sms"
    return "sms"


def _merge_root_tokens(base_css: str, token_css: str) -> str:
    if not token_css.strip():
        return base_css
    if re.search(r":root\s*\{", base_css, flags=re.I):
        return re.sub(
            r":root\s*\{[^}]*\}",
            token_css.strip(),
            base_css,
            count=1,
            flags=re.I | re.S,
        )
    return f"{token_css.strip()}\n{base_css}"


def _collect_brand_sources(out_dir: Path) -> Iterable[Tuple[Path, str]]:
    brand_dir = out_dir / "brand"
    if not brand_dir.is_dir():
        return []
    files = sorted(brand_dir.glob("*.md"), key=lambda p: (-_score_visual_file(p), p.name))
    return [(path, path.read_text(encoding="utf-8")) for path in files]


def resolve_brand_theme(out_dir: Path) -> Tuple[str, str]:
    """Return (theme_name, token_css_block). theme_name is 'traffic' or 'sms'."""
    token_css = ""
    theme = "sms"
    best_score = -1
    for path, text in _collect_brand_sources(out_dir):
        score = _score_visual_file(path)
        for block in extract_css_blocks(text):
            if ":root" not in block:
                continue
            candidate_theme = detect_theme(block, filename=path.name)
            if score > best_score or (score == best_score and candidate_theme == "traffic"):
                token_css = block.strip()
                theme = candidate_theme
                best_score = score
    return theme, token_css


def resolve_presentation_css(out_dir: Path) -> str:
    theme, token_css = resolve_brand_theme(out_dir)
    base = TRAFFIC_PRESENTATION_CSS if theme == "traffic" else DEFAULT_SMS_PRESENTATION_CSS
    return _merge_root_tokens(base, token_css)


def _token_css_to_publish_override(token_css: str, theme: str) -> str:
    """把品牌自定义 :root token CSS 转换为 publish 阶段可用的作用域覆盖样式。

    publish 基准 CSS（DEFAULT_SMS_PUBLISH_CSS / TRAFFIC_PUBLISH_CSS）使用硬编码色值，
    没有独立的 :root 块，因此不能直接 _merge_root_tokens。本函数采取两种策略：
    1) 对于 publish CSS 中已硬编码的「已知基准色值」，执行精确字符串替换，
       让自定义主色直接体现在 article 的各个细节位置；
    2) 额外追加一个高特异性作用域覆盖块（.tuoying-bw-article），兜底处理
       基准表里没有的自定义变量对应的属性声明（CSS 自定义属性会继承，
       只要 token 中有对应 --var，作者写出的 inline style=\"var(...)\" 也能生效）。
    """
    raw = token_css.strip()
    if not raw:
        return ""

    # --- 1. 从 token_css 提取 --name: value 对 ---
    # 先去掉外层 :root { }
    body_match = re.search(r":root\s*\{([\s\S]*)\}", raw, flags=re.I)
    body = body_match.group(1) if body_match else raw
    declarations = {}
    for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;}]+)", body):
        name = m.group(1).strip()
        value = m.group(2).strip()
        if name and value:
            declarations[name] = value
    if not declarations:
        return ""

    # --- 2. 基准色值精确替换映射表 ---
    # key = publish CSS 中硬编码的颜色常量值（小写，去掉空格以便匹配）
    # value = token 中的候选变量名（若存在则替换）
    base_map = {
        "sms": {
            "#5d765f": ["--green"],
            "#39433c": ["--text-body"],
            "#2d3831": ["--heading-secondary", "--text-body", "--green-dark"],
            "#132019": ["--heading-primary"],
            "#213027": ["--heading-secondary"],
            "#eef3ec": ["--green-light-bg"],
            "#c9d5c5": ["--border-green"],
            "#687268": ["--text-muted"],
            "#fbfcf8": ["--section-bg"],
            "#f1f5ef": ["--faq-question-bg"],
            "#f6f8f3": ["--faq-answer-bg"],
            "#dfe2da": ["--border-default"],
            "#f5f8f3": ["--green-lighter-bg"],
            "#f1f3ed": ["--ref-bg"],
        },
        "traffic": {
            "#b22222": ["--tc-red"],
            "#7f1d1d": ["--tc-red-dark"],
            "#dc3545": ["--tc-red-light"],
            "#18181b": ["--tc-gray-900"],
            "#2d2d2d": ["--tc-gray-800"],
            "#52525b": ["--tc-gray-700"],
            "#888888": ["--tc-gray-500"],
            "#cccccc": ["--tc-gray-300"],
            "#e8e8e8": ["--tc-gray-200"],
            "#f5f5f5": ["--tc-gray-100"],
            "#ffffff": ["--tc-white"],
            "#f4f4f6": ["--tc-bg"],
        },
    }
    replace_map: Dict[str, str] = {}
    theme_table = base_map.get(theme, {})
    for hard_color, var_names in theme_table.items():
        for vn in var_names:
            if vn in declarations:
                replace_map[hard_color] = declarations[vn]
                break

    base = TRAFFIC_PUBLISH_CSS if theme == "traffic" else DEFAULT_SMS_PUBLISH_CSS
    replaced = base
    if replace_map:
        # 大小写不敏感替换，保留声明顺序
        def _sub(m):
            return replace_map[m.group(0).lower()]
        pattern = re.compile("|".join(re.escape(k) for k in replace_map.keys()), flags=re.I)
        replaced = pattern.sub(_sub, replaced)

    # --- 3. 追加作用域覆盖，兜底自定义变量 ---
    # 把 :root 变量挂载到 article 根容器（继承向下传递），
    # 再把 token 中能识别到的常用 token 映射到 .tuoying-bw-article 的属性。
    scope_name = ".tuoying-bw-article"
    scoped_vars_body = "\n  ".join(f"{k}: {v};" for k, v in declarations.items())
    override_block = (
        f"\n/* Brand custom tokens (publish override, theme={theme}) */\n"
        f"{scope_name} {{\n  {scoped_vars_body}\n}}\n"
    )

    # 常用属性映射（变量名 → CSS 属性），能识别就多一层兜底
    prop_map = [
        ("--font", "font-family"),
        ("--tc-font", "font-family"),
        ("--heading-primary", "color"),
        ("--tc-gray-900", "color"),
        ("--text-body", "color"),
    ]
    extra_rules = []
    for var_name, css_prop in prop_map:
        if var_name in declarations:
            extra_rules.append(f"{scope_name} {{ {css_prop}: var({var_name}); }}")
    if extra_rules:
        override_block += "\n".join(extra_rules) + "\n"

    return replaced + "\n" + override_block


def resolve_publish_theme_css(out_dir: Path) -> str:
    theme, token_css = resolve_brand_theme(out_dir)
    if not token_css.strip():
        return TRAFFIC_PUBLISH_CSS if theme == "traffic" else DEFAULT_SMS_PUBLISH_CSS
    return _token_css_to_publish_override(token_css, theme)
