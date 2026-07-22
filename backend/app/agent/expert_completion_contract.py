"""Strict expert completion parsing and internal domain projection.

The model-facing JSON remains ``execution_status + message + next_action``.
This module validates that external payload once, then projects it into four
independent platform objects. It performs no persistence, routing, or SSE work.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError, model_validator

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


def _json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _strict_skill_stdout_payload(value: Any) -> SkillScriptStdoutPayload | None:
    payload = _json_object(value)
    if payload is None:
        return None
    try:
        return SkillScriptStdoutPayload.model_validate(payload)
    except ValidationError:
        return None


def _script_stdout_payload_from_result(
    result: dict[str, Any],
) -> tuple[SkillScriptStdoutPayload | None, str]:
    output = result.get("output") if isinstance(result.get("output"), dict) else {}
    for candidate in (output.get("stdout"), output.get("json_data"), result):
        parsed = _strict_skill_stdout_payload(candidate)
        if parsed is not None:
            return parsed, ""
    if str(result.get("execution_status") or "").strip() == "succeeded":
        return None, "脚本 stdout 不符合平台协议：缺少 message、next_action 或字段结构非法。"
    return None, ""


def _script_payload_from_tool_results(
    tool_results: list[dict[str, Any]] | None,
) -> tuple[SkillScriptStdoutPayload | None, str]:
    payload: SkillScriptStdoutPayload | None = None
    for result in tool_results or []:
        if not isinstance(result, dict):
            continue
        tool_call = result.get("tool_call") if isinstance(result.get("tool_call"), dict) else {}
        if str(tool_call.get("kind") or "").strip() != "script":
            continue
        parsed, error = _script_stdout_payload_from_result(result)
        if parsed is not None:
            if payload is not None and parsed.model_dump() != payload.model_dump():
                return None, "同一轮出现多个互相冲突的 Skill 流程控制信号。"
            payload = parsed
        elif error:
            return None, error
    return payload, ""


def select_expert_completion(
    *,
    final_content: str,
    tool_results: list[dict[str, Any]] | None = None,
) -> ParsedExpertCompletion:
    """Select one valid completion from finalizer JSON or script stdout."""
    content_payload: ExpertFinalStatePayload | None = None
    content_error: Exception | None = None
    if str(final_content or "").strip():
        try:
            content_payload = parse_strict_pydantic_object(final_content, ExpertFinalStatePayload)
        except Exception as exc:
            content_error = exc
    script_payload, script_error = _script_payload_from_tool_results(tool_results)
    if script_error:
        raise ExpertFinalStateProtocolError(script_error)
    selected = script_payload or content_payload
    if selected is None:
        raise ExpertFinalStateProtocolError("专家没有产出合格的 expert_final_state.v2。") from content_error
    payload = ExpertFinalStatePayload.model_validate(selected.model_dump())
    return project_expert_completion(payload)
