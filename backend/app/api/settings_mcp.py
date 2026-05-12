"""MCP 设置 API。"""
from __future__ import annotations

import asyncio
import io
import json
import time
import uuid
import zipfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import user_context_dependency
from app.core.user_context import get_current_username
from app.core.user_settings_paths import mcp_config_path
from app.mcp.manager import dispose_mcp_runtime_for_user, ensure_user_mcp_bootstrapped, execute_mcp_call

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])


async def _mcp_runtime_for_request():
    """当前登录用户的 MCP 运行时（已加载该用户 mcp_servers.json）。"""
    un = get_current_username()
    if not un:
        raise HTTPException(status_code=401, detail="未登录")
    return await ensure_user_mcp_bootstrapped(un)


async def _invalidate_mcp_runtime_after_config_change():
    """磁盘上的 mcp_servers.json 变更后丢弃内存中的连接，下次再懒加载。"""
    un = get_current_username()
    if un:
        await dispose_mcp_runtime_for_user(un)


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
    config_path = mcp_config_path()
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_mcp_config(servers: List[Dict[str, Any]]):
    """保存 MCP 配置"""
    config_path = mcp_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(servers, f, ensure_ascii=False, indent=2)


def _build_single_mcp_bundle_zip_bytes(server: Dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mcp_servers.json", json.dumps([server], ensure_ascii=False, indent=2) + "\n")
    return buf.getvalue()

@router.get("/settings/mcp")
async def get_mcp_servers():
    """获取 MCP Server 列表"""
    servers = load_mcp_config()
    mcp_manager = await _mcp_runtime_for_request()

    # 确保已连接非 lazy 且尚未连接的 server
    try:
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


@router.get("/settings/mcp/{server_id}/share-link")
async def get_mcp_share_link(server_id: str):
    from app.core.scenario_share_store import find_share_id_for_object

    sid = str(server_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="server_id required")
    hit = next((x for x in load_mcp_config() if str(x.get("id") or "").strip() == sid), None)
    if not hit:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    share_id = find_share_id_for_object(get_current_username() or "", "mcp", sid)
    if not share_id:
        return {"status": "ok", "data": {"share_id": None, "open_path": None}}
    return {"status": "ok", "data": {"share_id": share_id, "open_path": f"/share/run?id={share_id}"}}


@router.post("/settings/mcp/{server_id}/publish-share")
async def publish_mcp_share(server_id: str):
    from app.core.scenario_share_store import upsert_public_share

    sid = str(server_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="server_id required")
    hit = next((x for x in load_mcp_config() if str(x.get("id") or "").strip() == sid), None)
    if not hit:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    zip_bytes = _build_single_mcp_bundle_zip_bytes(dict(hit))
    name = str(hit.get("name") or sid)
    share_id = upsert_public_share(
        zip_bytes,
        {
            "object_type": "mcp",
            "source_ref": sid,
            "title": name,
            "mcp_name": name,
            "created_by": get_current_username() or "",
            "summary": {"mcp_count": 1},
        },
    )
    return {
        "status": "ok",
        "data": {"share_id": share_id, "open_path": f"/share/run?id={share_id}", "server_id": sid, "server_name": name},
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
    await _invalidate_mcp_runtime_after_config_change()

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
    await _invalidate_mcp_runtime_after_config_change()

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
    await _invalidate_mcp_runtime_after_config_change()

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
            await _invalidate_mcp_runtime_after_config_change()
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
            await _invalidate_mcp_runtime_after_config_change()
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

    mcp_manager = await _mcp_runtime_for_request()

    import time

    start = time.perf_counter()
    try:
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
    mcp_manager = await _mcp_runtime_for_request()

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
    mcp_manager = await _mcp_runtime_for_request()

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

    ok, result, err = await execute_mcp_call(
        server_id=server_id,
        tool_name=tool_name,
        kwargs=body.arguments or {},
        session=session,
        timeout_sec=60.0,
    )
    if not ok:
        return {
            "status": "ok",
            "data": {
                "ok": False,
                "error": err,
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
    mcp_manager = await _mcp_runtime_for_request()

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
    ok, result, err = await execute_mcp_call(
        server_id=server_id,
        tool_name=tool_name,
        kwargs=body.arguments or {},
        session=session,
        timeout_sec=60.0,
    )
    if not ok:
        return {
            "status": "ok",
            "data": {
                "ok": False,
                "error": err,
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
