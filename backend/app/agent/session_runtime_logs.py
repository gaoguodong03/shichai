"""Session-level runtime log helpers for tool execution facts."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.agent.structured_output_contracts import ArtifactRef, ToolExecutionLogRecord
from app.agent.llm_runtime_diagnostics import llm_fault_definition
from app.api.group_chat_state import ensure_sessions_dir, format_storage_timestamp


_ALLOWED_SOURCES = {"mcp", "script", "workspace", "api", "host", "llm", "runtime"}
_TOOL_EXECUTION_LOG = "tool-execution.jsonl"
_SUMMARY_LIMIT = 800
_FAILURE_SUMMARY_LIMIT = 500
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[^\s;,]+")
_LEGACY_LLM_OUTPUT_SUMMARY_PATTERN = re.compile(r"^模型响应已接收：\d+ 字(?:；finish_reason=.*)?$")
_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?token|token|secret|password)"
    r"\s*[:=]\s*([^\s;,]+|\"[^\"]*\"|'[^']*')"
)


def _clean_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _log_path(session_id: str):
    return ensure_sessions_dir() / session_id / "execution_logs" / _TOOL_EXECUTION_LOG


def _artifact_refs_from(value: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").strip()
        name = str(item.get("name") or "").strip()
        path = str(item.get("path") or "").strip()
        if kind and name and path:
            try:
                rows.append(ArtifactRef.model_validate({"type": kind, "name": name, "path": path}).model_dump())
            except ValidationError:
                continue
    return rows


def _runtime_log_from_tool_result(
    item: dict[str, Any],
    *,
    message_id: str,
    agent_name: str,
    skill: str,
) -> dict[str, Any] | None:
    tool_call = item.get("tool_call") if isinstance(item.get("tool_call"), dict) else {}
    source = str(tool_call.get("kind") or "").strip()
    if source not in _ALLOWED_SOURCES:
        return None

    output = item.get("output") if isinstance(item.get("output"), dict) else {}
    clean_tool_call = _clean_dict(
        {
            "id": str(tool_call.get("id") or "").strip() or None,
            "name": str(tool_call.get("name") or "").strip() or None,
            "provider": str(tool_call.get("provider") or "").strip() or None,
            "provider_tool": str(tool_call.get("provider_tool") or "").strip() or None,
            "arguments": tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {},
        }
    )
    if "id" not in clean_tool_call or "name" not in clean_tool_call:
        return None

    raw_artifacts = output.get("artifacts")
    artifacts = _artifact_refs_from(raw_artifacts)
    if isinstance(raw_artifacts, list) and raw_artifacts and not artifacts:
        return None
    if not artifacts and isinstance(output.get("json_data"), dict):
        raw_json_artifacts = output.get("json_data", {}).get("artifacts")
        artifacts = _artifact_refs_from(raw_json_artifacts)
        if isinstance(raw_json_artifacts, list) and raw_json_artifacts and not artifacts:
            return None
    created_at = format_storage_timestamp()
    record = _clean_dict(
        {
            "log_id": f"log-{uuid.uuid4().hex[:12]}",
            "message_id": str(message_id or "").strip() or None,
            "created_at": str(item.get("created_at") or created_at).strip(),
            "source": source,
            "agent_name": str(agent_name or "").strip() or None,
            "skill": str(skill or "").strip() or None,
            "status": str(item.get("execution_status") or "").strip() or None,
            "tool_call": clean_tool_call,
            "output": {
                "content": str(output.get("content") or ""),
                "json_data": output.get("json_data") if output.get("json_data") is not None else {},
                "artifacts": artifacts,
                "stdout": str(output.get("stdout") or ""),
                "stderr": str(output.get("stderr") or ""),
            },
            "duration_ms": item.get("duration_ms") if isinstance(item.get("duration_ms"), int) else None,
        }
    )
    try:
        return ToolExecutionLogRecord.model_validate(record).model_dump(exclude_none=True)
    except ValidationError:
        return None


def append_tool_execution_logs(
    session_id: str,
    *,
    message_id: str,
    agent_name: str,
    skill: str,
    tool_results: list[dict[str, Any]],
) -> None:
    """Append tool execution facts for one history message."""
    records = [
        record
        for item in tool_results or []
        if isinstance(item, dict)
        for record in [_runtime_log_from_tool_result(item, message_id=message_id, agent_name=agent_name, skill=skill)]
        if record is not None
    ]
    if not records:
        return
    path = _log_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def append_host_execution_log(
    session_id: str,
    *,
    message_id: str,
    host_name: str,
    skill: str,
    current_phase: str,
    message: dict[str, Any],
    status: str = "succeeded",
) -> None:
    """Append one host scheduler fact for the message-side execution log panel."""
    clean_arguments = _clean_dict(
        {
            "current_phase": str(current_phase or "").strip() or None,
            "message": dict(message or {}),
        }
    )
    record = _clean_dict(
        {
            "log_id": f"log-{uuid.uuid4().hex[:12]}",
            "message_id": str(message_id or "").strip() or None,
            "created_at": format_storage_timestamp(),
            "source": "host",
            "agent_name": str(host_name or "").strip() or None,
            "skill": str(skill or "").strip() or None,
            "status": str(status or "succeeded").strip() or "succeeded",
            "tool_call": {
                "id": f"host-{uuid.uuid4().hex[:12]}",
                "name": "host_scheduler",
                "provider": "host",
                "provider_tool": "schedule_message",
                "arguments": clean_arguments,
            },
            "output": {
                "content": str((message or {}).get("content") or "").strip(),
                "json_data": {
                    "current_phase": str(current_phase or "").strip(),
                    "message": dict(message or {}),
                },
                "artifacts": list((message or {}).get("artifacts") or []),
                "stdout": "",
                "stderr": "",
            },
        }
    )
    try:
        validated = ToolExecutionLogRecord.model_validate(record).model_dump(exclude_none=True)
    except ValidationError:
        return
    path = _log_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(validated, ensure_ascii=False, separators=(",", ":")) + "\n")


def _safe_provider_endpoint(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def append_llm_execution_logs(
    session_id: str,
    *,
    message_id: str,
    agent_name: str,
    skill: str,
    calls: list[dict[str, Any]],
) -> None:
    """Append LiteLLM call facts already captured for one durable chat message."""
    records: list[dict[str, Any]] = []
    for index, call in enumerate(calls or [], start=1):
        if not isinstance(call, dict):
            continue
        status = str(call.get("status") or "failed").strip()
        if status not in {"succeeded", "failed"}:
            status = "failed"
        input_metrics = call.get("input_metrics") if isinstance(call.get("input_metrics"), dict) else {}
        output_metrics = call.get("output_metrics") if isinstance(call.get("output_metrics"), dict) else {}
        response_metadata = (
            call.get("response_metadata") if isinstance(call.get("response_metadata"), dict) else {}
        )
        token_usage = (
            response_metadata.get("token_usage")
            if isinstance(response_metadata.get("token_usage"), dict)
            else {}
        )
        error_code = str(call.get("error_code") or "").strip()
        error_summary = sanitize_runtime_failure_summary(call.get("error_summary")) if error_code else ""
        finish_reason = str(response_metadata.get("finish_reason") or "").strip()
        output_chars = output_metrics.get("output_chars") if isinstance(output_metrics.get("output_chars"), int) else 0
        operation = str(call.get("operation") or "llm_completion").strip() or "llm_completion"
        model = str(response_metadata.get("model") or call.get("model") or "").strip()
        output_content = str(call.get("output_content") or "")
        content_summary = output_content if output_content.strip() else (error_summary or "无文本输出")
        json_data = _clean_dict(
            {
                "operation": operation,
                "model": model or None,
                "finish_reason": finish_reason or None,
                "token_usage": dict(token_usage),
                "input_metrics": dict(input_metrics),
                "output_metrics": dict(output_metrics),
                "error_code": error_code or None,
                "error_type": str(call.get("error_type") or "").strip() or None,
                "error_summary": error_summary or None,
            }
        )
        record = _clean_dict(
            {
                "log_id": f"log-{uuid.uuid4().hex[:12]}",
                "message_id": str(message_id or "").strip() or None,
                "created_at": str(call.get("created_at") or format_storage_timestamp()).strip(),
                "source": "llm",
                "agent_name": str(agent_name or "").strip() or None,
                "skill": str(skill or "").strip() or None,
                "status": status,
                "tool_call": {
                    "id": f"llm-{uuid.uuid4().hex[:12]}",
                    "name": "llm_completion",
                    "provider": "litellm",
                    "provider_tool": operation,
                    "arguments": _clean_dict(
                        {
                            "call_index": index,
                            "method": str(call.get("method") or "").strip() or None,
                            "model": model or None,
                            "endpoint": _safe_provider_endpoint(call.get("provider_base_url")) or None,
                            **dict(input_metrics),
                        }
                    ),
                },
                "output": {
                    "content": content_summary,
                    "json_data": json_data,
                    "artifacts": [],
                    "stdout": "",
                    "stderr": "",
                },
                "duration_ms": call.get("duration_ms") if isinstance(call.get("duration_ms"), int) else None,
            }
        )
        try:
            records.append(ToolExecutionLogRecord.model_validate(record).model_dump(exclude_none=True))
        except ValidationError:
            continue
    if not records:
        return
    path = _log_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def sanitize_runtime_failure_summary(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "未提供异常摘要"
    safe_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and not line.lstrip().startswith("Traceback")
        and not line.lstrip().startswith("File \"")
    ]
    sanitized = " ".join(safe_lines)
    sanitized = _BEARER_PATTERN.sub("Bearer [REDACTED]", sanitized)
    sanitized = _SENSITIVE_ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", sanitized)
    if len(sanitized) > _FAILURE_SUMMARY_LIMIT:
        sanitized = sanitized[:_FAILURE_SUMMARY_LIMIT].rstrip() + "..."
    return sanitized or "未提供异常摘要"


def append_runtime_failure_log(
    session_id: str,
    *,
    message_id: str,
    agent_name: str,
    skill: str,
    error_code: str,
    error_type: str,
    phase: str,
    error_summary: str,
) -> None:
    """Append one sanitized group-chat runtime failure linked to a history message."""
    clean_error_code = str(error_code or "GROUP_CHAT_RUNTIME_FAILED").strip() or "GROUP_CHAT_RUNTIME_FAILED"
    clean_error_type = str(error_type or "RuntimeError").strip() or "RuntimeError"
    clean_phase = str(phase or "group_chat_runtime").strip() or "group_chat_runtime"
    clean_summary = sanitize_runtime_failure_summary(error_summary)
    record = _clean_dict(
        {
            "log_id": f"log-{uuid.uuid4().hex[:12]}",
            "message_id": str(message_id or "").strip() or None,
            "created_at": format_storage_timestamp(),
            "source": "runtime",
            "agent_name": str(agent_name or "").strip() or None,
            "skill": str(skill or "").strip() or None,
            "status": "failed",
            "tool_call": {
                "id": f"runtime-{uuid.uuid4().hex[:12]}",
                "name": "group_chat_failure",
                "provider": "runtime",
                "provider_tool": clean_phase,
                "arguments": {
                    "error_code": clean_error_code,
                    "error_type": clean_error_type,
                    "phase": clean_phase,
                },
            },
            "output": {
                "content": clean_summary,
                "json_data": {
                    "error_code": clean_error_code,
                    "error_type": clean_error_type,
                    "phase": clean_phase,
                    "error_summary": clean_summary,
                },
                "artifacts": [],
                "stdout": "",
                "stderr": "",
            },
        }
    )
    try:
        validated = ToolExecutionLogRecord.model_validate(record).model_dump(exclude_none=True)
    except ValidationError:
        return
    path = _log_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(validated, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_tool_execution_logs(session_id: str) -> list[dict[str, Any]]:
    """Load session-level tool execution logs for tests and diagnostics."""
    path = _log_path(session_id)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _short_text(value: Any, *, limit: int = _SUMMARY_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _argument_summary(arguments: Any) -> str:
    if not isinstance(arguments, dict) or not arguments:
        return ""
    parts: list[str] = []
    if "path" in arguments:
        parts.append(f"path={_short_text(arguments.get('path'), limit=120)}")
    for key, value in arguments.items():
        if key == "path":
            continue
        if isinstance(value, str):
            if key == "content" or len(value) > 120:
                parts.append(f"{key}=<{len(value)} chars>")
            else:
                parts.append(f"{key}={value}")
        elif isinstance(value, (int, float, bool)) or value is None:
            parts.append(f"{key}={value}")
        else:
            def summarize_json(item: Any) -> Any:
                if isinstance(item, str):
                    return item if len(item) <= 120 else f"<{len(item)} chars>"
                if isinstance(item, dict):
                    return {str(child_key): summarize_json(child_value) for child_key, child_value in item.items()}
                if isinstance(item, list):
                    return [summarize_json(child) for child in item]
                return item

            json_str = json.dumps(summarize_json(value), ensure_ascii=False, indent=2)
            parts.append(f"{key}=\n{_short_text(json_str)}")
    return "\n".join(parts)


def _output_summary(output: Any) -> str:
    if not isinstance(output, dict):
        return ""
    for key in ("content", "stderr", "stdout"):
        text = _short_text(output.get(key))
        if text:
            return text
    json_value = output.get("json_data")
    if isinstance(json_value, dict) and json_value:
        status = json_value.get("content") or json_value.get("message") or json_value.get("execution_status")
        if status:
            if isinstance(status, dict):
                content_text = _short_text(status.get("content"))
                if content_text:
                    return content_text
                seps = (",", ":")
                return f"message={json.dumps(status, ensure_ascii=False, separators=seps)}"
            return _short_text(status)
    return ""


def _llm_output_content(output: Any) -> str:
    if not isinstance(output, dict):
        return ""
    content = str(output.get("content") or "")
    if _LEGACY_LLM_OUTPUT_SUMMARY_PATTERN.fullmatch(content.strip()):
        return ""
    return content


def _execution_step_type(source: Any) -> str:
    normalized = str(source or "").strip()
    if normalized == "llm":
        return "model_decision"
    if normalized in {"workspace", "mcp", "api", "script"}:
        return "tool_execution"
    if normalized == "runtime":
        return "execution_failure"
    return ""


def message_execution_log_summaries(session_id: str, *, message_id: str) -> list[dict[str, Any]]:
    """Return folded tool-log summaries for one message."""
    wanted_message_id = str(message_id or "").strip()
    summaries: list[dict[str, Any]] = []
    for row in load_tool_execution_logs(session_id):
        if str(row.get("message_id") or "").strip() != wanted_message_id:
            continue
        tool_call = row.get("tool_call") if isinstance(row.get("tool_call"), dict) else {}
        output = row.get("output") if isinstance(row.get("output"), dict) else {}
        json_data = output.get("json_data") if isinstance(output.get("json_data"), dict) else {}
        token_usage = json_data.get("token_usage") if isinstance(json_data.get("token_usage"), dict) else {}
        input_metrics = json_data.get("input_metrics") if isinstance(json_data.get("input_metrics"), dict) else {}
        output_metrics = json_data.get("output_metrics") if isinstance(json_data.get("output_metrics"), dict) else {}
        arguments = tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {}
        error_code = str(json_data.get("error_code") or arguments.get("error_code") or "").strip()
        error_definition = llm_fault_definition(error_code)
        artifacts = output.get("artifacts") if isinstance(output.get("artifacts"), list) else []
        artifact_paths = [
            str(item.get("path") or "").strip()
            for item in artifacts
            if isinstance(item, dict) and str(item.get("path") or "").strip()
        ]
        summary = _clean_dict(
            {
                "log_id": str(row.get("log_id") or "").strip() or None,
                "created_at": str(row.get("created_at") or "").strip() or None,
                "source": str(row.get("source") or "").strip() or None,
                "step_type": _execution_step_type(row.get("source")) or None,
                "agent_name": str(row.get("agent_name") or "").strip() or None,
                "skill": str(row.get("skill") or "").strip() or None,
                "tool_name": str(tool_call.get("name") or "").strip() or None,
                "provider": str(tool_call.get("provider") or "").strip() or None,
                "provider_tool": str(tool_call.get("provider_tool") or "").strip() or None,
                "model": str(json_data.get("model") or arguments.get("model") or "").strip() or None,
                "operation": str(json_data.get("operation") or "").strip() or None,
                "phase": str(json_data.get("phase") or arguments.get("phase") or "").strip() or None,
                "argument_summary": _argument_summary(tool_call.get("arguments")),
                "output_summary": _output_summary(row.get("output")),
                "output_content": (_llm_output_content(output) or None) if row.get("source") == "llm" else None,
                "artifact_paths": artifact_paths,
                "status": str(row.get("status") or "").strip() or None,
                "duration_ms": row.get("duration_ms") if isinstance(row.get("duration_ms"), int) else None,
                "finish_reason": str(json_data.get("finish_reason") or "").strip() or None,
                "input_tokens": token_usage.get("input_tokens") if isinstance(token_usage.get("input_tokens"), int) else None,
                "output_tokens": token_usage.get("output_tokens") if isinstance(token_usage.get("output_tokens"), int) else None,
                "total_tokens": token_usage.get("total_tokens") if isinstance(token_usage.get("total_tokens"), int) else None,
                "cached_tokens": token_usage.get("cached_tokens") if isinstance(token_usage.get("cached_tokens"), int) else None,
                "reasoning_tokens": token_usage.get("reasoning_tokens") if isinstance(token_usage.get("reasoning_tokens"), int) else None,
                "cache_creation_tokens": token_usage.get("cache_creation_tokens") if isinstance(token_usage.get("cache_creation_tokens"), int) else None,
                "cache_read_tokens": token_usage.get("cache_read_tokens") if isinstance(token_usage.get("cache_read_tokens"), int) else None,
                "input_messages": input_metrics.get("input_messages") if isinstance(input_metrics.get("input_messages"), int) else None,
                "prompt_chars": input_metrics.get("prompt_chars") if isinstance(input_metrics.get("prompt_chars"), int) else None,
                "output_chars": output_metrics.get("output_chars") if isinstance(output_metrics.get("output_chars"), int) else None,
                "tool_call_count": input_metrics.get("tool_call_count") if isinstance(input_metrics.get("tool_call_count"), int) else None,
                "error_code": error_code or None,
                "error_name": (error_definition or {}).get("name") or None,
                "error_summary": str(json_data.get("error_summary") or "").strip() or None,
                "error_description": (error_definition or {}).get("description") or None,
                "error_action": (error_definition or {}).get("action") or None,
                "detail_available": True,
            }
        )
        summaries.append(summary)
    summaries.sort(key=lambda item: str(item.get("created_at") or ""))
    return summaries
