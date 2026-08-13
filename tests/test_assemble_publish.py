"""assemble_publish / publish 脚本冒烟测试"""
import importlib.util
import json
from pathlib import Path


def test_assemble_publish_creates_package(tmp_path: Path):
    script = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "blog-writer"
        / "assemble_publish.py"
    )
    spec = importlib.util.spec_from_file_location("assemble_publish", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    (tmp_path / "000 BID.json").write_text(
        json.dumps(
            {
                "keyword": "SMS API",
                "title": "7 Proven SMS API Tips",
                "seo_title": "7 Proven SMS API Tips for Scale",
                "slug": "sms-api-tips",
                "meta_description": "Learn proven SMS API patterns for reliable delivery and scale.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "001 启动确认.md").write_text(
        "## 品牌官网\n\nhttps://example.com\n", encoding="utf-8"
    )
    (tmp_path / "006 呈现文档.html").write_text(
        '<div class="blog-content"><section data-field="intro"><p>Hello</p></section></div>',
        encoding="utf-8",
    )

    md_path, json_path = mod.assemble(tmp_path, keyword="SMS API")
    assert md_path.exists()
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("### Keyword")
    assert text.count("### ") == 7
    pkg = json.loads(json_path.read_text(encoding="utf-8"))
    assert pkg["keyword"] == "SMS API"
    assert "Hello" in pkg["body_html"]
