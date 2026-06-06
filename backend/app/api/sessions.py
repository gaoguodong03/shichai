"""统一会话 API：与群聊共用存储，所有会话均为「带主持人的会话」。详见仓库 README / docs/书童四九.md。"""
import asyncio
import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.core.security import user_context_dependency

from app.api.group_chat import (
    _load_group_meta,
    _build_session_payload,
    create_session_internal,
    export_session_to_markdown,
    get_group_session,
    update_group_session,
    delete_group_session,
    delete_group_message,
    stop_group_session_run,
    group_chat_stream,
    group_session_events_stream,
    GroupSessionUpdate,
    GroupChatRequest,
)

router = APIRouter(tags=["sessions"], dependencies=[Depends(user_context_dependency)])
logger = logging.getLogger(__name__)


class SessionCreate(BaseModel):
    title: str = "新对话"
    agent_ids: List[str] = []
    expert_ids: List[str] = []  # 兼容字段：expert_ids
    leader_agent_id: Optional[str] = None  # 虚拟主持人 id 或兼容旧版真实 DHA
    host_config: Optional[Dict[str, Any]] = None  # 场景虚拟主持人配置


@router.get("/sessions")
async def list_sessions():
    """统一会话列表（群聊与会话共用存储）"""
    meta = _load_group_meta()
    sessions = []
    for gsid, gm in meta.items():
        sessions.append(_build_session_payload(gsid, gm))
    sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"status": "ok", "data": {"sessions": sessions}}


@router.post("/sessions")
async def create_session(body: SessionCreate):
    """创建会话（默认仅主持人，agent_ids 为空）"""
    data = create_session_internal(
        title=body.title or "新对话",
        agent_ids=body.agent_ids,
        expert_ids=body.expert_ids,
        leader_agent_id=body.leader_agent_id,
        host_config=body.host_config,
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
    """更新会话（标题、主持人配置、增删 DHA）"""
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
    """从会话历史中彻底删除一条消息（含专家发言），避免污染下一轮 DHA 的上下文。"""
    return await delete_group_message(session_id, message_id)


@router.post("/sessions/{session_id}/chat/stream")
async def session_chat_stream(session_id: str, request: GroupChatRequest):
    """会话流式对话（SSE）"""
    return await group_chat_stream(session_id, request)


@router.post("/sessions/{session_id}/chat")
async def session_chat_once(session_id: str, request: GroupChatRequest):
    """会话非流式对话（兜底）：内部复用 SSE 逻辑并聚合最终事件。"""
    stream_resp = await group_chat_stream(session_id, request)
    body_iter = getattr(stream_resp, "body_iterator", None)
    if body_iter is None:
        raise HTTPException(status_code=500, detail="chat fallback unavailable")

    route_event: Optional[Dict[str, Any]] = None
    content_events: List[Dict[str, Any]] = []
    message_events: List[Dict[str, Any]] = []
    end_event: Optional[Dict[str, Any]] = None
    error_event: Optional[Dict[str, Any]] = None

    buffer = ""
    interrupted = False
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
                elif event_type == "content":
                    content_events.append(payload)
                elif event_type == "message":
                    message_events.append(payload)
                elif event_type == "end":
                    end_event = payload
                elif event_type == "error":
                    error_event = payload
    except asyncio.CancelledError as e:
        interrupted = True
        logger.warning("session_chat_once 聚合流被取消: session=%s err=%s", session_id, e)
    except Exception as e:
        interrupted = True
        logger.exception("session_chat_once 聚合流失败: session=%s err=%s", session_id, e)
        error_event = error_event or {"error": str(e)}

    primary_message = message_events[-1] if message_events else None
    route_agent_id = route_event.get("agent_id") if isinstance(route_event, dict) else None
    if route_agent_id:
        primary_message = next(
            (msg for msg in reversed(message_events) if msg.get("agent_id") == route_agent_id),
            primary_message,
        )

    return {
        "status": "ok",
        "data": {
            "route": route_event,
            "contents": content_events,
            "messages": message_events,
            "message": primary_message,
            "end": end_event,
            "error": error_event,
            "interrupted": interrupted or (end_event is None),
        },
    }


@router.post("/sessions/{session_id}/export")
async def session_export(session_id: str):
    """将会话导出为 Markdown 到该会话工作区"""
    meta = _load_group_meta()
    if session_id not in meta:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        rel_path, download_url = export_session_to_markdown(session_id)
        return {"status": "ok", "data": {"path": rel_path, "download_url": download_url}}
    except HTTPException:
        raise
