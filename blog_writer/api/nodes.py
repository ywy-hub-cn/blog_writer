"""公开节点API - 只读接口（需鉴权，供平台编排侧拉取节点元数据）"""
import json
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Depends

from blog_writer.service_manager import get_service
from blog_writer.node_utils import find_node_file, validate_node_schema
from blog_writer.api.deps import get_current_user

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("")
async def list_nodes(_user: dict = Depends(get_current_user)):
    service = get_service()
    nodes = service.list_nodes()
    return {"nodes": nodes}


@router.get("/{node_id}")
async def get_node(node_id: str, _user: dict = Depends(get_current_user)):
    service = get_service()
    nodes_dir = service.nodes_dir
    
    target_file = find_node_file(nodes_dir, node_id)
    if not target_file:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")
    
    with open(target_file, 'r', encoding='utf-8') as f:
        node_data = json.load(f)
    
    return node_data


@router.post("/{node_id}/validate")
async def validate_node(node_id: str, _user: dict = Depends(get_current_user)):
    service = get_service()
    nodes_dir = service.nodes_dir
    
    target_file = find_node_file(nodes_dir, node_id)
    if not target_file:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")
    
    with open(target_file, 'r', encoding='utf-8') as f:
        node_data = json.load(f)
    
    validation = validate_node_schema(node_data)
    
    return {
        "node_id": node_id,
        "file": target_file.name,
        "validation": validation,
        "warnings": _check_node_warnings(node_data)
    }


def _check_node_warnings(node: Dict[str, Any]) -> List[str]:
    warnings = []
    kind = node.get("kind", "")
    
    if kind == "agent_action":
        if not node.get("resources", {}).get("allow"):
            warnings.append("agent_action 类型应定义 resources.allow")
        if not node.get("actions"):
            warnings.append("agent_action 类型应至少有一个action")
    
    if kind == "llm_completion":
        if not node.get("resources", {}).get("prompt_template"):
            warnings.append("llm_completion 类型应定义 prompt_template")
    
    if kind == "pure_code":
        if not node.get("resources", {}).get("script"):
            warnings.append("pure_code 类型应定义 script")
    
    if kind == "human_review":
        if "options" not in node and "actions" not in node:
            warnings.append("human_review 类型应定义决策选项")
    
    actions = node.get("actions", [])
    for action in actions:
        if not action.get("workflow"):
            warnings.append(f"Action '{action.get('name', 'unknown')}' 未定义workflow")
    
    return warnings
