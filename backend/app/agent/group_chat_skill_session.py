"""Skill-session lock helpers for group-chat runtime."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.agent.group_orchestration_fsm import (
    ORCHESTRATION_SCENE,
    clear_skill_session_lock,
    persist_skill_session_lock,
)
from app.agent.skill_session_contract import resolve_skill_session_state


def _tool_names_from_history_message(msg: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    results = msg.get("tool_results")
    for result in results if isinstance(results, list) else []:
        if not isinstance(result, dict):
            continue
        call = result.get("tool_call")
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _tool_output_payloads_from_history_message(msg: Dict[str, Any]) -> List[str]:
    payloads: List[str] = []
    results = msg.get("tool_results")
    for result in results if isinstance(results, list) else []:
        if not isinstance(result, dict):
            continue
        output = result.get("output")
        if isinstance(output, dict):
            json_data = output.get("json_data")
            if json_data is not None:
                try:
                    payloads.append(json.dumps(json_data, ensure_ascii=False))
                except Exception:
                    payloads.append(str(json_data))
            for key in ("stdout", "text", "markdown", "stderr"):
                value = str(output.get(key) or "").strip()
                if value:
                    payloads.append(value)
        error_log = result.get("error_log")
        if isinstance(error_log, dict):
            for key in ("raw_output", "stdout", "stderr", "message", "detail"):
                value = str(error_log.get(key) or "").strip()
                if value:
                    payloads.append(value)
    return payloads


def _tool_trace_items(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    debug = msg.get("debug")
    trace = debug.get("tool_trace") if isinstance(debug, dict) else None
    return [item for item in trace if isinstance(item, dict)] if isinstance(trace, list) else []


def _has_bound_skill_introspection_direct_final(debug_items: Any) -> bool:
    if not isinstance(debug_items, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("source") == "bound_skill_introspection_direct_final"
        and item.get("matched") is True
        for item in debug_items
    )


def _message_is_bound_skill_introspection_direct_final(msg: Dict[str, Any]) -> bool:
    for item in _tool_trace_items(msg):
        data = item.get("data")
        attempts = data.get("tool_attempt_debug") if isinstance(data, dict) else None
        if _has_bound_skill_introspection_direct_final(attempts):
            return True
    return False


def _message_role(msg: Dict[str, Any]) -> str:
    speaker = msg.get("speaker")
    if isinstance(speaker, dict):
        return str(speaker.get("type") or "").strip()
    return str(msg.get("role") or "").strip()


def _message_agent_name(msg: Dict[str, Any]) -> str:
    speaker = msg.get("speaker")
    if isinstance(speaker, dict):
        return str(speaker.get("agent_name") or "").strip()
    return str(msg.get("agent_name") or "").strip()


def _message_skill(msg: Dict[str, Any]) -> str:
    speaker = msg.get("speaker")
    if isinstance(speaker, dict):
        return str(speaker.get("skill") or "").strip()
    return str(msg.get("skill") or "").strip()


def _skill_session_from_message_result(msg: Dict[str, Any]) -> str:
    result = msg.get("skill_result")
    if not isinstance(result, dict):
        return ""
    action = result.get("next_action")
    if not isinstance(action, dict):
        return ""
    return str(action.get("skill_session") or "").strip().lower()


def _store_skill_session_lock_for_turn(
    session_item: Dict[str, Any],
    *,
    owner_agent_name: str,
    skill: str,
    skill_session_over: Optional[bool],
    force_keep: bool = False,
) -> None:
    """Persist cross-request Skill routing only for explicit continuation states."""
    if skill_session_over is True:
        clear_skill_session_lock(session_item)
    elif skill_session_over is False or force_keep:
        persist_skill_session_lock(session_item, owner_agent_name=owner_agent_name, skill=skill)
    else:
        clear_skill_session_lock(session_item)


def _should_handoff_to_host_after_expert(
    *,
    orchestration_profile: str,
    skill_session_over: Optional[bool],
    has_auto_continue_signal: bool,
) -> bool:
    """Decide whether an expert turn should immediately return to the host scheduler."""
    if skill_session_over is False:
        return False
    if str(orchestration_profile or "").strip().lower() == ORCHESTRATION_SCENE:
        return True
    return skill_session_over is True or has_auto_continue_signal


def _clear_completed_skill_session_lock_from_history(
    session_item: Dict[str, Any],
    messages: List[Dict[str, Any]],
) -> bool:
    """Clear stale locks unless the last matching expert turn explicitly asked to continue."""
    owner = str(session_item.get("skill_session_owner_name") or "").strip().casefold()
    skill = str(session_item.get("skill_session_skill") or "").strip()
    if not owner or not skill:
        return False
    for msg in reversed(messages or []):
        if _message_role(msg) not in {"assistant", "expert"}:
            continue
        if _message_agent_name(msg).casefold() != owner:
            continue
        if _message_skill(msg) != skill:
            continue
        if _message_is_bound_skill_introspection_direct_final(msg):
            clear_skill_session_lock(session_item)
            return True
        parsed_from_result = _skill_session_from_message_result(msg)
        if parsed_from_result in {"keep", "release"}:
            if parsed_from_result == "keep":
                return False
            clear_skill_session_lock(session_item)
            return True
        for item in _tool_trace_items(msg):
            data = item.get("data")
            state = data.get("skill_session_state") if isinstance(data, dict) else None
            if isinstance(state, dict):
                parsed_session = str(state.get("skill_session") or "").strip().lower()
                if parsed_session in {"keep", "release"}:
                    if parsed_session == "keep":
                        return False
                    clear_skill_session_lock(session_item)
                    return True
                parsed = state.get("over")
                if isinstance(parsed, bool):
                    if parsed is False:
                        return False
                    clear_skill_session_lock(session_item)
                    return True
        if msg.get("required_user_fields"):
            return False
        tool_names = _tool_names_from_history_message(msg)
        tool_outputs = _tool_output_payloads_from_history_message(msg)
        resolved = resolve_skill_session_state(
            str(msg.get("content") or ""),
            tool_outputs or None,
            tool_names=tool_names or None,
        )
        if resolved.over is False:
            return False
        clear_skill_session_lock(session_item)
        return True
    return False
