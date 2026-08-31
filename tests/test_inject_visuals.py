import importlib.util
import json
import re
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


def _sample_html(title: str = "OTP SMS Verification Guide") -> str:
    return f"""<!DOCTYPE html>
<html><head><title>{title}</title></head><body>
<div class="blog-content">
<h1>{title}</h1>
<section><h2>Delivery chain overview</h2><p>Body text here.</p></section>
<section><h2>Retry decision logic</h2><p>More body text.</p></section>
</div>
</body></html>"""


def test_inject_visuals_produces_svg_cover_and_mermaid(tmp_path: Path):
    """New test: verify SVG cover + Mermaid diagrams are generated."""
    mod = _load("inject_visuals.py")
    (tmp_path / "006 呈现文档.html").write_text(_sample_html(), encoding="utf-8")
    (tmp_path / "000 BID.json").write_text(
        json.dumps({"keyword": "OTP SMS verification", "title": "OTP SMS Guide"}),
        encoding="utf-8",
    )

    mod.run(tmp_path)

    html = (tmp_path / "006 呈现文档.html").read_text(encoding="utf-8")
    # Verify cover figure exists
    assert 'data-seq="cover"' in html
    # Verify Mermaid diagrams exist
    assert 'data-seq="mermaid-1"' in html
    assert 'data-seq="mermaid-2"' in html
    # Verify Mermaid CDN injected
    assert "cdn.jsdelivr.net/npm/mermaid" in html
    # Verify SVG cover was generated
    svg_path = tmp_path / "visual-cover.svg"
    assert svg_path.exists()
    assert svg_path.stat().st_size > 200
    svg_content = svg_path.read_text(encoding="utf-8")
    assert "<svg" in svg_content
    # Verify cover is referenced in HTML
    assert "visual-cover.svg" in html

    # Validation log should exist (pass or warn, not fail)
    log_path = tmp_path / "007-visual-validation.log"
    assert log_path.exists()
    log = log_path.read_text(encoding="utf-8")
    # In relaxed mode, [PASS] or [OK] is expected
    assert "[PASS]" in log or "[OK]" in log or "[WARN]" in log


def test_inject_visuals_strips_old_visuals_and_reinjects(tmp_path: Path):
    """Test: old pixel PNG visuals get stripped and replaced with SVG/Mermaid."""
    mod = _load("inject_visuals.py")
    validator = _load("validate_visuals.py")
    (tmp_path / "000 BID.json").write_text(
        json.dumps({"keyword": "SMS routing failover"}),
        encoding="utf-8",
    )
    # Create HTML with old-style pixel PNG visuals
    bad_html = _sample_html().replace(
        "</h1>",
        '</h1><figure data-seq="cover"><img src="visual-cover.png" alt="understand apply">'
        '<figcaption>understand apply</figcaption></figure>',
    )
    (tmp_path / "006 呈现文档.html").write_text(bad_html, encoding="utf-8")
    # Create a fake PNG file
    (tmp_path / "visual-cover.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 128)

    # Run inject_visuals - it should detect old visuals and reinject
    mod.run(tmp_path)
    
    html = (tmp_path / "006 呈现文档.html").read_text(encoding="utf-8")
    # Old placeholder text should be gone
    assert "understand apply" not in html.lower()
    # New SVG cover should be present
    assert "visual-cover.svg" in html
    # Mermaid diagrams should be present
    assert "mermaid" in html.lower()


def test_mermaid_clean_for_special_chars():
    """Test: _clean_for_mermaid handles special characters properly."""
    mod = _load("inject_visuals.py")
    # Special characters should be removed
    cleaned = mod._clean_for_mermaid("Test <with> {special} [chars] |here|")
    assert "<" not in cleaned
    assert ">" not in cleaned
    assert "{" not in cleaned
    assert "}" not in cleaned
    assert "[" not in cleaned
    assert "]" not in cleaned
    assert "|" not in cleaned
    # Should still preserve the core text
    assert "Test" in cleaned
    assert "with" in cleaned
    assert "special" in cleaned
    assert "chars" in cleaned
    assert "here" in cleaned


def test_mermaid_code_generation():
    """Test: _generate_mermaid_code produces valid Mermaid syntax."""
    mod = _load("inject_visuals.py")
    
    # First section should produce a mindmap
    code0 = mod._generate_mermaid_code("Overview", "OTP SMS", 0, 3, ["Overview", "Details", "Examples"])
    assert "mindmap" in code0
    assert "root" in code0
    
    # Second section should produce a flowchart TD
    code1 = mod._generate_mermaid_code("Key Concepts", "OTP SMS", 1, 3, ["Overview", "Details", "Examples"])
    assert "flowchart TD" in code1
    
    # Third+ sections should produce flowchart LR
    code2 = mod._generate_mermaid_code("Implementation", "OTP SMS", 2, 3, ["Overview", "Details", "Examples"])
    assert "flowchart LR" in code2


def test_svg_cover_generation(tmp_path: Path):
    """Test: SVG cover is generated with proper structure."""
    mod = _load("inject_visuals.py")
    palettes = mod.PALETTES
    assert len(palettes) >= 4  # At least 4 different color schemes
    
    output_path = tmp_path / "test-cover.svg"
    mod._generate_cover_svg("Test Article Title", "test-keyword", output_path, 0)
    
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "<svg" in content
    assert "viewBox" in content
    assert "linearGradient" in content
    assert "Test Article Title" in content or "Test" in content


def test_different_palettes_produce_different_colors(tmp_path: Path):
    """Test: different palette indices produce visually different SVGs."""
    mod = _load("inject_visuals.py")
    
    paths = []
    for i in range(len(mod.PALETTES)):
        p = tmp_path / f"cover-{i}.svg"
        mod._generate_cover_svg(f"Article {i}", "keyword", p, i)
        paths.append(p)
    
    # All files should exist and have content
    for p in paths:
        assert p.exists()
        assert p.stat().st_size > 200
    
    # At least some should have different content (different colors)
    contents = [p.read_text(encoding="utf-8") for p in paths]
    # Not all should be identical
    assert len(set(contents)) > 1
