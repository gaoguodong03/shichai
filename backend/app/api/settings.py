"""设置 API - MCP / Skills / 主持人提示词"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import yaml
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from app.core.user_context import get_current_user_context

router = APIRouter(tags=["settings"])

# 使用 mcp.manager 的全局单例，与 chat 共用
def get_mcp_manager():
    """获取 MCP Manager 实例（与 chat 共用同一实例）"""
    from app.mcp.manager import get_mcp_manager as _get_mcp
    return _get_mcp()

# 配置文件路径（当没有用户上下文时使用）
MCP_CONFIG_PATH = os.getenv("MCP_CONFIG_PATH", "./config/mcp_servers.json")
SKILLS_DIR = os.getenv("SKILLS_DIR", "./skills")
APP_SETTINGS_PATH = os.getenv("APP_SETTINGS_PATH", "./config/app_settings.json")


def _get_app_settings_path() -> Path:
    """根据当前用户返回 app_settings.json 路径，实现设置级隔离。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        return (user_ctx.config_dir / "app_settings.json").resolve()
    path = Path(APP_SETTINGS_PATH)
    return path if path.is_absolute() else path.resolve()


def _get_mcp_config_path() -> Path:
    """根据当前用户返回 mcp_servers.json 路径。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        return (user_ctx.config_dir / "mcp_servers.json").resolve()
    path = Path(MCP_CONFIG_PATH)
    return path if path.is_absolute() else path.resolve()


def _get_skills_dir() -> Path:
    """根据当前用户返回 skills 目录。

    当前设计为：优先使用用户私有 skills 目录（data/users/{username}/skills），
    若无上下文则回退到全局 SKILLS_DIR。
    """
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        return user_ctx.skills_dir.resolve()
    path = Path(SKILLS_DIR)
    return path if path.is_absolute() else path.resolve()


def _get_session_presets_path() -> Path:
    """根据当前用户返回 session_presets.json 路径。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        return (user_ctx.config_dir / "session_presets.json").resolve()
    # 兼容旧结构：默认读取 backend/config/session_presets.json
    return (Path(APP_SETTINGS_PATH).resolve().parent / "session_presets.json").resolve()
# ========== 应用设置 API（LLM 选择、系统提示词） ==========

class AppSettingsBody(BaseModel):
    """应用设置请求体"""
    default_llm: Optional[str] = None  # 如 qwen、jeniya
    llm_providers: Optional[Dict[str, Dict[str, Any]]] = None  # provider_id -> {base_url, model, api_key_env}

# 默认 llm_providers（无配置文件时使用）；jeniya 系共用 JENIYA_API_KEY + base_url，模型见 https://jeniya.top/pricing
_JENIYA_BASE = "http://jeniya.top/v1"
_JENIYA_KEY = "JENIYA_API_KEY"
_DEFAULT_LLM_PROVIDERS = {
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3-max",
        "api_key_env": "QWEN_API_KEY",
    },
    "jeniya": {
        "base_url": _JENIYA_BASE,
        "model": "gpt-4o",
        "api_key_env": _JENIYA_KEY,
    },
    "gemini": {
        "base_url": _JENIYA_BASE,
        "model": "gemini-3-pro-preview",
        "api_key_env": _JENIYA_KEY,
    },
    "claude": {
        "base_url": _JENIYA_BASE,
        "model": "claude-sonnet-4-6",
        "api_key_env": _JENIYA_KEY,
    },
    "glm": {
        "base_url": _JENIYA_BASE,
        "model": "glm-4.7",
        "api_key_env": _JENIYA_KEY,
    },
    "deepseek": {
        "base_url": _JENIYA_BASE,
        "model": "deepseek-chat",
        "api_key_env": _JENIYA_KEY,
    },
    "kimi": {
        "base_url": _JENIYA_BASE,
        "model": "moonshot-v1-128k",
        "api_key_env": _JENIYA_KEY,
    },
}

_DEFAULT_HOST_PROMPTS: Dict[str, str] = {
    # 方案 A：只保留两个字段，避免“首轮/非首轮、0/1 成员”等碎片化配置
    "host_master_prompt": (
        "你是群聊的主持人（调度器），你的职责只有三件事：\n"
        "1) 决定下一位发言人（next_speaker）；\n"
        "2) 为下一位专家生成本轮 next_prompt（必须自包含，能直接执行）；\n"
        "3) 当现有成员不适合/卡住/缺少专长或工具时，推荐新增成员 suggested_add_dha_ids（系统会自动邀请并继续跑）。\n\n"
        "【输入中你将看到】\n"
        "- 当前群聊参与者列表（含 dha_id/角色/技能）\n"
        "- 讨论目标与最近讨论内容\n"
        "- 可邀请专家列表（当需要补人时，从此列表选 suggested_add_dha_ids）\n\n"
        "【输出规则（必须遵守）】\n"
        "- 你必须输出一段简短主持词（1～4 句，说明下一步安排/为何补人）。\n"
        "- 然后在最后输出且仅输出一段 JSON（可放在 ```json 代码块中或直接输出 JSON）。\n"
        "- JSON 字段：\n"
        '  {"task_done": bool, "next_speaker": "user|dha_id", "announcement": str, "reason": str, "next_prompt": str, "suggested_add_dha_ids": [dha_id,...]}\n'
        "- next_speaker 若为某 dha_id：必须输出 next_prompt。\n"
        "- next_prompt 必须「自包含」：与根本任务相关的关键细节都要写清楚，不能依赖“前面某轮写过”。\n"
        "- 当你判断当前成员无法完成任务/明显不适合/连续两轮无进展/缺少专长或工具时：\n"
        "  - 在 JSON 输出 suggested_add_dha_ids（按优先级排序，不设上限：只要可能有帮助都列出来）。\n"
        '  - 并把 next_speaker 设为 "user"（系统会自动邀请这些成员加入并继续调度执行）。\n'
    ),
    "host_zero_member_policy": (
        "当前群聊 0 成员。你的目标是先组队：从可选专家列表中推荐尽可能合适的专家加入讨论（不设上限，按优先级排序）。\n"
        "输出要求：\n"
        "- 先用 1～4 句回复用户：说明你将邀请哪些专家以及理由。\n"
        "- 最后一段输出 JSON：必须包含 suggested_add_dha_ids（从可选专家列表选，不设上限）。\n"
        "系统会自动邀请并继续调度执行。"
    ),
}


