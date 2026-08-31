import os
import sys
import time
import json
import logging
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from blog_writer.api.nodes import router as nodes_router
from blog_writer.api.tasks import router as tasks_router
from blog_writer.api.auth import router as auth_router
from blog_writer.api.admin.nodes import router as admin_nodes_router
from blog_writer.api.admin.config import router as admin_config_router
from blog_writer.api.brands import router as brands_router
from blog_writer.api.deps import get_current_user, resolve_client_ip, is_task_auth_required
from blog_writer.api.response import success, error, ErrorCode
from blog_writer.api.webhooks import get_webhook_manager
from blog_writer.service_manager import get_config, get_service
from blog_writer.security.path_security import init_path_security
from blog_writer.security.masking import mask_log_content
from blog_writer.security.rate_limiter import init_rate_limiter, get_rate_limiter, reinit_rate_limiter
from blog_writer.integrations import (
    setup_structured_logging,
    get_metrics_collector,
    create_notification_service,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("blog-writer")

# 与 API / WorkflowService 共用同一 ConfigManager（避免热更新分裂）
config = get_config()

init_rate_limiter(config.get_all())
setup_structured_logging(config.get_all())
_notification_service = create_notification_service(config.get_all())
_metrics = get_metrics_collector()
_webhook_mgr = get_webhook_manager()


def _on_config_changed(new_cfg: dict):
    """API / 文件热更新后刷新可热切换的运行时组件。

    需重启才生效：database.*、CORS allowed_origins、nodes_dir/instance_root 路径根。
    """
    try:
        reinit_rate_limiter(new_cfg if isinstance(new_cfg, dict) else config.get_all())
    except Exception as e:
        logger.warning("rate limiter hot reload failed: %s", e)
    try:
        from blog_writer.api.deps import reset_auth_provider_cache
        reset_auth_provider_cache()
    except Exception as e:
        logger.warning("deps auth cache reset failed: %s", e)
    try:
        from blog_writer.api.auth import reset_auth_provider_cache as reset_login_provider
        reset_login_provider()
    except Exception as e:
        logger.warning("login auth cache reset failed: %s", e)
    try:
        svc = get_service()
        if hasattr(svc, "apply_runtime_config"):
            svc.apply_runtime_config()
        elif hasattr(svc, "reload_llm"):
            svc.reload_llm()
    except Exception as e:
        logger.warning("workflow runtime config refresh failed: %s", e)


config.on_change(_on_config_changed)

_start_time = time.time()
IS_PRODUCTION = os.environ.get("BLOG_WRITER_MODE", "development") == "production"

# Java平台对接配置：字段命名转换开关
# snake_case（Python默认）→ camelCase（Java常用）
# 设置环境变量 RESPONSE_CASE=camel 即可一键切换
# 支持运行时读取（修改环境变量后无需重启）
def _get_response_case():
    """获取当前字段命名模式（支持运行时切换）"""
    return os.environ.get("RESPONSE_CASE", "snake").lower() == "camel"

app = FastAPI(
    title="Blog-Writer AI Workflow System",
    description="AI驱动的社媒运营工作流引擎 - 企业版",
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ============ 1. CORS 配置 ============
# 支持公司平台前端跨域访问
env_origins = os.environ.get("CORS_ORIGINS", "")
config_origins = config.get("security.allowed_origins", [])

default_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
]

if env_origins:
    allowed_origins = [o.strip() for o in env_origins.split(",") if o.strip()]
elif config_origins:
    allowed_origins = config_origins
else:
    allowed_origins = default_origins

# 生产环境额外允许公司内部域名（精确匹配，避免通配符子域）
if IS_PRODUCTION:
    company_domain = os.environ.get("COMPANY_DOMAIN", "")
    if company_domain:
        # 使用具体子域而非通配符，降低 XSS 扩散风险
        for prefix in ("app", "admin", "api", "ops"):
            allowed_origins.append(f"https://{prefix}.{company_domain}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Request", "X-Request-ID", "X-API-Key", "Idempotency-Key"],
    expose_headers=["X-RateLimit-Remaining", "X-RateLimit-Reset", "Content-Disposition"],
    max_age=3600,
)

