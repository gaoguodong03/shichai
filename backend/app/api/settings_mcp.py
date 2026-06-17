"""MCP 设置 API。"""
from __future__ import annotations

import asyncio
import io
import json
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.resource_store import mirror_rows_to_resource_dir
from app.core.security import user_context_dependency
from app.core.scenario_bundle import sanitize_mcp_servers_for_bundle
from app.core.settings_bundle_import import mcp_name_identity_import_plan, upsert_rows_by_id
from app.core.settings_references import merge_reference_rows_for_ids, normalize_reference_rows
from app.core.user_context import get_current_user_context, get_current_username
from app.core.user_settings_paths import mcp_config_path, skills_dir_path
from app.mcp.manager import dispose_mcp_runtime_for_user, ensure_user_mcp_config_loaded, execute_mcp_call

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])


async def _mcp_runtime_for_request():
    """当前登录用户的 MCP 运行时（只加载配置，不因查看设置页主动连接 Server）。"""
    un = get_current_username()
    if not un:
        raise HTTPException(status_code=401, detail="未登录")
    return await ensure_user_mcp_config_loaded(un)


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
    transport: MCPTransport
    metadata: Optional[Dict[str, Any]] = None

class MCPServerUpdate(BaseModel):
    """更新 MCP Server 请求"""
    name: Optional[str] = None
    transport: Optional[MCPTransport] = None
    metadata: Optional[Dict[str, Any]] = None

def load_mcp_config() -> List[Dict[str, Any]]:
    """加载 MCP 配置"""
    config_path = mcp_config_path()
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            rows = json.load(f)
        if isinstance(rows, list):
            return [_strip_legacy_runtime_fields(row) for row in rows if isinstance(row, dict)]
    return []

def save_mcp_config(servers: List[Dict[str, Any]]):
    """保存 MCP 配置"""
    config_path = mcp_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    servers = [_strip_legacy_runtime_fields(row) for row in servers or [] if isinstance(row, dict)]
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(servers, f, ensure_ascii=False, indent=2)
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        resource_rows = []
        for row in servers or []:
            if not isinstance(row, dict):
                continue
            copied = dict(row)
            copied.setdefault("type", "mcp")
            resource_rows.append(copied)
        mirror_rows_to_resource_dir(
            resource_rows,
            user_ctx.tools_dir.resolve(),
            "id",
            body_filename="tool.json",
        )


def _strip_legacy_runtime_fields(server: Dict[str, Any]) -> Dict[str, Any]:
    copied = dict(server)
    copied.pop("enabled", None)
    copied.pop("status", None)
    copied.pop("tool_count", None)
    return copied


def _frontmatter_mcp_ids(fm: Dict[str, Any]) -> List[str]:
    for key in ("auto-tools", "allowed-tools"):
        tools = fm.get(key)
        if isinstance(tools, dict):
            raw = tools.get("mcp")
            if isinstance(raw, list):
                return list(dict.fromkeys(str(x).strip() for x in raw if str(x).strip()))
    legacy = fm.get("mcp_server_ids")
    if isinstance(legacy, list):
        return list(dict.fromkeys(str(x).strip() for x in legacy if str(x).strip()))
    return []


def _read_skill_frontmatter(skill_file: Path) -> tuple[Dict[str, Any], str]:
    text = skill_file.read_text(encoding="utf-8")
    if not text.strip().startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    parsed = yaml.safe_load(parts[1]) or {}
    return parsed if isinstance(parsed, dict) else {}, parts[2].lstrip("\n")


def _write_skill_frontmatter(skill_file: Path, fm: Dict[str, Any], body: str) -> None:
    content = "---\n" + yaml.dump(fm, allow_unicode=True, default_flow_style=False) + "---\n" + body
    skill_file.write_text(content, encoding="utf-8")


