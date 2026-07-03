from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping

_FILE_REF_RE = re.compile(r"【文件引用：([^】]+)】")
_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S | re.I)


def _normalize_cite(value: Any, context: str = "") -> List[str]:
    cites: List[str] = []
    if isinstance(value, str):
        raw_items = [part.strip() for part in re.split(r"[,\n;]+", value) if part.strip()]
        cites.extend(raw_items)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, str)):
        for item in value:
            text = str(item or "").strip()
            if text:
                cites.append(text)
    if not cites and context:
        seen = set()
        for body in _FILE_REF_RE.findall(context):
            path = body.split("｜", 1)[-1].strip()
            if path and path not in seen:
                cites.append(path)
                seen.add(path)
    return cites


def record_from_message(message: Mapping[str, Any]) -> Dict[str, Any]:
    role = str(message.get("role") or "").strip() or "user"
    context = str(message.get("content") or message.get("context") or "")
    cite = _normalize_cite(message.get("cite") or message.get("cites") or message.get("files"), context)
    record: Dict[str, Any] = {
        "role": role,
        "context": context,
        "cite": cite,
    }
    agent_name = str(message.get("agent_name") or "").strip()
    if agent_name:
        record["agent_name"] = agent_name
    message_id = str(message.get("message_id") or "").strip()
    if message_id:
        record["message_id"] = message_id
    timestamp = str(message.get("timestamp") or "").strip()
    if timestamp:
        record["timestamp"] = timestamp
    return record


def format_session_chat_markdown(messages: Iterable[Mapping[str, Any]]) -> str:
    records = [record_from_message(message) for message in messages or []]
    lines: List[str] = ["# 会话历史", ""]
    for idx, record in enumerate(records, 1):
        lines.append(f"## {idx}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(record, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_session_chat_markdown(text: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for block in _JSON_BLOCK_RE.findall(text or ""):
        try:
            raw = json.loads(block)
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip() or "user"
        context = str(raw.get("context") or "")
        cite = _normalize_cite(raw.get("cite"), context)
        msg: Dict[str, Any] = {
            "role": role,
            "content": context,
            "context": context,
            "cite": cite,
        }
        for key in ("agent_name", "message_id", "timestamp"):
            value = str(raw.get(key) or "").strip()
            if value:
                msg[key] = value
        records.append(msg)
    return records
