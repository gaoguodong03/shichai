"""群聊记忆存储：维护专家回合提炼出的 facts.md，并构建主持人派发上下文。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.api.files import get_workspace_root_path


def _workspace_root(session_id: str, workspace_root: Optional[Path] = None) -> Path:
    return workspace_root.resolve() if workspace_root else get_workspace_root_path(session_id)


def _memory_root(session_id: str, workspace_root: Optional[Path] = None) -> Path:
    root = _workspace_root(session_id, workspace_root=workspace_root)
    mem = root / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    return mem


def _truncate(text: str, limit: int) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "..."


def upsert_facts(
    session_id: str,
    facts_delta: List[str],
    max_facts: int = 60,
    workspace_root: Optional[Path] = None,
) -> List[str]:
    """合并事实清单到 memory/facts.md，按归一化文本去重并截断到上限。"""
    mem = _memory_root(session_id, workspace_root=workspace_root)
    facts_file = mem / "facts.md"
    existing: List[str] = []
    if facts_file.exists():
        for line in facts_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("- "):
                existing.append(line[2:].strip())

    merged: List[str] = []
    seen = set()
    for item in existing + (facts_delta or []):
        fact = _truncate(str(item or "").strip(), 220)
        if not fact:
            continue
        key = re.sub(r"\s+", " ", fact).lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(fact)

    merged = merged[-max(1, int(max_facts)) :]
    body = "# Facts\n\n" + "\n".join([f"- {x}" for x in merged]) + ("\n" if merged else "")
    facts_file.write_text(body, encoding="utf-8")
    return merged


def build_dispatch_context(
    session_id: str,
    target_agent_id: str,
    goal: str,
    k: int = 3,
    max_facts: int = 60,
    workspace_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """读取 memory/facts，返回派发上下文；旧 logs/messages 不进入下一轮提示词。"""
    mem = _memory_root(session_id, workspace_root=workspace_root)
    facts_file = mem / "facts.md"

    facts: List[str] = []
    if facts_file.exists():
        for line in facts_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("- "):
                facts.append(line[2:].strip())
    facts = facts[-max(1, int(max_facts)) :]

    lines: List[str] = []
    if facts:
        lines.append("【关键事实】")
        lines.extend([f"- {f}" for f in facts[-10:]])
    rendered = "\n".join(lines).strip()

    return {
        "facts": facts,
        "logs": [],
        "refs": [],
        "rendered": rendered,
        "has_memory": bool(facts),
    }
