"""Pure tool-output flow helpers used by SimpleAgent."""
from __future__ import annotations

import logging
from typing import Any

from app.agent.simple_agent_finalization import _json_loads_maybe
from app.agent.simple_agent_tool_ids import _tool_call_args
from app.agent.expert_completion_contract import SkillScriptStdoutPayload
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
