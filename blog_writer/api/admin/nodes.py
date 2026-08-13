"""管理员节点管理API - 需要鉴权"""
import json
import os
import re
import shutil
import zipfile
import tempfile
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from pydantic import BaseModel

from blog_writer.service_manager import get_service, get_config
from blog_writer.config_manager import NodeBackupManager
from blog_writer.api.deps import verify_admin_access
from blog_writer.node_utils import find_node_file, validate_node_schema as _base_validate
from blog_writer.node_utils import check_sensitive_content_in_node
from blog_writer.security.path_security import safe_basename

router = APIRouter(prefix="/nodes", tags=["admin-nodes"])


class NodeCreateRequest(BaseModel):
    id: str
    name: str
    seq: int
    kind: str
    exec_type: Optional[str] = None
    description: str = ""
    actions: List[Dict[str, Any]] = []
    checks: List[Dict[str, Any]] = []
    resources: Dict[str, Any] = {}
    constraints: Dict[str, Any] = {}
    params: Dict[str, Any] = {}
    llm_model: str = "default"


class NodeUpdateRequest(BaseModel):
    name: Optional[str] = None
    seq: Optional[int] = None
    kind: Optional[str] = None
    exec_type: Optional[str] = None
    description: Optional[str] = None
    actions: Optional[List[Dict[str, Any]]] = None
    checks: Optional[List[Dict[str, Any]]] = None
    resources: Optional[Dict[str, Any]] = None
    constraints: Optional[Dict[str, Any]] = None
    params: Optional[Dict[str, Any]] = None
    llm_model: Optional[str] = None


def get_backup_manager(nodes_dir: str, backup_dir: str) -> NodeBackupManager:
    config = get_config()
    max_versions = config.get("workflow.max_backup_versions", 10)
    return NodeBackupManager(nodes_dir, backup_dir, max_versions)


def validate_node_schema(node: Dict[str, Any]) -> Dict[str, Any]:
    result = _base_validate(node)
    
    if result["valid"] and "id" in node:
        existing_nodes = get_service().list_nodes()
        for existing in existing_nodes:
            if existing.get("id") == node["id"]:
                result["errors"].append(f"Node ID '{node['id']}' already exists")
                result["valid"] = False
                break
    
    return result


@router.get("")
async def list_admin_nodes(admin: dict = Depends(verify_admin_access)):
    service = get_service()
    nodes = service.list_nodes()
    return {"nodes": nodes, "total": len(nodes)}


@router.post("")
async def create_node(request: NodeCreateRequest, admin: dict = Depends(verify_admin_access)):
    node_data = request.model_dump()
    
    if not node_data.get("exec_type"):
        node_data["exec_type"] = node_data.get("kind", "agent_action")
    
    validation = validate_node_schema(node_data)
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=validation["errors"])
    
    # 敏感内容检测
    sensitive_warnings = check_sensitive_content_in_node(node_data)
    if sensitive_warnings:
        raise HTTPException(
            status_code=400,
            detail=f"节点数据包含疑似敏感信息: {'; '.join(sensitive_warnings)}"
        )
    
    service = get_service()
    nodes_dir = service.nodes_dir
    nodes_dir.mkdir(parents=True, exist_ok=True)
    
    seq = node_data["seq"]
    if not isinstance(seq, int) or seq < 0 or seq > 999:
        raise HTTPException(status_code=400, detail="seq 必须是 0～999 的整数")

    node_id = node_data["id"]
    if not isinstance(node_id, str) or "/" in node_id or "\\" in node_id or ".." in node_id:
        raise HTTPException(status_code=400, detail="节点 ID 非法")

    raw_suffix = node_id.split(".")[-1] if "." in node_id else node_id
    safe_suffix = safe_basename(f"{raw_suffix}.json", default="node.json")
    if not safe_suffix or not safe_suffix.endswith(".json"):
        raise HTTPException(status_code=400, detail="节点 ID 无法生成安全文件名")
    stem = safe_suffix[:-5]  # strip .json
    if not stem or not re.match(r"^[A-Za-z0-9_-]+$", stem):
        raise HTTPException(status_code=400, detail="节点 ID 后缀仅允许字母数字 _-")
    filename = f"S{seq:03d}-{stem}.json"
    
    filepath = (nodes_dir / filename).resolve()
    try:
        filepath.relative_to(nodes_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="节点路径越界")
    if filepath.exists():
        raise HTTPException(status_code=409, detail=f"Node file already exists: {filename}")
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(node_data, f, indent=2, ensure_ascii=False)
    
    return {"status": "created", "file": filename, "node": node_data}


