"""MCP 设置 API。"""
from __future__ import annotations

import asyncio
import io
import json
import time
import zipfile
from pathlib import Path
from urllib.parse import quote
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from app.api.request_models import StrictRequestModel

from app.core.resource_store import mirror_rows_to_resource_dir
from app.core.security import user_context_dependency
from app.core.name_based_resources import normalize_tool_row
from app.core.scenario_bundle import sanitize_mcp_servers_for_bundle
from app.core.user_context import get_current_user_context, get_current_username
from app.mcp.manager import dispose_mcp_runtime_for_user, ensure_user_mcp_config_loaded, execute_mcp_call

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])
LEGACY_MCP_RUNTIME_FIELDS = {"enabled", "status", "tool_count"}


async def _mcp_runtime_for_request():
    """当前登录用户的 MCP 运行时（只加载配置，不因查看设置页主动连接 Server）。"""
    un = get_current_username()
    if not un:
        raise HTTPException(status_code=401, detail="未登录")
    return await ensure_user_mcp_config_loaded(un)


async def _invalidate_mcp_runtime_after_config_change():
    """工具资源变更后丢弃内存中的 MCP 连接，下次再懒加载。"""
    un = get_current_username()
    if un:
        await dispose_mcp_runtime_for_user(un)


class MCPTransport(StrictRequestModel):
    """MCP 传输配置"""
    type: str  # stdio, sse, http
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    base_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    env: Optional[Dict[str, str]] = None

class MCPServerCreate(StrictRequestModel):
    """新建 MCP Server 请求"""
    name: str
    type: str = "mcp"
    description: str = ""
    transport: Optional[MCPTransport] = None
    server_config: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

class MCPServerUpdate(StrictRequestModel):
    """更新 MCP Server 请求"""
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    transport: Optional[MCPTransport] = None
    server_config: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

