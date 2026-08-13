"""品牌管理 API - 品牌文档上传与下拉列表"""
import hashlib
import os
import re
import shutil
import stat
import traceback
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from blog_writer.db import BrandRepository
from blog_writer.security.path_security import safe_basename

router = APIRouter(prefix="/brands", tags=["brands"])

# 品牌文件保存根目录（项目根下的 brands/）
BRANDS_ROOT = Path(__file__).parent.parent.parent / "brands"

# 单文件大小限制：10MB
MAX_FILE_SIZE = 10 * 1024 * 1024

# 允许的文件后缀
ALLOWED_EXTENSIONS = {".md", ".txt"}


def _generate_brand_id(display_name: str) -> str:
    """从显示名生成安全的英文 brand_id。

    优先级：
    1. 若显示名本身是 ASCII（如 "SMS Boosting"），直接 slug 化，可复用已有目录
    2. 若环境安装了 pypinyin，中文转拼音生成可读 slug
    3. 回退到 md5 前 8 位，保证纯 ASCII、稳定可复现

    同一个名称每次生成同一个 ID，满足"重复 brand_id 直接覆盖"的需求。
    """
    # 1. ASCII 名称直接 slug 化
    if display_name.isascii():
        slug = re.sub(r"[^a-z0-9-]", "", display_name.lower().replace(" ", "-")).strip("-")
        slug = re.sub(r"-{2,}", "-", slug)
        if slug:
            return slug[:50]

    # 2. 尝试 pypinyin 生成可读拼音 slug
    try:
        from pypinyin import Style, lazy_pinyin

        pinyin_parts = lazy_pinyin(display_name, style=Style.NORMAL)
        slug = "-".join(pinyin_parts)
        slug = re.sub(r"[^a-z0-9-]", "", slug.lower()).strip("-")
        slug = re.sub(r"-{2,}", "-", slug)
        if slug:
            return slug[:50]
    except ImportError:
        pass

    # 3. 回退：md5 前 8 位
    return hashlib.md5(display_name.encode("utf-8")).hexdigest()[:8]


def _rmtree_safe(path: Path):
    """安全删除目录，处理 Windows 下只读文件无法删除的问题。"""
    def _on_error(func, err_path, exc_info):
        # 尝试将文件改为可写后重试删除
        try:
            os.chmod(err_path, stat.S_IWRITE)
            func(err_path)
        except Exception:
            pass

    if path.exists():
        shutil.rmtree(path, onerror=_on_error)


@router.get("")
async def list_brands(verbose: bool = False):
    """获取品牌列表（公开读取）。

    Args:
        verbose: 是否返回详细信息（文件数、创建时间等），品牌管理页面用

    返回数组：
    - 简洁模式（下拉框用）：[{display_name, inner_path}]
    - 详细模式（管理页用）：[{brand_id, display_name, inner_path, file_count, total_size, created_at, updated_at}]
    """
    repo = BrandRepository()
    brands = repo.list_brands()

    if not verbose:
        # 简洁模式：只返回下拉框需要的字段
        result = [
            {"display_name": b["display_name"], "inner_path": b["inner_path"]}
            for b in brands
        ]
        return {"brands": result, "total": len(result)}

    # 详细模式：补充文件统计信息
    result = []
    for b in brands:
        brand_id = b.get("brand_id", "")
        brand_dir = BRANDS_ROOT / brand_id
        file_count = 0
        total_size = 0
        if brand_dir.exists():
            for f in brand_dir.iterdir():
                if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS:
                    file_count += 1
                    total_size += f.stat().st_size
        result.append({
            "brand_id": brand_id,
            "display_name": b["display_name"],
            "inner_path": b["inner_path"],
            "file_count": file_count,
            "total_size": total_size,
            "created_at": b.get("created_at", ""),
            "updated_at": b.get("updated_at", ""),
        })
    return {"brands": result, "total": len(result)}


@router.get("/{brand_id}/files")
async def list_brand_files(brand_id: str):
    """获取品牌下的文件列表。

    Args:
        brand_id: 品牌ID

    Returns:
        {files: [{name, size, modified_at}], total: N}
    """
    # 安全校验：brand_id 只能包含字母数字连字符
    if not re.match(r"^[a-z0-9-]+$", brand_id):
        raise HTTPException(status_code=400, detail="无效的品牌ID")

    brand_dir = BRANDS_ROOT / brand_id
    if not brand_dir.exists():
        raise HTTPException(status_code=404, detail=f"品牌 {brand_id} 不存在")

    files = []
    for f in sorted(brand_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS:
            stat = f.stat()
            files.append({
                "name": f.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })

    return {"files": files, "total": len(files)}


@router.put("/{brand_id}")
async def update_brand(
    brand_id: str,
    display_name: str = Form(..., description="新的品牌显示名称"),
):
    """更新品牌显示名称（重命名）。

    Args:
        brand_id: 品牌ID
        display_name: 新的显示名称

    Note:
        只修改数据库中的 display_name，不改变 brand_id 和目录名。
        如果需要修改 brand_id，需要删除后重新上传。
    """
    # 安全校验
    if not re.match(r"^[a-z0-9-]+$", brand_id):
        raise HTTPException(status_code=400, detail="无效的品牌ID")

    display_name = (display_name or "").strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="品牌显示名称不能为空")
    if len(display_name) > 100:
        raise HTTPException(status_code=400, detail="品牌显示名称长度不能超过 100")

    repo = BrandRepository()
    existing = repo.get_brand(brand_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"品牌 {brand_id} 不存在")

    # 更新数据库（inner_path 不变，因为目录名不变）
    inner_path = existing.get("inner_path", f"./brands/{brand_id}")
    repo.save_brand(brand_id, display_name, inner_path)

    return {
        "status": "success",
        "brand_id": brand_id,
        "display_name": display_name,
        "inner_path": inner_path,
        "updated_at": datetime.now().isoformat(),
    }


