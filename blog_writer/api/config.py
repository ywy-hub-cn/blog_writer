from typing import Any, Dict

from fastapi import APIRouter

from blog_writer.service_manager import get_config, get_service

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
async def get_config_endpoint():
    return get_config().get_all()


@router.put("")
async def update_config(updates: Dict[str, Any]):
    config = get_config()
    config.update(updates)
    service = get_service()
    service.reload_llm()
    return {"status": "updated", "config": config.get_all()}


@router.get("/llm")
async def get_llm_config():
    config = get_config()
    llm_config = config.get_llm_config()
    safe_config = llm_config.copy()
    if "api_key" in safe_config and safe_config["api_key"]:
        safe_config["api_key"] = safe_config["api_key"][:8] + "..."
    return safe_config


@router.put("/llm")
async def update_llm_config(updates: Dict[str, Any]):
    config = get_config()
    for key, value in updates.items():
        config.set(f"llm.{key}", value)
    service = get_service()
    service.reload_llm()
    return {"status": "updated", "llm": config.get_llm_config()}


@router.get("/workflow")
async def get_workflow_config():
    return get_config().get_workflow_config()


@router.put("/workflow")
async def update_workflow_config(updates: Dict[str, Any]):
    config = get_config()
    for key, value in updates.items():
        config.set(f"workflow.{key}", value)
    return {"status": "updated", "workflow": config.get_workflow_config()}


@router.get("/stats")
async def get_system_stats():
    service = get_service()
    
    tasks = list(service.get_all_tasks().values())
    total_tokens = sum(
        r.get("token_usage", {}).get("total_tokens_used", 0)
        for task in tasks
        for r in task.get("results", [])
    )
    
    llm_stats = service.get_llm_stats() if service.has_llm_provider() else {"total_tokens_used": 0, "total_calls": 0}
    
    return {
        "total_tasks": len(tasks),
        "completed_tasks": len([t for t in tasks if t["status"] == "completed"]),
        "running_tasks": len([t for t in tasks if t["status"] in ["running", "waiting_review"]]),
        "pending_reviews": len([t for t in tasks if t["status"] == "waiting_review"]),
        "nodes_count": len(service.list_nodes()),
        "llm_stats": llm_stats,
        "total_tokens_consumed": total_tokens,
        "tasks": [{
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
