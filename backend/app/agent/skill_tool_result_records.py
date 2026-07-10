from __future__ import annotations

import json
from typing import Any

from app.agent.platform_prompts import render_platform_prompt
from app.agent.tool_trace_contracts import ToolResultRecord


_WORKSPACE_TOOL_NAMES = {
    "read_workspace_file",
    "write_workspace_file",
    "edit_workspace_file",
    "rename_workspace_file",
    "mkdir_workspace",
    "list_workspace_directory",
}


def _tool_metadata(tool: object) -> dict[str, Any]:
    metadata = getattr(tool, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def _tool_mcp_identity(tool: object) -> tuple[str, str]:
    metadata = _tool_metadata(tool)
    return (
        str(metadata.get("mcp_server_name") or "").strip(),
        str(metadata.get("mcp_tool_name") or "").strip(),
    )


def _tool_trace_identity(tool: object | None) -> tuple[str, str, str]:
    metadata = _tool_metadata(tool) if tool is not None else {}
    return (
        str(metadata.get("source") or "").strip(),
        str(metadata.get("provider") or "").strip(),
        str(metadata.get("provider_tool") or "").strip(),
    )


def _tool_call_kind(tool_name: str, tool: object | None = None) -> str:
    source, _provider, _provider_tool = _tool_trace_identity(tool)
    if source in {"mcp", "script", "workspace", "api"}:
        return source
    server_name, provider_tool = _tool_mcp_identity(tool) if tool is not None else ("", "")
    if server_name or provider_tool:
        return "mcp"
    name = str(tool_name or "").strip()
    if name.startswith("run_skill_script_"):
        return "script"
    if name in _WORKSPACE_TOOL_NAMES:
        return "workspace"
    if name.startswith("http_api_"):
        return "api"
    raise ValueError(f"tool source is missing for {name or 'tool'}")


def _stable_tool_call_name(tool_name: str, tool: object | None = None) -> str:
    _source, _provider, trace_provider_tool = _tool_trace_identity(tool)
    if trace_provider_tool:
        return trace_provider_tool
    _server_name, provider_tool = _tool_mcp_identity(tool) if tool is not None else ("", "")
    if provider_tool:
        return provider_tool
    if str(tool_name or "").startswith("run_skill_script_"):
        return "run_skill_script"
    return str(tool_name or "").strip() or "unknown"


def _tool_call_record_payload(*, tool_name: str, tool: object | None, arguments: dict, tool_call_id: str) -> dict:
    _source, provider, provider_tool = _tool_trace_identity(tool)
    if not provider and not provider_tool:
        provider, provider_tool = _tool_mcp_identity(tool) if tool is not None else ("", "")
    payload = {
        "id": str(tool_call_id or tool_name or "tool"),
        "name": _stable_tool_call_name(tool_name, tool),
        "kind": _tool_call_kind(tool_name, tool),
        "arguments": dict(arguments or {}),
    }
    if provider:
        payload["provider"] = provider
    if provider_tool:
        payload["provider_tool"] = provider_tool
    return payload


def _json_object_from_result(raw_result: object) -> dict | None:
    if isinstance(raw_result, dict):
        return raw_result
    text = str(raw_result or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _tool_result_record_from_raw(*, tool_name: str, tool: object | None, arguments: dict, tool_call_id: str, raw_result: object) -> dict:
    if isinstance(raw_result, ToolResultRecord):
        return raw_result.model_dump(exclude_none=True)
    raw_payload = _json_object_from_result(raw_result)
    if isinstance(raw_payload, dict) and raw_payload.get("tool_call") and raw_payload.get("execution_status"):
        return ToolResultRecord.model_validate(raw_payload).model_dump(exclude_none=True)
    text = str(raw_result or "")
    status = "succeeded"
    message = "工具执行成功"
    output: dict[str, Any] = {"text": text}
    error_log = None
    if str(tool_name or "").startswith("run_skill_script_") and isinstance(raw_payload, dict):
        stdout = str(raw_payload.get("stdout") or "")
        stderr = str(raw_payload.get("stderr") or "")
        returncode = raw_payload.get("returncode")
        ok = raw_payload.get("ok")
        code = str(raw_payload.get("code") or "").strip()
        message = str(raw_payload.get("message") or "").strip() or message
        output = {"text": text, "stdout": stdout, "stderr": stderr, "json_data": raw_payload}
        status = "failed" if ok is False or (isinstance(returncode, int) and returncode != 0) else "succeeded"
        if status == "failed":
            error_log = {"message": message or stderr or "脚本执行失败", "stdout": stdout, "stderr": stderr, "raw_output": text, "retryable": False}
    payload = {
        "tool_call": _tool_call_record_payload(tool_name=tool_name, tool=tool, arguments=arguments, tool_call_id=tool_call_id),
        "execution_status": status,
        "message": message,
        "output": output,
    }
    if error_log is not None:
        payload["error_log"] = error_log
    return ToolResultRecord.model_validate(payload).model_dump(exclude_none=True)


def _tool_result_record_from_exception(*, tool_name: str, tool: object | None, arguments: dict, tool_call_id: str, error: Exception) -> dict:
    message = str(error or "").strip() or "工具执行异常"
    payload = {
        "tool_call": _tool_call_record_payload(tool_name=tool_name, tool=tool, arguments=arguments, tool_call_id=tool_call_id),
        "execution_status": "failed",
        "message": message,
        "error_log": {"message": message, "detail": type(error).__name__, "raw_output": message, "retryable": False},
    }
    return ToolResultRecord.model_validate(payload).model_dump(exclude_none=True)


def _missing_tool_result_record(*, tool_name: str, arguments: dict, tool_call_id: str, available_tools: list[str]) -> dict:
    status = "blocked" if tool_name == "read_workspace_file" else "failed"
    message = (
        render_platform_prompt("skill.execution.read_workspace_unavailable.v1", {})
        if status == "blocked"
        else render_platform_prompt("skill.execution.tool_missing_message.v1", {"tool_name": tool_name, "available_tools": ", ".join(available_tools)})
    )
    payload: dict[str, Any] = {
        "tool_call": _tool_call_record_payload(tool_name=tool_name, tool=None, arguments=arguments, tool_call_id=tool_call_id),
        "execution_status": status,
        "message": message,
        "output": {"text": message},
    }
    if status != "blocked":
        payload["error_log"] = {"message": message, "detail": f"available_tools={available_tools}", "retryable": False}
    return ToolResultRecord.model_validate(payload).model_dump(exclude_none=True)
