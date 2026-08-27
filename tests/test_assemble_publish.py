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
    assert pkg["schema_version"] == "1.0"
    assert pkg["keyword"] == "SMS API"
    assert "Hello" in pkg["body_html"]
    assert 'id="blog-writer-theme"' in pkg["body_html"]
    assert 'class="tuoying-bw-article"' in pkg["body_html"]


def test_extract_article_html_preserves_nested_divs(tmp_path: Path):
    """FAQ/visual nested divs must not truncate the latter article sections."""
    script = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "blog-writer"
        / "assemble_publish.py"
    )
    spec = importlib.util.spec_from_file_location("assemble_publish_nested", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    (tmp_path / "006 呈现文档.html").write_text(
        """<!doctype html><body>
<div class="blog-content">
  <section><h2>Before</h2><div class="visual-mermaid">chart</div></section>
  <section class="faq-section"><div class="faq-list"><div class="faq-answer">answer</div></div></section>
  <section><h2>Conclusion</h2><p>THIS MUST SURVIVE</p></section>
</div>
</body>""",
        encoding="utf-8",
    )

    article = mod.extract_article_html(tmp_path)
    assert "chart" in article
    assert "answer" in article
    assert "THIS MUST SURVIVE" in article
