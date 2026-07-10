"""统一会话 API 薄入口。

本文件只接收当前契约请求模型并转交服务层；旧的会话控制字段在
Pydantic 边界被拒绝，不能进入运行时主路径。
"""
import asyncio
import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any

from app.core.security import user_context_dependency

from app.api.group_chat_state import build_session_payload, load_session_definitions
from app.api.settings_app import load_app_settings, normalize_host_profile
from app.agent.group_chat_runtime import group_chat_stream
from app.agent.session_contracts import GroupChatRequest, SessionCreateRequest, SseErrorEvent
from app.agent.group_session_service import (
    GroupSessionUpdate,
    create_session_internal,
    delete_group_message,
    delete_group_session,
    export_session_to_markdown,
    get_group_session,
    group_session_events_stream,
    stop_group_session_run,
    update_group_session,
)
from app.session_state.service import (
    capture_session_checkpoint,
    clone_session_from_checkpoint,
    list_session_checkpoints,
    rollback_session_to_message,
)

router = APIRouter(tags=["sessions"], dependencies=[Depends(user_context_dependency)])
logger = logging.getLogger(__name__)


class SessionRollback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: Optional[str] = None
    message_id: Optional[str] = None


class SessionClone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: Optional[str] = None
    message_id: Optional[str] = None


@router.get("/sessions")
async def list_sessions():
    """统一会话列表（群聊与会话共用存储）"""
    session_definitions = load_session_definitions()
    sessions = []
    for gsid, session_item in session_definitions.items():
        sessions.append(build_session_payload(gsid, session_item))
    sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"status": "ok", "data": {"sessions": sessions}}