def _normalize_host_prompts(hp: Dict[str, Any]) -> Dict[str, str]:
    """将历史的 host_prompts 结构迁移/归一为方案 A 的两字段结构。"""
    base = dict(_DEFAULT_HOST_PROMPTS)
    if not isinstance(hp, dict):
        return base
    # 新字段优先
    if isinstance(hp.get("host_master_prompt"), str) and hp.get("host_master_prompt").strip():
        base["host_master_prompt"] = hp["host_master_prompt"]
    else:
        # 迁移：保留旧 next_prompt 规则（若存在）以减少用户已调优内容丢失
        legacy_rules = hp.get("host_next_prompt_rules")
        if isinstance(legacy_rules, str) and legacy_rules.strip():
            base["host_master_prompt"] = base["host_master_prompt"].rstrip() + "\n\n【补充规则（来自旧配置）】\n" + legacy_rules.strip()
    if isinstance(hp.get("host_zero_member_policy"), str) and hp.get("host_zero_member_policy").strip():
        base["host_zero_member_policy"] = hp["host_zero_member_policy"]
    else:
        # 迁移：若旧 0 成员 user 模板存在，则附加到 policy，减少迁移损失
        legacy_zero = hp.get("host_zero_member_user_template")
        if isinstance(legacy_zero, str) and legacy_zero.strip():
            base["host_zero_member_policy"] = base["host_zero_member_policy"].rstrip() + "\n\n【补充模板（来自旧配置）】\n" + legacy_zero.strip()
    return base

def load_app_settings() -> Dict[str, Any]:
    """加载应用设置；合并默认 provider，保证新增的模型在未保存前也可用"""
    path = _get_app_settings_path()
    # 说明：历史上支持过 system_prompt（全局系统提示词），现已废弃
    data = {
        "default_llm": "qwen",
        "llm_providers": dict(_DEFAULT_LLM_PROVIDERS),
        # 主持人提示词（群聊主持调度用），默认使用 group_chat.py 的历史硬编码内容
        "host_prompts": dict(_DEFAULT_HOST_PROMPTS),
    }
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict) and "system_prompt" in loaded:
                    loaded = dict(loaded)
                    loaded.pop("system_prompt", None)
                # 合并 host_prompts，保证新增字段不会因为旧配置缺失而丢失
                if isinstance(loaded, dict):
                    hp = loaded.get("host_prompts")
                    if isinstance(hp, dict):
                        loaded = dict(loaded)
                        loaded["host_prompts"] = _normalize_host_prompts(hp)
                data.update(loaded)
                providers = data.get("llm_providers") or {}
                for k, v in _DEFAULT_LLM_PROVIDERS.items():
                    if k not in providers:
                        providers[k] = v
                data["llm_providers"] = providers
                return data
        except Exception:
            pass
    return data


class HostPromptsBody(BaseModel):
    """主持人提示词（群聊调度用）"""

    host_master_prompt: Optional[str] = None
    host_zero_member_policy: Optional[str] = None


@router.get("/settings/host-prompts")
async def get_host_prompts():
    data = load_app_settings()
    hp = data.get("host_prompts") or {}
    payload = _normalize_host_prompts(hp if isinstance(hp, dict) else {})
    return {"status": "ok", "data": payload}


@router.put("/settings/host-prompts")
async def update_host_prompts(body: HostPromptsBody):
    incoming = body.model_dump(exclude_none=True)
    current = load_app_settings()
    hp = current.get("host_prompts") if isinstance(current.get("host_prompts"), dict) else {}
    merged = _normalize_host_prompts(hp if isinstance(hp, dict) else {})
    for k in ("host_master_prompt", "host_zero_member_policy"):
        if k in incoming:
            merged[k] = incoming[k] or ""
    save_app_settings({"host_prompts": merged})
    return {"status": "ok", "data": merged}


@router.get("/settings/host-prompts/defaults")
async def get_host_prompts_defaults():
    """返回内置默认主持人提示词（不读配置文件）。"""
    return {"status": "ok", "data": dict(_DEFAULT_HOST_PROMPTS)}


@router.post("/settings/host-prompts/reset")
async def reset_host_prompts():
    """将主持人提示词恢复为内置默认值。"""
    save_app_settings({"host_prompts": dict(_DEFAULT_HOST_PROMPTS)})
    return {"status": "ok", "data": dict(_DEFAULT_HOST_PROMPTS)}


@router.get("/settings/session-presets")
async def get_session_presets():
    """读取会话快捷预设（用于前端快捷按钮），兼容历史字段 expert_ids。"""
    path = _get_session_presets_path()
    presets: List[Dict[str, Any]] = []
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    pid = str(item.get("id") or "").strip()
                    name = str(item.get("name") or "").strip()
                    dha_ids = item.get("dha_ids")
                    if not isinstance(dha_ids, list) or not dha_ids:
                        dha_ids = item.get("expert_ids")
                    if not isinstance(dha_ids, list):
                        dha_ids = []
                    normalized_ids = [str(x).strip() for x in dha_ids if str(x).strip()]
                    if not pid or not name or not normalized_ids:
                        continue
                    presets.append(
                        {
                            "id": pid,
                            "name": name,
                            "dha_ids": normalized_ids,
                            "description": str(item.get("description") or ""),
                            "discussion_goal_example": str(item.get("discussion_goal_example") or ""),
                        }
                    )
        except Exception:
            presets = []
    return {"status": "ok", "data": {"presets": presets}}

def save_app_settings(data: Dict[str, Any]):
    """保存应用设置"""
    path = _get_app_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_app_settings()
    patch = {k: v for k, v in data.items() if v is not None}

    # llm_providers 需要“保留密钥”的合并语义：
    # - GET 返回会隐藏 api_key，前端通常不会回传；若直接覆盖会导致已保存的 key 被清空。
    # - 支持通过传入 api_key 显式更新；传入空字符串表示删除。
    if "llm_providers" in patch and isinstance(patch["llm_providers"], dict):
        # 以现有配置为底，增量覆盖 incoming，避免只传部分 provider 时丢失其他项
        existing = (current.get("llm_providers") or {}) if isinstance(current.get("llm_providers"), dict) else {}
        merged: Dict[str, Dict[str, Any]] = {
            pid: (dict(meta) if isinstance(meta, dict) else {}) for pid, meta in (existing or {}).items()
        }
        incoming = patch["llm_providers"]
        for pid, meta in incoming.items():
            base: Dict[str, Any] = dict(existing.get(pid) or {})
            if isinstance(meta, dict):
                base.update(meta)
                if "api_key" not in meta and "api_key" in existing.get(pid, {}):
                    # 前端未传 api_key 时，保留旧值
                    base["api_key"] = existing[pid].get("api_key")
                if isinstance(meta.get("api_key"), str) and meta.get("api_key") == "":
                    # 显式清空
                    base.pop("api_key", None)
            merged[pid] = base
        patch["llm_providers"] = merged

    current.update(patch)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

