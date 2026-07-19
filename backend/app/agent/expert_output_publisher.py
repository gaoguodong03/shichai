"""Expert message construction and publication.

This module consumes expert output and execution outcome only. Runtime control
directives are deliberately outside its dependency boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.expert_completion_contract import (
    ExpertExecutionOutcome,
    ExpertOutputSubmission,
)
from app.agent.group_chat_tool_trace import record_group_chat_tool_trace
from app.api.group_chat_state import (
    frontend_history_message,
    save_group_history,
    save_session_definitions,
)


@dataclass(frozen=True)
class PublishedExpertMessage:
    record: dict[str, Any]


def build_expert_message_record(
    *,
    submission: ExpertOutputSubmission,
    execution: ExpertExecutionOutcome,
    agent_name: str,
    skill: str,
    message_id: str,
    created_at: str,
) -> PublishedExpertMessage | None:
    """Build one canonical expert message without interpreting runtime control."""
    if submission.is_empty:
        return None
    record = {
        "message_id": message_id,
        "speaker": {
            "type": "expert",
            "agent_name": str(agent_name or "").strip(),
            "skill": str(skill or "").strip(),
        },
        "message": submission.message.model_dump(exclude_none=True, exclude_defaults=True),
        "created_at": created_at,
        "skill_result": {"execution_status": execution.status},
    }
    return PublishedExpertMessage(record=frontend_history_message(record))


def publish_expert_output(
    *,
    submission: ExpertOutputSubmission,
    execution: ExpertExecutionOutcome,
    agent_name: str,
    skill: str,
    message_id: str,
    created_at: str,
    group_session_id: str,
    messages: list[dict[str, Any]],
    session_definitions: dict[str, dict[str, Any]],
    session_item: dict[str, Any],
    tool_results: list[dict[str, Any]],
) -> PublishedExpertMessage | None:
    """Persist one non-empty expert output and its associated tool trace."""
    published = build_expert_message_record(
        submission=submission,
        execution=execution,
        agent_name=agent_name,
        skill=skill,
        message_id=message_id,
        created_at=created_at,
    )
    if published is None:
        return None
    record_group_chat_tool_trace(
        group_session_id,
        message_id=str(published.record.get("message_id") or ""),
        agent_name=agent_name,
        skill=skill,
        tool_results=tool_results,
    )
    messages.append(published.record)
    save_group_history(group_session_id, messages, checkpoint_trigger="turn_completed")
    session_item["updated_at"] = created_at
    save_session_definitions(session_definitions)
    return published
