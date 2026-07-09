from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping


def record_from_message(message: Mapping[str, Any]) -> Dict[str, Any]:
    return dict(message or {})


def format_session_export_markdown(messages: Iterable[Mapping[str, Any]]) -> str:
    """Format an explicit user export from canonical history records."""
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