@router.post("/sessions")
async def create_session(body: SessionCreateRequest):
    """新建会话（默认仅主持人，agent_names 为空）"""
    host = dict(body.host.model_dump()) if body.host else None
    if host is None:
        settings = load_app_settings()
        host = normalize_host_profile(settings.get("host") if isinstance(settings, dict) else {})
    data = create_session_internal(
        title=body.title or "新对话",
        agent_names=body.agent_names,
        host=host,
    )
    return {"status": "ok", "data": data}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情与消息"""
    return await get_group_session(session_id)


@router.get("/sessions/{session_id}/events/stream")
async def session_events_stream(session_id: str):
    """会话运行态与消息更新事件流（SSE）。"""
    return await group_session_events_stream(session_id)


@router.put("/sessions/{session_id}")
async def update_session(session_id: str, body: GroupSessionUpdate):
    """更新会话（标题、主持人配置、增删 Agent）"""
    return await update_group_session(session_id, body)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    return await delete_group_session(session_id)


@router.post("/sessions/{session_id}/chat/stop")
async def stop_session_chat(session_id: str):
    """停止该会话当前正在运行的回复。"""
    return await stop_group_session_run(session_id)


@router.delete("/sessions/{session_id}/messages/{message_id}")
async def delete_session_message(session_id: str, message_id: str):
    """从会话历史中彻底删除一条消息（含 Agent 发言），避免污染下一轮上下文。"""
    return await delete_group_message(session_id, message_id)


@router.post("/sessions/{session_id}/chat/stream")
async def session_chat_stream(session_id: str, request: GroupChatRequest):
    """会话流式对话（SSE）"""
    return await group_chat_stream(session_id, request)


@router.post("/sessions/{session_id}/chat")
async def session_chat_once(session_id: str, request: GroupChatRequest):
    """会话非流式对话：内部复用 SSE 逻辑并聚合最终事件。"""
    stream_resp = await group_chat_stream(session_id, request)
    body_iter = getattr(stream_resp, "body_iterator", None)
    if body_iter is None:
        raise HTTPException(status_code=500, detail="chat stream aggregation unavailable")

    route_event: Optional[Dict[str, Any]] = None
    progress_events: List[Dict[str, Any]] = []
    message_events: List[Dict[str, Any]] = []
    end_event: Optional[Dict[str, Any]] = None
    error_event: Optional[Dict[str, Any]] = None

    buffer = ""
    try:
        async for chunk in body_iter:
            part = chunk.decode("utf-8", errors="ignore") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
            buffer += part.replace("\r", "")
            blocks = buffer.split("\n\n")
            buffer = blocks.pop() or ""
            for block_raw in blocks:
                block = block_raw.strip()
                if not block.startswith("event: "):
                    continue
                event_type = (block.split("\n")[0] or "").replace("event: ", "").strip()
                data_lines = [line[6:].strip() for line in block.split("\n") if line.startswith("data: ")]
                data_str = "\n".join(data_lines).strip()
                if not data_str:
                    continue
                try:
                    payload = json.loads(data_str)
                except Exception:
                    continue
                if event_type == "route":
                    route_event = payload
                elif event_type == "progress":
                    progress_events.append(payload)
                elif event_type == "message":
                    message_events.append(payload)
                elif event_type == "end":
                    end_event = payload
                elif event_type == "error":
                    error_event = payload
    except asyncio.CancelledError as e:
        logger.warning("session_chat_once 聚合流被取消: session=%s err=%s", session_id, e)
        error_event = error_event or SseErrorEvent(
            type="error",
            run_id=None,
            code="chat_once_cancelled",
            message=str(e) or "chat once stream cancelled",
        ).model_dump(exclude_none=False)
    except Exception as e:
        logger.exception("session_chat_once 聚合流失败: session=%s err=%s", session_id, e)
        error_event = error_event or SseErrorEvent(
            type="error",
            run_id=None,
            code="chat_once_stream_error",
            message=str(e) or e.__class__.__name__,
        ).model_dump(exclude_none=False)

    primary_message = message_events[-1] if message_events else None
    route_agent_name = route_event.get("agent_name") if isinstance(route_event, dict) else None
    if route_agent_name:
        primary_message = next(
            (
                msg
                for msg in reversed(message_events)
                if isinstance(msg.get("speaker"), dict)
                and str((msg.get("speaker") or {}).get("agent_name") or "").strip() == route_agent_name
            ),
            primary_message,
        )

    return {
        "status": "ok",
        "data": {
            "route": route_event,
            "progress": progress_events,
            "messages": message_events,
            "message": primary_message,
            "end": end_event,
            "error": error_event,
        },
    }


@router.post("/sessions/{session_id}/export")
async def session_export(session_id: str):
    """将会话导出为 Markdown 到该会话工作区"""
    session_definitions = load_session_definitions()
    if session_id not in session_definitions:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        rel_path, download_url = export_session_to_markdown(session_id)
        return {"status": "ok", "data": {"path": rel_path, "download_url": download_url}}
    except HTTPException:
        raise


@router.post("/sessions/{session_id}/snapshot")
async def session_snapshot(session_id: str):
    """为当前会话创建一个状态快照。"""
    return {"status": "ok", "data": capture_session_checkpoint(session_id, trigger="manual_snapshot")}


@router.get("/sessions/{session_id}/snapshots")
async def session_snapshots(session_id: str):
    """列出当前会话已保存的状态链。"""
    return {"status": "ok", "data": {"checkpoints": list_session_checkpoints(session_id)}}


@router.post("/sessions/{session_id}/clone")
async def session_clone(session_id: str, body: SessionClone = SessionClone()):
    """复制当前会话并新建一个窗口；可指定 checkpoint 或 message_id 从该时刻分叉。"""
    checkpoint_id = (body.checkpoint_id or "").strip() or None
    message_id = (body.message_id or "").strip() or None
    return {
        "status": "ok",
        "data": clone_session_from_checkpoint(
            session_id,
            checkpoint_id=checkpoint_id,
            message_id=message_id,
        ),
    }


@router.post("/sessions/{session_id}/rollback")
async def session_rollback(session_id: str, body: SessionRollback):
    """回溯到指定 message_id 或 checkpoint，并删除其后的状态记录。"""
    checkpoint_id = (body.checkpoint_id or "").strip() or None
    message_id = (body.message_id or "").strip() or None
    if not checkpoint_id and not message_id:
        raise HTTPException(status_code=400, detail="checkpoint_id or message_id is required")
    data = await rollback_session_to_message(
        session_id,
        checkpoint_id=checkpoint_id,
        message_id=message_id,
    )
    return {"status": "ok", "data": data}
