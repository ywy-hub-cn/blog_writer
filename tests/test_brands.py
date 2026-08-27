"""品牌管理模块测试 — 覆盖 _generate_brand_id、BrandRepository、/brands API 全链路。"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from blog_writer.security.auth import _hash_password


# ┌─────────────────────────────────────────────────────
#  1. _generate_brand_id 单元测试
# ┌─────────────────────────────────────────────────────
class TestGenerateBrandId:
    """测试 brand_id 生成函数的三条路径。"""

    def test_ascii_name_slug(self):
        from blog_writer.api.brands import _generate_brand_id
        assert _generate_brand_id("SMS Boosting") == "sms-boosting"

    def test_ascii_with_special_chars(self):
        from blog_writer.api.brands import _generate_brand_id
        # 特殊字符被清除，空格转连字符
        result = _generate_brand_id("Hello! World?")
        assert result == "hello-world"

    def test_ascii_multiple_spaces(self):
        from blog_writer.api.brands import _generate_brand_id
        result = _generate_brand_id("My   Brand  Name")
        # 多空格 → 多连字符 → 去重
        assert "--" not in result
        assert result == "my-brand-name"

    def test_ascii_truncation(self):
        from blog_writer.api.brands import _generate_brand_id
        long_name = "a" * 60
        result = _generate_brand_id(long_name)
        assert len(result) <= 50

    def test_chinese_name_pypinyin_or_md5(self):
        """中文名应走 pypinyin 或 md5 回退，结果必须是纯 ASCII。"""
        from blog_writer.api.brands import _generate_brand_id
        result = _generate_brand_id("短信推广")
        assert result.isascii()
        assert len(result) > 0

    def test_same_name_same_id(self):
        from blog_writer.api.brands import _generate_brand_id
        assert _generate_brand_id("Test Brand") == _generate_brand_id("Test Brand")

    def test_different_names_different_ids(self):
        from blog_writer.api.brands import _generate_brand_id
        assert _generate_brand_id("Alpha") != _generate_brand_id("Beta")

    def test_empty_string_fallback(self):
        from blog_writer.api.brands import _generate_brand_id
        result = _generate_brand_id("")
        # 空字符串 isascii() 返回 True，slug 为空，pypinyin 也为空 → md5 回退
        assert len(result) > 0


# ┌─────────────────────────────────────────────────────
#  2. BrandRepository 单元测试
# ┌─────────────────────────────────────────────────────
class TestBrandRepository:
    """测试品牌数据访问层的 CRUD。"""

    def test_save_and_get(self, temp_dir):
        from blog_writer.db import DatabaseManager, BrandRepository
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=str(Path(temp_dir) / "test.db"))
        repo = BrandRepository(db=db)

        repo.save_brand("test-brand", "测试品牌", "./brands/test-brand")
        result = repo.get_brand("test-brand")
        assert result is not None
        assert result["brand_id"] == "test-brand"
        assert result["display_name"] == "测试品牌"
        assert result["inner_path"] == "./brands/test-brand"
        db.close_all()

    def test_list_brands_ordered(self, temp_dir):
        from blog_writer.db import DatabaseManager, BrandRepository
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=str(Path(temp_dir) / "test.db"))
        repo = BrandRepository(db=db)

        repo.save_brand("b-brand", "B品牌", "./brands/b-brand")
        repo.save_brand("a-brand", "A品牌", "./brands/a-brand")
        repo.save_brand("c-brand", "C品牌", "./brands/c-brand")

        brands = repo.list_brands()
        assert len(brands) == 3
        # 按 created_at ASC 排序
        assert brands[0]["brand_id"] == "b-brand"
        assert brands[2]["brand_id"] == "c-brand"
        db.close_all()

    def test_save_upsert(self, temp_dir):
        from blog_writer.db import DatabaseManager, BrandRepository
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=str(Path(temp_dir) / "test.db"))
        repo = BrandRepository(db=db)

        repo.save_brand("dup", "原名", "./brands/dup")
        repo.save_brand("dup", "新名", "./brands/dup")

        brands = repo.list_brands()
        assert len(brands) == 1
        assert brands[0]["display_name"] == "新名"
        db.close_all()

    def test_get_nonexistent(self, temp_dir):
        from blog_writer.db import DatabaseManager, BrandRepository
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=str(Path(temp_dir) / "test.db"))
        repo = BrandRepository(db=db)
        assert repo.get_brand("nonexistent") is None
        db.close_all()

    def test_delete(self, temp_dir):
        from blog_writer.db import DatabaseManager, BrandRepository
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=str(Path(temp_dir) / "test.db"))
        repo = BrandRepository(db=db)

        repo.save_brand("to-delete", "待删除", "./brands/to-delete")
        assert repo.delete_brand("to-delete") is True
        assert repo.get_brand("to-delete") is None
        db.close_all()

    def test_delete_nonexistent(self, temp_dir):
        from blog_writer.db import DatabaseManager, BrandRepository
        DatabaseManager._instance = None
        db = DatabaseManager(db_path=str(Path(temp_dir) / "test.db"))
        repo = BrandRepository(db=db)
        assert repo.delete_brand("nonexistent") is False
        db.close_all()


# ┌─────────────────────────────────────────────────────
#  3. /brands API 集成测试
# ┌─────────────────────────────────────────────────────

@pytest.fixture
def brands_client(temp_dir, monkeypatch):
    """带 brands 路由的 TestClient。"""
    config_path = Path(temp_dir) / "config.json"
    config = {
        "security": {
            "admin_password_hash": _hash_password("test-pass"),
            "token_expire_hours": 1,
            "api_token": "test-token",
        },
        "workflow": {
            "nodes_dir": "nodes",
            "instance_root": "instance",
            "use_database": True,
            "use_file_fallback": False,
        },
        "database": {
            "backend": "sqlite",
            "sqlite_path": str(Path(temp_dir) / "test.db"),
        },
        "llm": {
            "models": {
                "default": {
                    "api_key": "sk-test",
                    "base_url": "https://example.invalid/v1",
                    "model": "test-model",
                }
            }
        },
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    monkeypatch.setenv("BLOG_WRITER_CONFIG", str(config_path))
    monkeypatch.setenv("BLOG_WRITER_MODE", "development")
    monkeypatch.setenv("BLOG_WRITER_API_TOKEN", "test-token")
    monkeypatch.setenv("BLOG_WRITER_STATE_BACKEND", "memory")
    monkeypatch.delenv("REDIS_URL", raising=False)

    # 指向真实 nodes
    nodes = Path(__file__).resolve().parents[1] / "blog_writer" / "nodes"
    instance = Path(temp_dir) / "instance"
    instance.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg["workflow"]["nodes_dir"] = str(nodes)
    cfg["workflow"]["instance_root"] = str(instance)
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    from blog_writer.state_store import reset_state_store_for_tests
    from blog_writer.security.auth import _active_tokens, _invalidate_cache, _rate_limit
    reset_state_store_for_tests()
    _active_tokens.clear()
    _rate_limit.clear()
    _invalidate_cache()

    # 显式重置 DatabaseManager 单例，确保使用测试数据库
    from blog_writer.db import DatabaseManager
    if DatabaseManager._instance is not None:
        try:
            DatabaseManager._instance.close_all()
        except Exception:
            pass
        DatabaseManager._instance = None

    # 禁用限流，测试中同一 IP 大量请求会触发 429
    from blog_writer.security import rate_limiter as rl_mod
    from unittest.mock import MagicMock
    mock_rl = MagicMock()
    mock_rl.is_allowed.return_value = (True, "test")
    rl_mod._rate_limiter = mock_rl
    rl_mod.get_rate_limiter = lambda: mock_rl

    from blog_writer.config_manager import ConfigManager
    from blog_writer.service_manager import set_config, reset_service
    cfg_mgr = ConfigManager(str(config_path))
    set_config(cfg_mgr)
    reset_service()

    os.environ.pop("BLOG_WRITER_ADMIN_PASSWORD", None)
    os.environ.pop("BLOG_WRITER_OPERATOR_PASSWORD", None)

    # patch BRANDS_ROOT 到临时目录
    brands_root = Path(temp_dir) / "brands"
    brands_root.mkdir(parents=True, exist_ok=True)

    with patch("blog_writer.main.config", cfg_mgr):
        import blog_writer.api.brands as brands_mod
        with patch.object(brands_mod, "BRANDS_ROOT", brands_root):
            from blog_writer.main import app
            with TestClient(app) as c:
                yield c, brands_root


class TestBrandsApiUpload:
    """POST /brands/upload"""

    def test_upload_success(self, brands_client):
        client, brands_root = brands_client
        content = b"# Brand doc\nHello world"
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "Test Brand"},
            files=[("files", ("doc.md", io.BytesIO(content), "text/markdown"))],
        )
        assert resp.status_code == 200
        data = resp.json()
        # 兼容 envelope
        body = data.get("data", data)
        assert body["status"] == "success"
        assert body["brand_id"] == "test-brand"
        assert body["display_name"] == "Test Brand"
        assert body["inner_path"] == "./brands/test-brand"
        assert "doc.md" in body["files_saved"]
        # 验证文件落地
        assert (brands_root / "test-brand" / "doc.md").exists()

    def test_upload_empty_name(self, brands_client):
        client, _ = brands_client
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": ""},
            files=[("files", ("doc.md", io.BytesIO(b"content"), "text/markdown"))],
        )
        assert resp.status_code in (400, 422)

    def test_upload_no_files(self, brands_client):
        client, _ = brands_client
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "NoFiles"},
        )
        assert resp.status_code in (400, 422)

    def test_upload_empty_file(self, brands_client):
        client, brands_root = brands_client
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "EmptyFile"},
            files=[("files", ("empty.md", io.BytesIO(b""), "text/markdown"))],
        )
        assert resp.status_code in (400, 422)

    def test_upload_invalid_extension(self, brands_client):
        client, _ = brands_client
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "BadExt"},
            files=[("files", ("malware.exe", io.BytesIO(b"MZ"), "application/octet-stream"))],
        )
        assert resp.status_code in (400, 422)

    def test_upload_txt_allowed(self, brands_client):
        client, brands_root = brands_client
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "Txt Brand"},
            files=[("files", ("notes.txt", io.BytesIO(b"text content"), "text/plain"))],
        )
        assert resp.status_code == 200

    def test_upload_duplicate_overwrites(self, brands_client):
        client, brands_root = brands_client
        # 第一次上传
        client.post(
            "/api/brands/upload",
            data={"display_name": "Dup Brand"},
            files=[("files", ("v1.md", io.BytesIO(b"v1"), "text/markdown"))],
        )
        # 第二次同名上传 → 覆盖
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "Dup Brand"},
            files=[("files", ("v2.md", io.BytesIO(b"v2"), "text/markdown"))],
        )
        assert resp.status_code == 200
        # v2.md 存在，v1.md 不存在
        brand_dir = brands_root / "dup-brand"
        assert (brand_dir / "v2.md").exists()
        assert not (brand_dir / "v1.md").exists()

    def test_upload_chinese_name(self, brands_client):
        client, brands_root = brands_client
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "短信推广"},
            files=[("files", ("doc.md", io.BytesIO(b"content"), "text/markdown"))],
        )
        assert resp.status_code == 200
        body = resp.json()
        result = body.get("data", body)
        brand_id = result["brand_id"]
        # brand_id 必须纯 ASCII
        assert brand_id.isascii()
        assert (brands_root / brand_id / "doc.md").exists()

    def test_upload_multiple_files(self, brands_client):
        client, brands_root = brands_client
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "Multi Brand"},
            files=[
                ("files", ("a.md", io.BytesIO(b"a"), "text/markdown")),
                ("files", ("b.md", io.BytesIO(b"b"), "text/markdown")),
                ("files", ("c.txt", io.BytesIO(b"c"), "text/plain")),
            ],
        )
        assert resp.status_code == 200
        body = resp.json()
        result = body.get("data", body)
        assert len(result["files_saved"]) == 3


class TestBrandsApiList:
    """GET /brands"""

    def test_list_empty(self, brands_client):
        """全新 temp 数据库应可正常返回空列表。"""
        client, _ = brands_client
        resp = client.get("/api/brands")
        assert resp.status_code == 200
        body = resp.json()
        result = body.get("data", body)
        assert "brands" in result
        assert "total" in result

    def test_list_after_upload(self, brands_client):
        """上传后列表应包含该品牌。"""
        client, _ = brands_client
        client.post(
            "/api/brands/upload",
            data={"display_name": "Listed Brand"},
            files=[("files", ("doc.md", io.BytesIO(b"content"), "text/markdown"))],
        )
        resp = client.get("/api/brands")
        assert resp.status_code == 200
        body = resp.json()
        result = body.get("data", body)
        names = [b["display_name"] for b in result["brands"]]
        assert "Listed Brand" in names

    def test_list_verbose(self, brands_client):
        """verbose 模式应返回 file_count 字段。"""
        client, _ = brands_client
        client.post(
            "/api/brands/upload",
            data={"display_name": "Verbose Brand"},
            files=[("files", ("doc.md", io.BytesIO(b"content"), "text/markdown"))],
        )
        resp = client.get("/api/brands?verbose=true")
        assert resp.status_code == 200
        body = resp.json()
        result = body.get("data", body)
        # 找到我们上传的品牌
        verbose_brand = next(
            (b for b in result["brands"] if b["display_name"] == "Verbose Brand"),
            None,
        )
        assert verbose_brand is not None
        assert verbose_brand.get("file_count") == 1


class TestBrandsApiUpdate:
    """PUT /brands/{brand_id}"""

    def test_update_name(self, brands_client):
        client, _ = brands_client
        # 先上传
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "Old Name"},
            files=[("files", ("doc.md", io.BytesIO(b"c"), "text/markdown"))],
        )
        body = resp.json()
        result = body.get("data", body)
        brand_id = result["brand_id"]

        # 更新名称
        resp = client.put(
            f"/api/brands/{brand_id}",
            data={"display_name": "New Name"},
        )
        assert resp.status_code == 200
        body = resp.json()
        result = body.get("data", body)
        assert result["display_name"] == "New Name"
        # inner_path 不变
        assert result["inner_path"] == f"./brands/{brand_id}"

    def test_update_nonexistent(self, brands_client):
        client, _ = brands_client
        resp = client.put(
            "/api/brands/nonexistent",
            data={"display_name": "Whatever"},
        )
        assert resp.status_code == 404

    def test_update_empty_name(self, brands_client):
        client, _ = brands_client
        client.post(
            "/api/brands/upload",
            data={"display_name": "ToRename"},
            files=[("files", ("doc.md", io.BytesIO(b"c"), "text/markdown"))],
        )
        resp = client.put(
            "/api/brands/to-rename",
            data={"display_name": ""},
        )
        assert resp.status_code in (400, 422)


class TestBrandsApiDelete:
    """DELETE /brands/{brand_id}"""

    def test_delete_success(self, brands_client):
        client, brands_root = brands_client
        client.post(
            "/api/brands/upload",
            data={"display_name": "Delete Me"},
            files=[("files", ("doc.md", io.BytesIO(b"c"), "text/markdown"))],
        )
        assert (brands_root / "delete-me").exists()
        resp = client.delete("/api/brands/delete-me")
        assert resp.status_code == 200
        # 目录已删除
        assert not (brands_root / "delete-me").exists()

    def test_delete_nonexistent(self, brands_client):
        client, _ = brands_client
        resp = client.delete("/api/brands/nonexistent")
        assert resp.status_code == 404


class TestBrandsApiFiles:
    """GET /brands/{brand_id}/files"""

    def test_list_files(self, brands_client):
        client, _ = brands_client
        client.post(
            "/api/brands/upload",
            data={"display_name": "Files Brand"},
            files=[
                ("files", ("a.md", io.BytesIO(b"a"), "text/markdown")),
                ("files", ("b.txt", io.BytesIO(b"b"), "text/plain")),
            ],
        )
        resp = client.get("/api/brands/files-brand/files")
        assert resp.status_code == 200
        body = resp.json()
        result = body.get("data", body)
        assert result["total"] == 2
        names = [f["name"] for f in result["files"]]
        assert "a.md" in names
        assert "b.txt" in names

    def test_list_files_nonexistent(self, brands_client):
        client, _ = brands_client
        resp = client.get("/api/brands/nonexistent/files")
        assert resp.status_code == 404


# ┌─────────────────────────────────────────────────────
#  4. 安全边界测试
# ┌─────────────────────────────────────────────────────
class TestBrandSecurity:
    """安全相关边界测试。"""

    def test_brand_id_injection_attempt(self, brands_client):
        """brand_id 正则校验阻止路径遍历。"""
        client, _ = brands_client
        # 尝试通过 brand_id 注入路径
        malicious_ids = [
            "../etc",
            "..\\windows",
            "test/../../etc",
            "test;rm-rf",
            "test brand",  # 空格
        ]
        for mid in malicious_ids:
            resp = client.get(f"/api/brands/{mid}/files")
            assert resp.status_code in (400, 404), f"brand_id={mid} should be rejected"

    def test_brand_id_update_injection(self, brands_client):
        client, _ = brands_client
        resp = client.put(
            "/api/brands/../etc",
            data={"display_name": "hacked"},
        )
        assert resp.status_code in (400, 404, 422)

    def test_brand_id_delete_injection(self, brands_client):
        client, _ = brands_client
        resp = client.delete("/api/brands/../etc")
        assert resp.status_code in (400, 404, 422)

    def test_long_display_name(self, brands_client):
        client, _ = brands_client
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "A" * 200},
            files=[("files", ("doc.md", io.BytesIO(b"c"), "text/markdown"))],
        )
        assert resp.status_code in (400, 422)

    def test_file_size_limit(self, brands_client):
        """单文件超过 10MB 应拒绝。"""
        client, _ = brands_client
        large_content = b"x" * (10 * 1024 * 1024 + 1)
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "BigFile"},
            files=[("files", ("big.md", io.BytesIO(large_content), "text/markdown"))],
        )
        assert resp.status_code in (400, 422)

    def test_filename_path_traversal(self, brands_client):
        """文件名含路径分隔符应被 safe_basename 处理。"""
        client, brands_root = brands_client
        resp = client.post(
            "/api/brands/upload",
            data={"display_name": "Traversal"},
            files=[("files", ("../../../etc/passwd.md", io.BytesIO(b"hack"), "text/markdown"))],
        )
        # safe_basename 会取 basename 或回退到 brand_doc_N.md
        assert resp.status_code == 200
        brand_dir = brands_root / "traversal"
        # 不应出现目录穿越
        assert not (Path("etc") / "passwd.md").exists()
        # 文件应落地在 brand_dir 内
        saved = list(brand_dir.glob("*.md"))
        assert len(saved) > 0
