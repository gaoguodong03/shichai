"""Assemble execution context with deterministic trimming rules."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ContextPack:
    text: str
    sections: Dict[str, Any]
    dropped: List[str]


def _truncate_lines(lines: List[str], max_chars: int) -> List[str]:
    out: List[str] = []
    used = 0
    for line in lines:
        if used >= max_chars:
            break
        step = len(line) + 1
        if used + step > max_chars:
            break
        out.append(line)
        used += step
    return out


def assemble_context(
    *,
    task_brief: str,
    relevant_facts: List[str],
    last_turns: List[str],
    file_manifest_refs: List[str],
    max_chars: int = 9000,
) -> ContextPack:
    """Build a self-contained context packet for expert execution."""
    dropped: List[str] = []
    lines: List[str] = []
    lines.append("【TASK_BRIEF】")
    lines.append((task_brief or "").strip() or "(none)")
    lines.append("")

    if relevant_facts:
        lines.append("【RELEVANT_FACTS】")
        for f in relevant_facts[:30]:
            lines.append(f"- {f}")
        lines.append("")

    if last_turns:
        lines.append("【LAST_TURNS】")
        for t in last_turns[:12]:
            lines.append(f"- {t}")
        lines.append("")

    if file_manifest_refs:
        lines.append("【FILE_MANIFEST_REFS】")
        for ref in file_manifest_refs[:20]:
            lines.append(f"- {ref}")
        lines.append("")

    cropped = _truncate_lines(lines, max_chars=max(1200, int(max_chars)))
    if len(cropped) < len(lines):
        dropped.append("context_trimmed_by_max_chars")
    payload = "\n".join(cropped).strip()
    return ContextPack(
        text=payload,
        sections={
            "task_brief": task_brief,
            "facts_count": len(relevant_facts or []),
            "last_turns_count": len(last_turns or []),
            "file_refs_count": len(file_manifest_refs or []),
        },
        dropped=dropped,
    )
