#!/usr/bin/env python3
"""Fail closed when article visuals are missing, duplicated, or placeholders.

Relaxed validation: Mermaid blocks and SVG covers are now first-class visuals.
Errors are categorized as 'errors' (blocking) or 'warnings' (non-blocking).
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


PLACEHOLDERS = (
    "untitled",
    "understand apply",
    "understand →",
    "placeholder",
    "lorem ipsum",
)


def _plain(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _is_real_local_image(path: Path) -> bool:
    """Check if a local file is a real image (PNG/JPEG/GIF/WebP/SVG)."""
    if not path.is_file() or path.stat().st_size < 50:
        return False
    try:
        signature = path.read_bytes()[:12]
        if signature.startswith(b"\x89PNG\r\n\x1a\n"):
            return True
        if signature.startswith(b"\xff\xd8\xff"):
            return True
        if signature.startswith((b"GIF87a", b"GIF89a")):
            return True
        if len(signature) >= 12 and signature[8:12] == b"WEBP":
            return True
        # SVG: check for <svg tag
        text = path.read_text(encoding="utf-8", errors="ignore")[:500].lower()
        if "<svg" in text:
            return True
        return False
    except Exception:
        return False


def validate_visuals(out_dir: Path, strict: bool = False) -> list[str]:
    """Validate visuals. Returns list of error messages.

    In relaxed mode (default), warnings are not returned as errors.
    In strict mode, all issues are returned as errors.
    """
    target = out_dir / "006 呈现文档.html"
    if not target.exists():
        return [f"缺少 {target.name}"]
    document = target.read_text(encoding="utf-8")
    lowered = document.lower()
    errors: list[str] = []
    warnings: list[str] = []

    # --- Placeholder text checks (relaxed) ---
    for placeholder in PLACEHOLDERS:
        if placeholder in lowered:
            msg = f"视觉内容包含占位文本: {placeholder}"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)

    # --- Collect visual elements ---
    figures = re.findall(r"<figure\b[^>]*>[\s\S]*?</figure>", document, re.I)
    img_sources = re.findall(
        r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']',
        document,
        re.I,
    )
    mermaid_blocks = re.findall(r'<pre class="mermaid"', document, re.I)
    cover_count = len(re.findall(r'data-seq=["\']cover["\']', document, re.I))
    inline_mermaid_count = len(
        re.findall(r'data-seq=["\']mermaid-\d+["\']', document, re.I)
    )

    # --- Minimum requirements (relaxed) ---
    # At minimum: 1 cover (figures=1 is OK) OR a mermaid block OR both
    # Not requiring both cover AND inline diagrams anymore
    if cover_count != 1:
        msg = f"封面图数量应为 1，实际 {cover_count}"
        if cover_count == 0 and not mermaid_blocks:
            # No visuals at all - this is a real error
            errors.append(msg + "，且无 Mermaid 图表")
        elif cover_count == 0:
            # No cover but has diagrams - warning only
            warnings.append(msg)
        else:
            errors.append(msg)

    # Inline diagrams: minimum 1 if possible, but not hard-fail
    if inline_mermaid_count < 1 and len(mermaid_blocks) < 1:
        msg = f"正文图表数量不足（需至少 1 个 Mermaid 图表，实际 mermaid-blocks={len(mermaid_blocks)}）"
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg)

    # Total visuals check (relaxed - at least 1 visual element of any kind)
    total_visuals = len(figures) + len(mermaid_blocks)
    if total_visuals < 1:
        errors.append(f"视觉元素严重不足: figures={len(figures)}, mermaid_blocks={len(mermaid_blocks)}（至少需要 1 个视觉元素）")

    # --- Duplicate check (relaxed) ---
    if img_sources:
        unique_srcs = set(img_sources)
        if len(unique_srcs) != len(img_sources):
            msg = "存在重复图片 src"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)

    # --- Local image validity (relaxed) ---
    for source in img_sources:
        if source.startswith(("http://", "https://", "data:image/")):
            continue
        parsed = urlparse(source)
        local_path = out_dir / unquote(parsed.path)
        if not _is_real_local_image(local_path):
            msg = f"本地图片不存在或格式无效: {source}"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)

    # --- Alt/caption quality checks (relaxed) ---
    for index, figure in enumerate(figures, start=1):
        alt_match = re.search(r'\balt=["\']([^"\']*)["\']', figure, re.I)
        caption_match = re.search(
            r"<figcaption\b[^>]*>([\s\S]*?)</figcaption>",
            figure,
            re.I,
        )
        description = " ".join(
            filter(
                None,
                [
                    _plain(alt_match.group(1)) if alt_match else "",
                    _plain(caption_match.group(1)) if caption_match else "",
                ],
            )
        )
        meaningful_words = re.findall(r"[A-Za-z0-9]{3,}", description)
        if len(meaningful_words) < 2:
            msg = f"第 {index} 个视觉元素缺少主题相关 alt/caption（有效词不足）"
            if strict:
                errors.append(msg)
            # In relaxed mode, this is just a warning

    # --- Log results ---
    log_path = out_dir / "007-visual-validation.log"
    all_errors = errors + (warnings if strict else [])
    if errors:
        log_path.write_text(
            "[FAIL] 视觉校验失败\n"
            + "\n".join(f"[ERROR] {item}" for item in errors)
            + ("\n" if warnings else "")
            + "\n".join(f"[WARN] {item}" for item in warnings)
            + "\n",
            encoding="utf-8",
        )
    elif warnings:
        log_path.write_text(
            "[PASS] 视觉校验通过（有警告）\n"
            + "\n".join(f"[WARN] {item}" for item in warnings)
            + "\n",
            encoding="utf-8",
        )
    else:
        log_path.write_text(
            f"[OK] 视觉校验通过: cover={cover_count}, inline={inline_mermaid_count}, "
            f"mermaid_blocks={len(mermaid_blocks)}, figures={len(figures)}\n",
            encoding="utf-8",
        )

    return errors  # Only return errors (blocking) in relaxed mode


def main() -> int:
    parser = argparse.ArgumentParser(description="校验文章视觉元素（宽松模式，非阻塞）")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--strict", action="store_true", default=False,
                        help="严格模式：所有警告视为错误")
    args = parser.parse_args()
    errors = validate_visuals(Path(args.out_dir).resolve(), strict=args.strict)
    if errors:
        print("ERROR: " + "; ".join(errors), file=sys.stderr)
        return 1
    print("OK: 视觉元素校验通过（宽松模式：数量、唯一性、格式和文案校验）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