@router.get("/settings/app")
async def get_app_settings():
    """获取应用设置（LLM 选择、系统提示词）"""
    # 出于安全考虑：不把 api_key 明文返回给前端，只返回是否已设置
    data = load_app_settings()
    safe = dict(data)
    providers = safe.get("llm_providers") or {}
    if isinstance(providers, dict):
        safe_providers: Dict[str, Dict[str, Any]] = {}
        for pid, meta in providers.items():
            m = dict(meta or {}) if isinstance(meta, dict) else {}
            api_key = (m.get("api_key") or "").strip()
            if api_key:
                m["api_key_set"] = True
            else:
                m["api_key_set"] = False
            m.pop("api_key", None)
            safe_providers[pid] = m
        safe["llm_providers"] = safe_providers
    return {"status": "ok", "data": safe}

@router.put("/settings/app")
async def update_app_settings(body: AppSettingsBody):
    """更新应用设置"""
    save_app_settings(body.model_dump(exclude_none=True))
    return {"status": "ok", "data": load_app_settings()}


# ========== MCP 配置 API ==========

class MCPTransport(BaseModel):
    """MCP 传输配置"""
    type: str  # stdio, sse, http
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    base_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    env: Optional[Dict[str, str]] = None

class MCPServerCreate(BaseModel):
    """创建 MCP Server 请求"""
    name: str
    enabled: bool = True
    transport: MCPTransport
    metadata: Optional[Dict[str, Any]] = None

class MCPServerUpdate(BaseModel):
    """更新 MCP Server 请求"""
    name: Optional[str] = None
    enabled: Optional[bool] = None
    transport: Optional[MCPTransport] = None
    metadata: Optional[Dict[str, Any]] = None

def load_mcp_config() -> List[Dict[str, Any]]:
    """加载 MCP 配置"""
    config_path = _get_mcp_config_path()
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_mcp_config(servers: List[Dict[str, Any]]):
    """保存 MCP 配置"""
    config_path = _get_mcp_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(servers, f, ensure_ascii=False, indent=2)

@router.get("/settings/mcp")
async def get_mcp_servers():
    """获取 MCP Server 列表"""
    servers = load_mcp_config()
    mcp_manager = get_mcp_manager()
    
    # 确保 MCP Manager 已加载配置和初始化
    try:
        await mcp_manager.load_config()
        # 对每个已启用且尚未连接的 server 尝试连接（包括 HTTP 远程 server）
        for config in mcp_manager.server_configs:
            server_id = config.get("id", "")
            if not config.get("enabled", True):
                continue
            # lazy server：只在真正需要工具时连接，避免在状态页被提前拉起
            if config.get("lazy", False):
                continue
            if server_id in mcp_manager.sessions:
                continue
            try:
                await mcp_manager.connect_server(server_id, config)
            except asyncio.CancelledError:
                # 请求被取消（如前端断开、超时），不再继续连接，直接返回当前状态
                break
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"MCP Server {server_id} 连接失败: {e}")
    except asyncio.CancelledError:
        pass  # 被取消时不再抛错，下面会按当前 sessions 返回列表
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"MCP 配置加载失败: {e}")
    
    # 统计每个 server 的工具数量
    server_tool_counts = {}
    for tool_name, tool in mcp_manager.tools.items():
        # 工具名称格式: server_id_tool_name
        if '_' in tool_name:
            server_id = tool_name.split('_', 1)[0]
            server_tool_counts[server_id] = server_tool_counts.get(server_id, 0) + 1
    
    # 检查连接状态
    server_status = {}
    for server_id in mcp_manager.sessions.keys():
        server_status[server_id] = "connected"
    
    # 添加状态信息
    result = []
    for server in servers:
        server_id = server.get("id", "")
        tool_count = server_tool_counts.get(server_id, 0)
        status = server_status.get(server_id, "disconnected")
        
        # 如果启用了但未连接，可能是连接失败
        if server.get("enabled", False) and status == "disconnected":
            status = "disconnected"
        
        server_info = {
            "id": server_id,
            "name": server.get("name", ""),
            "enabled": server.get("enabled", False),
            "tool_count": tool_count,
            "status": status,
            "transport": server.get("transport", {}),
            "metadata": server.get("metadata", {})
        }
        result.append(server_info)
    
    return {
        "status": "ok",
        "data": {
            "servers": result
        }
    }

@router.post("/settings/mcp")
async def create_mcp_server(server: MCPServerCreate):
    """创建 MCP Server"""
    servers = load_mcp_config()
    
    # 生成 ID
    server_id = f"mcp-{uuid.uuid4().hex[:8]}"
    
    new_server = {
        "id": server_id,
        "name": server.name,
        "enabled": server.enabled,
        "transport": server.transport.dict(exclude_none=True),
        "metadata": server.metadata or {}
    }
    
    servers.append(new_server)
    save_mcp_config(servers)
    
    return {
        "status": "ok",
        "data": new_server
    }

@router.put("/settings/mcp/{server_id}")
async def update_mcp_server(server_id: str, server_update: MCPServerUpdate):
    """更新 MCP Server"""
    servers = load_mcp_config()
    
    # 查找服务器
    server_index = None
    for i, s in enumerate(servers):
        if s.get("id") == server_id:
            server_index = i
            break
    
    if server_index is None:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    
    # 更新字段
    server = servers[server_index]
    if server_update.name is not None:
        server["name"] = server_update.name
    if server_update.enabled is not None:
        server["enabled"] = server_update.enabled
    if server_update.transport is not None:
        server["transport"] = server_update.transport.dict(exclude_none=True)
    if server_update.metadata is not None:
        server["metadata"] = server_update.metadata
    
    save_mcp_config(servers)
    
    return {
        "status": "ok",
        "data": server
    }

@router.delete("/settings/mcp/{server_id}")
async def delete_mcp_server(server_id: str):
    """删除 MCP Server"""
    servers = load_mcp_config()
    
    # 查找并删除
    original_count = len(servers)
    servers = [s for s in servers if s.get("id") != server_id]
    
    if len(servers) == original_count:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    
    save_mcp_config(servers)
    
    return {
        "status": "ok",
        "data": {
            "id": server_id,
            "deleted": True
        }
    }

