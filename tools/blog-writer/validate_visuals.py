#!/usr/bin/env python3
"""Fail closed when article visuals are missing, duplicated, or placeholders."""
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
    if not path.is_file() or path.stat().st_size < 100:
        return False
    signature = path.read_bytes()[:12]
    return (
        signature.startswith(b"\x89PNG\r\n\x1a\n")
        or signature.startswith(b"\xff\xd8\xff")
        or signature.startswith((b"GIF87a", b"GIF89a"))
        or (len(signature) >= 12 and signature[8:12] == b"WEBP")
    )


def validate_visuals(out_dir: Path) -> list[str]:
    target = out_dir / "006 呈现文档.html"
    if not target.exists():
        return [f"缺少 {target.name}"]
    document = target.read_text(encoding="utf-8")
    lowered = document.lower()
    errors: list[str] = []

    for placeholder in PLACEHOLDERS:
        if placeholder in lowered:
            errors.append(f"视觉内容包含占位文本: {placeholder}")

    figures = re.findall(r"<figure\b[^>]*>[\s\S]*?</figure>", document, re.I)
    image_sources = re.findall(
        r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']',
        document,
        re.I,
    )
    cover_count = len(re.findall(r'data-seq=["\']cover["\']', document, re.I))
    inline_count = len(
        re.findall(r'data-seq=["\']mermaid-\d+["\']', document, re.I)
    )
    if cover_count != 1:
        errors.append(f"封面图数量必须为 1，实际 {cover_count}")
    if inline_count < 1:
        errors.append(f"正文图数量不足 1，实际 {inline_count}")
    # 新生成默认最多 2 张；旧稿若已有更多图，允许保留，不因上限硬失败
    if len(figures) < 2 or len(image_sources) < 2:
        errors.append(
            f"视觉元素不足: figures={len(figures)}, images={len(image_sources)}（至少封面+1）"
        )
    if len(set(image_sources)) != len(image_sources):
        errors.append("存在重复图片 src，视觉元素不能复用同一图片")

    for source in image_sources:
        if source.startswith(("http://", "https://", "data:image/")):
            continue
        parsed = urlparse(source)
        local_path = out_dir / unquote(parsed.path)
        if not _is_real_local_image(local_path):
            errors.append(f"本地图片不存在或格式无效: {source}")

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
        if len(meaningful_words) < 3:
            errors.append(f"第 {index} 个视觉元素缺少主题相关 alt/caption")

    log_path = out_dir / "007-visual-validation.log"
    if errors:
        log_path.write_text(
            "[FAIL] 视觉校验失败\n" + "\n".join(f"- {item}" for item in errors) + "\n",
            encoding="utf-8",
        )
    else:
        log_path.write_text(
            f"[OK] 视觉校验通过: cover={cover_count}, inline={inline_count}, "
            f"unique_images={len(set(image_sources))}\n",
            encoding="utf-8",
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验文章视觉元素")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    errors = validate_visuals(Path(args.out_dir).resolve())
    if errors:
        print("ERROR: " + "; ".join(errors), file=sys.stderr)
        return 1
    print("OK: 视觉元素数量、唯一性、文件格式和文案校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
