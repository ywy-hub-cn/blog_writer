import importlib.util
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "blog-writer"


def _load(name: str):
    script = TOOLS / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), script)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _prepare_brand_instance(tmp_path: Path, brand_id: str) -> Path:
    src = ROOT / "brands" / brand_id
    brand_dir = tmp_path / "brand"
    brand_dir.mkdir(parents=True, exist_ok=True)
    for path in src.glob("*.md"):
        shutil.copy2(path, brand_dir / path.name)
    return tmp_path


def test_traffic_brand_uses_red_theme_css(tmp_path: Path):
    brand_css = _load("brand_css.py")
    out_dir = _prepare_brand_instance(tmp_path, "traffic")

    theme, token_css = brand_css.resolve_brand_theme(out_dir)
    css = brand_css.resolve_presentation_css(out_dir)

    assert theme == "traffic"
    assert "--tc-red" in token_css
    assert "#B22222" in css
    assert "var(--tc-red)" in css
    assert "--green:" not in css


def test_sms_brand_uses_green_theme_css(tmp_path: Path):
    brand_css = _load("brand_css.py")
    out_dir = _prepare_brand_instance(tmp_path, "sms-boosting")

    theme, _token_css = brand_css.resolve_brand_theme(out_dir)
    css = brand_css.resolve_presentation_css(out_dir)
    publish_css = brand_css.resolve_publish_theme_css(out_dir)

    assert theme == "sms"
    assert "--green:" in css
    assert "#5D765F" in publish_css


def test_generate_presentation_applies_traffic_css(tmp_path: Path):
    generator = _load("generate_presentation.py")
    out_dir = _prepare_brand_instance(tmp_path, "traffic")
    (out_dir / "005 字段化文档.html").write_text(
        '<div class="blog-content"><h1>Traffic Guide</h1>'
        '<section data-field="section" data-seq="01"><h2>Topic</h2>'
        '<p data-field="paragraph" data-seq="01">Body</p></section></div>',
        encoding="utf-8",
    )
    (out_dir / "000 BID.json").write_text(
        '{"title":"Traffic Guide","seo":{"title":"Traffic Guide","description":"Desc"}}',
        encoding="utf-8",
    )

    generator.generate(out_dir)
    html = (out_dir / "006 呈现文档.html").read_text(encoding="utf-8")

    assert "#B22222" in html
    assert "var(--tc-red)" in html
    assert "--green:" not in html
