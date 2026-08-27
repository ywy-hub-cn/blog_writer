#!/usr/bin/env python3
"""将 007 发布包发布到 WordPress（草稿）。

从 brand_path 或 out-dir 查找 wp-config.json，调用 WP REST + 可选 Rank Math。
未配置凭据时必须显式传入 --dry-run；默认会 hard fail，避免无图草稿被当成发布成功。
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_wp_config(brand_path: str, out_dir: Path) -> Optional[Path]:
    candidates = []
    if brand_path:
        bp = Path(brand_path)
        candidates.extend(
            [
                bp / "wp-config.json",
                bp / "config" / "wp-config.json",
            ]
        )
    candidates.extend(
        [
            out_dir / "wp-config.json",
            out_dir / "brand" / "wp-config.json",
            out_dir.parent.parent / "brands" / "wp-config.json",
        ]
    )
    for p in candidates:
        if p.exists():
            return p
    return None


def extract_body_from_md(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8")
    m = re.search(
        r"###\s*Final article body\s*\n+```html\n([\s\S]*?)\n```",
        text,
        re.I,
    )
    return m.group(1).strip() if m else ""


def basic_auth_header(username: str, app_password: str) -> str:
    raw = f"{username}:{app_password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def http_json(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    body: Optional[Dict[str, Any]] = None,
    timeout: int = 60,
) -> Tuple[int, Any]:
    data = None
    req_headers = dict(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return resp.status, {"raw": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return e.code, payload


def upload_media(
    site_url: str,
    auth: str,
    image_url: str,
    timeout: int = 60,
    base_dir: Optional[Path] = None,
) -> Tuple[Optional[int], str]:
    if not image_url:
        return None, ""
    raw = b""
    filename = "image.png"
    content_type = "application/octet-stream"

    if image_url.startswith("http"):
        try:
            with urllib.request.urlopen(image_url, timeout=timeout) as response:
                raw = response.read()
                content_type = response.headers.get_content_type()
            filename = Path(urllib.parse.urlparse(image_url).path).name or "image.jpg"
        except Exception as e:
            print(f"WARN: 远程图片下载失败: {e}", file=sys.stderr)
            return None, ""
    elif image_url.startswith("data:image/"):
        try:
            header, encoded = image_url.split(",", 1)
            content_type = header[5:].split(";", 1)[0]
            raw = base64.b64decode(encoded) if ";base64" in header else urllib.parse.unquote_to_bytes(encoded)
            extension = mimetypes.guess_extension(content_type) or ".png"
            filename = f"image{extension}"
        except Exception as e:
            print(f"WARN: data URI 图片解码失败: {e}", file=sys.stderr)
            return None, ""
    else:
        path = Path(image_url)
        if not path.is_absolute() and base_dir is not None:
            path = base_dir / path
        if not path.exists():
            return None, ""
        raw = path.read_bytes()
        filename = path.name
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    if not raw:
        return None, ""
    req = urllib.request.Request(
        f"{site_url.rstrip('/')}/wp-json/wp/v2/media",
        data=raw,
        headers={
            "Authorization": auth,
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            media_id = int(data.get("id") or 0) or None
            return media_id, str(data.get("source_url") or "")
    except Exception as e:
        print(f"WARN: 图片上传失败: {e}", file=sys.stderr)
        return None, ""


def update_rankmath(
    site_url: str,
    auth: str,
    post_id: int,
    seo_title: str,
    meta_description: str,
) -> bool:
    url = f"{site_url.rstrip('/')}/wp-json/rankmath/v1/updateMeta"
    status, _ = http_json(
        "POST",
        url,
        headers={"Authorization": auth},
        body={
            "objectID": post_id,
            "objectType": "post",
            "meta": {
                "rank_math_title": seo_title,
                "rank_math_description": meta_description,
            },
        },
    )
    return 200 <= status < 300


def publish(out_dir: Path, brand_path: str = "", dry_run: bool = False) -> Dict[str, Any]:
    pkg_json = out_dir / "007 发布包.json"
    pkg_md = out_dir / "007 发布包.md"

    if not pkg_json.exists():
        # 尝试先组装（不依赖 CWD / sys.path）
        try:
            import importlib.util
            script = Path(__file__).resolve().parent / "assemble_publish.py"
            spec = importlib.util.spec_from_file_location("assemble_publish", script)
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(mod)
            mod.assemble(out_dir)
        except Exception as e:
            raise SystemExit(
                f"ERROR: 缺少 007 发布包.json，请先运行 assemble_publish.py ({e})"
            )

    pkg = _load_json(pkg_json)
    body_html = pkg.get("body_html") or extract_body_from_md(pkg_md)
    if not body_html:
        raise SystemExit("ERROR: 发布包缺少 Final article body HTML")

    cfg_path = find_wp_config(brand_path, out_dir)
    record_path = out_dir / "发布记录.json"

    if not cfg_path and not dry_run:
        raise SystemExit(
            "ERROR: 未找到 wp-config.json，无法上传正文图片并真实发布。"
            "本地联调请显式传入 --dry-run"
        )

    if dry_run:
        unresolved_images = [
            src
            for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html, re.I)
            if not src.startswith(("http://", "https://"))
        ]
        record = {
            "post_id": 0,
            "post_url": "",
            "status": "dry-run",
            "dry_run": True,
            "reason": "dry_run",
            "title": pkg.get("title", ""),
            "slug": pkg.get("slug", ""),
            "images_ready": not unresolved_images,
            "unresolved_images": unresolved_images,
        }
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK: dry-run 发布记录已写入 {record_path.name}")
        return record

    cfg = _load_json(cfg_path)
    site_url = (cfg.get("site_url") or cfg.get("url") or "").rstrip("/")
    username = cfg.get("username") or cfg.get("user") or ""
    app_password = cfg.get("app_password") or cfg.get("application_password") or ""
    if not site_url or not username or not app_password:
        raise SystemExit("ERROR: wp-config.json 缺少 site_url/username/app_password")

    auth = basic_auth_header(username, app_password)
    cover_image = pkg.get("cover_image") or ""
    featured_media = None
    image_sources = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html, re.I)
    uploaded_images = 0
    failed_local_images = []
    for image_src in dict.fromkeys(image_sources):
        media_id, media_url = upload_media(
            site_url,
            auth,
            image_src,
            base_dir=out_dir,
        )
        if media_url:
            uploaded_images += 1
            body_html = body_html.replace(
                f'src="{image_src}"',
                f'src="{media_url}"',
            ).replace(
                f"src='{image_src}'",
                f"src='{media_url}'",
            )
        elif not image_src.startswith(("http://", "https://")):
            failed_local_images.append(image_src)
        if image_src == cover_image and media_id:
            featured_media = media_id

    if failed_local_images:
        raise SystemExit(
            "ERROR: 正文图片上传失败，已阻止创建无图草稿: "
            + ", ".join(failed_local_images)
        )

    unresolved_images = [
        src
        for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body_html, re.I)
        if not src.startswith(("http://", "https://"))
    ]
    if unresolved_images:
        raise SystemExit(
            "ERROR: 正文仍包含不可发布的本地/data 图片地址: "
            + ", ".join(unresolved_images)
        )

    # cover_image may not be present in body HTML in legacy packages.
    if cover_image and featured_media is None:
        featured_media, _ = upload_media(
            site_url,
            auth,
            cover_image,
            base_dir=out_dir,
        )

    post_body: Dict[str, Any] = {
        "title": pkg.get("title") or pkg.get("seo_title") or "Untitled",
        "slug": pkg.get("slug") or "",
        "content": body_html,
        "excerpt": pkg.get("excerpt") or "",
        "status": "draft",
    }
    if featured_media:
        post_body["featured_media"] = featured_media

    status, data = http_json(
        "POST",
        f"{site_url}/wp-json/wp/v2/posts",
        headers={"Authorization": auth},
        body=post_body,
    )
    if status not in (200, 201) or not isinstance(data, dict):
        raise SystemExit(f"ERROR: 创建文章失败 HTTP {status}: {data}")

    post_id = int(data.get("id") or 0)
    post_url = data.get("link") or ""
    if post_id > 0:
        try:
            update_rankmath(
                site_url,
                auth,
                post_id,
                pkg.get("seo_title") or "",
                pkg.get("meta_description") or "",
            )
        except Exception as e:
            print(f"WARN: Rank Math 写入失败: {e}", file=sys.stderr)

    record = {
        "post_id": post_id,
        "post_url": post_url,
        "status": "draft",
        "dry_run": False,
        "title": post_body["title"],
        "slug": post_body.get("slug", ""),
        "image_count": len(set(image_sources)),
        "uploaded_image_count": uploaded_images,
        "images_ready": True,
    }
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: 已发布草稿 post_id={post_id} url={post_url}")
    return record


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="发布到 WordPress")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--brand-path", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).resolve()
    if not out_dir.is_dir():
        print(f"ERROR: out-dir 不存在: {out_dir}", file=sys.stderr)
        return 1
    try:
        publish(out_dir, brand_path=args.brand_path, dry_run=args.dry_run)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