# ============ 2. 路径安全初始化 ============
base_dirs = [
    config.resolve_path(config.get("workflow.instance_root", "./instance")),
    Path("./brands").resolve(),
    config.resolve_path(config.get("workflow.nodes_dir", "./nodes")),
]
# 兼容根目录 brands
brands_root = Path(__file__).resolve().parent.parent / "brands"
if brands_root.exists():
    base_dirs.append(brands_root.resolve())
init_path_security(base_dirs)


# ============ 3. 字段命名转换工具 ============
import re as _re

def _snake_to_camel(name: str) -> str:
    """snake_case → camelCase"""
    components = name.split("_")
    return components[0] + "".join(x.title() for x in components[1:])

def _convert_keys(obj, converter):
    """递归转换字典的key命名"""
    if isinstance(obj, dict):
        return {converter(k) if isinstance(k, str) else k: _convert_keys(v, converter) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_keys(item, converter) for item in obj]
    return obj

# ============ 4. 请求体 camelCase → snake_case 转换中间件 ============
# 注意：camelCase → snake_case 转换已在 Pydantic 模型层通过别名实现
# （见 tasks.py / auth.py 中的 ConfigDict + populate_by_name）
# 此中间件保留用于特殊场景（如嵌套dict字段转换），默认关闭

@app.middleware("http")
async def request_case_convert_middleware(request: Request, call_next):
    """请求体预处理中间件
    
    默认直通（不修改请求），Pydantic 模型层的 populate_by_name 
    已能同时接受 snake_case 和 camelCase 字段名。
    """
    return await call_next(request)


# ============ 5. 统一响应格式中间件 ============
_HOP_BY_HOP_HEADERS = {
    "content-length",
    "content-type",
    "transfer-encoding",
    "content-encoding",
}

# 超过此大小的 JSON 不再全量缓冲包装（避免破坏流式 / OOM）
MAX_WRAPPED_JSON_BYTES = 1 * 1024 * 1024
_STREAM_CONTENT_TYPES = (
    "text/event-stream",
    "application/jsonl",
    "application/x-ndjson",
    "application/octet-stream",
)


def _passthrough_headers(headers) -> dict:
    """复制响应头时去掉会与重建 body 冲突的 hop-by-hop / 长度相关头。"""
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }


def _should_skip_json_wrap(response) -> bool:
    """流式 / 附件 / 超大 JSON：直接透传。"""
    content_type = (response.headers.get("content-type") or "").lower()
    if any(t in content_type for t in _STREAM_CONTENT_TYPES):
        return True
    disposition = (response.headers.get("content-disposition") or "").lower()
    if "attachment" in disposition:
        return True
    cl = response.headers.get("content-length")
    if cl:
        try:
            if int(cl) > MAX_WRAPPED_JSON_BYTES:
                return True
        except (TypeError, ValueError):
            pass
    return False


async def _read_body_bounded(response, max_bytes: int) -> tuple:
    """读取 body；超限时返回 (None, buffered_chunks, remaining_iterator)。"""
    buf = bytearray()
    chunks = []
    iterator = response.body_iterator
    async for chunk in iterator:
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        chunks.append(chunk)
        buf.extend(chunk)
        if len(buf) > max_bytes:
            return None, chunks, iterator
    return bytes(buf), chunks, None