def load_mcp_config() -> List[Dict[str, Any]]:
    """从 resources/tools 读取 MCP 工具资源。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return []
    root = user_ctx.tools_dir.resolve()
    if not root.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        body = child / "tool.json"
        if not body.is_file():
            continue
        try:
            row = json.loads(body.read_text(encoding="utf-8"))
            if isinstance(row, dict):
                out.append(normalize_tool_row(row))
        except Exception:
            continue
    return out

def save_mcp_config(servers: List[Dict[str, Any]]):
    """保存 MCP 工具资源。"""
    servers = [normalize_tool_row(row) for row in servers or [] if isinstance(row, dict)]
    seen: set[str] = set()
    unique_servers: List[Dict[str, Any]] = []
    for row in servers:
        key = str(row.get("name") or "").strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_servers.append(row)
    servers = unique_servers
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        mirror_rows_to_resource_dir(
            [dict(row) for row in servers or [] if isinstance(row, dict)],
            user_ctx.tools_dir.resolve(),
            "name",
            body_filename="tool.json",
        )


def _legacy_runtime_fields_in_payload(server: Dict[str, Any]) -> List[str]:
    return sorted(LEGACY_MCP_RUNTIME_FIELDS.intersection(server or {}))


def _reject_legacy_runtime_fields(server: Dict[str, Any]) -> None:
    fields = _legacy_runtime_fields_in_payload(server)
    if fields:
        raise HTTPException(
            status_code=400,
            detail=f"MCP 配置包含旧运行字段: {', '.join(fields)}；请只提交当前资源配置字段。",
        )


def _build_single_mcp_bundle_zip_bytes(server: Dict[str, Any]) -> bytes:
    safe_rows = sanitize_mcp_servers_for_bundle([server])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mcp_servers.json", json.dumps(safe_rows, ensure_ascii=False, indent=2) + "\n")
    return buf.getvalue()


def _content_disposition_attachment(filename: str) -> str:
    filename = str(filename or "mcp-export.zip")
    try:
        filename.encode("ascii")
        safe = filename.replace("\\", "\\\\").replace('"', '\\"')
        return f'attachment; filename="{safe}"'
    except UnicodeEncodeError:
        return f"attachment; filename=\"mcp-export.zip\"; filename*=UTF-8''{quote(filename, safe='')}"


def _read_mcp_bundle_rows(raw: bytes) -> List[Dict[str, Any]]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            try:
                payload = zf.read("mcp_servers.json")
            except KeyError as exc:
                raise HTTPException(status_code=400, detail="ZIP 中缺少 mcp_servers.json") from exc
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="不是有效的 ZIP 文件") from exc
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="mcp_servers.json 格式错误") from exc
    rows = [x for x in parsed if isinstance(x, dict)] if isinstance(parsed, list) else []
    if not rows:
        raise HTTPException(status_code=400, detail="分享包中没有可导入的 MCP 配置")
    return rows

@router.get("/settings/mcp")
async def get_mcp_servers():
    """获取 MCP Server 列表"""
    servers = load_mcp_config()
    result = [dict(server) for server in servers]
    
    return {
        "status": "ok",
        "data": {
            "servers": result
        }
    }


@router.get("/settings/mcp/{tool_name}/export-zip")
async def export_mcp_server_zip(tool_name: str):
    name = str(tool_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="tool name required")
    hit = next((x for x in load_mcp_config() if str(x.get("name") or "").strip() == name), None)
    if not hit:
        raise HTTPException(status_code=404, detail="Tool not found")
    raw = _build_single_mcp_bundle_zip_bytes(dict(hit))
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_attachment(f"{name}.zip")},
    )


@router.post("/settings/mcp/import-zip")
async def import_mcp_server_zip(file: UploadFile = File(...), dry_run: bool = Form(False)):
    raw = await file.read()
    rows = _read_mcp_bundle_rows(raw)
    for row in rows:
        _reject_legacy_runtime_fields(row)
    rows = [normalize_tool_row(row) for row in rows]
    preview = [{"name": str(x.get("name") or ""), "type": str(x.get("type") or "")} for x in rows]
    if dry_run:
        return {"status": "ok", "data": {"object_type": "tool", "preview": {"tools": preview}}}
    existing = load_mcp_config()
    existing_names = {str(row.get("name") or "").strip().casefold() for row in existing}
    rows_to_import = [row for row in rows if str(row.get("name") or "").strip().casefold() not in existing_names]
    merged = existing + rows_to_import
    mcp_added = len(rows_to_import)
    mcp_skipped = len(rows) - len(rows_to_import)
    mcp_updated = 0
    save_mcp_config(merged)
    await _invalidate_mcp_runtime_after_config_change()
    return {
        "status": "ok",
        "data": {
            "object_type": "mcp",
            "summary": {
                "mcp_added": mcp_added,
                "mcp_skipped": mcp_skipped,
                "mcp_updated": mcp_updated,
                "tools_added": mcp_added,
                "tools_skipped": mcp_skipped,
            },
        },
    }


@router.post("/settings/mcp")
async def create_mcp_server(server: MCPServerCreate):
    """新建工具"""
    servers = load_mcp_config()
    if any(str(s.get("name") or "").strip().casefold() == server.name.strip().casefold() for s in servers):
        raise HTTPException(status_code=409, detail="同名工具已存在")

    raw_server = server.model_dump(exclude_none=True)
    if server.transport is not None:
        raw_server["transport"] = server.transport.model_dump(exclude_none=True)
    new_server = normalize_tool_row(raw_server)
    
    servers.append(new_server)
    save_mcp_config(servers)
    await _invalidate_mcp_runtime_after_config_change()

    return {
        "status": "ok",
        "data": new_server
    }

@router.put("/settings/mcp/{tool_name}")
async def update_mcp_server(tool_name: str, server_update: MCPServerUpdate):
    """更新工具"""
    servers = load_mcp_config()
    current_name = str(tool_name or "").strip()
    server_index = None
    for i, s in enumerate(servers):
        if str(s.get("name") or "").strip() == current_name:
            server_index = i
            break
    
    if server_index is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    
    server = dict(servers[server_index])
    update_data = server_update.model_dump(exclude_none=True)
    if server_update.transport is not None:
        update_data["transport"] = server_update.transport.model_dump(exclude_none=True)
    server.update(update_data)
    normalized = normalize_tool_row(server)
    new_name = str(normalized.get("name") or "").strip()
    if new_name.casefold() != current_name.casefold() and any(
        str(s.get("name") or "").strip().casefold() == new_name.casefold()
        for idx, s in enumerate(servers)
        if idx != server_index
    ):
        raise HTTPException(status_code=409, detail="同名工具已存在")
    servers[server_index] = normalized
    
    save_mcp_config(servers)
    await _invalidate_mcp_runtime_after_config_change()

    return {
        "status": "ok",
        "data": normalized
    }

@router.delete("/settings/mcp/{tool_name}")
async def delete_mcp_server(tool_name: str):
    """删除工具"""
    servers = load_mcp_config()
    name = str(tool_name or "").strip()
    original_count = len(servers)
    target = next((s for s in servers if str(s.get("name") or "").strip() == name), None)
    servers = [s for s in servers if str(s.get("name") or "").strip() != name]
    
    if len(servers) == original_count:
        raise HTTPException(status_code=404, detail="Tool not found")
    
    save_mcp_config(servers)
    await _invalidate_mcp_runtime_after_config_change()

    return {
        "status": "ok",
        "data": {
            "name": name,
            "deleted": True
        }
    }

@router.post("/settings/mcp/{tool_name}/test")
async def test_mcp_server(tool_name: str):
    """测试 MCP Server 连接（真实调用 MCP Manager）"""
    servers = load_mcp_config()
    tool_key = str(tool_name or "").strip()

    server = next((s for s in servers if str(s.get("name") or "").strip() == tool_key), None)
    if server is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    if server.get("type") != "mcp":
        raise HTTPException(status_code=400, detail="只有 MCP 工具支持连接测试")

    mcp_manager = await _mcp_runtime_for_request()

    import time

    start = time.perf_counter()
    try:
        # 如果当前没有 session，则尝试连接
        if tool_key not in mcp_manager.sessions:
            ok = await mcp_manager.connect_server(tool_key, server)
            if not ok:
                elapsed = int((time.perf_counter() - start) * 1000)
                return {
                    "status": "ok",
                    "data": {
                        "connected": False,
                        "response_time": elapsed,
                        "error": f"Failed to connect to MCP server {tool_key}",
                    },
                }
        # 调用 list_tools 做一次简单健康检查
        session = mcp_manager.sessions.get(tool_key)
        if not session:
            elapsed = int((time.perf_counter() - start) * 1000)
            return {
                "status": "ok",
                "data": {
                    "connected": False,
                    "response_time": elapsed,
                    "error": f"No active session for MCP server {tool_key}",
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

@router.get("/settings/mcp/{tool_name}/tools")
async def get_mcp_server_tools(tool_name: str):
    """获取 MCP Server 工具列表（含 input_schema），用于前端动态渲染参数表单"""
    mcp_manager = await _mcp_runtime_for_request()

    # 找到对应 server 配置
    tool_key = str(tool_name or "").strip()
    config = next((c for c in mcp_manager.server_configs if str(c.get("name") or "").strip() == tool_key), None)
    if not config:
        raise HTTPException(status_code=404, detail="Tool not found")

    # 确保已连接
    if tool_key not in mcp_manager.sessions:
        ok = await mcp_manager.connect_server(tool_key, config)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to connect MCP server {tool_key}")

    session = mcp_manager.sessions.get(tool_key)
    if not session:
        raise HTTPException(status_code=500, detail=f"No active session for MCP server {tool_key}")

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


class MCPToolCallBody(StrictRequestModel):
    """调用 MCP 工具的请求体（用于前端测试）"""

    arguments: Dict[str, Any] = {}


@router.post("/settings/mcp/{server_name}/tools/{tool_name}/call")
async def call_mcp_tool(server_name: str, tool_name: str, body: MCPToolCallBody):
    """调用指定 MCP Server 上的某个工具，用于前端测试面板"""
    mcp_manager = await _mcp_runtime_for_request()

    tool_key = str(server_name or "").strip()
    config = next((c for c in mcp_manager.server_configs if str(c.get("name") or "").strip() == tool_key), None)
    if not config:
        raise HTTPException(status_code=404, detail="Tool not found")

    # 确保连接
    if tool_key not in mcp_manager.sessions:
        ok = await mcp_manager.connect_server(tool_key, config)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to connect MCP server {tool_key}")

    session = mcp_manager.sessions.get(tool_key)
    if not session:
        raise HTTPException(status_code=500, detail=f"No active session for MCP server {tool_key}")

    ok, result, err = await execute_mcp_call(
        server_name=tool_key,
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


class MCPSandboxCallBody(StrictRequestModel):
    """沙箱调用：不关心具体工具名，只在该 MCP Server 上调用第一个工具"""

    arguments: Dict[str, Any] = {}


@router.post("/settings/mcp/{tool_name}/sandbox-call")
async def call_mcp_sandbox(tool_name: str, body: MCPSandboxCallBody):
    """
    沙箱调用：在指定 MCP Server 上选择第一个可用工具进行一次调用。
    前端只需提供 arguments，不需要关心工具名。
    """
    mcp_manager = await _mcp_runtime_for_request()

    tool_key = str(tool_name or "").strip()
    config = next((c for c in mcp_manager.server_configs if str(c.get("name") or "").strip() == tool_key), None)
    if not config:
        raise HTTPException(status_code=404, detail="Tool not found")

    # 确保连接
    if tool_key not in mcp_manager.sessions:
        ok = await mcp_manager.connect_server(tool_key, config)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to connect MCP server {tool_key}")

    session = mcp_manager.sessions.get(tool_key)
    if not session:
        raise HTTPException(status_code=500, detail=f"No active session for MCP server {tool_key}")

    # 获取工具列表，选择第一个工具名
    try:
        tools_result = await session.list_tools()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_tools error: {e}")

    tools = getattr(tools_result, "tools", []) or []
    if not tools:
        raise HTTPException(status_code=500, detail=f"MCP server {tool_key} has no tools")

    tool_name = getattr(tools[0], "name", None)
    if not tool_name:
        raise HTTPException(status_code=500, detail=f"First tool of MCP server {tool_key} has no name")

    # 调用第一个工具
    ok, result, err = await execute_mcp_call(
        server_name=tool_key,
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
