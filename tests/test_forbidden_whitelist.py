"""禁用词单次白名单单元测试"""
import json
import subprocess
import sys
from pathlib import Path

from blog_writer.forbidden import (
    filter_forbidden_words,
    normalize_forbidden_whitelist,
)


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "blog-writer"


def test_normalize_forbidden_whitelist():
    assert normalize_forbidden_whitelist("保证, 最好，唯一") == ["保证", "最好", "唯一"]
    assert normalize_forbidden_whitelist(["保证", "保证", "最佳"]) == ["保证", "最佳"]
    assert normalize_forbidden_whitelist(None) == []
    assert normalize_forbidden_whitelist("") == []


def test_filter_forbidden_words():
    forbidden = ["最好", "保证", "垃圾短信"]
    wl = ["保证"]
    assert filter_forbidden_words(forbidden, wl) == ["最好", "垃圾短信"]


def test_setup_brand_writes_whitelist(tmp_path: Path):
    brand = tmp_path / "brand"
    brand.mkdir()
    (brand / "禁用词清单.md").write_text("# 禁用\n- 最好\n- 保证\n", encoding="utf-8")
    (brand / "品牌知识库.md").write_text("# 知识\nSMS API\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    cmd = [
        sys.executable,
        str(TOOLS / "setup_brand.py"),
        "--brand-path",
        str(brand),
        "--keywords",
        "SMS API",
        "--out-dir",
        str(out),
        "--forbidden-whitelist",
        "保证,最好",
    ]
    env = dict(**{**dict(**__import__("os").environ), "PYTHONIOENCODING": "utf-8"})
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    startup = (out / "001 启动确认.md").read_text(encoding="utf-8")
    assert "## 本次禁用词白名单" in startup
    assert "- 保证" in startup
    data = json.loads((out / "forbidden_whitelist.json").read_text(encoding="utf-8"))
    assert "保证" in data["words"]


def test_setup_brand_autofills_brand_site_url(tmp_path: Path):
    brand = tmp_path / "brand"
    brand.mkdir()
    (brand / "品牌知识库.md").write_text(
        "# 知识\n品牌官网：https://smsboosting.com\nAlso https://smsboosting.com/blog/a\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    out.mkdir()
    cmd = [
        sys.executable,
        str(TOOLS / "setup_brand.py"),
        "--brand-path",
        str(brand),
        "--keywords",
        "OTP SMS",
        "--out-dir",
        str(out),
    ]
    env = dict(**{**dict(**__import__("os").environ), "PYTHONIOENCODING": "utf-8"})
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    startup = (out / "001 启动确认.md").read_text(encoding="utf-8")
    assert "## 品牌官网" in startup
    assert "https://smsboosting.com" in startup
    assert "**品牌官网**: https://smsboosting.com" in startup


def test_check_forbidden_respects_whitelist(tmp_path: Path):
    (tmp_path / "001 启动确认.md").write_text(
        "## 禁用词原文\n\n- 最好\n- 保证\n\n## 本次禁用词白名单\n\n- 保证\n",
        encoding="utf-8",
    )
    (tmp_path / "004 正文.md").write_text(
        "# Title\n\n我们保证送达，但不说最好。\n",
        encoding="utf-8",
    )
    env = dict(**{**dict(**__import__("os").environ), "PYTHONIOENCODING": "utf-8"})
    # 有「最好」应失败
    r = subprocess.run(
        [sys.executable, str(TOOLS / "check_forbidden.py"), "--out-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert r.returncode == 1
    out = (r.stdout or "") + (r.stderr or "")
    assert "最好" in out

    # 去掉「最好」后，仅剩白名单「保证」应通过
    (tmp_path / "004 正文.md").write_text(
        "# Title\n\n我们保证送达。\n",
        encoding="utf-8",
    )
    r2 = subprocess.run(
        [sys.executable, str(TOOLS / "check_forbidden.py"), "--out-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert r2.returncode == 0, (r2.stdout or "") + (r2.stderr or "")