@app.middleware("http")
async def unified_response_middleware(request: Request, call_next):
    """将所有 API 响应包装为 {code, message, data, timestamp} 标准格式"""
    
    path = request.url.path
    
    # 跳过非API端点
    if path == "/" or path.startswith("/health") or path.startswith("/ready") or path.startswith("/docs") or path.startswith("/openapi.json") or path.startswith("/redoc") or path.startswith("/static"):
        return await call_next(request)
    
    # Metrics/Notifications/Webhook管理端点保持原样（不包装）
    if path.startswith("/api/metrics") or path.startswith("/api/v1/metrics"):
        return await call_next(request)
    if path.startswith("/api/notifications") or path.startswith("/api/v1/notifications"):
        return await call_next(request)
    if path.startswith("/api/webhooks") or path.startswith("/api/v1/webhooks"):
        return await call_next(request)
    
    response = await call_next(request)
    
    # 跳过非JSON响应
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return response

    if _should_skip_json_wrap(response):
        return response
    
    # 读取并重建响应体（带大小上限；超限透传已缓冲+剩余流）
    try:
        body, chunks, remaining = await _read_body_bounded(
            response, MAX_WRAPPED_JSON_BYTES
        )
        if body is None:
            # 超限：重建 StreamingResponse，避免返回已耗尽的 iterator
            async def _replay():
                for c in chunks:
                    yield c
                if remaining is not None:
                    async for c in remaining:
                        if isinstance(c, str):
                            c = c.encode("utf-8")
                        yield c

            return StreamingResponse(
                _replay(),
                status_code=response.status_code,
                media_type=content_type,
                headers=_passthrough_headers(response.headers),
            )

        if not body:
            return response
        
        original_data = json.loads(body.decode("utf-8"))
    except Exception:
        # 解析失败时若已消费 body，用已缓冲内容重建，避免空响应
        try:
            if "chunks" in locals() and chunks:
                async def _replay_err():
                    for c in chunks:
                        yield c
                return StreamingResponse(
                    _replay_err(),
                    status_code=response.status_code,
                    media_type=content_type or "application/json",
                    headers=_passthrough_headers(response.headers),
                )
        except Exception:
            pass
        return response

    passthrough = _passthrough_headers(response.headers)
    
    # 已经是标准格式，跳过包装但执行命名转换
    if isinstance(original_data, dict) and "code" in original_data and "timestamp" in original_data:
        if _get_response_case():
            original_data = _convert_keys(original_data, _snake_to_camel)
        return JSONResponse(content=original_data, status_code=response.status_code, headers=passthrough)
    
    # 包装为标准格式（保留真实 HTTP 状态码，便于平台熔断/重试；业务码见 body.code）
    status_code = response.status_code
    # 提取原始 detail（若有），避免通用文案覆盖具体错误信息
    orig_detail = None
    if isinstance(original_data, dict):
        orig_detail = original_data.get("detail") or original_data.get("message")

    if 200 <= status_code < 300:
        wrapped = success(original_data)
    elif status_code == 401:
        wrapped = error(ErrorCode.AUTH_FAILED, str(orig_detail or "认证失败或Token已过期")[:200])
    elif status_code == 403:
        wrapped = error(ErrorCode.PERMISSION_DENIED, str(orig_detail or "权限不足")[:200])
    elif status_code == 404:
        wrapped = error(ErrorCode.NOT_FOUND, str(orig_detail or "资源不存在")[:200])
    elif status_code == 429:
        wrapped = error(ErrorCode.RATE_LIMITED, str(orig_detail or "请求过于频繁，请稍后重试")[:200])
    elif status_code in (400, 422):
        wrapped = error(ErrorCode.PARAM_ERROR, str(orig_detail or "参数验证失败")[:200])
    elif status_code >= 500:
        wrapped = error(ErrorCode.INTERNAL_ERROR, str(orig_detail or "服务器内部错误")[:200])
    else:
        detail = orig_detail or "请求失败"
        wrapped = error(ErrorCode.INTERNAL_ERROR, str(detail)[:200])
    
    # 对包装后的响应应用命名转换
    if _get_response_case():
        wrapped = _convert_keys(wrapped, _snake_to_camel)
    
    return JSONResponse(content=wrapped, status_code=status_code, headers=passthrough)

# ============ 6. 请求日志和安全中间件（先注册 → 内层）============
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    start_time = datetime.now()
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path

    # 探针不写访问日志（限流层已 bypass；此处对齐）
    if path in ("/health", "/ready", "/metrics", "/docs", "/openapi.json", "/", "/redoc") or path.startswith(
        "/health"
    ) or path.startswith("/ready") or path.startswith("/metrics"):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
    
    log_path = path
    if "/api/admin/config" in path and request.method == "GET":
        log_path = "/api/admin/config (GET)"
    
    logger.info(f"[{client_ip}] {request.method} {log_path}")
    
    try:
        response = await call_next(request)
        
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.debug(f"[{client_ip}] {request.method} {path} -> {response.status_code} ({duration:.3f}s)")
        
        return response
        
    except Exception as e:
        logger.error(f"[{client_ip}] {request.method} {path} failed: {str(e)}")
        raise


