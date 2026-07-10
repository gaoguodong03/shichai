"""Pure tool-output flow helpers used by SimpleAgent.

This module decides whether tool outputs imply script continuation, whether
workspace write calls have already succeeded, and which client should synthesize
post-tool output. It does not call the model or execute tools.
"""
from __future__ import annotations

from typing import Any

from app.agent.simple_agent_finalization import _json_loads_maybe
from app.agent.simple_agent_tool_errors import _normalize_workspace_path_for_compare
from app.agent.simple_agent_tool_ids import _tool_call_args
from app.agent.structured_output_contracts import SkillScriptStdoutPayload

RUN_SKILL_SCRIPT_AGENT_TURN_CONTINUE = "continue"
WORKSPACE_WRITE_SUCCESS_MARKER = "已写入当前 Chat 工作区文件："
WORKSPACE_MUTATING_TOOL_NAMES = {
    "write_workspace_file",
    "edit_workspace_file",
    "rename_workspace_file",
}


def iter_run_skill_raw_output_payloads(tool_out: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract raw JSON payloads from run_skill_script tool output records."""
    raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out, dict) else None
    if not isinstance(raw_outputs, list):
        return []
    payloads: list[dict[str, Any]] = []
    for raw in raw_outputs:
        payload = _json_loads_maybe(raw)
        if isinstance(payload, dict):
            payloads.append(payload)
            stdout_payload = _json_loads_maybe(payload.get("stdout"))
            if isinstance(stdout_payload, dict):
                payloads.append(stdout_payload)
    return payloads


def iter_strict_skill_stdout_payloads(tool_out: dict[str, Any]) -> list[SkillScriptStdoutPayload]:
    """Validate extracted script payloads against the strict Skill stdout contract."""
    out: list[SkillScriptStdoutPayload] = []
    for payload in iter_run_skill_raw_output_payloads(tool_out):
        try:
            out.append(SkillScriptStdoutPayload.model_validate(payload))
        except Exception:
            continue
    return out


def run_skill_outputs_request_agent_turn_continue(tool_out: dict[str, Any]) -> bool:
    """Return whether strict script stdout requests another agent turn."""
    payloads = iter_strict_skill_stdout_payloads(tool_out)
    if not payloads:
        return False
    saw_continue = False
    for payload in payloads:
        if payload.execution_status == "failed":
            return False
        if payload.next_action.agent_turn == RUN_SKILL_SCRIPT_AGENT_TURN_CONTINUE:
            saw_continue = True
    return saw_continue


def has_successful_workspace_write_output(raw_outputs: list[str]) -> bool:
    """Return whether a tool output contains the canonical workspace-write success marker."""
    return any(WORKSPACE_WRITE_SUCCESS_MARKER in str(raw or "") for raw in raw_outputs or [])


def has_workspace_mutating_tool_call(tool_calls: list[Any]) -> bool:
    """Return whether tool calls include a workspace-mutating operation."""
    for tool_call in tool_calls or []:
        if not isinstance(tool_call, dict):
            continue
        if str(tool_call.get("name") or tool_call.get("tool") or "").strip() in WORKSPACE_MUTATING_TOOL_NAMES:
            return True
    return False


def workspace_write_call_key(tool_call: Any) -> str:
    """Build a stable key for one write_workspace_file call."""
    if not isinstance(tool_call, dict):
        return ""
    tool_name = str(tool_call.get("name") or tool_call.get("tool") or "").strip()
    if tool_name != "write_workspace_file":
        return ""
    args = _tool_call_args(tool_call)
    path = _normalize_workspace_path_for_compare(args.get("path") or args.get("__arg1"))
    content = str(args.get("content") or args.get("__arg2") or "")
    if not path or not content:
        return ""
    return f"{tool_name}\0{path}\0{content}"


def remember_successful_workspace_writes(tool_out: dict[str, Any], seen_keys: set[str]) -> None:
    """Record write_workspace_file calls only after canonical success output is present."""
    raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out, dict) else None
    if not isinstance(raw_outputs, list) or not has_successful_workspace_write_output(raw_outputs):
        return
    calls = tool_out.get("tool_calls") if isinstance(tool_out, dict) else None
    if not isinstance(calls, list):
        return
    for call in calls:
        key = workspace_write_call_key(call)
        if key:
            seen_keys.add(key)


def all_workspace_write_calls_already_succeeded(tool_calls: list[Any], seen_keys: set[str]) -> bool:
    """Return whether every pending tool call is a write already recorded as successful."""
    if not seen_keys or not tool_calls:
        return False
    saw_write = False
    for call in tool_calls:
        if not isinstance(call, dict):
            return False
        tool_name = str(call.get("name") or call.get("tool") or "").strip()
        if tool_name != "write_workspace_file":
            return False
        key = workspace_write_call_key(call)
        if not key or key not in seen_keys:
            return False
        saw_write = True
    return saw_write


def is_run_skill_script_workflow_step(tool_out: dict[str, Any]) -> bool:
    """Compatibility predicate for script-driven continue steps."""
    return run_skill_outputs_request_agent_turn_continue(tool_out)


def post_tool_synthesis_should_use_bound_client(tool_out: dict[str, Any]) -> bool:
    """Return whether synthesis should use the tool-bound model client."""
    calls = tool_out.get("tool_calls") if isinstance(tool_out, dict) else None
    if not isinstance(calls, list) or not calls:
        return False
    saw_call = False
    for call in calls:
        if not isinstance(call, dict):
            return False
        tool_name = str(call.get("tool") or call.get("name") or "").strip()
        if not tool_name:
            return False
        saw_call = True
        if not tool_name.startswith("run_skill_script"):
            return True
    return not saw_call
