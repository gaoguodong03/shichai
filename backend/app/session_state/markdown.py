from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping

_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S | re.I)


def record_from_message(message: Mapping[str, Any]) -> Dict[str, Any]:
    return dict(message or {})


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
        records.append(raw)
    return records
