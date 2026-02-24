"""DHA 实例 API - 多 DHA 群聊的智能体配置"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["dha"])

DHA_INSTANCES_PATH = os.getenv("DHA_INSTANCES_PATH", "./config/dha_instances.json")


class DHACreate(BaseModel):
    """创建 DHA 实例请求"""
    name: str
    role: str = ""
    system_prompt: Optional[str] = None
    skill_ids: List[str] = []
    mcp_server_ids: List[str] = []
    is_leader: bool = False


class DHAUpdate(BaseModel):
    """更新 DHA 实例请求"""
    name: Optional[str] = None
    role: Optional[str] = None
    system_prompt: Optional[str] = None
    skill_ids: Optional[List[str]] = None
    mcp_server_ids: Optional[List[str]] = None
    is_leader: Optional[bool] = None


def _ensure_config_dir() -> Path:
    path = Path(DHA_INSTANCES_PATH).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_dha_instances() -> List[Dict[str, Any]]:
    """加载 DHA 实例配置"""
    path = _ensure_config_dir()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def save_dha_instances(instances: List[Dict[str, Any]]) -> None:
    """保存 DHA 实例配置"""
    path = _ensure_config_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(instances, f, ensure_ascii=False, indent=2)


@router.get("/dha/instances")
async def get_dha_instances():
    """获取 DHA 实例列表"""
    instances = load_dha_instances()
    return {"status": "ok", "data": {"instances": instances}}


@router.post("/dha/instances")
async def create_dha_instance(body: DHACreate):
    """创建 DHA 实例"""
    instances = load_dha_instances()
    dha_id = f"dha-{uuid.uuid4().hex[:8]}"
    new_instance = {
        "dha_id": dha_id,
        "name": body.name,
        "role": body.role or "",
        "system_prompt": body.system_prompt or "",
        "skill_ids": body.skill_ids or [],
        "mcp_server_ids": body.mcp_server_ids or [],
        "is_leader": body.is_leader,
    }
    instances.append(new_instance)
    save_dha_instances(instances)
    return {"status": "ok", "data": new_instance}


@router.put("/dha/instances/{dha_id}")
async def update_dha_instance(dha_id: str, body: DHAUpdate):
    """更新 DHA 实例"""
    instances = load_dha_instances()
    idx = next((i for i, d in enumerate(instances) if d.get("dha_id") == dha_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="DHA instance not found")
    inst = instances[idx]
    if body.name is not None:
        inst["name"] = body.name
    if body.role is not None:
        inst["role"] = body.role
    if body.system_prompt is not None:
        inst["system_prompt"] = body.system_prompt
    if body.skill_ids is not None:
        inst["skill_ids"] = body.skill_ids
    if body.mcp_server_ids is not None:
        inst["mcp_server_ids"] = body.mcp_server_ids
    if body.is_leader is not None:
        inst["is_leader"] = body.is_leader
    save_dha_instances(instances)
    return {"status": "ok", "data": inst}


@router.delete("/dha/instances/{dha_id}")
async def delete_dha_instance(dha_id: str):
    """删除 DHA 实例"""
    instances = load_dha_instances()
    original = len(instances)
    instances = [d for d in instances if d.get("dha_id") != dha_id]
    if len(instances) == original:
        raise HTTPException(status_code=404, detail="DHA instance not found")
    save_dha_instances(instances)
    return {"status": "ok", "data": {"dha_id": dha_id, "deleted": True}}
