"""Session-level runtime log helpers for tool execution facts."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.api.group_chat_state import ensure_sessions_dir, format_storage_timestamp


_ALLOWED_SOURCES = {"mcp", "script", "workspace", "api"}
_TOOL_EXECUTION_LOG = "tool-execution.jsonl"


def _clean_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _log_path(session_id: str):
    return ensure_sessions_dir() / session_id / "execution_logs" / _TOOL_EXECUTION_LOG


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

    artifacts = item.get("artifacts") if isinstance(item.get("artifacts"), list) else []
    created_at = format_storage_timestamp()
    record = _clean_dict(
        {
            "log_id": f"log-{uuid.uuid4().hex[:12]}",
            "message_id": str(message_id or "").strip() or None,
            "created_at": created_at,
            "source": source,
            "agent_name": str(agent_name or "").strip() or None,
            "skill": str(skill or "").strip() or None,
            "tool_call": clean_tool_call,
            "output": {
                "text": str(output.get("text") or ""),
                "json": output.get("json_data") if output.get("json_data") is not None else {},
                "stdout": str(output.get("stdout") or ""),
                "stderr": str(output.get("stderr") or ""),
            },
            "artifacts": artifacts,
        }
    )
    return record if record.get("message_id") else None


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
