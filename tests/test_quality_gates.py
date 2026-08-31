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


def _draft(citation: str = "[1][2]") -> str:
    return f"""# OTP SMS Guide

OTP SMS helps users verify accounts. {citation}

## First
OTP SMS details.
## Second
OTP SMS details.
## Third
Details.
## Fourth
Details.
## FAQ
Question?
Answer.
Question?
Answer.
Question?
Answer.

[SMSBoosting OTP SMS](https://smsboosting.com/otp-sms/)

## References
- [Source One](https://example.com/one) — first claim
- [Source Two](https://example.org/two) — second claim
"""


def test_content_gate_checks_citations_and_internal_link(tmp_path: Path):
    validator = _load("validate_content.py")
    (tmp_path / "004 正文.md").write_text(_draft(), encoding="utf-8")
    (tmp_path / "000 BID.json").write_text(
        json.dumps({"summary": {"keyword": "OTP SMS"}}),
        encoding="utf-8",
    )
    assert validator.validate_content(
        str(tmp_path),
        "https://smsboosting.com",
    )


def test_content_gate_rejects_out_of_range_citation(tmp_path: Path):
    validator = _load("validate_content.py")
    (tmp_path / "004 正文.md").write_text(_draft("[1][3]"), encoding="utf-8")
    (tmp_path / "000 BID.json").write_text(
        json.dumps({"summary": {"keyword": "OTP SMS"}}),
        encoding="utf-8",
    )
    assert not validator.validate_content(
        str(tmp_path),
        "https://smsboosting.com",
    )


def test_content_gate_rejects_brand_domain_in_references(tmp_path: Path):
    validator = _load("validate_content.py")
    body = _draft().replace(
        "- [Source Two](https://example.org/two) — second claim",
        "- [SMSBoosting](https://smsboosting.com/blog/) — brand page",
    )
    (tmp_path / "004 正文.md").write_text(body, encoding="utf-8")
    (tmp_path / "000 BID.json").write_text(
        json.dumps({"summary": {"keyword": "OTP SMS"}}),
        encoding="utf-8",
    )
    assert not validator.validate_content(
        str(tmp_path),
        "https://smsboosting.com",
    )


def test_start_task_accepts_long_user_note():
    from blog_writer.api.tasks import StartTaskRequest

    note = "A" * 5000
    req = StartTaskRequest.model_validate(
        {
            "brandPath": "brands/sms-boosting",
            "keywords": "OTP SMS",
            "userNote": note,
            "brandSiteUrl": "https://smsboosting.com",
        }
    )
    assert len(req.user_note) == 5000


def test_start_task_rejects_invalid_brand_site_url():
    from blog_writer.api.tasks import StartTaskRequest
    import pytest

    with pytest.raises(Exception):
        StartTaskRequest.model_validate(
            {
                "brandPath": "brands/sms-boosting",
                "keywords": "OTP SMS",
                "brandSiteUrl": "smsboosting.com",
            }
        )


def test_resolve_brand_site_url_supports_setup_brand_formats():
    import importlib.util

    script = TOOLS / "brand_site_url.py"
    spec = importlib.util.spec_from_file_location("brand_site_url", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    inline = "# 启动确认\n## 基本信息\n- **品牌官网**: https://smsboosting.com\n"
    assert mod.resolve_brand_site_url(inline) == "https://smsboosting.com"

    heading = "## 品牌官网\n\nhttps://example.com\n"
    assert mod.resolve_brand_site_url(heading) == "https://example.com"

    placeholder = "## 品牌官网\n未提供\n"
    assert (
        mod.resolve_brand_site_url(placeholder, "https://smsboosting.com")
        == "https://smsboosting.com"
    )

    assert (
        mod.pick_brand_site_url(
            "",
            ["https://smsboosting.com/blog/a", "https://smsboosting.com"],
            brand_text="品牌官网：https://smsboosting.com",
        )
        == "https://smsboosting.com"
    )


def test_visual_gate_rejects_placeholder_and_accepts_real_files(tmp_path: Path):
    validator = _load("validate_visuals.py")
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 128
    for index in range(1, 3):
        (tmp_path / f"section-{index}.png").write_bytes(png)
    document = """
    <html><head><title>OTP SMS Guide</title></head><body>
    <figure data-seq="cover"><img src="https://example.com/cover.jpg"
      alt="OTP SMS verification cover"><figcaption>OTP SMS verification</figcaption></figure>
    <h2>Delivery chain</h2>
    <figure data-seq="mermaid-1"><img src="section-1.png"
      alt="Application carrier delivery chain"><figcaption>Application to carrier delivery</figcaption></figure>
    <h2>Retry logic</h2>
    <figure data-seq="mermaid-2"><img src="section-2.png"
      alt="OTP retry decision flow"><figcaption>OTP retry decision flow</figcaption></figure>
    </body></html>
    """
    (tmp_path / "006 呈现文档.html").write_text(document, encoding="utf-8")
    # 宽松模式：有效视觉元素通过校验（返回空错误列表）
    assert validator.validate_visuals(tmp_path) == []

    # 宽松模式：placeholder 仅记录警告，不阻塞流程
    (tmp_path / "006 呈现文档.html").write_text(
        document.replace("OTP SMS Guide", "Untitled"),
        encoding="utf-8",
    )
    # 宽松模式下 placeholder 是警告，不阻塞
    assert validator.validate_visuals(tmp_path) == []
    # 验证警告已记录到日志
    log_content = (tmp_path / "007-visual-validation.log").read_text(encoding="utf-8")
    assert "untitled" in log_content.lower()

    # 严格模式下 placeholder 仍可被检测为错误
    assert validator.validate_visuals(tmp_path, strict=True)


def test_wordpress_publish_replaces_local_inline_images(tmp_path: Path):
    publisher = _load("publish_to_wp.py")
    (tmp_path / "inline.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 128)
    (tmp_path / "wp-config.json").write_text(
        json.dumps(
            {
                "site_url": "https://smsboosting.com",
                "username": "tester",
                "app_password": "app-password",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "007 发布包.json").write_text(
        json.dumps(
            {
                "title": "OTP SMS",
                "slug": "otp-sms",
                "body_html": '<p>Body</p><img src="inline.png" alt="OTP flow">',
                "cover_image": "",
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_upload(*_args, **_kwargs):
        return 42, "https://smsboosting.com/wp-content/uploads/inline.png"

    def fake_http(_method, _url, *, headers, body=None, timeout=60):
        captured["body"] = body
        return 201, {"id": 99, "link": "https://smsboosting.com/?p=99"}

    publisher.upload_media = fake_upload
    publisher.http_json = fake_http
    publisher.update_rankmath = lambda *_args, **_kwargs: True
    record = publisher.publish(tmp_path)
    assert "inline.png" in captured["body"]["content"]
    assert 'src="https://smsboosting.com/' in captured["body"]["content"]
    assert record["images_ready"] is True
    assert record["uploaded_image_count"] == 1


def test_rerun_request_accepts_updated_brand_site_url():
    from blog_writer.api.tasks import RerunFromRequest

    request = RerunFromRequest.model_validate(
        {
            "nodeFile": "S005-field.json",
            "brandSiteUrl": "https://smsboosting.com",
        }
    )
    assert request.brand_site_url == "https://smsboosting.com"
