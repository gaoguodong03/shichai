"""Persist visible and traceable group-chat runtime failures."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Literal

from app.agent.group_chat_tool_trace import record_group_chat_tool_trace
from app.agent.session_runtime_logs import append_runtime_failure_log
from app.api.group_chat_state import (
    format_storage_timestamp,
    frontend_history_message,
    load_group_orchestration_state,
    save_group_history,
    save_session_definitions,
    write_group_orchestration_state,
)


def _failure_content(*, speaker_type: str, agent_name: str, error_code: str) -> str:
    if speaker_type == "expert":
        return f"{agent_name}本轮执行失败（错误码：{error_code}）。请稍后重试或调整任务。"
    return f"本轮群聊执行失败（错误码：{error_code}）。请稍后重试或调整任务。"


def _clear_failed_orchestration_state(group_session_id: str, *, agent_name: str) -> None:
    state = load_group_orchestration_state(group_session_id)
    state.pop("host_scheduler", None)
    sessions = state.get("skill_sessions") if isinstance(state.get("skill_sessions"), dict) else {}
    matching_key = next(
        (
            str(key)
            for key in sessions
            if str(key).strip().casefold() == str(agent_name or "").strip().casefold()
        ),
        None,
    )
    if matching_key is not None:
        sessions = dict(sessions)
        sessions.pop(matching_key, None)
        if sessions:
            state["skill_sessions"] = sessions
        else:
            state.pop("skill_sessions", None)
    write_group_orchestration_state(group_session_id, state)


def persist_group_chat_failure(
    *,
    group_session_id: str,
    session_definitions: Dict[str, Dict[str, Any]],
    session_item: Dict[str, Any],
    messages: List[Dict[str, Any]],
    speaker_type: Literal["host", "expert"],
    agent_name: str,
    skill: str,
    error_code: str,
    error_type: str,
    error_summary: str,
    phase: str,
    tool_results: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Persist a canonical failure message and its sanitized runtime log."""
    clean_agent_name = str(agent_name or "四九").strip() or "四九"
    clean_skill = str(skill or "").strip()
    clean_error_code = str(error_code or "GROUP_CHAT_RUNTIME_FAILED").strip() or "GROUP_CHAT_RUNTIME_FAILED"
    speaker: Dict[str, Any] = {"type": speaker_type, "agent_name": clean_agent_name}
    if clean_skill:
        speaker["skill"] = clean_skill
    failure_message: Dict[str, Any] = {
        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
        "speaker": speaker,
        "message": {
            "content": _failure_content(
                speaker_type=speaker_type,
                agent_name=clean_agent_name,
                error_code=clean_error_code,
            )
        },
        "created_at": format_storage_timestamp(),
    }
    if clean_skill:
        failure_message["skill_result"] = {
            "execution_status": "failed",
        }
    failure_message = frontend_history_message(failure_message)
    messages.append(failure_message)
    save_group_history(group_session_id, messages, checkpoint_trigger="turn_completed")
    session_item["updated_at"] = format_storage_timestamp()
    save_session_definitions(session_definitions)
    _clear_failed_orchestration_state(group_session_id, agent_name=clean_agent_name)
    append_runtime_failure_log(
        group_session_id,
        message_id=str(failure_message["message_id"]),
        agent_name=clean_agent_name,
        skill=clean_skill,
        error_code=clean_error_code,
        error_type=error_type,
        phase=phase,
        error_summary=error_summary,
    )
    record_group_chat_tool_trace(
        group_session_id,
        message_id=str(failure_message["message_id"]),
        agent_name=clean_agent_name,
        skill=clean_skill,
        tool_results=list(tool_results or []),
    )
    return failure_message
