#!/usr/bin/env python3
"""将 Markdown 正文字段化为带 data-field / data-seq 的 HTML 片段。

供 S005 调用。输出 005 字段化文档.html（非完整页面，供 S006 包裹）。
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding="utf-8")


def parse_semantic_types(structure_md: str) -> Dict[str, str]:
    """从 003 文章结构.md 提取 H2 标题 → semantic_type 映射。"""
    mapping: Dict[str, str] = {}
    # 常见写法: ## Title (type) 或 semantic_type: xxx / type: xxx
    for m in re.finditer(
        r"^##\s+(.+?)(?:\s*[|｜]\s*|\s*\()\s*([a-zA-Z_][\w\-]*)\s*\)?\s*$",
        structure_md,
        re.M,
    ):
        title = m.group(1).strip().rstrip("#").strip()
        mapping[title.lower()] = m.group(2).strip().lower()

    for m in re.finditer(
        r"(?:^|\n)[-*]\s*(?:H2|标题)[:：]?\s*(.+?)\s*[,，]\s*(?:semantic_)?type[:：]?\s*([a-zA-Z_][\w\-]*)",
        structure_md,
        re.I,
    ):
        mapping[m.group(1).strip().lower()] = m.group(2).strip().lower()

    for m in re.finditer(
        r"(?:^|\n)##\s+(.+)\n(?:.*\n)*?(?:semantic_type|type)\s*[:：]\s*`?([a-zA-Z_][\w\-]*)`?",
        structure_md,
        re.I,
    ):
        mapping[m.group(1).strip().lower()] = m.group(2).strip().lower()

    return mapping


def _inline_md(text: str) -> str:
    """有限 Markdown 行内转换。先保护链接，避免 URL 中的下划线被当成斜体。"""
    links: list[tuple[str, str]] = []

    def _park_link(match: re.Match) -> str:
        links.append((match.group(1), match.group(2)))
        return f"\x00LINK{len(links) - 1}\x00"

    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", _park_link, text)
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    for index, (label, url) in enumerate(links):
        anchor = (
            f'<a href="{html.escape(url, quote=True)}" rel="noopener noreferrer">'
            f"{html.escape(label)}</a>"
        )
        text = text.replace(f"\x00LINK{index}\x00", anchor)
    return text


def _guess_type(title: str, mapping: Dict[str, str], default: str = "section") -> str:
    key = title.strip().lower()
    if key in mapping:
        return mapping[key]
    for k, v in mapping.items():
        if k in key or key in k:
            return v
    lowered = key
    if "faq" in lowered:
        return "faq"
    if "reference" in lowered or "参考" in lowered:
        return "references"
    if "intro" in lowered or "概述" in lowered or "什么是" in lowered:
        return "intro"
    if "结论" in lowered or "总结" in lowered or "conclusion" in lowered:
        return "conclusion"
    if "对比" in lowered or "compar" in lowered:
        return "comparison"
    return default


def _paragraph_field(text: str, idx: int) -> str:
    low = text.lower()
    if text.strip().startswith(">") or text.strip().startswith("「"):
        field = "quote"
    elif re.search(r"\d+%|\d+\.\d+|\$\d+", text):
        field = "data"
    elif "例如" in text or "for example" in low or "e.g." in low:
        field = "example"
    elif idx == 0:
        field = "hook"
    else:
        field = "explanation"
    return field


def _flush_list(
    items: List[str], list_tag: str, seq: int
) -> Tuple[str, int]:
    if not items:
        return "", seq
    lis = []
    for item in items:
        seq += 1
        lis.append(
            f'<li data-field="list_item" data-seq="{seq:02d}">{_inline_md(item)}</li>'
        )
    seq += 1
    block = (
        f'<{list_tag} data-field="list" data-seq="{seq:02d}">'
        + "".join(lis)
        + f"</{list_tag}>"
    )
    return block, seq


def convert_section_body(body: str, start_seq: int = 1) -> Tuple[str, int]:
    """把一个 H2 节内的 Markdown 转为带标记的 HTML。"""
    lines = body.splitlines()
    out: List[str] = []
    seq = start_seq
    i = 0
    para_idx = 0
    list_items: List[str] = []
    list_tag = "ul"

    def flush_list():
        nonlocal list_items, list_tag, seq
        html_block, seq = _flush_list(list_items, list_tag, seq)
        if html_block:
            out.append(html_block)
        list_items = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_list()
            i += 1
            continue

        # 表格
        if "|" in stripped and i + 1 < len(lines) and re.match(r"^\s*\|?[\s\-:|]+\|", lines[i + 1]):
            flush_list()
            rows = []
            while i < len(lines) and "|" in lines[i]:
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not re.match(r"^[\s\-:]+$", "".join(row)):
                    rows.append(row)
                i += 1
            if rows:
                seq += 1
                thead = "".join(f"<th>{_inline_md(c)}</th>" for c in rows[0])
                body_rows = []
                for row in rows[1:]:
                    body_rows.append(
                        "<tr>" + "".join(f"<td>{_inline_md(c)}</td>" for c in row) + "</tr>"
                    )
                out.append(
                    f'<table data-field="table" data-seq="{seq:02d}">'
                    f"<thead><tr>{thead}</tr></thead>"
                    f"<tbody>{''.join(body_rows)}</tbody></table>"
                )
            continue

        # H3
        if stripped.startswith("### "):
            flush_list()
            seq += 1
            title = stripped[4:].strip()
            out.append(
                f'<h3 data-field="heading" data-seq="{seq:02d}">{_inline_md(title)}</h3>'
            )
            i += 1
            continue

        # References 条目（必须先于普通列表，避免 URL 下划线被当成斜体）
        ref_m = re.match(r"^[-*]\s+\[(.+?)\]\((https?://[^)]+)\)(.*)$", stripped)
        if ref_m:
            flush_list()
            seq += 1
            label, url, rest = ref_m.group(1), ref_m.group(2), ref_m.group(3)
            out.append(
                f'<p data-field="reference" data-seq="{seq:02d}">'
                f'<a href="{html.escape(url, quote=True)}" rel="noopener noreferrer">'
                f"{_inline_md(label)}</a>{_inline_md(rest)}</p>"
            )
            i += 1
            continue

        # 列表
        m_ul = re.match(r"^[-*+]\s+(.+)$", stripped)
        m_ol = re.match(r"^\d+\.\s+(.+)$", stripped)
        if m_ul or m_ol:
            tag = "ul" if m_ul else "ol"
            if list_items and tag != list_tag:
                flush_list()
            list_tag = tag
            list_items.append((m_ul or m_ol).group(1))
            i += 1
            continue

        # 引用
        if stripped.startswith(">"):
            flush_list()
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            seq += 1
            out.append(
                f'<blockquote data-field="quote" data-seq="{seq:02d}">'
                f"<p>{_inline_md(' '.join(quote_lines))}</p></blockquote>"
            )
            continue

        # FAQ 风格: **Q?** 后跟答案段
        faq_m = re.match(r"^\*\*(.+\?)\*\*\s*$", stripped) or re.match(
            r"^###?\s*(.+\?)\s*$", stripped
        )
        if faq_m:
            flush_list()
            q = faq_m.group(1).strip()
            i += 1
            ans_lines = []
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("#"):
                if re.match(r"^\*\*.+\?\*\*\s*$", lines[i].strip()):
                    break
                ans_lines.append(lines[i].strip())
                i += 1
            seq += 1
            ans_html = _inline_md(" ".join(ans_lines)) if ans_lines else ""
            out.append(
                f'<details class="faq-item" data-field="faq" data-seq="{seq:02d}">'
                f"<summary>{_inline_md(q)}</summary>"
                f'<div class="faq-answer"><p data-field="faq_answer">{ans_html}</p></div>'
                f"</details>"
            )
            continue

        # 普通段落（合并续行）
        flush_list()
        para = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (
                not nxt
                or nxt.startswith("#")
                or nxt.startswith(">")
                or nxt.startswith("|")
                or re.match(r"^[-*+]\s+", nxt)
                or re.match(r"^\d+\.\s+", nxt)
            ):
                break
            para.append(nxt)
            i += 1
        text = " ".join(para)
        field = _paragraph_field(text, para_idx)
        para_idx += 1
        seq += 1
        out.append(
            f'<p data-field="{field}" data-seq="{seq:02d}">{_inline_md(text)}</p>'
        )

    flush_list()
    return "\n".join(out), seq


def split_h2_sections(draft: str) -> List[Tuple[str, str]]:
    """返回 [(h2_title, body), ...]；开头无 H2 的前言归入 intro。"""
    text = draft.strip()
    # 去掉首行 # 标题（留给呈现层）
    text = re.sub(r"^#\s+.+\n+", "", text, count=1)
    parts = re.split(r"^##\s+(.+)$", text, flags=re.M)
    sections: List[Tuple[str, str]] = []
    if parts[0].strip():
        sections.append(("Introduction", parts[0].strip()))
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections.append((title, body))
    return sections


def field_markup(draft_md: str, structure_md: str = "") -> str:
    mapping = parse_semantic_types(structure_md)
    sections = split_h2_sections(draft_md)
    chunks: List[str] = []
    seq_counter = 0

    for idx, (title, body) in enumerate(sections, start=1):
        stype = _guess_type(title, mapping, default="intro" if idx == 1 else "section")
        inner, used = convert_section_body(body, start_seq=1)
        seq_counter += 1
        # FAQ 节用专用外壳
        if stype == "faq" or "faq" in title.lower():
            chunks.append(
                f'<section class="faq-section" data-field="faq" data-seq="{idx:02d}">\n'
                f"<h2>{html.escape(title)}</h2>\n"
                f'<div class="faq-list">\n{inner}\n</div>\n</section>'
            )
        elif stype == "references" or "reference" in title.lower() or "参考" in title:
            chunks.append(
                f'<section class="references-section" data-field="references" data-seq="{idx:02d}">\n'
                f"<h2>{html.escape(title)}</h2>\n{inner}\n</section>"
            )
        else:
            heading = f"<h2>{html.escape(title)}</h2>\n" if title != "Introduction" else ""
            chunks.append(
                f'<section data-field="{html.escape(stype)}" data-seq="{idx:02d}">\n'
                f"{heading}{inner}\n</section>"
            )
        _ = used

    return "\n\n".join(chunks).strip() + "\n"


def run(
    draft: Path,
    structure: Optional[Path],
    out: Path,
) -> None:
    draft_md = _read(draft)
    structure_md = _read(structure) if structure and structure.exists() else ""
    html_body = field_markup(draft_md, structure_md)

    if "<section" not in html_body or "data-field=" not in html_body:
        raise SystemExit("ERROR: 字段化结果缺少 section/data-field")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_body, encoding="utf-8")
    print(f"OK: wrote {out.name} ({len(html_body)} bytes)", file=sys.stderr)
    print(f"OK: {out}")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Markdown → 字段化 HTML")
    parser.add_argument("--draft", default="004 正文.md")
    parser.add_argument("--structure", default="003 文章结构.md")
    parser.add_argument("--out", default="005 字段化文档.html")
    parser.add_argument("--out-dir", default="", help="若指定，相对路径基于该目录")
    args = parser.parse_args(argv)

    base = Path(args.out_dir).resolve() if args.out_dir else Path.cwd()
    draft = Path(args.draft)
    structure = Path(args.structure)
    out = Path(args.out)
    if not draft.is_absolute():
        draft = base / draft
    if not structure.is_absolute():
        structure = base / structure
    if not out.is_absolute():
        out = base / out

    try:
        run(draft, structure, out)
    except FileNotFoundError as e:
        print(f"ERROR: 文件不存在: {e}", file=sys.stderr)
        return 1
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