@router.delete("/{brand_id}")
async def delete_brand(brand_id: str):
    """删除品牌（同时删除数据库记录和本地文件目录）。

    Args:
        brand_id: 品牌ID

    Warning:
        此操作不可恢复，删除后品牌目录和所有文件将被永久删除。
        已使用该品牌创建的任务不受影响（任务表中保存的是路径快照）。
    """
    # 安全校验
    if not re.match(r"^[a-z0-9-]+$", brand_id):
        raise HTTPException(status_code=400, detail="无效的品牌ID")

    repo = BrandRepository()
    existing = repo.get_brand(brand_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"品牌 {brand_id} 不存在")

    brand_dir = BRANDS_ROOT / brand_id
    deleted_files = 0

    try:
        # 删除本地文件目录
        if brand_dir.exists():
            deleted_files = sum(
                1 for f in brand_dir.iterdir()
                if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS
            )
            _rmtree_safe(brand_dir)

        # 删除数据库记录
        repo.delete_brand(brand_id)

    except Exception as e:
        print(f"[品牌删除异常] brand_id={brand_id}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"品牌删除失败: {type(e).__name__}: {e}",
        )

    return {
        "status": "success",
        "brand_id": brand_id,
        "display_name": existing.get("display_name", ""),
        "deleted_files": deleted_files,
        "deleted_at": datetime.now().isoformat(),
    }


@router.post("/upload")
async def upload_brand(
    display_name: str = Form(..., description="品牌中文显示名称"),
    files: List[UploadFile] = File(..., description="品牌文档文件（.md / .txt）"),
):
    """上传品牌文档（无需登录，运营可直接使用）。

    1. 将中文名称做安全处理生成英文 brand_id
    2. 文件保存到 ./brands/{brand_id}/
    3. 数据库表存储 display_name 和 inner_path
    4. 重复 brand_id 直接覆盖目录，不做版本、不做备份
    """
    # 校验显示名
    display_name = (display_name or "").strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="品牌显示名称不能为空")
    if len(display_name) > 100:
        raise HTTPException(status_code=400, detail="品牌显示名称长度不能超过 100")

    # 校验文件列表
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个品牌文档文件")

    # 生成 brand_id 和内部路径
    brand_id = _generate_brand_id(display_name)
    inner_path = f"./brands/{brand_id}"
    brand_dir = BRANDS_ROOT / brand_id

    saved_files = []

    try:
        # 确保 brands 根目录存在
        BRANDS_ROOT.mkdir(parents=True, exist_ok=True)

        # 重复 brand_id 直接覆盖目录（不备份），用安全删除处理 Windows 只读文件
        _rmtree_safe(brand_dir)
        brand_dir.mkdir(parents=True, exist_ok=True)

        for upload_file in files:
            filename = upload_file.filename or ""
            # 后缀校验
            ext = Path(filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"文件 {filename} 类型不允许，仅支持 .md / .txt",
                )

            # 读取内容并校验大小
            content = await upload_file.read()
            if len(content) > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"文件 {filename} 超过大小限制（单文件最大 10MB）",
                )
            if len(content) == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"文件 {filename} 内容为空",
                )

            # 安全文件名处理
            safe_name = safe_basename(filename, default=f"brand_doc{ext}")
            if not safe_name or not safe_name.lower().endswith(ext):
                safe_name = f"brand_doc_{len(saved_files)}{ext}"

            # 重名处理：文件夹上传时不同子目录可能有同名文件，自动加序号
            final_name = safe_name
            counter = 1
            while (brand_dir / final_name).exists():
                stem = Path(safe_name).stem
                final_name = f"{stem}_{counter}{ext}"
                counter += 1

            # 写入文件
            file_path = brand_dir / final_name
            with open(file_path, "wb") as f:
                f.write(content)
            saved_files.append(final_name)

        # 存入数据库（upsert）
        repo = BrandRepository()
        repo.save_brand(brand_id, display_name, inner_path)

    except HTTPException:
        # 业务校验失败：清理半成品目录后重新抛出
        if brand_dir.exists() and not saved_files:
            _rmtree_safe(brand_dir)
        raise
    except Exception as e:
        # 未预期异常：打印完整堆栈便于排查，清理半成品，返回具体错误
        print(f"[品牌上传异常] display_name={display_name}, brand_id={brand_id}")
        traceback.print_exc()
        if brand_dir.exists() and not saved_files:
            _rmtree_safe(brand_dir)
        raise HTTPException(
            status_code=500,
            detail=f"品牌上传失败: {type(e).__name__}: {e}",
        )

    return {
        "status": "success",
        "brand_id": brand_id,
        "display_name": display_name,
        "inner_path": inner_path,
        "files_saved": saved_files,
        "created_at": datetime.now().isoformat(),
    }