@router.put("/{node_id}")
async def update_node(node_id: str, request: NodeUpdateRequest, admin: dict = Depends(verify_admin_access)):
    service = get_service()
    nodes_dir = service.nodes_dir
    
    target_file = find_node_file(nodes_dir, node_id)
    
    if not target_file:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")
    
    with open(target_file, 'r', encoding='utf-8') as f:
        existing = json.load(f)
    
    backup_mgr = get_backup_manager(str(nodes_dir), str(nodes_dir / ".backup"))
    backup_mgr.backup_node(node_id)
    
    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            existing[key] = value
    
    # 敏感内容检测（合并后的数据）
    sensitive_warnings = check_sensitive_content_in_node(existing)
    if sensitive_warnings:
        raise HTTPException(
            status_code=400,
            detail=f"节点数据包含疑似敏感信息: {'; '.join(sensitive_warnings)}"
        )
    
    with open(target_file, 'w', encoding='utf-8') as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    
    return {"status": "updated", "file": target_file.name, "node": existing}


@router.delete("/{node_id}")
async def delete_node(node_id: str, admin: dict = Depends(verify_admin_access)):
    service = get_service()
    nodes_dir = service.nodes_dir
    
    target_file = find_node_file(nodes_dir, node_id)
    
    if not target_file:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")
    
    backup_mgr = get_backup_manager(str(nodes_dir), str(nodes_dir / ".backup"))
    backup_mgr.backup_node(node_id)
    
    target_file.unlink()
    
    return {"status": "deleted", "file": target_file.name}


@router.post("/import")
async def import_nodes(files: List[UploadFile] = File(...), admin: dict = Depends(verify_admin_access)):
    service = get_service()
    nodes_dir = service.nodes_dir
    nodes_dir.mkdir(parents=True, exist_ok=True)
    
    imported = []
    errors = []
    
    for upload_file in files:
        try:
            content = await upload_file.read()
            node_data = json.loads(content.decode('utf-8'))
            
            validation = validate_node_schema(node_data)
            if not validation["valid"]:
                errors.append({
                    "file": upload_file.filename,
                    "errors": validation["errors"]
                })
                continue

            # 敏感内容检测
            sensitive_warnings = check_sensitive_content_in_node(node_data)
            if sensitive_warnings:
                errors.append({
                    "file": upload_file.filename,
                    "errors": [f"包含疑似敏感信息: {'; '.join(sensitive_warnings)}"]
                })
                continue

            safe_name = safe_basename(upload_file.filename, default="node.json")
            if not safe_name or not safe_name.endswith(".json"):
                errors.append({
                    "file": upload_file.filename,
                    "error": "非法文件名（仅允许 *.json basename）"
                })
                continue

            target_path = (nodes_dir / safe_name).resolve()
            try:
                target_path.relative_to(nodes_dir.resolve())
            except ValueError:
                errors.append({
                    "file": upload_file.filename,
                    "error": "路径越界"
                })
                continue

            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(node_data, f, indent=2, ensure_ascii=False)
            
            imported.append({
                "file": safe_name,
                "id": node_data.get("id"),
                "name": node_data.get("name")
            })
        except Exception as e:
            errors.append({
                "file": upload_file.filename,
                "error": str(e)
            })
    
    return {"imported": imported, "errors": errors}


@router.get("/export")
async def export_nodes(admin: dict = Depends(verify_admin_access)):
    service = get_service()
    nodes_dir = service.nodes_dir
    
    nodes = list(nodes_dir.glob("*.json"))
    if not nodes:
        raise HTTPException(status_code=404, detail="No nodes to export")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
        tmp_path = tmp.name
    
    with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for node_file in nodes:
            zf.write(node_file, node_file.name)
    
    with open(tmp_path, 'rb') as f:
        content = f.read()
    
    os.unlink(tmp_path)
    
    zip_b64 = base64.b64encode(content).decode()
    
    return {
        "filename": f"nodes_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
        "files": [n.name for n in nodes],
        "zip_base64": zip_b64
    }


@router.get("/{node_id}/backups")
async def list_node_backups(node_id: str, admin: dict = Depends(verify_admin_access)):
    service = get_service()
    nodes_dir = service.nodes_dir
    backup_dir = nodes_dir / ".backup"
    
    backup_mgr = get_backup_manager(str(nodes_dir), str(backup_dir))
    backups = backup_mgr.list_backups(node_id)
    
    return {"node_id": node_id, "backups": backups}


@router.post("/{node_id}/backups/{version}/restore")
async def restore_node_backup(node_id: str, version: str, admin: dict = Depends(verify_admin_access)):
    service = get_service()
    nodes_dir = service.nodes_dir
    backup_dir = nodes_dir / ".backup"
    
    backup_mgr = get_backup_manager(str(nodes_dir), str(backup_dir))
    success = backup_mgr.restore_backup(version)
    
    if success:
        return {"status": "restored", "version": version}
    else:
        raise HTTPException(status_code=404, detail=f"Backup not found: {version}")