# ============ 7. 限流中间件（后注册 → 最外层：先限流再记安全日志）============
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def _is_task_poll_get(method: str, path: str) -> bool:
    """任务状态/列表/日志等只读轮询：不计入严格限流（仍保护 start/login 等写接口）。"""
    if (method or "").upper() != "GET":
        return False
    for prefix in ("/api/tasks", "/api/v1/tasks"):
        if path == prefix or path.startswith(prefix + "/"):
            # 仍限流敏感子路径（若未来有 GET 侧写操作可在此排除）
            return True
    return False


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    rate_limiter = get_rate_limiter()
    client_ip = resolve_client_ip(request)
    # 有 Bearer 时按 token 维度限流，避免 Java 网关与运营浏览器共用同一 NAT IP 互相踩限
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer ") and len(auth) > 20:
        client_id = f"tok:{auth[7:23]}"
    else:
        client_id = client_ip
    path = request.url.path
    
    if path in ("/health", "/ready", "/metrics", "/docs", "/openapi.json", "/", "/redoc", "/favicon.ico"):
        return await call_next(request)
    if path.startswith("/health") or path.startswith("/ready") or path.startswith("/metrics") or path.startswith("/api/metrics") or path.startswith("/api/v1/metrics") or path.startswith("/static"):
        return await call_next(request)
    if _is_task_poll_get(request.method, path):
        return await call_next(request)
    
    allowed, reason = rate_limiter.is_allowed(client_id, path)
    
    if not allowed:
        logger.warning(f"Rate limited: {client_id} -> {path} ({reason})")
        return JSONResponse(
            status_code=429,
            content=error(ErrorCode.RATE_LIMITED, f"请求过于频繁，请稍后重试 ({reason})"),
            headers={
                "Retry-After": "60",
                "X-RateLimit-Exceeded": "true",
                **_SECURITY_HEADERS,
            }
        )
    
    response = await call_next(request)
    return response