@router.post("/settings/mcp/{server_id}/enable")
async def enable_mcp_server(server_id: str):
    """启用 MCP Server"""
    servers = load_mcp_config()
    
    for server in servers:
        if server.get("id") == server_id:
            server["enabled"] = True
            save_mcp_config(servers)
            return {
                "status": "ok",
                "data": server
            }
    
    raise HTTPException(status_code=404, detail="MCP Server not found")

@router.post("/settings/mcp/{server_id}/disable")
async def disable_mcp_server(server_id: str):
    """禁用 MCP Server"""
    servers = load_mcp_config()
    
    for server in servers:
        if server.get("id") == server_id:
            server["enabled"] = False
            save_mcp_config(servers)
            return {
                "status": "ok",
                "data": server
            }
    
    raise HTTPException(status_code=404, detail="MCP Server not found")

@router.post("/settings/mcp/{server_id}/test")
async def test_mcp_server(server_id: str):
    """测试 MCP Server 连接（真实调用 MCP Manager）"""
    servers = load_mcp_config()

    # 查找服务器配置
    server = next((s for s in servers if s.get("id") == server_id), None)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP Server not found")

    mcp_manager = get_mcp_manager()

    import time

    start = time.perf_counter()
    try:
        # 确保已加载配置
        await mcp_manager.load_config()
        # 如果当前没有 session，则尝试连接
        if server_id not in mcp_manager.sessions:
            ok = await mcp_manager.connect_server(server_id, server)
            if not ok:
                elapsed = int((time.perf_counter() - start) * 1000)
                return {
                    "status": "ok",
                    "data": {
                        "connected": False,
                        "response_time": elapsed,
                        "error": f"Failed to connect to MCP server {server_id}",
                    },
                }
        # 调用 list_tools 做一次简单健康检查
        session = mcp_manager.sessions.get(server_id)
        if not session:
            elapsed = int((time.perf_counter() - start) * 1000)
            return {
                "status": "ok",
                "data": {
                    "connected": False,
                    "response_time": elapsed,
                    "error": f"No active session for MCP server {server_id}",
                },
            }
        try:
            tools_result = await session.list_tools()
            tool_count = len(getattr(tools_result, "tools", []) or [])
            elapsed = int((time.perf_counter() - start) * 1000)
            return {
                "status": "ok",
                "data": {
                    "connected": True,
                    "response_time": elapsed,
                    "tool_count": tool_count,
                    "error": None,
                },
            }
        except Exception as e:
            elapsed = int((time.perf_counter() - start) * 1000)
            return {
                "status": "ok",
                "data": {
                    "connected": False,
                    "response_time": elapsed,
                    "error": f"list_tools error: {e}",
                },
            }
    except asyncio.CancelledError:
        raise
    except Exception as e:
        elapsed = int((time.perf_counter() - start) * 1000)
        return {
            "status": "ok",
            "data": {
                "connected": False,
                "response_time": elapsed,
                "error": f"Unexpected error: {e}",
            },
        }

@router.get("/settings/mcp/{server_id}/tools")
async def get_mcp_server_tools(server_id: str):
    """获取 MCP Server 工具列表（含 input_schema），用于前端动态渲染参数表单"""
    mcp_manager = get_mcp_manager()
    await mcp_manager.load_config()

    # 找到对应 server 配置
    config = next((c for c in mcp_manager.server_configs if c.get("id") == server_id), None)
    if not config:
        raise HTTPException(status_code=404, detail="MCP Server not found")

    # 确保已连接
    if server_id not in mcp_manager.sessions:
        ok = await mcp_manager.connect_server(server_id, config)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to connect MCP server {server_id}")

    session = mcp_manager.sessions.get(server_id)
    if not session:
        raise HTTPException(status_code=500, detail=f"No active session for MCP server {server_id}")

    try:
        tools_result = await session.list_tools()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_tools error: {e}")

    tools_payload = []
    for t in getattr(tools_result, "tools", []) or []:
        # mcp Tool 对象通常有 name / description / inputSchema
        input_schema = getattr(t, "inputSchema", None)
        # 尽量转换为原生 dict 以便前端消费
        if hasattr(input_schema, "model_dump"):
            input_schema = input_schema.model_dump()
        tools_payload.append(
            {
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", "") or "",
                "input_schema": input_schema or {},
            }
        )

    return {
        "status": "ok",
        "data": {
            "tools": tools_payload,
        },
    }


class MCPToolCallBody(BaseModel):
    """调用 MCP 工具的请求体（用于前端测试）"""

    arguments: Dict[str, Any] = {}


@router.post("/settings/mcp/{server_id}/tools/{tool_name}/call")
async def call_mcp_tool(server_id: str, tool_name: str, body: MCPToolCallBody):
    """调用指定 MCP Server 上的某个工具，用于前端测试面板"""
    mcp_manager = get_mcp_manager()
    await mcp_manager.load_config()

    config = next((c for c in mcp_manager.server_configs if c.get("id") == server_id), None)
    if not config:
        raise HTTPException(status_code=404, detail="MCP Server not found")

    # 确保连接
    if server_id not in mcp_manager.sessions:
        ok = await mcp_manager.connect_server(server_id, config)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to connect MCP server {server_id}")

    session = mcp_manager.sessions.get(server_id)
    if not session:
        raise HTTPException(status_code=500, detail=f"No active session for MCP server {server_id}")

    try:
        result = await session.call_tool(tool_name, body.arguments or {})
    except asyncio.CancelledError:
        raise
    except Exception as e:
        # 把错误直接返回给前端，便于调试
        return {
            "status": "ok",
            "data": {
                "ok": False,
                "error": str(e),
                "raw": None,
            },
        }

    # 将 MCP ToolResult 内容序列化为易读结构
    blocks = []
    for block in getattr(result, "content", []) or []:
        # 文本内容
        if hasattr(block, "text"):
            blocks.append({"type": "text", "text": block.text})
        else:
            # 兜底：直接转字符串
            blocks.append({"type": "unknown", "raw": str(block)})

    return {
        "status": "ok",
        "data": {
            "ok": True,
            "blocks": blocks,
        },
    }


class MCPSandboxCallBody(BaseModel):
    """沙箱调用：不关心具体工具名，只在该 MCP Server 上调用第一个工具"""

    arguments: Dict[str, Any] = {}


