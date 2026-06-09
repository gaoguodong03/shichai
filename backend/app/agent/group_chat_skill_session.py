"""Skill-session lock helpers for group-chat runtime."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.group_orchestration_fsm import (
    ORCHESTRATION_SCENE,
    clear_skill_session_lock,
    persist_skill_session_lock,
)
from app.agent.skill_session_contract import resolve_skill_session_state


def _tool_names_from_history_message(msg: Dict[str, Any]) -> List[str]:
    debug = msg.get("tool_debug")
    calls = debug.get("tool_calls") if isinstance(debug, dict) else None
    if not isinstance(calls, list):
        return []
    names: List[str] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        name = str(call.get("tool") or call.get("name") or "").strip()
        if name:
            names.append(name)
    return names


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
    debug = msg.get("tool_debug")
    items = debug.get("tool_attempt_debug") if isinstance(debug, dict) else None
    return _has_bound_skill_introspection_direct_final(items)


def _store_skill_session_lock_for_turn(
    meta_item: Dict[str, Any],
    *,
    owner_agent_id: str,
    skill_id: str,
    skill_session_over: Optional[bool],
    force_keep: bool = False,
) -> None:
    """Persist cross-request Skill routing only for explicit continuation states."""
    if skill_session_over is True:
        clear_skill_session_lock(meta_item)
    elif skill_session_over is False or force_keep:
        persist_skill_session_lock(meta_item, owner_agent_id=owner_agent_id, skill_id=skill_id)
    else:
        clear_skill_session_lock(meta_item)


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
    meta_item: Dict[str, Any],
    messages: List[Dict[str, Any]],
) -> bool:
    """Clear stale locks unless the last matching expert turn explicitly asked to continue."""
    owner = str(meta_item.get("skill_session_owner_id") or "").strip().lower()
    skill_id = str(meta_item.get("skill_session_skill_id") or "").strip()
    if not owner or not skill_id:
        return False
    for msg in reversed(messages or []):
        if str(msg.get("role") or "") != "assistant":
            continue
        if str(msg.get("agent_id") or "").strip().lower() != owner:
            continue
        if str(msg.get("skill_id") or "").strip() != skill_id:
            continue
        if _message_is_bound_skill_introspection_direct_final(msg):
            clear_skill_session_lock(meta_item)
            return True
        debug = msg.get("tool_debug")
        state = debug.get("skill_session_state") if isinstance(debug, dict) else None
        if isinstance(state, dict):
            parsed_session = str(state.get("skill_session") or "").strip().lower()
            if parsed_session in {"keep", "release"}:
                if parsed_session == "keep":
                    return False
                clear_skill_session_lock(meta_item)
                return True
            parsed = state.get("over")
            if isinstance(parsed, bool):
                if parsed is False:
                    return False
                clear_skill_session_lock(meta_item)
                return True
        if msg.get("required_user_fields"):
            return False
        raw_results = msg.get("tool_raw_results")
        tool_names = _tool_names_from_history_message(msg)
        resolved = resolve_skill_session_state(
            str(msg.get("content") or ""),
            raw_results if isinstance(raw_results, list) else None,
            tool_names=tool_names or None,
        )
        if resolved.over is False:
            return False
        clear_skill_session_lock(meta_item)
        return True
    return False
