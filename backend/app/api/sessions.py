"""统一会话 API：与群聊共用存储，所有会话均为「带主持人的会话」。详见仓库 README / docs/书童四九.md。"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List

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
    group_chat_stream,
    preview_next_speaker_prompt,
    GroupSessionUpdate,
    GroupChatRequest,
    GroupPromptPreviewRequest,
)

router = APIRouter(tags=["sessions"], dependencies=[Depends(user_context_dependency)])


class SessionCreate(BaseModel):
    title: str = "新对话"
    agent_ids: List[str] = []
    expert_ids: List[str] = []  # 兼容字段：expert_ids


@router.get("/sessions")
async def list_sessions():
    """统一会话列表（与 group-sessions 共用存储，同一份列表）"""
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
        speak_mode="auto",
    )
    return {"status": "ok", "data": data}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情与消息（与 GET /group-sessions/{id} 一致）"""
    return await get_group_session(session_id)


@router.put("/sessions/{session_id}")
async def update_session(session_id: str, body: GroupSessionUpdate):
    """更新会话（标题、发言模式、增删 DHA）"""
    return await update_group_session(session_id, body)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    return await delete_group_session(session_id)


@router.delete("/sessions/{session_id}/messages/{message_id}")
async def delete_session_message(session_id: str, message_id: str):
    """从会话历史中彻底删除一条消息（含专家发言），避免污染下一轮 DHA 的上下文。"""
    return await delete_group_message(session_id, message_id)


@router.post("/sessions/{session_id}/chat/stream")
async def session_chat_stream(session_id: str, request: GroupChatRequest):
    """会话流式对话（与 POST /group-sessions/{id}/chat/stream 一致）"""
    return await group_chat_stream(session_id, request)


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


@router.post("/sessions/{session_id}/prompt-preview")
async def session_prompt_preview(session_id: str, body: GroupPromptPreviewRequest):
    """预览指定 DHA 作为下一发言人时的提示词（与 group-sessions 一致）"""
    return await preview_next_speaker_prompt(session_id, body)
