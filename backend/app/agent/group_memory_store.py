"""群聊记忆存储：维护 session 级 memory/facts.md，并构建主持人派发上下文。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.security import get_current_user
from app.session_state.paths import ensure_session_layout


def _session_root(session_id: str, workspace_root: Optional[Path] = None) -> Path:
    if workspace_root:
        root = workspace_root.resolve()
        return root.parent if root.name == "workspace" else root
    return ensure_session_layout(get_current_user().ctx, session_id).session_root


def _memory_root(session_id: str, workspace_root: Optional[Path] = None) -> Path:
    root = _session_root(session_id, workspace_root=workspace_root)
    mem = root / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    return mem


def _truncate(text: str, limit: int) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "..."


def _clean_index_value(value: Any, limit: int) -> str:
    return _truncate(str(value or "").replace("\n", " ").strip(), limit)


def _read_index_entries(index_file: Path) -> List[Dict[str, Any]]:
    if not index_file.exists():
        return []

    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    in_files = False
    for raw in index_file.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("- agent_name:"):
            if current:
                entries.append(current)
            current = {
                "agent_name": stripped.removeprefix("- agent_name:").strip(),
                "skill": "",
                "summary": "",
                "files": [],
            }
            in_files = False
            continue
        if not current:
            continue
        if stripped.startswith("skill:"):
            current["skill"] = stripped.removeprefix("skill:").strip()
            in_files = False
            continue
        if stripped.startswith("summary:"):
            current["summary"] = stripped.removeprefix("summary:").strip()
            in_files = False
            continue
        if stripped == "files:":
            in_files = True
            continue
        if in_files and stripped.startswith("- "):
            path = stripped[2:].strip()
            if path:
                current.setdefault("files", []).append(path)
    if current:
        entries.append(current)
    return entries


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


def upsert_index_entries(
    session_id: str,
    entries_delta: List[Dict[str, Any]],
    max_entries: int = 60,
    workspace_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """合并工作区产物索引到 memory/index.md，供后续专家定位文件。"""
    mem = _memory_root(session_id, workspace_root=workspace_root)
    index_file = mem / "index.md"
    existing = _read_index_entries(index_file)

    normalized_delta: List[Dict[str, Any]] = []
    for entry in entries_delta or []:
        if not isinstance(entry, dict):
            continue
        files: List[str] = []
        seen_files = set()
        for raw_path in entry.get("files") or []:
            path = _clean_index_value(raw_path, 240)
            if not path or path in seen_files:
                continue
            seen_files.add(path)
            files.append(path)
        if not files:
            continue
        normalized_delta.append(
            {
                "agent_name": _clean_index_value(entry.get("agent_name"), 80) or "unknown",
                "skill": _clean_index_value(entry.get("skill"), 120) or "default",
                "summary": _clean_index_value(entry.get("summary"), 180) or "更新工作区文件",
                "files": files,
            }
        )

    merged: List[Dict[str, Any]] = []
    seen_entries = set()
    for entry in existing + normalized_delta:
        files = [str(x).strip() for x in entry.get("files") or [] if str(x or "").strip()]
        if not files:
            continue
        clean_entry = {
            "agent_name": _clean_index_value(entry.get("agent_name"), 80) or "unknown",
            "skill": _clean_index_value(entry.get("skill"), 120) or "default",
            "summary": _clean_index_value(entry.get("summary"), 180) or "更新工作区文件",
            "files": files,
        }
        key = (
            clean_entry["agent_name"],
            clean_entry["skill"],
            tuple(clean_entry["files"]),
        )
        if key in seen_entries:
            continue
        seen_entries.add(key)
        merged.append(clean_entry)

    merged = merged[-max(1, int(max_entries)) :]
    lines = ["# Index", ""]
    for entry in merged:
        lines.append(f"- agent_name: {entry['agent_name']}")
        lines.append(f"  skill: {entry['skill']}")
        lines.append(f"  summary: {entry['summary']}")
        lines.append("  files:")
        for path in entry["files"]:
            lines.append(f"    - {path}")
        lines.append("")
    index_file.write_text("\n".join(lines).rstrip() + ("\n" if merged else "\n\n"), encoding="utf-8")
    return merged


def build_dispatch_context(
    session_id: str,
    target_agent_name: str,
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

    index_entries = _read_index_entries(mem / "index.md")

    lines: List[str] = []
    if facts:
        lines.append("【关键事实】")
        lines.extend([f"- {f}" for f in facts[-10:]])
    if index_entries:
        if lines:
            lines.append("")
        lines.append("【工作区索引】")
        lines.append("下列路径是工作区相对路径，读取上述文件时使用工作区相对路径。")
        for entry in index_entries[-10:]:
            agent = _clean_index_value(entry.get("agent_name"), 80) or "unknown"
            skill = _clean_index_value(entry.get("skill"), 120) or "default"
            summary = _clean_index_value(entry.get("summary"), 180) or "更新工作区文件"
            lines.append(f"- {agent} / {skill}: {summary}")
            for path in entry.get("files") or []:
                clean_path = _clean_index_value(path, 240)
                if clean_path:
                    lines.append(f"  - {clean_path}")
    rendered = "\n".join(lines).strip()

    return {
        "facts": facts,
        "index": index_entries,
        "logs": [],
        "refs": [],
        "rendered": rendered,
        "has_memory": bool(facts or index_entries),
    }
