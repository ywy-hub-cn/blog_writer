"""管理员配置API - 需要鉴权"""
from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends

from blog_writer.service_manager import get_config, get_service
from blog_writer.api.deps import verify_admin_access, reset_auth_provider_cache
from blog_writer.security.masking import mask_sensitive_data, create_config_response

router = APIRouter(prefix="/config", tags=["admin-config"])


@router.get("")
async def get_config_endpoint(admin: dict = Depends(verify_admin_access)):
    config = get_config()
    config_data = config.get_all()
    return create_config_response(config_data)


@router.put("")
async def update_config(updates: Dict[str, Any], admin: dict = Depends(verify_admin_access)):
    config = get_config()
    before = config.get_all()
    was_sso, was_fallback = _sso_flags(before)
    # 脱敏处理 - 防止敏感信息错误写入
    safe_updates = _sanitize_config_update(updates)
    config.update(safe_updates)
    after = config.get_all()
    now_sso, now_fallback = _sso_flags(after)
    service = get_service()
    service.reload_llm()
    # SSO/认证开关热更新后立即生效
    reset_auth_provider_cache()
    try:
        from blog_writer.api.auth import reset_auth_provider_cache as reset_login_provider
        reset_login_provider()
    except Exception:
        pass
    # 新启用 SSO，或关闭本地降级：吊销已有本地 JWT，避免绕过
    if now_sso and (not was_sso or (was_fallback and not now_fallback)):
        try:
            from blog_writer.security.auth import AuthManager
            AuthManager.revoke_all_tokens()
        except Exception:
            pass
    return {"status": "updated"}


@router.get("/llm")
async def get_llm_config(admin: dict = Depends(verify_admin_access)):
    config = get_config()
    llm_config = config.get_llm_config()
    # 脱敏API Key
    if "api_key" in llm_config:
        api_key = llm_config["api_key"]
        if api_key:
            if len(api_key) > 7:
                llm_config["api_key"] = api_key[:7] + "****" + api_key[-4:]
            else:
                llm_config["api_key"] = "****"
        else:
            llm_config["api_key"] = "未配置"
    return llm_config


@router.put("/llm")
async def update_llm_config(updates: Dict[str, Any], admin: dict = Depends(verify_admin_access)):
    config = get_config()
    
    # 检查是否需要更新API Key
    if "api_key" in updates:
        new_key = updates["api_key"]
        # 如果是掩码格式，不更新
        if "****" in new_key:
            del updates["api_key"]
    
    for key, value in updates.items():
        config.set(f"llm.{key}", value)
    
    service = get_service()
    service.reload_llm()
    return {"status": "updated"}


@router.get("/workflow")
async def get_workflow_config(admin: dict = Depends(verify_admin_access)):
    return get_config().get_workflow_config()


@router.put("/workflow")
async def update_workflow_config(updates: Dict[str, Any], admin: dict = Depends(verify_admin_access)):
    config = get_config()
    for key, value in updates.items():
        config.set(f"workflow.{key}", value)
    return {"status": "updated"}


@router.get("/stats")
async def get_system_stats(admin: dict = Depends(verify_admin_access)):
    service = get_service()
    
    tasks = list(service.get_all_tasks().values())
    total_tokens = sum(
        r.get("token_usage", {}).get("total_tokens_used", 0)
        for task in tasks
        for r in task.get("results", [])
    )
    
    llm_stats = service.get_llm_stats() if service.has_llm_provider() else {"total_tokens_used": 0, "total_calls": 0}
    
    completed_tasks = [t for t in tasks if t["status"] == "completed"]
    running_tasks = [t for t in tasks if t["status"] in ["running", "waiting_review"]]
    
    # 计算平均耗时
    total_duration = 0
    for task in completed_tasks:
        start = task.get("start_time")
        end = task.get("end_time", start)
        if start and end:
            from datetime import datetime
            try:
                s = datetime.fromisoformat(start)
                e = datetime.fromisoformat(end)
                total_duration += (e - s).total_seconds()
            except:
                pass
    
    avg_duration = total_duration / len(completed_tasks) if completed_tasks else 0
    
    # 预估成本（按DeepSeek定价 ¥2/1M tokens）
    estimated_cost = (total_tokens / 1_000_000) * 2.0
    
    return {
        "total_tasks": len(tasks),
        "completed_tasks": len(completed_tasks),
        "running_tasks": len(running_tasks),
        "pending_reviews": len([t for t in tasks if t["status"] == "waiting_review"]),
        "success_rate": len(completed_tasks) / len(tasks) * 100 if tasks else 0,
        "avg_duration_seconds": avg_duration,
        "nodes_count": len(service.list_nodes()),
        "llm_stats": llm_stats,
        "total_tokens_consumed": total_tokens,
        "estimated_cost_cny": round(estimated_cost, 4),
        "tasks_summary": [{
            "task_id": t["task_id"],
            "status": t["status"],
            "keywords": t.get("keywords", ""),
            "current_step": t.get("current_step", 0),
            "total_steps": t.get("total_steps", 0),
            "token_usage": sum(
                r.get("token_usage", {}).get("total_tokens_used", 0)
                for r in t.get("results", [])
            )
        } for t in tasks]
    }


@router.post("/test-llm")
async def test_llm_connection(admin: dict = Depends(verify_admin_access)):
    """测试LLM连接"""
    service = get_service()
    try:
        # 检查是否已配置API Key
        llm_config = service.config.get_llm_config()
        api_key = llm_config.get("api_key", "")
        if not api_key:
            return {"success": False, "message": "请先配置API Key"}
        
        # 强制重新加载LLM配置
        service.reload_llm()
        llm_provider = service.get_llm_provider()
        
        from blog_writer.llm.base import Message
        test_messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Reply with: Connection test successful")
        ]
        
        response = await llm_provider.chat(test_messages)
        return {
            "success": True,
            "message": "LLM connection successful",
            "response": response.content[:100],
            "tokens_used": response.usage.get("total_tokens", 0) if isinstance(response.usage, dict) else getattr(response.usage, 'total_tokens', 0) if response.usage else 0
        }
    except Exception as e:
        return {"success": False, "message": f"Connection failed: {str(e)}"}


def _sso_flags(cfg: Dict[str, Any]) -> Tuple[bool, bool]:
    """返回 (sso_enabled, allow_local_fallback)。"""
    security = cfg.get("security") or {}
    sso = security.get("sso") or cfg.get("sso") or {}
    return bool(sso.get("enabled")), bool(sso.get("allow_local_fallback", False))


def _sanitize_config_update(updates: Dict[str, Any]) -> Dict[str, Any]:
    """清理配置更新中的敏感数据（递归）。"""
    sensitive_keys = {
        "password",
        "admin_password_hash",
        "api_key",
        "secret",
        "token",
        "client_secret",
        "api_token",
        "callback_secret",
    }

    def _clean(obj: Any) -> Any:
        if isinstance(obj, dict):
            out: Dict[str, Any] = {}
            for key, value in obj.items():
                kl = str(key).lower()
                if kl in sensitive_keys:
                    if value and isinstance(value, str) and "****" not in value:
                        out[key] = value
                    # 空串 / 掩码：跳过，避免误清空或写入占位符
                else:
                    out[key] = _clean(value)
            return out
        if isinstance(obj, list):
            return [_clean(x) for x in obj]
        return obj

    return _clean(updates)
