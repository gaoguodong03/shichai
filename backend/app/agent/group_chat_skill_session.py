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

from app.agent.group_chat_tool_result_content import problem_tool_result_content
from app.agent.structured_output_contracts import SkillScriptStdoutPayload

_DEFAULT_NEXT_ACTION = {"agent_turn": "respond", "skill_session": "release"}
_GENERIC_EMPTY_CONTENT = {"", "模型没有返回可展示的文字内容。", "无可展示内容。"}


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
        return None, "脚本 stdout 不符合平台协议：缺少 next_action 或字段结构非法。"
    return None, ""


def _next_action_from_tool_results(tool_results: list[dict[str, Any]] | None) -> tuple[dict[str, str], str]:
    next_action = dict(_DEFAULT_NEXT_ACTION)
    protocol_error = ""
    for result in tool_results or []:
        if not isinstance(result, dict):
            continue
        tool_call = result.get("tool_call") if isinstance(result.get("tool_call"), dict) else {}
        if str(tool_call.get("kind") or "").strip() != "script":
            continue
        payload, error = _script_stdout_payload_from_result(result)
        if payload is not None:
            next_action = payload.next_action.model_dump()
        elif error and not protocol_error:
            protocol_error = error
    return next_action, protocol_error


def skill_result_from_content(
    *,
    status: str,
    content: str,
    artifacts: list[dict[str, Any]] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the canonical skill_result payload for an expert message."""
    normalized = status if status in {"succeeded", "blocked", "failed"} else "failed"
    next_action, protocol_error = _next_action_from_tool_results(tool_results)
    problem_content = problem_tool_result_content(tool_results)
    display_content = content or "无可展示内容。"
    if protocol_error:
        normalized = "failed"
        display_content = protocol_error
    elif problem_content and display_content.strip() in _GENERIC_EMPTY_CONTENT:
        display_content = problem_content
    return {
        "execution_status": normalized,
        "content": display_content,
        "artifacts": list(artifacts or []),
        "next_action": next_action,
    }


def apply_skill_result_to_orchestration_state(
    orchestration_state: dict[str, Any],
    *,
    agent_name: str,
    skill: str,
    skill_result: dict[str, Any],
) -> bool:
    """Apply message-level Skill session policy to orchestration_state."""
    next_action = skill_result.get("next_action") if isinstance(skill_result.get("next_action"), dict) else {}
    skill_policy = str(next_action.get("skill_session") or "release").strip()
    if skill_policy == "keep":
        row = {
            "owner_agent_name": str(agent_name or "").strip(),
            "skill_policy": "keep",
            "next_action": str(skill_result.get("content") or "").strip(),
        }
        skill_name = str(skill or "").strip()
        if skill_name:
            row["skill"] = skill_name
        previous = orchestration_state.get("continuation")
        orchestration_state["continuation"] = row
        return previous != row
    if "continuation" in orchestration_state:
        orchestration_state.pop("continuation", None)
        return True
    return False
