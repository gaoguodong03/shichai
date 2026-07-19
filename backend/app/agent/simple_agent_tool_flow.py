"""Pure tool-output flow helpers used by SimpleAgent.

This module decides whether workspace write calls have already succeeded and
which client should synthesize post-tool output. It does not call the model or
execute tools.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agent.simple_agent_finalization import _json_loads_maybe
from app.agent.simple_agent_tool_ids import _tool_call_args
from app.agent.expert_completion_contract import SkillScriptStdoutPayload
WORKSPACE_WRITE_SUCCESS_MARKERS = (
    "已写入当前 Chat 工作区文件：",
)
WORKSPACE_MUTATING_TOOL_NAMES = {
    "write_workspace_file",
    "edit_workspace_file",
    "rename_workspace_file",
}
logger = logging.getLogger(__name__)


def _normalize_workspace_path_for_compare(path: Any) -> str:
    text = str(path or "").strip().replace("\\", "/").strip("/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


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


def has_successful_workspace_write_output(raw_outputs: list[str]) -> bool:
    """Return whether a tool output contains the canonical workspace-write success marker."""
    return any(marker in str(raw or "") for raw in raw_outputs or [] for marker in WORKSPACE_WRITE_SUCCESS_MARKERS)


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
    path = _normalize_workspace_path_for_compare(args.get("path"))
    content = str(args.get("content") or "")
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


def read_file_should_synthesize_after_result(
    tool_out: dict[str, Any],
    synthesize_after_read_file_paths: tuple[str, ...],
    tool_attempt_debug: list[dict[str, Any]],
) -> bool:
    """Return whether a read_workspace_file result should trigger synthesis."""
    targets = {
        _normalize_workspace_path_for_compare(path)
        for path in (synthesize_after_read_file_paths or ())
        if _normalize_workspace_path_for_compare(path)
    }
    if not targets:
        return False
    calls = tool_out.get("tool_calls") if isinstance(tool_out, dict) else None
    if not isinstance(calls, list):
        return False
    for call in calls:
        if not isinstance(call, dict):
            continue
        tool_name = str(call.get("tool") or call.get("name") or "").strip()
        if tool_name != "read_workspace_file":
            continue
        args = _tool_call_args(call)
        path = _normalize_workspace_path_for_compare(args.get("path"))
        if not path:
            continue
        if not any(path == target or path.endswith(f"/{target}") for target in targets):
            continue
        logger.info("SimpleAgent: synthesize_after_read_workspace_file tool=%s path=%s", tool_name, path)
        tool_attempt_debug.append(
            {
                "source": "synthesize_after_read_workspace_file",
                "matched": True,
                "tool": tool_name,
                "path": path,
            }
        )
        return True
    return False
