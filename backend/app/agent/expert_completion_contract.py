"""Strict expert completion parsing and internal domain projection.

The model-facing JSON remains ``execution_status + message + next_action``.
This module validates that external payload once, then projects it into four
independent platform objects. It performs no persistence, routing, or SSE work.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import model_validator

from app.agent.structured_output_contracts import (
    ExpertFinalMessageBody,
    StrictModel,
    parse_strict_pydantic_object,
)


class ExpertFinalStateProtocolError(ValueError):
    """Raised when an expert turn did not produce one valid final state."""


class SkillNextAction(StrictModel):
    agent_turn: Literal["continue", "respond"]
    skill_session: Literal["keep", "release"]


class ExpertFinalStatePayload(StrictModel):
    execution_status: Literal["succeeded", "blocked", "failed"]
    message: ExpertFinalMessageBody
    next_action: SkillNextAction

    @model_validator(mode="after")
    def _validate_message_for_action(self) -> "ExpertFinalStatePayload":
        if self.next_action.agent_turn == "respond" and not self.message.content.strip():
            raise ValueError("agent_turn=respond requires non-empty message.content")
        return self


class SkillScriptStdoutPayload(ExpertFinalStatePayload):
    pass


@dataclass(frozen=True)
class ExpertExecutionOutcome:
    status: Literal["succeeded", "blocked", "failed"]


@dataclass(frozen=True)
class ExpertOutputSubmission:
    message: ExpertFinalMessageBody

    @property
    def is_empty(self) -> bool:
        return not (
            self.message.content.strip()
            or self.message.attachments
            or self.message.artifacts
        )


@dataclass(frozen=True)
class AgentTurnDirective:
    action: Literal["continue", "respond"]


@dataclass(frozen=True)
class SkillSessionDirective:
    action: Literal["keep", "release"]


@dataclass(frozen=True)
class ParsedExpertCompletion:
    execution: ExpertExecutionOutcome
    output: ExpertOutputSubmission
    agent_turn: AgentTurnDirective
    skill_session: SkillSessionDirective


def project_expert_completion(payload: ExpertFinalStatePayload) -> ParsedExpertCompletion:
    """Project one validated model payload into independent platform objects."""
    return ParsedExpertCompletion(
        execution=ExpertExecutionOutcome(status=payload.execution_status),
        output=ExpertOutputSubmission(message=payload.message),
        agent_turn=AgentTurnDirective(action=payload.next_action.agent_turn),
        skill_session=SkillSessionDirective(action=payload.next_action.skill_session),
    )


def parse_expert_completion(content: str) -> ParsedExpertCompletion:
    """Parse the unchanged model JSON and return its internal projection."""
    try:
        payload = parse_strict_pydantic_object(str(content or ""), ExpertFinalStatePayload)
    except Exception as exc:
        raise ExpertFinalStateProtocolError("专家没有产出合格的 expert_final_state.v2。") from exc
    return project_expert_completion(payload)


def select_expert_completion(
    *,
    final_content: str,
    tool_results: list[dict] | None = None,
) -> ParsedExpertCompletion:
    """Use only the finalizer JSON as the expert turn's control state.

    Script stdout may also follow this schema, but it is a model-visible tool
    result rather than a control signal for the enclosing expert turn.
    """
    # Retain the argument for callers that also persist tool traces. Tool output
    # is model context, not a second source of expert-turn control state.
    _ = tool_results
    return parse_expert_completion(final_content)