@router.post("/settings/mcp/{server_id}/sandbox-call")
async def call_mcp_sandbox(server_id: str, body: MCPSandboxCallBody):
    """
    沙箱调用：在指定 MCP Server 上选择第一个可用工具进行一次调用。
    前端只需提供 arguments，不需要关心工具名。
    """
    mcp_manager = get_mcp_manager()
    await mcp_manager.load_config()

    config = next((c for c in mcp_manager.server_configs if c.get("id") == server_id), None)
    if not config:
        raise HTTPException(status_code=404, detail="MCP Server not found")

    # 确保连接
    if server_id not in mcp_manager.sessions:
        ok = await mcp_manager.connect_server(server_id, config)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to connect MCP server {server_id}")

    session = mcp_manager.sessions.get(server_id)
    if not session:
        raise HTTPException(status_code=500, detail=f"No active session for MCP server {server_id}")

    # 获取工具列表，选择第一个工具名
    try:
        tools_result = await session.list_tools()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_tools error: {e}")

    tools = getattr(tools_result, "tools", []) or []
    if not tools:
        raise HTTPException(status_code=500, detail=f"MCP server {server_id} has no tools")

    tool_name = getattr(tools[0], "name", None)
    if not tool_name:
        raise HTTPException(status_code=500, detail=f"First tool of MCP server {server_id} has no name")

    # 调用第一个工具
    try:
        result = await session.call_tool(tool_name, body.arguments or {})
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return {
            "status": "ok",
            "data": {
                "ok": False,
                "error": str(e),
                "raw": None,
            },
        }

    blocks = []
    for block in getattr(result, "content", []) or []:
        if hasattr(block, "text"):
            blocks.append({"type": "text", "text": block.text})
        else:
            blocks.append({"type": "unknown", "raw": str(block)})

    return {
        "status": "ok",
        "data": {
            "ok": True,
            "tool_name": tool_name,
            "blocks": blocks,
        },
    }

# ========== Skills 配置 API ==========

class SkillCreate(BaseModel):
    """创建 Skill 请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    source: str = "local"  # local or git
    path: Optional[str] = None
    url: Optional[str] = None
    enabled: bool = True
    write_mode: str = "readonly"  # readonly or workspace_all

class SkillUpdate(BaseModel):
    """更新 Skill 请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    enabled: Optional[bool] = None
    body: Optional[str] = None  # SKILL.md frontmatter 之后的正文
    mcp_server_ids: Optional[List[str]] = None  # 该 skill 依赖的 MCP server id 列表，空表示只用内置工具
    write_mode: Optional[str] = None  # readonly or workspace_all


_GIT_URL_RE = re.compile(r"^(https://[^\s]+|git@[^\s:]+:[^\s]+)$")


def _validate_skill_write_mode(write_mode: str) -> str:
    mode = (write_mode or "readonly").strip()
    if mode not in {"readonly", "workspace_all"}:
        raise HTTPException(status_code=400, detail="Invalid write_mode, must be readonly or workspace_all")
    return mode


def _validate_git_url(url: Optional[str]) -> str:
    raw = (url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="url is required when source=git")
    if ".." in raw:
        raise HTTPException(status_code=400, detail="Invalid git url")
    if not _GIT_URL_RE.match(raw):
        raise HTTPException(status_code=400, detail="Only https:// or git@ URLs are allowed")
    return raw


def _normalize_git_import_source(url: str) -> tuple[str, str]:
    """将导入 URL 归一化为 (clone_url, subdir)。

    支持：
    - https://github.com/owner/repo(.git)
    - https://github.com/owner/repo/tree/<branch>/<subdir>
    - git@github.com:owner/repo(.git)
    """
    raw = _validate_git_url(url)
    if raw.startswith("git@"):
        return (raw if raw.endswith(".git") else f"{raw}.git", "")
    p = urlparse(raw)
    path_parts = [x for x in p.path.split("/") if x]
    if len(path_parts) >= 2 and path_parts[2:3] == ["tree"]:
        owner, repo = path_parts[0], path_parts[1]
        subdir_parts = path_parts[4:]  # tree/<branch>/<subdir...>
        subdir = "/".join(subdir_parts).strip("/")
        if ".." in subdir:
            raise HTTPException(status_code=400, detail="Invalid git tree path")
        clone_url = f"{p.scheme}://{p.netloc}/{owner}/{repo}.git"
        return clone_url, subdir
    return (raw if raw.endswith(".git") else f"{raw}.git", "")


def _suggest_skill_id_from_git_url(url: str) -> str:
    """根据 git 导入 URL 生成更可管理的默认 skill_id（目录名）。"""
    clone_url, subdir = _normalize_git_import_source(url)
    # git@github.com:owner/repo.git
    if clone_url.startswith("git@"):
        repo_part = clone_url.split(":", 1)[1] if ":" in clone_url else clone_url
    else:
        p = urlparse(clone_url)
        repo_part = p.path.strip("/")
    parts = [x for x in repo_part.split("/") if x]
    repo_name = parts[-1] if parts else "skill"
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    # tree 子目录导入时，把最后一级目录拼到 id，避免同仓库不同子 skill 冲突
    tail = ""
    if subdir:
        sub_parts = [x for x in subdir.split("/") if x]
        if sub_parts:
            tail = sub_parts[-1]
    base = f"{repo_name}-{tail}" if tail else repo_name
    return _slugify(base)


def _refresh_skills_loader():
    """刷新全局 SkillsLoader 缓存，确保新导入技能立即可见。"""
    from app.skills.loader import get_skills_loader

    loader = get_skills_loader()
    loader.skills_dir = _get_skills_dir()
    loader.load_all_skills()


