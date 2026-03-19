"""DHA 实例 API - 多 DHA 群聊的智能体配置"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["dha"])

DHA_INSTANCES_PATH = os.getenv("DHA_INSTANCES_PATH", "./config/dha_instances.json")

from app.core.user_context import get_current_user_context


def _get_dha_instances_path() -> Path:
    """根据当前用户返回 DHA 配置文件路径，实现多用户隔离。

    - 用户级：data/users/{username}/config/dha_instances.json
    - 无上下文：回退到全局 DHA_INSTANCES_PATH
    """
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        return (user_ctx.config_dir / "dha_instances.json").resolve()
    path = Path(DHA_INSTANCES_PATH)
    return path if path.is_absolute() else path.resolve()


class DHACreate(BaseModel):
    """创建 DHA 实例请求"""
    name: str
    role: str = ""
    system_prompt: Optional[str] = None
    skill_ids: List[str] = []
    mcp_server_ids: List[str] = []
    is_leader: bool = False
    llm_provider_id: Optional[str] = None  # 该 DHA 使用的 LLM，空则用应用默认
    avatar_url: Optional[str] = None  # 头像（可选，前端可传 data URL 或远程地址）
    expert_id: Optional[str] = Field(default=None, description="兼容字段：expert_id")


class DHAUpdate(BaseModel):
    """更新 DHA 实例请求"""
    name: Optional[str] = None
    role: Optional[str] = None
    system_prompt: Optional[str] = None
    skill_ids: Optional[List[str]] = None
    mcp_server_ids: Optional[List[str]] = None
    is_leader: Optional[bool] = None
    llm_provider_id: Optional[str] = None
    avatar_url: Optional[str] = None
    expert_id: Optional[str] = Field(default=None, description="兼容字段：expert_id")


def _attach_expert_alias(instance: Dict[str, Any]) -> Dict[str, Any]:
    """在响应中附加 expert_* 兼容别名，不改变存储结构。"""
    out = dict(instance or {})
    did = out.get("dha_id")
    if did is not None:
        out["expert_id"] = did
    return out


def _ensure_config_dir() -> Path:
    path = _get_dha_instances_path()
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
    """获取 DHA 实例列表（按名称排序）"""
    instances = load_dha_instances()
    instances = sorted(instances, key=lambda d: (d.get("name") or "").strip())
    return {"status": "ok", "data": {"instances": [_attach_expert_alias(x) for x in instances]}}


@router.post("/dha/instances")
async def create_dha_instance(body: DHACreate):
    """创建 DHA 实例"""
    instances = load_dha_instances()
    dha_id = (body.expert_id or "").strip() or f"dha-{uuid.uuid4().hex[:8]}"
    new_instance = {
        "dha_id": dha_id,
        "name": body.name,
        "role": body.role or "",
        "system_prompt": body.system_prompt or "",
        "skill_ids": body.skill_ids or [],
        "mcp_server_ids": body.mcp_server_ids or [],
        "is_leader": body.is_leader,
        "llm_provider_id": body.llm_provider_id or "",
        "avatar_url": body.avatar_url or "",
    }
    instances.append(new_instance)
    save_dha_instances(instances)
    return {"status": "ok", "data": _attach_expert_alias(new_instance)}


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
    if body.llm_provider_id is not None:
        inst["llm_provider_id"] = body.llm_provider_id or ""
    if body.avatar_url is not None:
        inst["avatar_url"] = body.avatar_url or ""
    save_dha_instances(instances)
    return {"status": "ok", "data": _attach_expert_alias(inst)}


@router.delete("/dha/instances/{dha_id}")
async def delete_dha_instance(dha_id: str):
    """删除 DHA 实例"""
    instances = load_dha_instances()
    original = len(instances)
    instances = [d for d in instances if d.get("dha_id") != dha_id]
    if len(instances) == original:
        raise HTTPException(status_code=404, detail="DHA instance not found")
    save_dha_instances(instances)
    return {"status": "ok", "data": {"dha_id": dha_id, "expert_id": dha_id, "deleted": True}}


@router.get("/experts")
async def get_experts():
    """专家列表别名接口（兼容到 /dha/instances）。"""
    return await get_dha_instances()


@router.post("/experts")
async def create_expert(body: DHACreate):
    """创建专家别名接口（兼容到 /dha/instances）。"""
    return await create_dha_instance(body)


@router.put("/experts/{expert_id}")
async def update_expert(expert_id: str, body: DHAUpdate):
    """更新专家别名接口（兼容到 /dha/instances/{dha_id}）。"""
    return await update_dha_instance(expert_id, body)


@router.delete("/experts/{expert_id}")
async def delete_expert(expert_id: str):
    """删除专家别名接口（兼容到 /dha/instances/{dha_id}）。"""
    return await delete_dha_instance(expert_id)
