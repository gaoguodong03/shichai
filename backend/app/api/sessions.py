"""统一会话 API 薄入口。

本文件只接收当前契约请求模型并转交服务层；旧的会话控制字段在
Pydantic 边界被拒绝，不能进入运行时主路径。
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict
from typing import Optional

from app.core.security import user_context_dependency

from app.api.group_chat_state import build_session_payload, load_session_definitions
from app.api.settings_app import load_app_settings, normalize_host_profile
from app.agent.group_chat_once import group_chat_once
from app.agent.group_chat_runtime import group_chat_stream
from app.agent.session_contracts import GroupChatRequest, SessionCreateRequest
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
    return await group_chat_once(session_id, request)


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