def _mark_mcp_id_missing_in_skills(server_id: str, server_name: str = "") -> None:
    """删除 MCP 前，为仍声明它的 Skill 保存名称快照。"""
    sid = str(server_id or "").strip()
    if not sid:
        return
    try:
        root = skills_dir_path().resolve()
    except Exception:
        return
    if not root.is_dir():
        return
    for child in root.iterdir():
        if not child.is_dir():
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            fm, body = _read_skill_frontmatter(skill_file)
            mcp_ids = _frontmatter_mcp_ids(fm)
            if sid not in mcp_ids:
                continue
            labels = fm.get("reference-labels") if isinstance(fm.get("reference-labels"), dict) else {}
            labels = dict(labels)
            refs = merge_reference_rows_for_ids(
                mcp_ids,
                labels.get("mcp"),
                {sid: server_name} if server_name else {},
            )
            if refs == normalize_reference_rows(labels.get("mcp")):
                continue
            labels["mcp"] = refs
            fm["reference-labels"] = labels
            _write_skill_frontmatter(skill_file, fm, body)
        except Exception:
            continue


def _build_single_mcp_bundle_zip_bytes(server: Dict[str, Any]) -> bytes:
    safe_rows = sanitize_mcp_servers_for_bundle([server])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mcp_servers.json", json.dumps(safe_rows, ensure_ascii=False, indent=2) + "\n")
    return buf.getvalue()


def _content_disposition_attachment(filename: str) -> str:
    safe = str(filename or "mcp-export.zip").replace("\\", "\\\\").replace('"', '\\"')
    return f'attachment; filename="{safe}"'


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
    result = []
    for server in servers:
        server_id = server.get("id", "")
        server_info = {
            "id": server_id,
            "name": server.get("name", ""),
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


@router.get("/settings/mcp/{server_id}/export-zip")
async def export_mcp_server_zip(server_id: str):
    sid = str(server_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="server_id required")
    hit = next((x for x in load_mcp_config() if str(x.get("id") or "").strip() == sid), None)
    if not hit:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    raw = _build_single_mcp_bundle_zip_bytes(dict(hit))
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_attachment(f"{sid}.zip")},
    )


@router.post("/settings/mcp/import-zip")
async def import_mcp_server_zip(file: UploadFile = File(...), dry_run: bool = Form(False)):
    raw = await file.read()
    rows = _read_mcp_bundle_rows(raw)
    preview = [{"id": str(x.get("id") or ""), "name": str(x.get("name") or "")} for x in rows]
    if dry_run:
        return {"status": "ok", "data": {"object_type": "mcp", "preview": {"mcps": preview}}}
    existing = load_mcp_config()
    mcp_id_map, rows_to_import, kept_mcp_ids = mcp_name_identity_import_plan(existing, rows)
    existing_ids = {str(row.get("id") or "").strip() for row in existing}
    imported_ids = {str(row.get("id") or "").strip() for row in rows_to_import}
    merged = upsert_rows_by_id(existing, rows_to_import, "id")
    mcp_added = len([mid for mid in imported_ids if mid and mid not in existing_ids])
    mcp_skipped = len(kept_mcp_ids)
    mcp_updated = len([mid for mid in imported_ids if mid and mid in existing_ids])
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
                "mcp_id_map": mcp_id_map,
                "mcp_kept_ids": kept_mcp_ids,
            },
        },
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
        "transport": server.transport.model_dump(exclude_none=True),
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
    if server_update.transport is not None:
        server["transport"] = server_update.transport.model_dump(exclude_none=True)
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
    target = next((s for s in servers if s.get("id") == server_id), None)
    servers = [s for s in servers if s.get("id") != server_id]
    
    if len(servers) == original_count:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    
    _mark_mcp_id_missing_in_skills(server_id, str((target or {}).get("name") or server_id))
    save_mcp_config(servers)
    await _invalidate_mcp_runtime_after_config_change()

    return {
        "status": "ok",
        "data": {
            "id": server_id,
            "deleted": True
        }
    }

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
