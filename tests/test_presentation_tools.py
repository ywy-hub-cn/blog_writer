"""field_markup / generate_presentation / publish dry-run 冒烟测试"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "blog-writer"


def _load(name: str):
    script = TOOLS / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), script)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_field_markup_and_presentation(tmp_path: Path):
    draft = tmp_path / "004 正文.md"
    structure = tmp_path / "003 文章结构.md"
    draft.write_text(
        """# SMS API Guide

## What is SMS API
SMS API lets you send messages programmatically. For example, use HTTP POST.

## How routing works
1. Submit message
2. Choose route
3. Deliver

## FAQ
**What is latency?**
Usually under one second for major corridors.

## References
- [Twilio Docs](https://www.twilio.com/docs)
- [GSMA Report](https://www.gsma.com/example)
""",
        encoding="utf-8",
    )
    structure.write_text(
        "## What is SMS API | intro\n## How routing works | explanation\n",
        encoding="utf-8",
    )

    field = _load("field_markup.py")
    out_html = tmp_path / "005 字段化文档.html"
    field.run(draft, structure, out_html)
    html = out_html.read_text(encoding="utf-8")
    assert "<section" in html
    assert 'data-field="' in html
    assert 'data-seq="' in html
    assert "<p data-field=" in html

    (tmp_path / "000 BID.json").write_text(
        json.dumps(
            {
                "keyword": "SMS API",
                "title": "SMS API Guide",
                "seo_title": "SMS API Guide for Scale",
                "slug": "sms-api-guide",
                "meta_description": "Learn how SMS API routing works for reliable delivery.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "001 启动确认.md").write_text(
        "## 品牌官网\n\nhttps://example.com\n", encoding="utf-8"
    )

    present = _load("generate_presentation.py")
    out = present.generate(tmp_path, brand_site_url="https://example.com")
    doc = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in doc
    assert "<h1>" in doc
    assert "read-time" in doc
    assert 'data-field="' in doc
    assert 'data-seq="' in doc
    assert 'name="description"' in doc
    assert "og:title" in doc
    assert "twitter:card" in doc


def test_publish_to_wp_auto_dry_run_without_config(tmp_path: Path):
    (tmp_path / "007 发布包.json").write_text(
        json.dumps(
            {
                "keyword": "SMS API",
                "title": "SMS API Guide",
                "seo_title": "SMS API Guide",
                "slug": "sms-api-guide",
                "meta_description": "desc",
                "excerpt": "excerpt",
                "body_html": "<p>Hello</p>",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "007 发布包.md").write_text(
        "### Final article body\n\n```html\n<p>Hello</p>\n```\n",
        encoding="utf-8",
    )

    mod = _load("publish_to_wp.py")
    record = mod.publish(tmp_path, brand_path="", dry_run=False)
    assert record["dry_run"] is True
    assert record["post_id"] > 0
    assert (tmp_path / "发布记录.json").exists()


def test_run_script_tool_whitelist(tmp_path: Path):
    from blog_writer.agent.tools import ToolRegistry

    reg = ToolRegistry(working_dir=str(tmp_path), instance_dir=str(tmp_path))
    blocked = reg._run_script("os.remove.py", [])
    assert "error" in blocked

    # setup_brand needs real brand; just ensure script is found & fails gracefully on missing args
    result = reg._run_script("generate_presentation.py", ["--out-dir", str(tmp_path)])
    assert result.get("returncode", 0) != 0 or result.get("success") is False
