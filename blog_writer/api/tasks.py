"""任务API - 任务启动、状态查询、审核（需鉴权）"""
import asyncio
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, List, Union

from fastapi import APIRouter, HTTPException, Request, Depends, Header
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator, model_validator, ConfigDict, Field

from blog_writer.service_manager import get_service
from blog_writer.api.webhooks import get_webhook_manager
from blog_writer.api.deps import get_current_user, security, verify_admin_access, is_task_auth_required
from blog_writer.api.task_access import (
    assert_task_access,
    filter_tasks_for_user,
    get_user_id,
    is_privileged,
)
from blog_writer.forbidden import normalize_forbidden_whitelist

router = APIRouter(prefix="/tasks", tags=["tasks"])

# 项目根目录（用于把相对品牌路径解析为绝对路径）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_brand_path(brand_path: str) -> str:
    """将相对品牌路径解析为绝对路径。

    工作流在实例目录（blog_writer/instance/<task_id>/）下执行，
    相对路径 ./brands/xxx 会被解析到实例目录下而找不到文件。
    这里统一解析为项目根下的绝对路径再传给工作流。
    数据库仍保存原始相对路径，保持历史兼容。
    """
    if not brand_path:
        return brand_path
    p = Path(brand_path)
    if p.is_absolute():
        return str(p)
    return str((_PROJECT_ROOT / p).resolve())

# 后台任务引用集合：防止 asyncio.Task 被 GC 回收
_bg_tasks: set = set()


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> dict:
    """任务接口鉴权。

    默认允许匿名使用（启动/查询/控制任务）；仅当 BLOG_WRITER_TASK_AUTH=required 时强制 Token。
    管理员能力（节点/配置）仍走 get_current_user，与任务接口分离。
    """
    try:
        return await get_current_user(request, credentials, x_api_key)
    except HTTPException:
        if is_task_auth_required():
            raise
        return {
            "is_admin": False,
            "user_id": "anonymous",
            "role": "anonymous",
            "auth_type": "anonymous",
            "token_created_at": None,
        }


def _enrich_task_dict(task: dict, full: bool = True) -> dict:
    if not task:
        return task
    from blog_writer.api.task_enrichment import enrich_task

    service = get_service()
    return enrich_task(task, service.instance_root, full=full)


def _track_task(coro, name: str = ""):
    """创建并追踪后台 asyncio.Task，防止被 GC 回收。"""
    t = asyncio.create_task(coro, name=name) if name else asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


def _validate_brand_path_value(v: str) -> str:
    if not v or len(v) > 255:
        raise ValueError("品牌路径不能为空且长度不能超过255")
    # 容错：统一路径分隔符，去除多余斜杠
    v = v.replace("\\", "/")
    while "//" in v:
        v = v.replace("//", "/")
    v = v.rstrip("/")
    if v.startswith("/") or v.startswith(".."):
        raise ValueError("路径不安全")
    # 检查路径遍历：任何段为 ".." 则拒绝
    if any(seg == ".." for seg in v.split("/")):
        raise ValueError("路径不安全，不允许目录遍历")
    if v.startswith("~") or "~/" in v:
        raise ValueError("路径不安全")
    # 禁止绝对路径盘符
    if len(v) >= 2 and v[1] == ":":
        raise ValueError("路径不安全")
    # 只允许安全字符
    if not re.match(r'^[a-zA-Z0-9_\-./]+$', v):
        raise ValueError("路径包含非法字符")
    return v


def _lookup_brand_path(value: str) -> Optional[str]:
    """按 display_name 或 brand_id 从品牌库解析 inner_path（忽略大小写）。"""
    from blog_writer.db import BrandRepository

    needle = value.strip()
    if not needle:
        return None
    needle_lower = needle.lower()
    repo = BrandRepository()
    # 先精确匹配
    for b in repo.list_brands():
        if b.get("display_name") == needle or b.get("brand_id") == needle:
            return b.get("inner_path") or f"./brands/{b['brand_id']}"
    # 再忽略大小写匹配
    for b in repo.list_brands():
        if (b.get("display_name") or "").lower() == needle_lower or \
           (b.get("brand_id") or "").lower() == needle_lower:
            return b.get("inner_path") or f"./brands/{b['brand_id']}"
    return None


