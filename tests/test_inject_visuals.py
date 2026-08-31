import importlib.util
import json
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
<section><h2>Delivery chain overview</h2>
<p>OTP SMS starts when the application requests a verification code.</p>
<ul>
<li>Application creates the OTP request</li>
<li>API gateway authenticates the sender</li>
<li>Router selects the best carrier path</li>
<li>Device receives and verifies the code</li>
</ul>
</section>
<section><h2>Retry decision logic</h2>
<p>Operators must decide whether to retry failed deliveries.</p>
<ul>
<li>Check provider error class</li>
<li>Compare soft fail vs hard fail</li>
<li>Apply rate limits before resend</li>
<li>Escalate risk checks for SIM swap</li>
</ul>
</section>
<section><h2>FAQ</h2><p>Should not receive a diagram.</p></section>
</div>
</body></html>"""


def test_inject_visuals_produces_svg_cover_and_mermaid(tmp_path: Path):
    """Verify SVG cover + content-aware Mermaid diagrams are generated."""
    mod = _load("inject_visuals.py")
    (tmp_path / "006 呈现文档.html").write_text(_sample_html(), encoding="utf-8")
    (tmp_path / "000 BID.json").write_text(
        json.dumps({"keyword": "OTP SMS verification", "title": "OTP SMS Guide"}),
        encoding="utf-8",
    )

    mod.run(tmp_path)

    html = (tmp_path / "006 呈现文档.html").read_text(encoding="utf-8")
    assert 'data-seq="cover"' in html
    assert 'data-seq="mermaid-1"' in html
    assert 'data-seq="mermaid-2"' in html
    assert "cdn.jsdelivr.net/npm/mermaid" in html
    assert "Application creates the OTP request" in html or "API gateway" in html
    assert "mermaid-container" in html
    assert "Key Concepts" not in html
    assert "Best Practices" not in html

    svg_path = tmp_path / "visual-cover.svg"
    assert svg_path.exists()
    assert svg_path.stat().st_size > 200
    assert "visual-cover.svg" in html

    log_path = tmp_path / "007-visual-validation.log"
    assert log_path.exists()
    log = log_path.read_text(encoding="utf-8")
    assert "[PASS]" in log or "[OK]" in log or "[WARN]" in log


def test_inject_visuals_strips_old_visuals_and_reinjects(tmp_path: Path):
    mod = _load("inject_visuals.py")
    (tmp_path / "000 BID.json").write_text(
        json.dumps({"keyword": "SMS routing failover"}),
        encoding="utf-8",
    )
    bad_html = _sample_html().replace(
        "</h1>",
        '</h1><figure data-seq="cover"><img src="visual-cover.png" alt="understand apply">'
        '<figcaption>understand apply</figcaption></figure>',
    )
    (tmp_path / "006 呈现文档.html").write_text(bad_html, encoding="utf-8")
    (tmp_path / "visual-cover.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 128)

    mod.run(tmp_path)

    html = (tmp_path / "006 呈现文档.html").read_text(encoding="utf-8")
    assert "understand apply" not in html.lower()
    assert "visual-cover.svg" in html
    assert "mermaid" in html.lower()


def test_mermaid_clean_for_special_chars():
    mod = _load("inject_visuals.py")
    cleaned = mod._clean_for_mermaid("Test <with> {special} [chars] |here|")
    assert "<" not in cleaned
    assert ">" not in cleaned
    assert "{" not in cleaned
    assert "}" not in cleaned
    assert "[" not in cleaned
    assert "]" not in cleaned
    assert "|" not in cleaned
    assert "Test" in cleaned
    assert "with" in cleaned
    assert "special" in cleaned
    assert "chars" in cleaned
    assert "here" in cleaned


def test_mermaid_code_generation_is_content_aware():
    mod = _load("inject_visuals.py")

    process = mod._generate_mermaid_code(
        "How to deliver OTP SMS",
        "OTP SMS",
        0,
        3,
        ["How to deliver OTP SMS", "Retry decision logic"],
        points=[
            "Create OTP request",
            "Route via carrier",
            "Verify on device",
        ],
    )
    assert "flowchart TD" in process
    assert "Create OTP request" in process
    assert "Key Concepts" not in process
    assert "Best Practices" not in process

    decision = mod._generate_mermaid_code(
        "Retry decision logic",
        "OTP SMS",
        1,
        3,
        ["Overview", "Retry decision logic"],
        points=["Soft fail", "Hard fail", "Resend", "Stop"],
    )
    assert "flowchart TD" in decision
    assert "Decision point" in decision or "{" in decision

    sequence = mod._generate_mermaid_code(
        "API verification handshake",
        "OTP SMS",
        1,
        3,
        ["Overview", "API verification handshake"],
        points=["App", "API", "Carrier", "Phone"],
    )
    assert "sequenceDiagram" in sequence


def test_extract_section_points_from_lists():
    mod = _load("inject_visuals.py")
    html = _sample_html()
    points = mod._extract_section_points(html, "Delivery chain overview")
    assert len(points) >= 3
    assert any("OTP request" in p for p in points)


def test_classify_skips_faq_and_prefers_process():
    mod = _load("inject_visuals.py")
    assert mod._should_skip_section("FAQ") is True
    assert mod._classify_diagram("How to set up routing", ["step one", "step two"], 1) == "process"


def test_svg_cover_generation(tmp_path: Path):
    mod = _load("inject_visuals.py")
    assert len(mod.PALETTES) >= 4

    output_path = tmp_path / "test-cover.svg"
    mod._generate_cover_svg("Test Article Title", "test-keyword", output_path, 0)

    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "<svg" in content
    assert "viewBox" in content
    assert "linearGradient" in content
    assert "Test Article Title" in content or "Test" in content


def test_different_palettes_produce_different_colors(tmp_path: Path):
    mod = _load("inject_visuals.py")

    paths = []
    for i in range(len(mod.PALETTES)):
        p = tmp_path / f"cover-{i}.svg"
        mod._generate_cover_svg(f"Article {i}", "keyword", p, i)
        paths.append(p)

    for p in paths:
        assert p.exists()
        assert p.stat().st_size > 200

    contents = [p.read_text(encoding="utf-8") for p in paths]
    assert len(set(contents)) > 1
