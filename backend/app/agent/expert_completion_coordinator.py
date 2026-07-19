"""Thin coordinator for applying one parsed expert completion."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.agent_turn_controller import AgentTurnResult, apply_agent_turn
from app.agent.expert_completion_contract import ParsedExpertCompletion
from app.agent.expert_output_publisher import PublishedExpertMessage, publish_expert_output
from app.agent.skill_session_manager import apply_skill_session
from app.api.group_chat_state import write_group_orchestration_state


@dataclass(frozen=True)
class AppliedExpertCompletion:
    published: PublishedExpertMessage | None
    agent_turn: AgentTurnResult


def coordinate_expert_completion(
    *,
    completion: ParsedExpertCompletion,
    orchestration_state: dict[str, Any],
    agent_name: str,
    skill: str,
    message_id: str,
    created_at: str,
    group_session_id: str,
    messages: list[dict[str, Any]],
    session_definitions: dict[str, dict[str, Any]],
    session_item: dict[str, Any],
    tool_results: list[dict[str, Any]],
) -> AppliedExpertCompletion:
    """Apply output, Skill affinity, then current-request turn control."""
    published = publish_expert_output(
        submission=completion.output,
        execution=completion.execution,
        agent_name=agent_name,
        skill=skill,
        message_id=message_id,
        created_at=created_at,
        group_session_id=group_session_id,
        messages=messages,
        session_definitions=session_definitions,
        session_item=session_item,
        tool_results=tool_results,
    )
    if apply_skill_session(
        orchestration_state,
        agent_name=agent_name,
        skill=skill,
        directive=completion.skill_session,
    ):
        write_group_orchestration_state(group_session_id, orchestration_state)
    agent_turn = apply_agent_turn(completion.agent_turn)
    return AppliedExpertCompletion(published=published, agent_turn=agent_turn)