def _parse_frontmatter_lenient(frontmatter_text: str) -> Dict[str, Any]:
    """解析 frontmatter：优先 YAML，失败时回退到宽容 key:value 解析。"""
    try:
        parsed = yaml.safe_load(frontmatter_text) or {}
        if isinstance(parsed, dict):
            return parsed
        return {}
    except Exception:
        result: Dict[str, Any] = {}
        for raw in (frontmatter_text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            key = (k or "").strip()
            if not key:
                continue
            val = (v or "").strip()
            # 兼容最常见 frontmatter 值类型
            if val.lower() == "true":
                result[key] = True
            elif val.lower() == "false":
                result[key] = False
            else:
                result[key] = val.strip("'\"")
        return result


def _run_git(repo_dir: Path, args: List[str], timeout_sec: int = 120) -> None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env={**os.environ},
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=400,
            detail="Git command failed: git is not installed in runtime environment. Please install git in your container/image.",
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Git command failed: {e}")
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise HTTPException(status_code=400, detail=f"Git command failed: {msg}")


def _import_skill_from_git(skill_dir: Path, git_url: str) -> None:
    """将 skill 同步到 skill_dir。目录存在则 pull，不存在则 clone。"""
    timeout_sec = int(os.getenv("SKILL_GIT_TIMEOUT", "120"))
    if (skill_dir / ".git").is_dir():
        _run_git(skill_dir, ["fetch", "--all"], timeout_sec=timeout_sec)
        _run_git(skill_dir, ["pull", "--ff-only"], timeout_sec=timeout_sec)
    elif skill_dir.exists():
        raise HTTPException(status_code=400, detail="Skill directory exists but is not a git repository")
    else:
        parent = skill_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        _run_git(parent, ["clone", git_url, skill_dir.name], timeout_sec=timeout_sec)


def _import_skill_from_git_subdir(skill_dir: Path, git_url: str, subdir: str) -> None:
    """从 git 仓库的子目录导入 skill 内容到 skill_dir。"""
    timeout_sec = int(os.getenv("SKILL_GIT_TIMEOUT", "120"))
    with tempfile.TemporaryDirectory(prefix="skill-import-") as tmp:
        tmp_path = Path(tmp).resolve()
        _run_git(tmp_path, ["clone", git_url, "repo"], timeout_sec=timeout_sec)
        src_root = (tmp_path / "repo").resolve()
        source = (src_root / subdir).resolve() if subdir else src_root
        if not str(source).startswith(str(src_root)) or not source.is_dir():
            raise HTTPException(status_code=400, detail=f"Skill subdir not found: {subdir}")
        if not (source / "SKILL.md").is_file():
            raise HTTPException(status_code=400, detail="SKILL.md not found in imported path")
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        shutil.copytree(source, skill_dir)

def load_skills_config() -> List[Dict[str, Any]]:
    """加载 Skills 配置"""
    # 从 skills 目录读取
    skills_dir = _get_skills_dir()
    if not skills_dir.exists():
        return []
    
    skills = []
    for skill_dir in skills_dir.iterdir():
        if skill_dir.is_dir():
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                # 读取 SKILL.md 的 frontmatter
                content = skill_file.read_text(encoding='utf-8')
                if content.startswith('---'):
                    # 解析 frontmatter
                    parts = content.split('---', 2)
                    if len(parts) >= 3:
                        try:
                            frontmatter = _parse_frontmatter_lenient(parts[1])
                            skill_id = skill_dir.name
                            fm_mcp = frontmatter.get("mcp_server_ids")
                            mcp_ids = fm_mcp if isinstance(fm_mcp, list) else []
                            # 仅当 frontmatter 显式包含 mcp_server_ids 时返回，否则不包含（表示用默认/fallback）
                            item = {
                                "id": skill_id,
                                "name": frontmatter.get("name", skill_id),
                                "description": frontmatter.get("description", ""),
                                "enabled": frontmatter.get("enabled", True),
                                "source": frontmatter.get("source", "local"),
                                "path": str(skill_dir),
                                "write_mode": frontmatter.get("write_mode", "readonly"),
                            }
                            if frontmatter.get("url"):
                                item["url"] = frontmatter.get("url")
                            if "mcp_server_ids" in frontmatter:
                                item["mcp_server_ids"] = mcp_ids
                            skills.append(item)
                        except Exception:
                            pass
    
    skills.sort(key=lambda x: (x.get("name") or x.get("id") or "").strip())
    return skills

# 当 skill 的 frontmatter 未显式配置 mcp_server_ids 时使用的默认映射（向后兼容）
# 与 backend/config/mcp_servers.json 中的 id 对应
_SKILL_MCP_SERVERS_FALLBACK: Dict[str, List[str]] = {
    # 兜底仅使用当前保留的 5 个 MCP：linkup / exa / amap-maps / file-reader / playwright-mcp
    "wechat-article-writer": ["linkup", "exa", "file-reader"],
    "amap-maps": ["amap-maps"],
    "app-icon-generator": [],
    "cover-image": [],
    "article-illustrator": [],
    "blog-write": ["linkup", "exa", "file-reader"],
    "data-report": ["linkup", "exa", "file-reader"],
    "zhipu-web-search": [],
    "weather-service": [],
    "news-summary": ["linkup", "exa", "file-reader"],
    "article-review": ["file-reader"],
    "deep-research": ["linkup", "exa", "file-reader"],
    "web-research": ["linkup", "exa", "file-reader"],
    "doc-coauthoring": ["file-reader"],
    "docs-write": ["file-reader"],
    "xlsx": ["file-reader"],
    "math-assistant": [],
    "group-host": ["file-reader"],
    "url-fetch": ["file-reader"],
    "seminar-companion": [],
    "seminar-guide": [],
    "seminar-divergence": [],
    "seminar-research-progress": [],
    "browser-playwright": ["playwright-mcp"],
    "session-export": [],
    "default": [],
    "script-demo": [],
    "prompt-engineering-patterns": [],
}

def get_mcp_servers_for_skill(skill_id: str) -> List[str]:
    """根据 skill_id 返回其关联的 MCP server_id 列表。
    优先从 SKILL.md frontmatter 的 mcp_server_ids 读取（前端可配置）；
    若未配置则使用 _SKILL_MCP_SERVERS_FALLBACK。"""
    skills = load_skills_config()
    enabled_ids = {s.get("id") for s in load_mcp_config() if s.get("enabled", True)}
    s = next((x for x in skills if x.get("id") == skill_id), None)
    if s is not None and "mcp_server_ids" in s:
        return [x for x in (s.get("mcp_server_ids") or []) if x in enabled_ids]
    return [x for x in list(_SKILL_MCP_SERVERS_FALLBACK.get(skill_id, [])) if x in enabled_ids]


def get_write_mode_for_skill(skill_id: str) -> str:
    """返回 skill 的写入模式。未配置时默认为 readonly。"""
    _ = skill_id
    return "workspace_all"

@router.get("/settings/skills")
async def get_skills():
    """获取 Skills 列表"""
    skills = load_skills_config()
    
    return {
        "status": "ok",
        "data": {
            "skills": skills
        }
    }

def _slugify(name: str) -> str:
    """生成可作目录名的 slug"""
    s = re.sub(r"[^\w\s-]", "", name)
    s = re.sub(r"[-\s]+", "-", s).strip("-").lower()
    return s or "skill"


@router.post("/settings/skills")
async def create_skill(skill: SkillCreate):
    """创建 Skill：在 skills 目录下创建 <id>/SKILL.md"""
    base = _get_skills_dir()
    base.mkdir(parents=True, exist_ok=True)
    source = (skill.source or "local").strip().lower()
    if source not in {"local", "git"}:
        raise HTTPException(status_code=400, detail="source must be local or git")
    write_mode = "workspace_all"
    # local：仍要求 name；git：允许仅 url（name/description 从 SKILL.md 自动提取）
    if source == "local" and not (skill.name or "").strip():
        raise HTTPException(status_code=400, detail="name is required when source=local")
    if source == "git" and not (skill.name or "").strip():
        raw_id = _suggest_skill_id_from_git_url(skill.url or "")
    else:
        raw_id = _slugify((skill.name or "skill").strip())
    skill_id = raw_id
    if source == "local" or source == "git":
        idx = 0
        while (base / skill_id).exists():
            idx += 1
            skill_id = f"{raw_id}-{idx}"
    skill_dir = base / skill_id
    if source == "git":
        git_url, git_subdir = _normalize_git_import_source(skill.url or "")
        if git_subdir:
            _import_skill_from_git_subdir(skill_dir, git_url, git_subdir)
        else:
            _import_skill_from_git(skill_dir, git_url)
        fm, body = _read_skill_file(skill_dir)
        # 自动提取元数据：仅当请求未显式提供时才覆盖
        final_name = (skill.name or fm.get("name") or skill_dir.name or skill_id).strip()
        final_desc = skill.description if skill.description is not None else (fm.get("description") or "")
        fm["name"] = final_name
        fm["description"] = final_desc
        fm["enabled"] = skill.enabled
        fm["source"] = "git"
        fm["url"] = skill.url or git_url
        fm["write_mode"] = write_mode
        _write_skill_file(skill_dir, fm, body)
    else:
        skill_dir.mkdir(parents=True, exist_ok=True)
        body = "\n## 说明\n\n（待补充）\n"
        frontmatter = {
            "name": (skill.name or "").strip(),
            "description": skill.description or "",
            "enabled": skill.enabled,
            "source": "local",
            "write_mode": "workspace_all",
        }
        content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n" + body
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    _refresh_skills_loader()
    if source == "git":
        # 以 SKILL.md 的最终内容回填返回字段
        fm2, _body2 = _read_skill_file(skill_dir)
        ret_name = (fm2.get("name") or skill_id).strip()
        ret_desc = fm2.get("description") or ""
    else:
        ret_name = (skill.name or skill_id).strip()
        ret_desc = skill.description or ""
    new_skill = {
        "id": skill_id,
        "name": ret_name,
        "description": ret_desc,
        "enabled": skill.enabled,
        "source": source,
        "path": str(skill_dir),
        "url": skill.url,
        "write_mode": "workspace_all",
    }
    return {"status": "ok", "data": new_skill}

def _read_skill_file(skill_dir: Path) -> tuple[Dict, str]:
    """读取 SKILL.md，返回 (frontmatter_dict, body)"""
    path = skill_dir / "SKILL.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Skill not found")
    text = path.read_text(encoding="utf-8")
    if not text.strip().startswith("---"):
        return ({}, text)
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ({}, text)
    fm = _parse_frontmatter_lenient(parts[1])
    return (fm, parts[2].lstrip("\n"))