# ============ 8. 全局异常处理 ============
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        field = " -> ".join(str(loc) for loc in err.get("loc", []) if loc != "body")
        msg = err.get("msg", "未知错误")
        errors.append(f"{field}: {msg}")

    # 记录请求体和验证错误，便于排查 422 根因
    try:
        body = await request.body()
        body_text = body.decode("utf-8", errors="replace")[:2000]
    except Exception:
        body_text = "<unreadable>"
    logger.warning(
        "422 validation error: %s %s | body=%s | errors=%s",
        request.method, request.url.path, body_text, errors
    )

    # 用第一条错误作为 message，让前端直接显示具体原因
    first_msg = errors[0] if errors else "参数验证失败"

    return JSONResponse(
        status_code=422,
        content=error(ErrorCode.PARAM_ERROR, first_msg, {"details": errors})
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail else None
    if exc.status_code == 401:
        return JSONResponse(status_code=401, content=error(ErrorCode.AUTH_FAILED, detail or "未认证或认证已过期"))
    elif exc.status_code == 403:
        return JSONResponse(status_code=403, content=error(ErrorCode.PERMISSION_DENIED, detail or "权限不足"))
    elif exc.status_code == 404:
        return JSONResponse(status_code=404, content=error(ErrorCode.NOT_FOUND, detail or "资源不存在"))
    else:
        return JSONResponse(
            status_code=exc.status_code,
            content=error(exc.status_code, exc.detail or "请求失败")
        )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {request.method} {request.url.path} - {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=error(ErrorCode.INTERNAL_ERROR, "服务器内部错误")
    )


# ============ 8. 路由注册（API版本化） ============

# v1 API - 主要版本
app.include_router(nodes_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_nodes_router, prefix="/api/v1/admin")
app.include_router(admin_config_router, prefix="/api/v1/admin")
app.include_router(brands_router, prefix="/api/v1")

# 兼容层 - 保持旧路径可用
app.include_router(nodes_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(admin_nodes_router, prefix="/api/admin")
app.include_router(admin_config_router, prefix="/api/admin")
app.include_router(brands_router, prefix="/api")


# ============ 9. Webhook 管理端点（需鉴权） ============
@app.get("/api/v1/webhooks")
@app.get("/api/webhooks")
async def list_webhooks(_user: dict = Depends(get_current_user)):
    """列出已注册的 Webhook 回调（非特权用户仅看自己的任务）"""
    from blog_writer.api.task_access import is_privileged, get_user_id, get_task_owner_id
    from blog_writer.service_manager import get_service

    callbacks = _webhook_mgr.get_callbacks()
    if not is_privileged(_user):
        service = get_service()
        uid = get_user_id(_user)
        filtered = {}
        for tid, cb in callbacks.items():
            task = service.get_task_status(tid)
            if task and get_task_owner_id(task) == uid:
                filtered[tid] = cb
        callbacks = filtered
    return success({
        "callbacks": callbacks,
        "total": len(callbacks),
    })


@app.get("/api/v1/webhooks/history")
@app.get("/api/webhooks/history")
async def webhook_history(task_id: str = None, limit: int = 20, _user: dict = Depends(get_current_user)):
    """获取 Webhook 回调历史"""
    from blog_writer.api.task_access import assert_task_access, is_privileged, get_user_id, get_task_owner_id
    from blog_writer.service_manager import get_service

    service = get_service()
    if task_id:
        assert_task_access(_user, service.get_task_status(task_id))
    history = _webhook_mgr.get_history(task_id, limit)
    if not is_privileged(_user) and not task_id:
        uid = get_user_id(_user)
        history = [
            h for h in history
            if get_task_owner_id(service.get_task_status(h.get("task_id")) or {}) == uid
        ]
    return success({"history": history})


@app.delete("/api/v1/webhooks/{task_id}")
@app.delete("/api/webhooks/{task_id}")
async def unregister_webhook(task_id: str, _user: dict = Depends(get_current_user)):
    """注销 Webhook 回调"""
    from blog_writer.api.task_access import assert_task_access
    from blog_writer.service_manager import get_service

    assert_task_access(_user, get_service().get_task_status(task_id))
    if _webhook_mgr.has_callback(task_id):
        _webhook_mgr.unregister(task_id)
        return success(message=f"Webhook for task {task_id} 已注销")
    return error(ErrorCode.TASK_NOT_FOUND, f"Task {task_id} 没有注册 Webhook")


@app.post("/api/v1/webhooks/{task_id}/test")
@app.post("/api/webhooks/{task_id}/test")
async def test_webhook(task_id: str, _user: dict = Depends(get_current_user)):
    """测试 Webhook 回调"""
    from blog_writer.api.task_access import assert_task_access
    from blog_writer.service_manager import get_service

    assert_task_access(_user, get_service().get_task_status(task_id))
    if not _webhook_mgr.has_callback(task_id):
        return error(ErrorCode.TASK_NOT_FOUND, f"Task {task_id} 没有注册 Webhook")
    
    import asyncio
    success_flag = await _webhook_mgr.fire(
        task_id,
        "webhook.test",
        {"test": True, "message": "Webhook connectivity test"}
    )
    
    if success_flag:
        return success(message="Webhook 测试成功")
    return error(ErrorCode.WEBHOOK_ERROR, "Webhook 测试失败")


# ============ 10. 静态文件 ============
web_dir = Path(__file__).parent / "web"
if web_dir.exists():
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")


@app.middleware("http")
async def static_cache_control_middleware(request: Request, call_next):
    """静态文件禁用缓存，确保前端更新即时生效"""
    response = await call_next(request)
    if request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ============ 11. 路由定义 ============
@app.get("/")
async def index():
    index_file = web_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {
        "name": "Blog-Writer AI Workflow System",
        "version": "2.1.0",
        "status": "running",
        "mode": os.environ.get("BLOG_WRITER_MODE", "development"),
        "api_docs": "/docs",
        "api_version": "v1",
        "endpoints": {
            "v1": {
                "nodes": "/api/v1/nodes",
                "tasks": "/api/v1/tasks",
                "tasks_start": "/api/v1/tasks/start",
                "tasks_batch": "/api/v1/tasks/batch",
                "reviews": "/api/v1/tasks/reviews/pending",
                "auth": "/api/v1/auth",
                "health": "/health",
                "ready": "/ready",
                "admin": {
                    "nodes": "/api/v1/admin/nodes",
                    "config": "/api/v1/admin/config",
                    "stats": "/api/v1/admin/config/stats",
                },
                "webhooks": "/api/v1/webhooks",
            },
            "integration": {
                "response_case": os.environ.get("RESPONSE_CASE", "snake"),
                "task_auth": os.environ.get("BLOG_WRITER_TASK_AUTH", "auto"),
                "health_envelope": os.environ.get("BLOG_WRITER_HEALTH_ENVELOPE", "false"),
            },
            "compatibility": "旧路径 /api/* 仍然可用",
        }
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    llm_ok = False
    try:
        llm_cfg = config.get("llm.models.default", {})
        if llm_cfg and (llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY")):
            llm_ok = True
    except Exception:
        pass

    body = {
        "status": "healthy",
        "version": "2.1.0",
        "api_version": "v1",
        "python_version": sys.version,
        "uptime_seconds": int(time.time() - _start_time),
        "config_loaded": config.config_path.exists(),
        "llm_provider": "configured" if llm_ok else "not_configured",
        "auth_mode": "sso" if (config.get("security.sso.enabled") or config.get("sso.enabled")) else "local_jwt",
        "deployment_mode": os.environ.get("BLOG_WRITER_MODE", "development"),
        "task_auth_required": is_task_auth_required(),
        "state_backend": os.environ.get("BLOG_WRITER_STATE_BACKEND", "memory").strip().lower() or "memory",
        "response_case": os.environ.get("RESPONSE_CASE", "snake").strip().lower() or "snake",
        "webhooks_registered": len(_webhook_mgr.get_callbacks()),
    }
    if os.environ.get("BLOG_WRITER_HEALTH_ENVELOPE", "").lower() in ("1", "true", "yes"):
        return {
            "code": 0,
            "message": "healthy",
            "data": body,
            "timestamp": int(time.time()),
        }
    return body


@app.get("/ready")
async def readiness_check():
    """进程就绪探针：DB/配置失败返回 503；LLM 仅作为能力项，不影响探针成功。"""
    checks = {
        "database": "unknown",
        "config": "ok" if config.config_path.exists() else "missing",
    }
    capabilities = {
        "llm_provider": "unknown",
    }
    
    try:
        from blog_writer.service_manager import get_service
        service = get_service()
        # 触达已初始化的 DB（避免另开未解析路径的连接）
        if getattr(service, "_db", None) is not None:
            conn = service._db.conn
            conn.execute("SELECT 1").fetchone()
            checks["database"] = "ok"
        else:
            checks["database"] = "unavailable"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:120]}"
    
    try:
        llm_cfg = config.get("llm.models.default", {})
        if llm_cfg and (llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY")):
            capabilities["llm_provider"] = "configured"
        else:
            capabilities["llm_provider"] = "not_configured"
    except Exception:
        capabilities["llm_provider"] = "error"
    
    process_ok = checks["database"] == "ok" and checks["config"] == "ok"
    status_code = 200 if process_ok else 503

    body = {
        "status": "ready" if process_ok else "not_ready",
        "checks": checks,
        "capabilities": capabilities,
        "version": "2.1.0",
        "uptime_seconds": int(time.time() - _start_time),
    }
    if os.environ.get("BLOG_WRITER_HEALTH_ENVELOPE", "").lower() in ("1", "true", "yes"):
        content = {
            "code": 0 if process_ok else 503,
            "message": "ready" if process_ok else "not_ready",
            "data": body,
            "timestamp": int(time.time()),
        }
    else:
        content = body

    return JSONResponse(
        status_code=status_code,
        content=content,
    )


@app.get("/api/v1/metrics")
@app.get("/api/metrics")
async def metrics_endpoint(format: str = "json"):
    rl = get_rate_limiter()
    metrics = get_metrics_collector()
    
    metrics.set_gauge("uptime_seconds", time.time() - _start_time)
    metrics.set_gauge("webhooks_active", len(_webhook_mgr.get_callbacks()))
    rl_stats = rl.get_stats()
    for key, value in rl_stats.items():
        if isinstance(value, (int, float)):
            metrics.set_gauge(f"rate_limiter_{key}", value)
    
    if format == "prometheus":
        prom_text = metrics.generate_prometheus()
        return Response(
            content=prom_text,
            media_type="text/plain; version=0.0.4; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=metrics.prom"}
        )
    
    return {
        "rate_limiter": rl_stats,
        "metrics": metrics.get_stats(),
        "system": {
            "uptime_seconds": int(time.time() - _start_time),
            "python_version": sys.version,
            "api_version": "v1",
            "webhooks_active": len(_webhook_mgr.get_callbacks()),
        }
    }


@app.get("/api/v1/notifications/channels")
@app.get("/api/notifications/channels")
async def list_notification_channels():
    channels = _notification_service.list_channels()
    return success({
        "channels": channels,
        "count": len(channels),
    })


# ============ 12. 启动事件 ============
@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    logger.info("🚀 Blog-Writer AI Workflow System v2.1 (企业API版)")
    logger.info("=" * 60)
    logger.info(f"   Mode: {os.environ.get('BLOG_WRITER_MODE', 'development')}")
    logger.info(f"   Config: {config.config_path}")
    logger.info(f"   API Version: v1 (向后兼容 /api/*)")
    logger.info(f"   Auth: {'SSO' if (config.get('security.sso.enabled') or config.get('sso.enabled')) else 'Local JWT'}")
    logger.info(f"   CORS Origins: {allowed_origins}")
    
    # SSO 模式信息
    if config.get("security.sso.enabled") or config.get("sso.enabled"):
        logger.info(f"   SSO: enabled (OAuth2)")
        logger.info(f"     - Auth URL: {config.get('security.sso.auth_url') or config.get('sso.auth_url', 'N/A')}")
        logger.info(f"     - Token URL: {config.get('security.sso.token_url') or config.get('sso.token_url', 'N/A')}")
    else:
        logger.info(f"   SSO: disabled (本地 JWT)")
    
    nodes_dir = config.resolve_path(config.get("workflow.nodes_dir", "./nodes"))
    if nodes_dir.exists():
        node_count = len(list(nodes_dir.glob("*.json")))
        logger.info(f"   Nodes: {node_count} definitions loaded from {nodes_dir}")
    else:
        logger.warning(f"   Nodes dir missing: {nodes_dir}")
    
    logger.info(f"   Webhook: 回调机制已就绪")
    logger.info("=" * 60)
    
    # 启动定时任务调度器（scheduled 任务到期自动执行）
    try:
        service = get_service()
        service.start_scheduler()
    except Exception as e:
        logger.warning(f"   Scheduler: 定时任务调度器启动失败 - {e}")
    else:
        logger.info("   Scheduler: 定时任务调度器已启动")
    
    logger.info("✅ System ready!")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("=" * 60)
    logger.info("🛑 Blog-Writer shutting down...")
    
    # 0. 停止定时任务调度器
    try:
        service = get_service()
        service.stop_scheduler()
        logger.info("   Scheduler stopped")
    except Exception as e:
        logger.warning(f"   Scheduler stop error: {e}")
    
    # 1. 清理共享线程池（等待正在执行的 webhook 完成）
    try:
        from blog_writer.workflow_service import _shared_executor
        _shared_executor.shutdown(wait=True, cancel_futures=False)
        logger.info("   Thread pool shutdown complete")
    except Exception as e:
        logger.warning(f"   Thread pool shutdown error: {e}")
    
    # 2. 清理数据库连接
    try:
        from blog_writer.db import DatabaseManager
        db = DatabaseManager()
        db.close_all()
        logger.info("   Database connections closed")
    except Exception as e:
        logger.warning(f"   Database cleanup error: {e}")
    
    # 3. 清理 Webhook 管理器
    try:
        from blog_writer.api.webhooks import WebhookManager
        # 不做额外清理，WebhookManager 是纯内存结构
        logger.info("   Webhook manager ready for shutdown")
    except Exception:
        pass
    
    logger.info("   Goodbye!")
    logger.info("=" * 60)
