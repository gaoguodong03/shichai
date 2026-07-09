"""Entry routing FSM for one group-chat turn.

This module owns the pre-host routing priority from
docs/contracts/runtime-interface-contract.md: target expert, host takeover,
host_scheduler, and continuation. It mutates only the short-term
orchestration_state object passed by the caller and returns the chosen route.
"""
from __future__ import annotations

from typing import Any

from app.agent.group_host_decision import user_requests_host_takeover
from app.agent.session_contracts import GroupChatRequest


def resolve_group_entry_route(
    *,
    request: GroupChatRequest,
    orchestration_state: dict[str, Any],
    agent_names: list[str],
    host_name: str,
    default_next_action: str,
) -> tuple[str, str, bool]:
    """Resolve strict entry routing before calling the host scheduler."""
    changed = False
    continuation = orchestration_state.get("continuation") if isinstance(orchestration_state.get("continuation"), dict) else {}
    host_scheduler = orchestration_state.get("host_scheduler") if isinstance(orchestration_state.get("host_scheduler"), dict) else {}

    if request.target_agent_name:
        if continuation:
            orchestration_state.pop("continuation", None)
            changed = True
        return request.target_agent_name, default_next_action, changed

    if continuation and user_requests_host_takeover(request.message, explicit_flag=None, host_display_name=host_name):
        orchestration_state.pop("continuation", None)
        changed = True

    scheduler_next = str((host_scheduler or {}).get("next_speaker") or "").strip()
    if scheduler_next in agent_names:
        continuation_owner = str((continuation or {}).get("owner_agent_name") or "").strip()
        if continuation_owner and continuation_owner != scheduler_next:
            orchestration_state.pop("continuation", None)
            changed = True
        return scheduler_next, str((host_scheduler or {}).get("next_action") or "").strip() or default_next_action, changed

    continuation = orchestration_state.get("continuation") if isinstance(orchestration_state.get("continuation"), dict) else {}
    owner = str((continuation or {}).get("owner_agent_name") or "").strip()
    skill_policy = str((continuation or {}).get("skill_policy") or "").strip()
    if owner:
        if owner not in agent_names or skill_policy not in {"keep", "release"}:
            orchestration_state.pop("continuation", None)
            changed = True
        else:
            return owner, str(continuation.get("next_action") or "").strip() or default_next_action, changed

    return "", default_next_action, changed
