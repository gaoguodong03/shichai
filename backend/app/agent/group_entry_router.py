"""Pure structured entry routing for one group-chat request."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from app.agent.session_contracts import GroupChatRequest


class GroupEntryRoute(TypedDict):
    next_speaker: str
    next_action: str
    route_source: Literal["target_agent", "host_scheduler_state"]


def resolve_group_entry_route(
    *,
    request: GroupChatRequest,
    orchestration_state: dict[str, Any],
    agent_names: list[str],
    default_next_action: str,
) -> GroupEntryRoute | None:
    """Resolve explicit structured targets without interpreting user text."""
    if request.target_agent_name:
        return {
            "next_speaker": request.target_agent_name,
            "next_action": str(request.message or "").strip() or default_next_action,
            "route_source": "target_agent",
        }

    host_scheduler = (
        orchestration_state.get("host_scheduler")
        if isinstance(orchestration_state.get("host_scheduler"), dict)
        else {}
    )
    message = host_scheduler.get("message") if isinstance(host_scheduler.get("message"), dict) else {}
    target = str(message.get("target_agent_name") or "").strip()
    last_expert_turn = (
        orchestration_state.get("last_expert_turn")
        if isinstance(orchestration_state.get("last_expert_turn"), dict)
        else None
    )
    if last_expert_turn is not None:
        new_user_message = str(last_expert_turn.get("user_message_id") or "") != request.message_id
        can_resume_same_expert = (
            new_user_message
            and str(last_expert_turn.get("agent_turn") or "") == "respond"
            and str(last_expert_turn.get("skill_session") or "") == "keep"
            and str(last_expert_turn.get("execution_status") or "") in {"succeeded", "blocked", "failed"}
        )
        if not can_resume_same_expert:
            return None
    if target in agent_names:
        return {
            "next_speaker": target,
            "next_action": str(message.get("content") or "").strip() or default_next_action,
            "route_source": "host_scheduler_state",
        }
    return None
