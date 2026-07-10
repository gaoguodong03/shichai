from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.api.agents import enrich_agent_instances, load_agent_instances
from app.api.files import get_workspace_root_path
from app.api.group_chat_state import (
    GROUP_SESSION_EVENT_SUBSCRIBERS as _GROUP_SESSION_EVENT_SUBSCRIBERS,
    GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK as _GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK,
    build_session_payload as _build_session_payload,
    cancel_group_session_run as _cancel_group_session_run,
    cleanup_orphan_group_histories as _cleanup_orphan_group_histories,
    ensure_sessions_dir as _ensure_sessions_dir,
    format_storage_timestamp,
    frontend_history_message as _frontend_history_message,
    load_group_history as _load_group_history,
    load_group_orchestration_state as _load_group_orchestration_state,
    load_session_definitions as _load_session_definitions,
    reject_group_session_mutation_if_running as _reject_group_session_mutation_if_running,
    runtime_for_session as _runtime_for_session,
    save_group_history as _save_group_history,
    save_session_definitions as _save_session_definitions,
    write_group_orchestration_state as _write_group_orchestration_state,
)
from app.core.scene_host import VIRTUAL_SCENE_HOST_ID
from app.core.security import get_current_user
from app.session_state.markdown import format_session_export_markdown
from app.agent.group_chat_streaming import (
    SSE_AGENT_KEEPALIVE_INTERVAL_SEC as _SSE_AGENT_KEEPALIVE_INTERVAL_SEC,
)
from app.agent.group_chat_title_meta import (
    _ensure_scene_profile_contract,
)
from app.agent.session_contracts import SessionUpdateRequest

logger = logging.getLogger(__name__)


GroupSessionUpdate = SessionUpdateRequest


