"""Agent 实例 API - 多专家群聊的智能体配置"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from app.core.security import user_context_dependency
from app.core.user_context import get_current_user_context

router = APIRouter(tags=["agents"], dependencies=[Depends(user_context_dependency)])

def _get_dha_instances_path() -> Path:
    """根据当前用户返回 Agent 配置文件路径，实现多用户隔离。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise RuntimeError("缺少用户上下文，无法解析 Agent 配置路径。")
    return (user_ctx.config_dir / "dha_instances.json").resolve()


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
    agent_id: Optional[str] = Field(default=None, description="兼容字段：agent_id")
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
    agent_id: Optional[str] = Field(default=None, description="兼容字段：agent_id")
    expert_id: Optional[str] = Field(default=None, description="兼容字段：expert_id")


def _attach_expert_alias(instance: Dict[str, Any]) -> Dict[str, Any]:
    """在响应中附加 expert 别名。"""
    out = dict(instance or {})
    did = out.get("agent_id")
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
    agent_id = (body.agent_id or body.expert_id or "").strip() or f"agent-{uuid.uuid4().hex[:8]}"
    new_instance = {
        "agent_id": agent_id,
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


@router.put("/dha/instances/{agent_id}")
async def update_dha_instance(agent_id: str, body: DHAUpdate):
    """更新 DHA 实例"""
    instances = load_dha_instances()
    idx = next((i for i, d in enumerate(instances) if d.get("agent_id") == agent_id), None)
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


@router.delete("/dha/instances/{agent_id}")
async def delete_dha_instance(agent_id: str):
    """删除 DHA 实例"""
    instances = load_dha_instances()
    original = len(instances)
    instances = [d for d in instances if d.get("agent_id") != agent_id]
    if len(instances) == original:
        raise HTTPException(status_code=404, detail="DHA instance not found")
    save_dha_instances(instances)
    return {"status": "ok", "data": {"agent_id": agent_id, "expert_id": agent_id, "deleted": True}}


@router.get("/agents")
async def get_agents():
    """获取 Agent 列表（主入口）。"""
    return await get_dha_instances()


@router.post("/agents")
async def create_agent(body: DHACreate):
    """创建 Agent（主入口）。"""
    return await create_dha_instance(body)


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, body: DHAUpdate):
    """更新 Agent（主入口）。"""
    return await update_dha_instance(agent_id, body)


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """删除 Agent（主入口）。"""
    return await delete_dha_instance(agent_id)


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
    """更新专家别名接口（兼容到 /dha/instances/{agent_id}）。"""
    return await update_dha_instance(expert_id, body)


@router.delete("/experts/{expert_id}")
async def delete_expert(expert_id: str):
    """删除专家别名接口（兼容到 /dha/instances/{agent_id}）。"""
    return await delete_dha_instance(expert_id)
