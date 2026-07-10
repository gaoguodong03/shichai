"""Skill-result to cross-turn session state mapping.

This file owns the contract bridge from `skill_result.next_action` to
`orchestration_state.json.continuation`. Tool records are inspected only to
extract strict Skill stdout payloads; routing state is derived from
`skill_result`, not from ad hoc tool fields.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.agent.group_chat_tool_result_content import problem_tool_result_content
from app.agent.structured_output_contracts import SkillScriptStdoutPayload

_DEFAULT_NEXT_ACTION = {"agent_turn": "respond", "skill_session": "release"}
_GENERIC_EMPTY_CONTENT = {"", "模型没有返回可展示的文字内容。", "无可展示内容。"}
_HIDDEN_STATE_START = "[[SKILL_SESSION_STATE]]"
_HIDDEN_STATE_END = "[[/SKILL_SESSION_STATE]]"
_HIDDEN_STATE_TAIL_RE = re.compile(
    r"\s*\[\[SKILL_SESSION_STATE\]\]\s*(?P<body>\{.*\})\s*\[\[/SKILL_SESSION_STATE\]\]\s*\Z",
    re.S,
)


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


def _hidden_state_payload_from_content(content: str) -> tuple[str, SkillScriptStdoutPayload | None, str]:
    text = str(content or "")
    if _HIDDEN_STATE_START not in text and _HIDDEN_STATE_END not in text:
        return text, None, ""
    match = _HIDDEN_STATE_TAIL_RE.search(text)
    if not match:
        return text, None, "专家隐藏状态块不符合平台协议：必须直接追加到正文末尾并包含合法 JSON 对象。"
    visible = text[: match.start()].strip()
    payload = _strict_skill_stdout_payload(match.group("body"))
    if payload is None:
        return visible, None, "专家隐藏状态块不符合平台协议：缺少 next_action 或字段结构非法。"
    return visible, payload, ""


def _flow_payloads_conflict(first: SkillScriptStdoutPayload, second: SkillScriptStdoutPayload) -> bool:
    return first.model_dump() != second.model_dump()


def _skill_result_display_content(
    *,
    visible_content: str,
    script_payload: SkillScriptStdoutPayload | None,
    flow_payload: SkillScriptStdoutPayload | None,
) -> str:
    """Select the message fact content without letting script output be LLM-rewritten."""
    if script_payload is not None:
        return script_payload.content or "无可展示内容。"
    if flow_payload is not None:
        return visible_content or flow_payload.content or "无可展示内容。"
    return visible_content or "无可展示内容。"


def skill_result_from_content(
    *,
    status: str,
    content: str,
    artifacts: list[dict[str, Any]] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the canonical skill_result payload for an expert message."""
    normalized = status if status in {"succeeded", "blocked", "failed"} else "failed"
    visible_content, hidden_payload, hidden_error = _hidden_state_payload_from_content(content)
    script_payload, script_error = _script_payload_from_tool_results(tool_results)
    protocol_error = script_error or hidden_error
    flow_payload = hidden_payload or script_payload
    if not protocol_error and hidden_payload is not None and script_payload is not None and _flow_payloads_conflict(hidden_payload, script_payload):
        protocol_error = "同一轮出现互相冲突的 Skill 流程控制信号。"
        flow_payload = None
    if flow_payload is not None:
        normalized = flow_payload.execution_status
    next_action = flow_payload.next_action.model_dump() if flow_payload is not None else dict(_DEFAULT_NEXT_ACTION)
    problem_content = problem_tool_result_content(tool_results)
    display_content = _skill_result_display_content(
        visible_content=visible_content,
        script_payload=script_payload,
        flow_payload=flow_payload,
    )
    if protocol_error:
        normalized = "failed"
        display_content = protocol_error
    elif problem_content and display_content.strip() in _GENERIC_EMPTY_CONTENT:
        display_content = problem_content
    result_artifacts = script_payload.artifacts if script_payload is not None else list(artifacts or [])
    return {
        "execution_status": normalized,
        "content": display_content,
        "artifacts": [
            artifact.model_dump() if hasattr(artifact, "model_dump") else dict(artifact)
            for artifact in result_artifacts
            if isinstance(artifact, dict) or hasattr(artifact, "model_dump")
        ],
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
