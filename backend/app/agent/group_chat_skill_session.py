"""Skill-result to cross-turn session state mapping.

This file owns the contract bridge from `skill_result.next_action` to
`orchestration_state.json.continuation`. Tool records are inspected only to
extract strict Skill stdout payloads; routing state is derived from
`skill_result`, not from ad hoc tool fields.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.agent.structured_output_contracts import (
    ExpertFinalStatePayload,
    SkillScriptStdoutPayload,
    parse_strict_pydantic_object,
)


class ExpertFinalStateProtocolError(ValueError):
    """Raised when an expert turn did not produce expert_final_state.v2."""


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
    if not isinstance(payload, dict):
        return None
    try:
        return SkillScriptStdoutPayload.model_validate(payload)
    except ValidationError:
        return None


def _script_stdout_payload_from_result(result: dict[str, Any]) -> tuple[SkillScriptStdoutPayload | None, str]:
    """Parse one script tool result and report successful-result protocol errors."""
    output = result.get("output") if isinstance(result.get("output"), dict) else {}
    for candidate in (
        output.get("stdout"),
        output.get("json_data"),
        result,
    ):
        parsed = _strict_skill_stdout_payload(candidate)
        if parsed is not None:
            return parsed, ""
    if str(result.get("execution_status") or "").strip() == "succeeded":
        return None, "脚本 stdout 不符合平台协议：缺少 schema_version、next_action 或字段结构非法。"
    return None, ""


def _script_payload_from_tool_results(tool_results: list[dict[str, Any]] | None) -> tuple[SkillScriptStdoutPayload | None, str]:
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


def _flow_payloads_conflict(first: SkillScriptStdoutPayload, second: SkillScriptStdoutPayload) -> bool:
    return first.model_dump() != second.model_dump()


def parse_expert_final_state_content(content: str) -> ExpertFinalStatePayload:
    """Parse the only legal expert final message payload."""
    try:
        return parse_strict_pydantic_object(str(content or ""), ExpertFinalStatePayload)
    except Exception as exc:
        raise ExpertFinalStateProtocolError("专家没有产出合格的 expert_final_state.v2。") from exc


def select_expert_final_state(
    *,
    final_content: str,
    tool_results: list[dict[str, Any]] | None = None,
) -> ExpertFinalStatePayload:
    """Select the unique final state from finalizer output or script stdout."""
    content_payload: ExpertFinalStatePayload | None = None
    content_error: Exception | None = None
    if str(final_content or "").strip():
        try:
            content_payload = parse_expert_final_state_content(final_content)
        except ExpertFinalStateProtocolError as exc:
            content_error = exc
    script_payload, script_error = _script_payload_from_tool_results(tool_results)
    if script_error:
        raise ExpertFinalStateProtocolError(script_error)
    if content_payload is not None and script_payload is not None and _flow_payloads_conflict(content_payload, script_payload):
        raise ExpertFinalStateProtocolError("同一轮出现多个互相冲突的 expert_final_state.v2。")
    payload = content_payload or script_payload
    if payload is None:
        raise ExpertFinalStateProtocolError("专家没有产出合格的 expert_final_state.v2。") from content_error
    return ExpertFinalStatePayload.model_validate(payload.model_dump())


def message_from_expert_final_state(final_state: ExpertFinalStatePayload) -> dict[str, Any]:
    return final_state.message.model_dump(exclude_none=True, exclude_defaults=True)


def skill_result_from_expert_final_state(final_state: ExpertFinalStatePayload) -> dict[str, Any]:
    return {
        "execution_status": final_state.execution_status,
        "next_action": final_state.next_action.model_dump(),
    }


def apply_skill_result_to_orchestration_state(
    orchestration_state: dict[str, Any],
    *,
    agent_name: str,
    skill: str,
    skill_result: dict[str, Any],
    message: dict[str, Any] | None = None,
) -> bool:
    """Apply message-level Skill session policy to orchestration_state."""
    next_action = skill_result.get("next_action") if isinstance(skill_result.get("next_action"), dict) else {}
    skill_session = str(next_action.get("skill_session") or "release").strip()
    previous_host_scheduler = orchestration_state.pop("host_scheduler", None)
    if skill_session == "keep":
        row = {
            "owner_agent_name": str(agent_name or "").strip(),
            "skill_session": "keep",
            "message": dict(message or {}),
        }
        skill_name = str(skill or "").strip()
        if skill_name:
            row["skill"] = skill_name
        previous = orchestration_state.get("continuation")
        orchestration_state["continuation"] = row
        return previous != row or previous_host_scheduler is not None
    if "continuation" in orchestration_state:
        orchestration_state.pop("continuation", None)
        return True
    return previous_host_scheduler is not None
