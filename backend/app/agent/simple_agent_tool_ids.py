from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.agent.messages import BaseMessage, ToolMessage

logger = logging.getLogger(__name__)

_OPENAI_RESPONSES_MAX_CALL_ID_LEN = 64


def _provider_safe_tool_call_id(raw_id: Any) -> str:
    raw = str(raw_id or "tool")
    if len(raw) <= _OPENAI_RESPONSES_MAX_CALL_ID_LEN:
        return raw
    return f"call_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


def _set_tool_call_id(tool_call: Any, call_id: str) -> None:
    if isinstance(tool_call, dict):
        tool_call["id"] = call_id
        if "tool_call_id" in tool_call:
            tool_call["tool_call_id"] = call_id
        return
    try:
        setattr(tool_call, "id", call_id)
    except Exception:
        pass
    if hasattr(tool_call, "tool_call_id"):
        try:
            setattr(tool_call, "tool_call_id", call_id)
        except Exception:
            pass


def _tool_call_id(tool_call: Any, idx: int) -> str:
    if isinstance(tool_call, dict):
        return str(tool_call.get("id") or tool_call.get("tool_call_id") or f"tool-{idx}")
    return str(getattr(tool_call, "id", None) or getattr(tool_call, "tool_call_id", None) or f"tool-{idx}")


def _tool_call_name(tool_call: Any) -> str:
    if isinstance(tool_call, dict):
        return str(tool_call.get("name") or "tool")
    return str(getattr(tool_call, "name", None) or "tool")


def _tool_call_args(tool_call: Any) -> dict[str, Any]:
    raw: Any = None
    if isinstance(tool_call, dict):
        raw = tool_call.get("arguments")
        if raw is None:
            raw = tool_call.get("args")
    else:
        raw = getattr(tool_call, "arguments", None)
        if raw is None:
            raw = getattr(tool_call, "args", None)
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _missing_tool_response_messages(tool_calls: list[Any], existing_messages: list[Any], reason: str) -> list[ToolMessage]:
    seen_ids = {
        str(getattr(msg, "tool_call_id", "") or "")
        for msg in existing_messages
        if isinstance(msg, ToolMessage) and str(getattr(msg, "tool_call_id", "") or "")
    }
    missing: list[ToolMessage] = []
    for idx, tool_call in enumerate(tool_calls):
        tcid = _tool_call_id(tool_call, idx)
        if tcid in seen_ids:
            continue
        missing.append(
            ToolMessage(
                content=f"工具 {_tool_call_name(tool_call)} 未继续执行：{reason}",
                tool_call_id=tcid,
            )
        )
    return missing


def _normalize_ai_tool_call_ids(message: BaseMessage) -> dict[str, str]:
    tool_calls = getattr(message, "tool_calls", None) or []
    remap: dict[str, str] = {}
    for idx, tool_call in enumerate(tool_calls):
        raw_id = _tool_call_id(tool_call, idx)
        safe_id = _provider_safe_tool_call_id(raw_id)
        if safe_id == raw_id:
            continue
        remap[raw_id] = safe_id
        _set_tool_call_id(tool_call, safe_id)

    additional_kwargs = getattr(message, "additional_kwargs", None)
    raw_tool_calls = additional_kwargs.get("tool_calls") if isinstance(additional_kwargs, dict) else None
    if isinstance(raw_tool_calls, list):
        for idx, tool_call in enumerate(raw_tool_calls):
            if not isinstance(tool_call, dict):
                continue
            raw_id = str(tool_call.get("id") or f"tool-{idx}")
            safe_id = remap.get(raw_id) or _provider_safe_tool_call_id(raw_id)
            if safe_id != raw_id:
                remap[raw_id] = safe_id
                tool_call["id"] = safe_id

    if remap:
        logger.warning(
            "SimpleAgent: shortened tool_call ids for provider compatibility count=%s max_len=%s",
            len(remap),
            _OPENAI_RESPONSES_MAX_CALL_ID_LEN,
        )
    return remap


def _normalize_tool_message_ids(messages: list[Any], id_map: dict[str, str]) -> None:
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        raw_id = str(getattr(message, "tool_call_id", "") or "")
        safe_id = id_map.get(raw_id) or _provider_safe_tool_call_id(raw_id)
        if safe_id == raw_id:
            continue
        try:
            message.tool_call_id = safe_id
        except Exception:
            logger.warning("SimpleAgent: failed to rewrite long ToolMessage tool_call_id", exc_info=True)
