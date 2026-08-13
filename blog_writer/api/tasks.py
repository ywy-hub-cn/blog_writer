"""任务API - 任务启动、状态查询、审核（需鉴权）"""
import asyncio
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, List, Union

from fastapi import APIRouter, HTTPException, Request, Depends, Header
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator, ConfigDict, Field

from blog_writer.service_manager import get_service
from blog_writer.api.webhooks import get_webhook_manager
from blog_writer.api.deps import get_current_user, security
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
    """任务接口鉴权：登录了返回真实用户，未登录返回默认运营用户（免登录使用）。

    运营场景下不需要登录即可启动/查看/管理任务；管理员接口（nodes/config）
    仍使用 get_current_user 保持登录要求。
    """
    try:
        return await get_current_user(request, credentials, x_api_key)
    except HTTPException:
        # 未登录或 token 无效：返回默认运营用户（admin 角色，可访问所有任务）
        return {
            "is_admin": True,
            "user_id": "operator",
            "role": "admin",
            "auth_type": "anonymous",
            "token_created_at": None,
        }


def _track_task(coro, name: str = ""):
    """创建并追踪后台 asyncio.Task，防止被 GC 回收。"""
    t = asyncio.create_task(coro, name=name) if name else asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


def _validate_brand_path_value(v: str) -> str:
    if not v or len(v) > 255:
        raise ValueError("品牌路径不能为空且长度不能超过255")
    if v.startswith("/") or v.startswith("\\") or v.startswith(".."):
        raise ValueError("路径不安全")
    # 检查路径遍历：任何段为 ".." 则拒绝
    if any(seg == ".." for seg in v.replace("\\", "/").split("/")):
        raise ValueError("路径不安全，不允许目录遍历")
    if v.startswith("~") or "~/" in v or "~\\" in v:
        raise ValueError("路径不安全")
    # 禁止绝对路径盘符
    if len(v) >= 2 and v[1] == ":":
        raise ValueError("路径不安全")
    # 只允许安全字符
    if not re.match(r'^[a-zA-Z0-9_\-./\\]+$', v):
        raise ValueError("路径包含非法字符")
    return v


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
    callback_url: Optional[str] = Field(default=None, alias="callbackUrl")
    callback_secret: Optional[str] = Field(default=None, alias="callbackSecret")

    @field_validator("brand_path")
    @classmethod
    def validate_brand_path(cls, v: str) -> str:
        return _validate_brand_path_value(v)

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, v: str) -> str:
        if not v or len(v) > 500:
            raise ValueError("关键词不能为空且长度不能超过500")
        v = re.sub(r'[<>\'"\x00-\x1f]', '', v)
        return v.strip()

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
        if len(v) > 2000:
            raise ValueError("附加说明长度不能超过2000")
        return v

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
    _user: dict = Depends(get_optional_user),
):
    service = get_service()
    webhook_mgr = get_webhook_manager()

    task_id = req.task_id or (
        f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
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
            webhook_mgr.register(task_id, req.callback_url, req.callback_secret or "")
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
        result["webhook"] = {"url": req.callback_url, "registered": True}
    return result


@router.get("")
async def list_tasks(_user: dict = Depends(get_optional_user)):
    service = get_service()
    return {"tasks": filter_tasks_for_user(_user, service.list_tasks())}


@router.get("/{task_id}")
async def get_task(task_id: str, _user: dict = Depends(get_optional_user)):
    service = get_service()
    task = service.get_task_status(task_id)
    assert_task_access(_user, task)
    return task


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
    _track_task(
        _safe_start_task(
            service.rerun_from_node(
                task_id=task_id,
                node_file=req.node_file,
                brand_path=brand_path,
                keywords=keywords,
                mode=mode,
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