def _write_skill_file(skill_dir: Path, frontmatter: Dict, body: str):
    """写入 SKILL.md"""
    content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n" + body
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


@router.put("/settings/skills/{skill_id}")
async def update_skill(skill_id: str, skill_update: SkillUpdate):
    """更新 Skill：修改 SKILL.md 的 frontmatter 与/或正文 body"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    fm, body = _read_skill_file(skill_dir)
    if skill_update.name is not None:
        fm["name"] = skill_update.name
    if skill_update.description is not None:
        fm["description"] = skill_update.description
    if skill_update.enabled is not None:
        fm["enabled"] = skill_update.enabled
    if skill_update.mcp_server_ids is not None:
        fm["mcp_server_ids"] = skill_update.mcp_server_ids
    if skill_update.write_mode is not None:
        fm["write_mode"] = "workspace_all"
    if skill_update.source is not None:
        src = (skill_update.source or "").strip().lower()
        if src not in {"local", "git"}:
            raise HTTPException(status_code=400, detail="source must be local or git")
        fm["source"] = src
    if skill_update.url is not None:
        if fm.get("source", "local") == "git":
            fm["url"] = _validate_git_url(skill_update.url)
        else:
            fm["url"] = skill_update.url
    if skill_update.body is not None:
        body = skill_update.body
    _write_skill_file(skill_dir, fm, body)
    _refresh_skills_loader()
    return {"status": "ok", "data": {"id": skill_id, "updated": True}}

@router.delete("/settings/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """删除 Skill：删除对应目录"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    shutil.rmtree(skill_dir)
    _refresh_skills_loader()
    return {"status": "ok", "data": {"id": skill_id, "deleted": True}}

@router.post("/settings/skills/{skill_id}/enable")
async def enable_skill(skill_id: str):
    """启用 Skill"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    fm, body = _read_skill_file(skill_dir)
    fm["enabled"] = True
    _write_skill_file(skill_dir, fm, body)
    _refresh_skills_loader()
    return {"status": "ok", "data": {"id": skill_id, "enabled": True}}

@router.post("/settings/skills/{skill_id}/disable")
async def disable_skill(skill_id: str):
    """禁用 Skill"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    fm, body = _read_skill_file(skill_dir)
    fm["enabled"] = False
    _write_skill_file(skill_dir, fm, body)
    _refresh_skills_loader()
    return {"status": "ok", "data": {"id": skill_id, "enabled": False}}


