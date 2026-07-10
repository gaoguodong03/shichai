from __future__ import annotations

import json
from typing import Any

from app.agent.messages import AIMessage


def _content_from_mcp_result(payload: dict[str, Any]) -> str:
    if str(payload.get("execution_status") or "").strip() != "succeeded":
        return ""
    return str(payload.get("content") or "").strip()


def _mcp_tool_result_direct_final_message(tool_out: dict[str, Any]) -> AIMessage | None:
    """Surface standard MCP content directly instead of asking the LLM to restate it."""
    calls = tool_out.get("tool_calls") if isinstance(tool_out, dict) else None
    if not isinstance(calls, list) or not calls:
        return None
    if any(
        isinstance(call, dict) and str(call.get("tool") or call.get("name") or "").startswith("run_skill_script_")
        for call in calls
    ):
        return None

    raw_outputs = tool_out.get("tool_raw_outputs")
    if not isinstance(raw_outputs, list):
        return None
    for raw in raw_outputs:
        try:
            outer = json.loads(str(raw or ""))
        except Exception:
            continue
        if not isinstance(outer, dict):
            continue
        text = _content_from_mcp_result(outer)
        if text:
            return AIMessage(content=text)

        stdout = outer.get("stdout")
        if not isinstance(stdout, str) or not stdout.strip():
            continue
        try:
            payload = json.loads(stdout.strip())
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        text = _content_from_mcp_result(payload)
        if text:
            return AIMessage(content=text)
    return None
