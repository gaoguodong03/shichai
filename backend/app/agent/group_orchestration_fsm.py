"""Entry routing FSM for one group-chat turn.

This module owns the pre-host routing priority from
docs/contracts/runtime-interface-contract.md: target expert, host_scheduler,
and continuation. It mutates only the short-term orchestration_state object
passed by the caller and returns the chosen route.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from app.agent.session_contracts import GroupChatRequest


class GroupRouteDecision(TypedDict):
    next_speaker: str
    next_action: str
    route_source: Literal["empty_group", "target_agent", "host_scheduler_state", "continuation", "host_scheduler"]
    skill_policy: Literal["none", "keep", "release"]
    skill: str | None


def _route_decision(
    *,
    next_speaker: str,
    next_action: str,
    route_source: Literal["target_agent", "host_scheduler_state", "continuation"],
    skill_policy: Literal["none", "keep", "release"] = "none",
    skill: str | None = None,
) -> GroupRouteDecision:
    return {
        "next_speaker": next_speaker,
        "next_action": next_action,
        "route_source": route_source,
        "skill_policy": skill_policy,
        "skill": skill if skill_policy == "keep" else None,
    }


def resolve_group_entry_route(
    *,
    request: GroupChatRequest,
    orchestration_state: dict[str, Any],
    agent_names: list[str],
    host_name: str,
    default_next_action: str,
) -> tuple[GroupRouteDecision | None, bool]:
    """Resolve strict entry routing before calling the host scheduler."""
    _ = host_name
    changed = False
    continuation = orchestration_state.get("continuation") if isinstance(orchestration_state.get("continuation"), dict) else {}
    host_scheduler = orchestration_state.get("host_scheduler") if isinstance(orchestration_state.get("host_scheduler"), dict) else {}

    if request.target_agent_name:
        if continuation:
            orchestration_state.pop("continuation", None)
            changed = True
        return (
            _route_decision(
                next_speaker=request.target_agent_name,
                next_action=default_next_action,
                route_source="target_agent",
            ),
            changed,
        )

    scheduler_next = str((host_scheduler or {}).get("next_speaker") or "").strip()
    if scheduler_next in agent_names:
        continuation_owner = str((continuation or {}).get("owner_agent_name") or "").strip()
        if continuation_owner and continuation_owner != scheduler_next:
            orchestration_state.pop("continuation", None)
            changed = True
        return (
            _route_decision(
                next_speaker=scheduler_next,
                next_action=str((host_scheduler or {}).get("next_action") or "").strip() or default_next_action,
                route_source="host_scheduler_state",
            ),
            changed,
        )

    continuation = orchestration_state.get("continuation") if isinstance(orchestration_state.get("continuation"), dict) else {}
    owner = str((continuation or {}).get("owner_agent_name") or "").strip()
    skill_policy = str((continuation or {}).get("skill_policy") or "").strip()
    if owner:
        if owner not in agent_names or skill_policy not in {"keep", "release"}:
            orchestration_state.pop("continuation", None)
            changed = True
        else:
            return (
                _route_decision(
                    next_speaker=owner,
                    next_action=str(continuation.get("next_action") or "").strip() or default_next_action,
                    route_source="continuation",
                    skill_policy="keep" if skill_policy == "keep" else "release",
                    skill=str(continuation.get("skill") or "").strip() or None,
                ),
                changed,
            )

    return None, changed