def _dedupe_names(values: Optional[List[str]]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in values or []:
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _agent_name_map(instances: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        str(row.get("name") or "").strip(): row
        for row in instances or []
        if str(row.get("name") or "").strip()
    }


def _validate_agent_names(names: List[str], valid_names: set[str]) -> None:
    for name in names:
        if name not in valid_names:
            raise HTTPException(status_code=400, detail=f"专家 {name} 不存在")


def _host_display_name(session_item: Dict[str, Any]) -> str:
    """Return the current session host display name for host-authored messages."""
    host_snapshot = session_item.get("host") if isinstance(session_item.get("host"), dict) else {}
    return str(host_snapshot.get("name") or "四九").strip() or "四九"


def _clear_host_scheduler_state(group_session_id: str) -> None:
    """Configuration changes invalidate only the host_scheduler orchestration block."""
    state = _load_group_orchestration_state(group_session_id)
    state.pop("host_scheduler", None)
    _write_group_orchestration_state(group_session_id, state)


def create_session_internal(
    title: str = "新对话",
    agent_names: Optional[List[str]] = None,
    host: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create session.json from the current contract without legacy controls."""
    instances = load_agent_instances()
    names = _dedupe_names(agent_names)
    valid_names = set(_agent_name_map(instances))
    _validate_agent_names(names, valid_names)
    gsid = f"group-{uuid.uuid4().hex[:12]}"
    now = format_storage_timestamp()
    session_definitions = _load_session_definitions()
    host_snapshot = dict(host or {})
    if not any(str(v or "").strip() for v in host_snapshot.values()):
        host_snapshot = {}
    row: Dict[str, Any] = {
        "title": title or "新对话",
        "title_auto_generated": True,
        "agent_names": names,
        "host": host_snapshot,
        "created_at": now,
        "updated_at": now,
    }
    session_definitions[gsid] = row
    _save_session_definitions(session_definitions)
    _save_group_history(gsid, [], checkpoint_trigger=None)
    # 工作区目录延后新建：仅在用户首次使用工作区（列表/上传/导出等）时由 files API 或 export 新建
    try:
        from app.session_state.service import capture_session_checkpoint

        capture_session_checkpoint(gsid, trigger="session_created")
    except Exception:
        logger.warning("session_state initial checkpoint failed: %s", gsid, exc_info=True)
    # 工作区目录延后创建：仅在用户首次使用工作区（列表/上传/导出等）时由 files API 或 export 创建
    return _build_session_payload(gsid, session_definitions[gsid])

def export_session_to_markdown(session_id: str, filename: Optional[str] = None) -> tuple:
    """将会话历史导出为 Markdown 到该会话工作区。历史来自 group_history。返回 (rel_path, download_url)。"""
    from app.api.files import get_workspace_root

    messages = _load_group_history(session_id)
    if not messages:
        raise HTTPException(status_code=400, detail="会话无消息，无法导出")
    md = format_session_export_markdown(messages)
    ws_root = get_workspace_root(session_id)
    fn = filename or f"session-{session_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}00.md"
    fn = fn.replace("..", "").replace("/", "")
    if not fn.endswith(".md"):
        fn += ".md"
    filepath = ws_root / fn
    filepath.write_text(md, encoding="utf-8")
    rel = str(filepath.relative_to(ws_root)).replace("\\", "/")
    return rel, f"/api/workspaces/{session_id}/files/download?path={rel}"

async def get_group_session(group_session_id: str):
    """获取群聊详情与消息。"""
    session_definitions = _load_session_definitions()
    if group_session_id not in session_definitions:
        raise HTTPException(status_code=404, detail="Group session not found")
    session_item = session_definitions[group_session_id]
    if _ensure_scene_profile_contract(session_item):
        _save_session_definitions(session_definitions)
    messages = _load_group_history(group_session_id)
    instances = load_agent_instances()
    enriched_instances = await enrich_agent_instances(instances, workspace_id=group_session_id)
    agent_map_raw = _agent_name_map(enriched_instances)
    normalized_messages = []
    for msg in messages:
        row = dict(msg or {})
        normalized_messages.append(_frontend_history_message(row))
    messages = normalized_messages
    agent_names_in_group = set(_dedupe_names(list(session_item.get("agent_names", []))))
    session_item["agent_names"] = list(agent_names_in_group)
    agent_names_in_messages = {
        str((msg.get("speaker") or {}).get("agent_name") or "").strip()
        for msg in messages
        if isinstance(msg.get("speaker"), dict) and str((msg.get("speaker") or {}).get("agent_name") or "").strip()
    }
    relevant_names = agent_names_in_group | agent_names_in_messages
    agent_map = {
        k: {
            "name": v.get("name") or "",
            "description": v.get("description") or "",
        }
        for k, v in agent_map_raw.items()
        if k in relevant_names
    }
    host_snapshot = session_item.get("host") if isinstance(session_item.get("host"), dict) else {}
    host_dn = str(host_snapshot.get("name") or "四九").strip() or "四九"
    agent_map[VIRTUAL_SCENE_HOST_ID] = {
        "name": host_dn,
        "description": "群聊场景主持人",
    }
    return {
        "status": "ok",
        "data": {
            **_build_session_payload(group_session_id, session_item),
            "messages": messages,
            "agent_map": agent_map,
            "runtime": _runtime_for_session(group_session_id, session_item),
        },
    }

async def group_session_events_stream(group_session_id: str):
    """会话事件推送流：用于页面恢复/多标签页时主动同步运行态与新消息。"""
    session_definitions = _load_session_definitions()
    if group_session_id not in session_definitions:
        raise HTTPException(status_code=404, detail="Group session not found")

    async def event_gen():
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=32)
        async with _GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
            subscribers = _GROUP_SESSION_EVENT_SUBSCRIBERS.setdefault(group_session_id, [])
            subscribers.append(queue)
        try:
            snapshot = {
                "session_id": group_session_id,
                "server_time": format_storage_timestamp(),
                "runtime": _runtime_for_session(group_session_id, session_definitions.get(group_session_id) or {}),
                "last_message_id": "",
                "updated_at": str((session_definitions.get(group_session_id) or {}).get("updated_at") or ""),
            }
            history = _load_group_history(group_session_id)
            if history:
                snapshot["last_message_id"] = str(history[-1].get("message_id") or "")
            yield f"event: snapshot\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_SSE_AGENT_KEEPALIVE_INTERVAL_SEC)
                except asyncio.TimeoutError:
                    yield f"event: keepalive\ndata: {json.dumps({'server_time': format_storage_timestamp()}, ensure_ascii=False)}\n\n"
                    continue
                event_name = str(item.pop("__event_type", None) or "message").strip() or "message"
                yield f"event: {event_name}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            async with _GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
                current = _GROUP_SESSION_EVENT_SUBSCRIBERS.get(group_session_id) or []
                _GROUP_SESSION_EVENT_SUBSCRIBERS[group_session_id] = [q for q in current if q is not queue]
                if not _GROUP_SESSION_EVENT_SUBSCRIBERS[group_session_id]:
                    _GROUP_SESSION_EVENT_SUBSCRIBERS.pop(group_session_id, None)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

async def update_group_session(group_session_id: str, body: GroupSessionUpdate):
    """Update only current session contract fields: title, host, and agent_names."""
    session_definitions = _load_session_definitions()
    if group_session_id not in session_definitions:
        raise HTTPException(status_code=404, detail="Group session not found")
    if body.title is not None and str(body.title).strip():
        next_title = body.title.strip()
        session_definitions[group_session_id]["title"] = next_title
        session_definitions[group_session_id]["title_auto_generated"] = False
    if body.host is not None:
        session_definitions[group_session_id]["host"] = body.host.model_dump()
        _clear_host_scheduler_state(group_session_id)
    direct_names = body.agent_names
    if direct_names is not None:
        instances = load_agent_instances()
        valid_names = set(_agent_name_map(instances))
        deduped = _dedupe_names(list(direct_names or []))
        _validate_agent_names(deduped, valid_names)
        session_definitions[group_session_id]["agent_names"] = deduped
        _clear_host_scheduler_state(group_session_id)
    add_names = body.add_agent_names
    remove_names = body.remove_agent_names
    if add_names or remove_names:
        instances = load_agent_instances()
        valid_names = set(_agent_name_map(instances))
        current = set(_dedupe_names(list(session_definitions[group_session_id].get("agent_names", []))))
        add_names_norm = _dedupe_names(list(add_names or []))
        remove_names_norm = _dedupe_names(list(remove_names or []))
        before_names = set(current)
        newly_added_names: List[str] = []
        if add_names_norm:
            _validate_agent_names(add_names_norm, valid_names)
            for name in add_names_norm:
                if name not in current:
                    newly_added_names.append(name)
                current.add(name)
        if remove_names_norm:
            for name in remove_names_norm:
                current.discard(name)
        session_definitions[group_session_id]["agent_names"] = list(current)
        if current != before_names:
            _clear_host_scheduler_state(group_session_id)
        # 成员变更：邀请 / 移出各写入一条系统提示（合并一次读写历史）
        unique_added = (
            list(
                dict.fromkeys(
                    [x for x in newly_added_names if x in current and x not in before_names],
                )
            )
            if newly_added_names
            else []
        )
        unique_removed = (
            list(dict.fromkeys([x for x in remove_names_norm if x in before_names]))
            if remove_names_norm
            else []
        )
        if unique_added or unique_removed:
            messages = _load_group_history(group_session_id)
            for name in unique_added:
                display_name = name
                messages.append(
                    {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "speaker": {"type": "host", "agent_name": _host_display_name(session_definitions[group_session_id])},
                        "message": {"content": f"已邀请“{display_name}”加入会话"},
                        "created_at": format_storage_timestamp(),
                    }
                )
            for name in unique_removed:
                display_name = name
                messages.append(
                    {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "speaker": {"type": "host", "agent_name": _host_display_name(session_definitions[group_session_id])},
                        "message": {"content": f"已将“{display_name}”移出会话"},
                        "created_at": format_storage_timestamp(),
                    }
                )
            _save_group_history(group_session_id, messages, checkpoint_trigger="session_changed")
    if _ensure_scene_profile_contract(session_definitions[group_session_id]):
        pass
    session_definitions[group_session_id]["updated_at"] = format_storage_timestamp()
    _save_session_definitions(session_definitions)
    try:
        from app.session_state.service import capture_session_checkpoint

        capture_session_checkpoint(group_session_id, trigger="session_changed")
    except Exception:
        logger.warning("session_state update checkpoint failed: %s", group_session_id, exc_info=True)
    return {"status": "ok", "data": _build_session_payload(group_session_id, session_definitions[group_session_id])}

async def delete_group_session(group_session_id: str):
    """删除群聊会话：同时删除会话定义、群聊历史文件与该会话的工作区目录。"""
    current_user = get_current_user()
    await _cancel_group_session_run(group_session_id, reason="session_deleted")
    try:
        from app.agent.sandbox_workspace_access import get_shared_sandbox_service

        await get_shared_sandbox_service().dispose_session(group_session_id, turn_id="session_deleted")
    except Exception:
        logger.warning("删除群聊 %s 时取消沙箱会话失败。", group_session_id, exc_info=True)
    session_definitions = _load_session_definitions()
    if group_session_id not in session_definitions:
        raise HTTPException(status_code=404, detail="Group session not found")
    del session_definitions[group_session_id]
    _save_session_definitions(session_definitions, preserve_unmentioned=False)
    _cleanup_orphan_group_histories(session_definitions)
    # 删除会话目录（history / workspace / checkpoints）
    user_ctx = current_user.ctx
    from app.session_state.paths import SessionLayoutPaths

    layout = SessionLayoutPaths.from_user_ctx(user_ctx, group_session_id)
    if layout.session_root.exists():
        try:
            shutil.rmtree(layout.session_root)
        except Exception:
            logger.warning("删除群聊 %s 的会话目录失败，可手动清理。", group_session_id, exc_info=True)
    return {"status": "ok", "data": {"id": group_session_id, "deleted": True}}

async def stop_group_session_run(group_session_id: str):
    """停止某个群聊会话当前正在运行的流式任务。"""
    session_definitions = _load_session_definitions()
    if group_session_id not in session_definitions:
        raise HTTPException(status_code=404, detail="Group session not found")
    cancelled = await _cancel_group_session_run(group_session_id, reason="user_stop")
    try:
        from app.agent.sandbox_workspace_access import get_shared_sandbox_service

        await get_shared_sandbox_service().dispose_session(group_session_id, turn_id="user_stop")
    except Exception:
        logger.warning("停止群聊 %s 时取消沙箱会话失败。", group_session_id, exc_info=True)
    return {"status": "ok", "data": {"id": group_session_id, "cancelled": cancelled}}

async def delete_group_message(group_session_id: str, message_id: str):
    """从会话列表和会话历史中彻底删除一条消息（含专家发言），避免污染下一轮 Agent 的上下文。"""
    _reject_group_session_mutation_if_running(group_session_id, operation="deleting messages")
    session_definitions = _load_session_definitions()
    if group_session_id not in session_definitions:
        raise HTTPException(status_code=404, detail="Group session not found")
    messages = _load_group_history(group_session_id)
    before = len(messages)
    messages = [m for m in messages if m.get("message_id") != message_id]
    if len(messages) == before:
        raise HTTPException(status_code=404, detail="Message not found")
    _save_group_history(group_session_id, messages, checkpoint_trigger="message_deleted")
    return {"status": "ok", "data": {"message_id": message_id, "deleted": True}}