@router.get("/settings/skills/{skill_id}/content")
async def get_skill_content(skill_id: str):
    """获取技能 SKILL.md 的完整内容（raw 全文）及 frontmatter 解析结果，用于详情页展示。"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    path = skill_dir / "SKILL.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Skill not found")
    raw = path.read_text(encoding="utf-8")
    fm, body = _read_skill_file(skill_dir)
    if "mcp_server_ids" in fm:
        mcp_ids = fm["mcp_server_ids"] if isinstance(fm["mcp_server_ids"], list) else []
    else:
        mcp_ids = get_mcp_servers_for_skill(skill_id)  # 未配置时返回 fallback，便于前端展示
    return {
        "status": "ok",
        "data": {
            "raw": raw,
            "name": fm.get("name", skill_id),
            "description": fm.get("description", ""),
            "enabled": fm.get("enabled", True),
            "source": fm.get("source", "local"),
            "url": fm.get("url"),
            "write_mode": fm.get("write_mode", "readonly"),
            "body": body,
            "mcp_server_ids": mcp_ids,
        },
    }


# ========== Skill 辅助目录（references / assets / scripts / other）==========

ALLOWED_PART_TYPES = ("references", "assets", "scripts", "other")


def _list_skill_part_dir(skill_dir: Path, part_type: str) -> List[Dict[str, str]]:
    """列出 skill 下某子目录中的文件，返回 [{name, path}]，path 为相对该子目录的路径。"""
    if part_type not in ALLOWED_PART_TYPES:
        return []
    # other: 列出 skill 根目录下除标准目录与 SKILL.md 外的文件（含子目录）
    if part_type == "other":
        items: List[Dict[str, str]] = []
        exclude = {"references", "assets", "scripts", ".git"}
        for fp in sorted(skill_dir.rglob("*")):
            if fp.is_dir():
                continue
            try:
                rel = fp.relative_to(skill_dir)
            except ValueError:
                continue
            if rel.parts and rel.parts[0] in exclude:
                continue
            if str(rel).replace("\\", "/") == "SKILL.md":
                continue
            items.append({"name": str(rel).replace("\\", "/"), "path": str(rel).replace("\\", "/")})
        return items
    dir_path = skill_dir / part_type
    if not dir_path.is_dir():
        return []
    items = []
    for p in sorted(dir_path.iterdir()):
        if p.is_file():
            items.append({"name": p.name, "path": p.name})
        elif p.is_dir():
            for fp in sorted(p.rglob("*")):
                if fp.is_file():
                    rel = fp.relative_to(dir_path)
                    items.append({"name": str(rel), "path": str(rel).replace("\\", "/")})
    return items


@router.get("/settings/skills/{skill_id}/parts")
async def get_skill_parts(skill_id: str):
    """获取某 skill 目录下 references、assets、scripts 的文件列表。"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    return {
        "status": "ok",
        "data": {
            "references": _list_skill_part_dir(skill_dir, "references"),
            "assets": _list_skill_part_dir(skill_dir, "assets"),
            "scripts": _list_skill_part_dir(skill_dir, "scripts"),
            "other": _list_skill_part_dir(skill_dir, "other"),
        },
    }


@router.get("/settings/skills/{skill_id}/parts/{part_type}/{file_path:path}")
async def get_skill_part_file(skill_id: str, part_type: str, file_path: str):
    """获取某 skill 下 references/assets/scripts 中指定文件的内容。file_path 为相对该子目录的路径，禁止 ..。"""
    if part_type not in ALLOWED_PART_TYPES:
        raise HTTPException(status_code=400, detail="Invalid part type")
    if ".." in file_path or file_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    if part_type == "other":
        full_path = (skill_dir / file_path).resolve()
        base_dir = skill_dir.resolve()
        if not str(full_path).startswith(str(base_dir)):
            raise HTTPException(status_code=400, detail="Invalid file path")
        if full_path.name == "SKILL.md" or full_path.parts and "skills" in full_path.parts and full_path.name == ".git":
            raise HTTPException(status_code=400, detail="Invalid file path")
    else:
        full_path = skill_dir / part_type / file_path
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        content = full_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {e}")
    return {"status": "ok", "data": {"path": file_path, "content": content}}


class PartFileCreate(BaseModel):
    """在 references/assets/scripts 下新建文件"""
    path: str  # 相对该子目录的路径，如 new-doc.md 或 subdir/file.txt
    content: str = ""


class PartFileUpdate(BaseModel):
    """更新 references/assets/scripts 下某文件内容"""
    content: str


@router.post("/settings/skills/{skill_id}/parts/{part_type}")
async def create_skill_part_file(skill_id: str, part_type: str, body: PartFileCreate):
    """在 skill 的 references/assets/scripts 下新建文件。path 为相对该子目录的路径，禁止 ..。"""
    if part_type not in ALLOWED_PART_TYPES:
        raise HTTPException(status_code=400, detail="Invalid part type")
    path = (body.path or "").strip().lstrip("/")
    if ".." in path or not path:
        raise HTTPException(status_code=400, detail="Invalid path")
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    if part_type == "other":
        full_path = (skill_dir / path).resolve()
        base_dir = skill_dir.resolve()
        if not str(full_path).startswith(str(base_dir)):
            raise HTTPException(status_code=400, detail="Path outside skill dir")
        if str(full_path.relative_to(base_dir)).replace("\\", "/") == "SKILL.md":
            raise HTTPException(status_code=400, detail="Cannot create SKILL.md in other")
    else:
        full_path = (skill_dir / part_type / path).resolve()
        part_dir = (skill_dir / part_type).resolve()
        if not str(full_path).startswith(str(part_dir)):
            raise HTTPException(status_code=400, detail="Path outside part dir")
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(body.content or "", encoding="utf-8")
    return {"status": "ok", "data": {"path": path.replace("\\", "/")}}


@router.put("/settings/skills/{skill_id}/parts/{part_type}/{file_path:path}")
async def update_skill_part_file(skill_id: str, part_type: str, file_path: str, body: PartFileUpdate):
    """更新 skill 下 references/assets/scripts 中指定文件的内容。"""
    if part_type not in ALLOWED_PART_TYPES:
        raise HTTPException(status_code=400, detail="Invalid part type")
    if ".." in file_path or file_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    if part_type == "other":
        full_path = (skill_dir / file_path).resolve()
        base_dir = skill_dir.resolve()
        if not str(full_path).startswith(str(base_dir)):
            raise HTTPException(status_code=400, detail="Invalid file path")
        if str(full_path.relative_to(base_dir)).replace("\\", "/") == "SKILL.md":
            raise HTTPException(status_code=400, detail="Cannot edit SKILL.md via other")
    else:
        full_path = skill_dir / part_type / file_path
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    full_path.write_text(body.content, encoding="utf-8")
    return {"status": "ok", "data": {"path": file_path}}


@router.delete("/settings/skills/{skill_id}/parts/{part_type}/{file_path:path}")
async def delete_skill_part_file(skill_id: str, part_type: str, file_path: str):
    """删除 skill 下 references/assets/scripts 中的指定文件。"""
    if part_type not in ALLOWED_PART_TYPES:
        raise HTTPException(status_code=400, detail="Invalid part type")
    if ".." in file_path or file_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    if part_type == "other":
        full_path = (skill_dir / file_path).resolve()
        base_dir = skill_dir.resolve()
        if not str(full_path).startswith(str(base_dir)):
            raise HTTPException(status_code=400, detail="Invalid file path")
        if str(full_path.relative_to(base_dir)).replace("\\", "/") == "SKILL.md":
            raise HTTPException(status_code=400, detail="Cannot delete SKILL.md via other")
    else:
        full_path = skill_dir / part_type / file_path
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    full_path.unlink()
    return {"status": "ok", "data": {"path": file_path, "deleted": True}}