def _normalize_brand_path_input(value: str) -> str:
    """兼容 Java/运营侧多种品牌字段写法，统一为可校验的相对路径。"""
    raw = str(value).strip()
    if not raw:
        raise ValueError("品牌路径不能为空，请选择或上传品牌后再启动任务")

    # 中文显示名、含空格等：按品牌库解析
    if re.search(r"[^\w\-./\\]", raw) or " " in raw:
        resolved = _lookup_brand_path(raw)
        if not resolved:
            # 给出可用品牌列表，便于排查
            from blog_writer.db import BrandRepository
            repo = BrandRepository()
            available = [b.get("display_name") for b in repo.list_brands() if b.get("display_name")]
            hint = f"可用品牌：{', '.join(available)}" if available else "当前暂无品牌，请先上传"
            raise ValueError(
                f"未找到品牌「{raw}」，{hint}；也可传 brandPath=brands/<brand_id>"
            )
        raw = resolved

    # 仅 brand_id（无路径分隔符）→ brands/<id>
    if "/" not in raw and "\\" not in raw:
        raw = f"brands/{raw}"

    # 先标准化路径分隔符，便于判断前缀
    raw = raw.replace("\\", "/")
    while "//" in raw:
        raw = raw.replace("//", "/")
    raw = raw.rstrip("/")

    # 容错：自动添加 ./ 前缀（相对路径）
    if not raw.startswith("./") and not raw.startswith("../"):
        raw = "./" + raw

    return _validate_brand_path_value(raw)


class StartTaskRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    brand_path: str = Field(alias="brandPath")
    keywords: str
    user_note: str = Field(default="", alias="userNote")
    mode: str = "auto"
    brand_site_url: str = Field(default="", alias="brandSiteUrl")
    # 单次任务禁用词白名单：本任务写作/Gate 检测豁免，不改品牌词库
    forbidden_whitelist: Union[List[str], str, None] = Field(
        default=None, alias="forbiddenWhitelist"
    )
    step_files: Optional[list] = Field(default=None, alias="stepFiles")
    resume_from: Optional[str] = Field(default=None, alias="resumeFrom")
    task_id: Optional[str] = Field(default=None, alias="taskId")
    model: str = Field(default="default", alias="model")
    temperature: Optional[float] = Field(default=None, alias="temperature", ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, alias="maxTokens", ge=1, le=256000)
    priority: int = Field(default=2, alias="priority", ge=1, le=3)
    callback_url: Optional[str] = Field(default=None, alias="callbackUrl")
    callback_secret: Optional[str] = Field(default=None, alias="callbackSecret")
    callback_events: Optional[List[str]] = Field(default=None, alias="callbackEvents")

    @model_validator(mode="before")
    @classmethod
    def merge_integration_aliases(cls, data: Any) -> Any:
        """兼容 Java 对接常见字段名：brandId / keyword / displayName 等。"""
        if not isinstance(data, dict):
            return data
        merged = dict(data)

        if merged.get("keywords") is None and merged.get("keyword") is not None:
            merged["keywords"] = merged["keyword"]

        if not merged.get("brandPath") and not merged.get("brand_path"):
            for key in (
                "brandId", "brand_id",
                "displayName", "display_name", "brandName", "brand_name",
            ):
                if merged.get(key):
                    merged["brandPath"] = merged[key]
                    break

        return merged

    @field_validator("brand_path", mode="before")
    @classmethod
    def normalize_brand_path(cls, v: Any) -> str:
        if v is None:
            return v
        return _normalize_brand_path_input(str(v))

    @field_validator("keywords", mode="before")
    @classmethod
    def normalize_keywords(cls, v: Any) -> str:
        if v is None:
            return v
        if isinstance(v, list):
            v = ", ".join(str(x).strip() for x in v if str(x).strip())
        raw = str(v)
        # 容错：统一多种分隔符为逗号+空格
        raw = re.sub(r'[;；\n\r\t]+', ', ', raw)
        # 容错：多个空格合并为一个
        raw = re.sub(r' {2,}', ' ', raw)
        # 容错：去除重复的逗号分隔关键词
        parts = [p.strip() for p in raw.split(',') if p.strip()]
        seen = set()
        unique = []
        for p in parts:
            if p.lower() not in seen:
                seen.add(p.lower())
                unique.append(p)
        return ", ".join(unique) if unique else raw.strip()

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, v: str) -> str:
        if not v:
            raise ValueError("关键词不能为空，请输入至少一个关键词")
        # 清洗危险字符
        v = re.sub(r'[<>\'"\x00-\x1f]', '', v)
        v = v.strip()
        if not v:
            raise ValueError("关键词不能为空，请输入至少一个关键词")
        # 容错：长度超限时自动截断（而不是直接报错）
        if len(v) > 500:
            v = v[:500].rsplit(',', 1)[0].strip() if ',' in v[:500] else v[:500]
        return v

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ["auto", "supervised", "manual"]:
            raise ValueError("模式必须是 auto, supervised 或 manual")
        return v

    @field_validator("task_id")
    @classmethod
    def validate_task_id_field(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        from blog_writer.security.path_security import validate_task_id
        if not validate_task_id(v):
            raise ValueError("task_id 非法：仅允许字母数字及 ._- ，禁止路径分隔符")
        return v

    @field_validator("user_note")
    @classmethod
    def validate_user_note(cls, v: str) -> str:
        # 附加要求不设硬性字数上限；仅清洗控制字符，避免截断运营长指令
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", v or "")

    @field_validator("brand_site_url")
    @classmethod
    def validate_brand_site_url(cls, v: str) -> str:
        raw = (v or "").strip()
        if not raw:
            return ""
        if not re.match(r"^https?://.+", raw, re.I):
            raise ValueError("品牌官网地址需以 http:// 或 https:// 开头")
        return raw.rstrip("/")

    @field_validator("forbidden_whitelist", mode="before")
    @classmethod
    def validate_forbidden_whitelist(cls, v):
        return normalize_forbidden_whitelist(v)
    
    @field_validator("callback_url")
    @classmethod
    def validate_callback_url(cls, v: str) -> str:
        if v is None:
            return v
        from blog_writer.security.url_safety import validate_webhook_url_or_raise
        return validate_webhook_url_or_raise(v)


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    decision: str = "approve"
    modifications: Optional[dict] = None

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        if v not in ["approve", "reject", "modify", "retry"]:
            raise ValueError("决策必须是 approve, reject, modify 或 retry")
        return v


class ResumeFromRequest(BaseModel):
    """断点续跑请求 - 从指定节点继续"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    node_file: str = Field(alias="nodeFile")
    brand_path: str = Field(default="", alias="brandPath")
    keywords: str = ""
    mode: str = "auto"

    @field_validator("node_file")
    @classmethod
    def validate_node_file(cls, v: str) -> str:
        if not v or not v.endswith('.json'):
            raise ValueError("节点文件名必须以.json结尾")
        if '/' in v or '\\' in v or '..' in v:
            raise ValueError("节点文件名不安全")
        return v

    @field_validator("brand_path")
    @classmethod
    def validate_brand_path_optional(cls, v: str) -> str:
        if not v:
            return v
        return _validate_brand_path_value(v)


class RerunFromRequest(BaseModel):
    """指定节点重跑请求 - 从指定节点重新运行（忽略之前结果）"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    node_file: str = Field(alias="nodeFile")
    brand_path: str = Field(default="", alias="brandPath")
    keywords: str = ""
    mode: str = "auto"
    user_note: str = Field(default="", alias="userNote")
    brand_site_url: str = Field(default="", alias="brandSiteUrl")

    @field_validator("node_file")
    @classmethod
    def validate_node_file(cls, v: str) -> str:
        if not v or not v.endswith('.json'):
            raise ValueError("节点文件名必须以.json结尾")
        if '/' in v or '\\' in v or '..' in v:
            raise ValueError("节点文件名不安全")
        return v

    @field_validator("brand_path")
    @classmethod
    def validate_brand_path_optional(cls, v: str) -> str:
        if not v:
            return v
        return _validate_brand_path_value(v)

    @field_validator("brand_site_url")
    @classmethod
    def validate_brand_site_url(cls, v: str) -> str:
        raw = (v or "").strip()
        if not raw:
            return ""
        if not re.match(r"^https?://.+", raw, re.I):
            raise ValueError("品牌官网地址需以 http:// 或 https:// 开头")
        return raw.rstrip("/")

    @field_validator("user_note")
    @classmethod
    def validate_user_note(cls, v: str) -> str:
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", v or "")


class BatchTaskItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    keywords: str
    user_note: str = Field(default="", alias="userNote")
    brand_site_url: str = Field(default="", alias="brandSiteUrl")


class BatchStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    brand_path: str = Field(alias="brandPath")
    mode: str = "auto"
    priority: int = Field(default=2, alias="priority", ge=1, le=3)
    user_note: str = Field(default="", alias="userNote")
    brand_site_url: str = Field(default="", alias="brandSiteUrl")
    forbidden_whitelist: Union[List[str], str, None] = Field(
        default=None, alias="forbiddenWhitelist"
    )
    tasks: List[BatchTaskItem]
    callback_url: Optional[str] = Field(default=None, alias="callbackUrl")
    callback_secret: Optional[str] = Field(default=None, alias="callbackSecret")
    callback_events: Optional[List[str]] = Field(default=None, alias="callbackEvents")
    batch_id: Optional[str] = Field(default=None, alias="batchId")

    @field_validator("brand_path", mode="before")
    @classmethod
    def normalize_brand_path(cls, v: Any) -> str:
        if v is None:
            return v
        return _normalize_brand_path_input(str(v))

    @field_validator("brand_path")
    @classmethod
    def validate_brand_path(cls, v: str) -> str:
        return _validate_brand_path_value(v)

    @field_validator("forbidden_whitelist", mode="before")
    @classmethod
    def validate_forbidden_whitelist(cls, v):
        return normalize_forbidden_whitelist(v)


class RetryNodeRequest(BaseModel):
    """重试指定节点请求"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    node_file: str = Field(alias="nodeFile")

    @field_validator("node_file")
    @classmethod
    def validate_node_file(cls, v: str) -> str:
        if not v or not v.endswith('.json'):
            raise ValueError("节点文件名必须以.json结尾")
        if '/' in v or '\\' in v or '..' in v:
            raise ValueError("节点文件名不安全")
        return v


async def _safe_start_task(task, task_id: str = None, timeout: float = None):
    """安全执行后台任务；失败时将关联任务标记为 failed。

    默认不加整任务超时：人工审核等待与多步 LLM 可能远超 1h。
    单步超时由 workflow.step_timeout_minutes 约束。
    可通过环境变量 BLOG_WRITER_TASK_TIMEOUT_SECONDS 设置整任务上限（秒）。
    """
    import logging
    import os
    log = logging.getLogger(__name__)
    if timeout is None:
        raw = os.environ.get("BLOG_WRITER_TASK_TIMEOUT_SECONDS", "").strip()
        if raw:
            try:
                timeout = float(raw)
            except ValueError:
                timeout = None
        else:
            timeout = None
    try:
        if timeout is not None and timeout > 0:
            await asyncio.wait_for(task, timeout=timeout)
        else:
            await task
    except asyncio.TimeoutError:
        log.error("后台任务执行超时 (%ss) task_id=%s", timeout, task_id)
        if task_id:
            _mark_task_failed(task_id, f"timeout after {timeout}s")
    except asyncio.CancelledError:
        log.warning("后台任务被取消 task_id=%s", task_id)
        raise
    except Exception as e:
        log.error("后台任务执行失败 task_id=%s: %s", task_id, e, exc_info=True)
        if task_id:
            _mark_task_failed(task_id, str(e))


def _mark_task_failed(task_id: str, error_msg: str) -> None:
    try:
        service = get_service()
        task = service._ensure_task_loaded(task_id)
        if not task:
            return
        # waiting_review 被整任务超时误杀时也要落盘；终态不覆盖
        if task.get("status") in ("completed", "failed", "cancelled", "rejected", "completed_partial"):
            return
        task["status"] = "failed"
        task["end_time"] = datetime.now().isoformat()
        extra = dict(task.get("extra") or {})
        extra["last_error"] = str(error_msg)[:500]
        task["extra"] = extra
        service._save_state(task_id)
        service._fire_task_webhook(
            task_id,
            "task.failed",
            {"task_id": task_id, "status": "failed", "error": str(error_msg)[:200]},
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"_mark_task_failed failed for {task_id}: {e}")


@router.post("/start")
async def start_task(
    request: Request,
    req: StartTaskRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    _user: dict = Depends(get_optional_user),
):
    service = get_service()
    webhook_mgr = get_webhook_manager()

    from blog_writer.api.case_convert import normalize_idempotency_key
    from blog_writer.security.path_security import validate_task_id

    existing_idempotent = None
    if req.task_id:
        task_id = req.task_id
    elif idempotency_key:
        candidate = normalize_idempotency_key(idempotency_key)
        if candidate and validate_task_id(candidate):
            existing_idempotent = service.get_task_status(candidate)
            task_id = candidate
        else:
            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    else:
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    if existing_idempotent:
        return _enrich_task_dict(
            {
                "task_id": task_id,
                "status": existing_idempotent.get("status", "unknown"),
                "message": "任务已存在（幂等键命中）",
                "idempotent_hit": True,
            },
            full=True,
        )

    owner_id = get_user_id(_user)

    step_files = req.step_files
    if step_files is not None and not is_privileged(_user):
        raise HTTPException(status_code=403, detail="仅管理员可指定 step_files")
    if step_files is not None:
        try:
            step_files = service.normalize_step_files(step_files)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    kwargs = {
        "brand_path": _resolve_brand_path(req.brand_path),
        "keywords": req.keywords,
        "user_note": req.user_note,
        "mode": req.mode,
        "brand_site_url": req.brand_site_url,
        "forbidden_whitelist": req.forbidden_whitelist or [],
        "step_files": step_files,
        "task_id": task_id,
        "resume_from": req.resume_from,
        "model": req.model,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
        "priority": req.priority,
    }

    if not req.resume_from:
        try:
            service.pre_register_task(
                task_id=task_id,
                brand_path=req.brand_path,
                keywords=req.keywords,
                user_note=req.user_note,
                mode=req.mode,
                brand_site_url=req.brand_site_url,
                forbidden_whitelist=req.forbidden_whitelist or [],
                step_files=step_files,
                owner_id=owner_id,
                model=req.model,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            )
        except ValueError as e:
            msg = str(e)
            code = 409 if "已存在" in msg else 400
            raise HTTPException(status_code=code, detail=msg)
    else:
        existing = service.get_task_status(task_id)
        assert_task_access(_user, existing)
        if service.is_task_executing(task_id):
            raise HTTPException(
                status_code=409,
                detail=f"任务 {task_id} 正在执行中，无法重复启动",
            )

    if req.callback_url:
        try:
            webhook_mgr.register(
                task_id,
                req.callback_url,
                req.callback_secret or "",
                events=req.callback_events,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        _track_task(
            webhook_mgr.fire(
                task_id,
                "task.created",
                {
                    "task_id": task_id,
                    "keywords": req.keywords,
                    "mode": req.mode,
                    "status": "started",
                },
            ),
            name=f"webhook:task.created:{task_id}",
        )

    _track_task(
        _safe_start_task(service.start_workflow(**kwargs), task_id=task_id),
        name=f"workflow:start:{task_id}",
    )

    result = {
        "task_id": task_id,
        "status": "started",
        "resume_from": req.resume_from,
        "message": "任务已启动",
        "owner_id": owner_id,
    }
    if req.callback_url:
        result["webhook"] = {
            "url": req.callback_url,
            "registered": True,
            "events": req.callback_events,
        }
    if idempotency_key:
        result["idempotency_key"] = idempotency_key
    return _enrich_task_dict(result, full=False)


@router.post("/batch")
async def batch_start_tasks(
    req: BatchStartRequest,
    _user: dict = Depends(get_optional_user),
):
    """批量启动写作任务（Java 编排常用）。"""
    if not req.tasks:
        raise HTTPException(status_code=400, detail="tasks 不能为空")

    service = get_service()
    webhook_mgr = get_webhook_manager()
    owner_id = get_user_id(_user)
    batch_id = req.batch_id or (
        f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )

    started: List[dict] = []
    for index, item in enumerate(req.tasks, start=1):
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        keywords = (item.keywords or "").strip()
        if not keywords:
            raise HTTPException(status_code=400, detail=f"tasks[{index - 1}] 缺少 keywords")

        user_note = item.user_note or req.user_note
        brand_site_url = item.brand_site_url or req.brand_site_url
        brand_path = _resolve_brand_path(req.brand_path)

        try:
            service.pre_register_task(
                task_id=task_id,
                brand_path=req.brand_path,
                keywords=keywords,
                user_note=user_note,
                mode=req.mode,
                brand_site_url=brand_site_url,
                forbidden_whitelist=req.forbidden_whitelist or [],
                owner_id=owner_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        task = service.get_task_status(task_id) or {}
        extra = dict(task.get("extra") or {})
        extra["batch_id"] = batch_id
        task["extra"] = extra
        service._tasks[task_id] = task
        service._save_state(task_id)

        if req.callback_url:
            try:
                webhook_mgr.register(
                    task_id,
                    req.callback_url,
                    req.callback_secret or "",
                    events=req.callback_events,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        kwargs = {
            "brand_path": brand_path,
            "keywords": keywords,
            "user_note": user_note,
            "mode": req.mode,
            "brand_site_url": brand_site_url,
            "forbidden_whitelist": req.forbidden_whitelist or [],
            "task_id": task_id,
            "priority": req.priority,
        }
        _track_task(
            _safe_start_task(service.start_workflow(**kwargs), task_id=task_id),
            name=f"workflow:batch:{batch_id}:{task_id}",
        )
        started.append({"task_id": task_id, "keywords": keywords, "status": "started"})

    return {
        "batch_id": batch_id,
        "task_count": len(started),
        "tasks": started,
        "message": "批量任务已启动",
    }


@router.get("/concurrency")
async def get_concurrency_info(_user: dict = Depends(get_optional_user)):
    """获取并发和排队信息。"""
    service = get_service()
    return service.get_concurrency_info()


@router.get("/queued")
async def get_queued_tasks(_user: dict = Depends(get_optional_user)):
    """获取排队中的任务列表（按优先级排序）。"""
    service = get_service()
    return {"tasks": service.get_queued_tasks()}


@router.post("/{task_id}/cancel-queue")
async def cancel_queued_task(task_id: str, _user: dict = Depends(get_optional_user)):
    """取消排队中的任务。"""
    service = get_service()
    task = service.get_task_status(task_id)
    assert_task_access(_user, task)
    if service.cancel_queued_task(task_id):
        return {"task_id": task_id, "status": "cancelled", "message": "排队任务已取消"}
    raise HTTPException(status_code=400, detail="任务不在排队中，无法取消")


class PriorityRequest(BaseModel):
    priority: int = Field(ge=1, le=3, description="优先级: 1=低, 2=中, 3=高")


@router.put("/{task_id}/priority")
async def set_task_priority(task_id: str, req: PriorityRequest, _user: dict = Depends(get_optional_user)):
    """修改排队任务的优先级。"""
    service = get_service()
    task = service.get_task_status(task_id)
    assert_task_access(_user, task)
    if service.set_task_priority(task_id, req.priority):
        return {"task_id": task_id, "priority": req.priority, "message": "优先级已更新"}
    raise HTTPException(status_code=400, detail="任务不在排队中，无法修改优先级")


class ConcurrencyRequest(BaseModel):
    max_concurrent: int = Field(ge=1, le=20, description="最大并发任务数")


@router.put("/concurrency")
async def set_max_concurrent(req: ConcurrencyRequest, admin: dict = Depends(verify_admin_access)):
    """动态调整最大并发数（管理员）。"""
    service = get_service()
    result = service.set_max_concurrent(req.max_concurrent)
    return result


@router.get("")
async def list_tasks(_user: dict = Depends(get_optional_user)):
    service = get_service()
    tasks = filter_tasks_for_user(_user, service.list_tasks())
    enriched = [_enrich_task_dict(t, full=False) for t in tasks]
    return {"tasks": enriched}


@router.get("/{task_id}")
async def get_task(task_id: str, _user: dict = Depends(get_optional_user)):
    service = get_service()
    task = service.get_task_status(task_id)
    assert_task_access(_user, task)
    return _enrich_task_dict(task, full=True)


@router.get("/{task_id}/logs")
async def get_task_logs(task_id: str, _user: dict = Depends(get_optional_user)):
    service = get_service()
    task = service.get_task_status(task_id)
    assert_task_access(_user, task)
    return {"task_id": task_id, "logs": service.get_task_logs(task_id)}


@router.post("/{task_id}/pause")
async def pause_task(task_id: str, _user: dict = Depends(get_optional_user)):
    service = get_service()
    assert_task_access(_user, service.get_task_status(task_id))
    if service.pause_task(task_id):
        return {"status": "paused", "task_id": task_id}
    raise HTTPException(status_code=400, detail="无法暂停任务（未在运行）")


@router.post("/{task_id}/resume")
async def resume_task(task_id: str, _user: dict = Depends(get_optional_user)):
    service = get_service()
    assert_task_access(_user, service.get_task_status(task_id))
    if service.resume_task(task_id):
        return {"status": "resumed", "task_id": task_id}
    raise HTTPException(status_code=400, detail="无法恢复任务（未暂停）")


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, _user: dict = Depends(get_optional_user)):
    service = get_service()
    assert_task_access(_user, service.get_task_status(task_id))
    if service.cancel_task(task_id):
        return {"status": "cancelled", "task_id": task_id}
    raise HTTPException(status_code=400, detail="无法取消任务")


@router.post("/{task_id}/resume-from")
async def resume_from_node(
    task_id: str,
    req: ResumeFromRequest,
    _user: dict = Depends(get_optional_user),
):
    service = get_service()
    task = assert_task_access(_user, service.get_task_status(task_id))
    if service.is_task_executing(task_id):
        raise HTTPException(status_code=409, detail="任务正在执行中，无法续跑")
    brand_path = req.brand_path or task.get("brand_path", "")
    keywords = req.keywords or task.get("keywords", "")
    if not brand_path:
        raise HTTPException(status_code=400, detail="brand_path 不能为空")
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords 不能为空")
    mode = task.get("mode") or "auto"
    _track_task(
        _safe_start_task(
            service.start_workflow(
                brand_path=brand_path,
                keywords=keywords,
                mode=mode,
                task_id=task_id,
                resume_from=req.node_file,
                user_note=task.get("user_note", ""),
                brand_site_url=task.get("brand_site_url", ""),
            ),
            task_id=task_id,
        )
    )
    return {
        "task_id": task_id,
        "status": "resuming",
        "resume_from": req.node_file,
        "mode": mode,
        "message": f"从节点 {req.node_file} 开始续跑",
    }


@router.post("/{task_id}/rerun-from")
async def rerun_from_node(
    task_id: str,
    req: RerunFromRequest,
    _user: dict = Depends(get_optional_user),
):
    service = get_service()
    task = assert_task_access(_user, service.get_task_status(task_id))
    if service.is_task_executing(task_id):
        raise HTTPException(status_code=409, detail="任务正在执行中，无法重跑")
    brand_path = req.brand_path or task.get("brand_path", "")
    keywords = req.keywords or task.get("keywords", "")
    if not brand_path:
        raise HTTPException(status_code=400, detail="brand_path 不能为空")
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords 不能为空")
    mode = task.get("mode") or "auto"
    user_note = req.user_note or task.get("user_note", "")
    brand_site_url = req.brand_site_url or task.get("brand_site_url", "")
    _track_task(
        _safe_start_task(
            service.rerun_from_node(
                task_id=task_id,
                node_file=req.node_file,
                brand_path=brand_path,
                keywords=keywords,
                mode=mode,
                user_note=user_note,
                brand_site_url=brand_site_url,
            ),
            task_id=task_id,
        )
    )
    return {
        "task_id": task_id,
        "status": "rerunning",
        "rerun_from": req.node_file,
        "mode": mode,
        "message": f"从节点 {req.node_file} 开始重跑（清除该节点及之后的结果）",
    }


@router.post("/{task_id}/retry-node")
async def retry_node(
    task_id: str,
    req: RetryNodeRequest,
    _user: dict = Depends(get_optional_user),
):
    service = get_service()
    assert_task_access(_user, service.get_task_status(task_id))
    if service.retry_node(task_id, req.node_file):
        return {
            "task_id": task_id,
            "status": "retry_marked",
            "node_file": req.node_file,
            "message": f"节点 {req.node_file} 已标记为重试",
        }
    raise HTTPException(status_code=400, detail="无法标记重试")


@router.get("/reviews/pending")
async def get_pending_reviews(_user: dict = Depends(get_optional_user)):
    service = get_service()
    reviews = service.get_pending_reviews()
    if is_privileged(_user):
        return {"reviews": reviews}
    uid = get_user_id(_user)
    filtered = []
    for r in reviews:
        tid = r.get("task_id")
        t = service.get_task_status(tid) if tid else None
        if t and (t.get("owner_id") or (t.get("extra") or {}).get("owner_id")) == uid:
            filtered.append(r)
    return {"reviews": filtered}


@router.post("/{task_id}/review")
async def submit_review(
    task_id: str,
    req: ReviewDecisionRequest,
    _user: dict = Depends(get_optional_user),
):
    service = get_service()
    assert_task_access(_user, service.get_task_status(task_id))
    success = service.approve_review(
        task_id=task_id,
        decision=req.decision,
        modifications=req.modifications,
    )
    if success:
        return {"status": req.decision, "task_id": task_id, "decision": req.decision}
    raise HTTPException(status_code=400, detail="无法提交审核（未等待审核）")


@router.get("/{task_id}/files")
async def list_task_files(task_id: str, _user: dict = Depends(get_optional_user)):
    """获取任务生成的文件列表。"""
    service = get_service()
    assert_task_access(_user, service.get_task_status(task_id))
    
    instance_dir = _PROJECT_ROOT / "blog_writer" / "instance" / task_id
    if not instance_dir.exists():
        return {"files": [], "total": 0}
    
    files = []
    for f in sorted(instance_dir.iterdir()):
        if f.is_file() and not f.name.startswith('.'):
            stat = f.stat()
            files.append({
                "name": f.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "ext": f.suffix.lower(),
            })
    return {"files": files, "total": len(files)}


@router.get("/{task_id}/files/{filename}")
async def get_task_file(
    task_id: str,
    filename: str,
    download: bool = False,
    _user: dict = Depends(get_optional_user),
):
    """查看或下载任务生成的文件内容。
    - download=false（默认）：返回文本内容（用于前端预览）
    - download=true：返回文件下载响应
    """
    from fastapi.responses import FileResponse, PlainTextResponse
    
    service = get_service()
    assert_task_access(_user, service.get_task_status(task_id))
    
    # 安全校验：防止路径穿越
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    
    instance_dir = _PROJECT_ROOT / "blog_writer" / "instance" / task_id
    file_path = instance_dir / filename
    
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    if download:
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type="application/octet-stream",
        )
    
    # 预览模式：文本文件返回内容，其他返回下载
    text_exts = {'.md', '.txt', '.json', '.html', '.xml', '.csv', '.yaml', '.yml'}
    if file_path.suffix.lower() in text_exts:
        try:
            content = file_path.read_text(encoding='utf-8')
            return PlainTextResponse(content=content, media_type="text/plain; charset=utf-8")
        except UnicodeDecodeError:
            return FileResponse(path=str(file_path), filename=filename)
    
    return FileResponse(path=str(file_path), filename=filename)


@router.delete("/{task_id}")
async def delete_task(task_id: str, _user: dict = Depends(get_optional_user)):
    """删除任务（同时删除数据库记录和instance目录）。"""
    import shutil
    
    service = get_service()
    task_status = service.get_task_status(task_id)
    assert_task_access(_user, task_status)
    
    # 如果任务正在运行，先取消
    if task_status and task_status.get("status") in ("running", "waiting_review", "pending"):
        try:
            service.cancel_task(task_id)
        except Exception:
            pass
    
    # 删除数据库记录
    try:
        # 使用 service 中的数据库连接（与 list_tasks 同一个数据源）
        db = getattr(service, "_db", None)
        if db is not None:
            conn = db.conn
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM task_results WHERE task_id = ?", (task_id,))
            db.conn.commit()
        else:
            # 兜底：尝试直接获取数据库管理器
            from blog_writer.db import create_database_manager
            db = create_database_manager()
            conn = db.conn
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM task_results WHERE task_id = ?", (task_id,))
            conn.commit()
    except Exception as e:
        print(f"删除数据库记录失败: {e}")
    
    # 删除instance目录
    instance_dir = _PROJECT_ROOT / "blog_writer" / "instance" / task_id
    if instance_dir.exists():
        try:
            shutil.rmtree(instance_dir)
        except Exception as e:
            print(f"删除instance目录失败: {e}")
    
    # 从内存中移除
    if hasattr(service, '_tasks') and task_id in service._tasks:
        del service._tasks[task_id]
    
    # 清理任务缓存
    if hasattr(service, '_task_cache'):
        service._task_cache.pop(task_id, None)
    
    return {"task_id": task_id, "status": "deleted", "message": "任务已删除"}
