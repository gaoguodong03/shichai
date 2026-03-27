"""群聊记忆存储：将专家回合落盘到工作区，并构建主持人派发上下文。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.api.files import get_workspace_root_path


def _workspace_root(session_id: str, workspace_root: Optional[Path] = None) -> Path:
    return workspace_root.resolve() if workspace_root else get_workspace_root_path(session_id)


def _memory_root(session_id: str, workspace_root: Optional[Path] = None) -> Path:
    root = _workspace_root(session_id, workspace_root=workspace_root)
    mem = root / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "logs").mkdir(parents=True, exist_ok=True)
    (mem / "messages").mkdir(parents=True, exist_ok=True)
    return mem


def _truncate(text: str, limit: int) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "..."


def _safe_name(v: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", (v or "unknown")).strip("-") or "unknown"


def append_turn_log(
    session_id: str,
    turn_record: Dict[str, Any],
    max_logs: int = 20,
    workspace_root: Optional[Path] = None,
) -> str:
    """追加一条专家回合日志到 memory/logs，并限制日志文件数量。"""
    mem = _memory_root(session_id, workspace_root=workspace_root)
    logs_dir = mem / "logs"
    ts = (turn_record.get("timestamp") or datetime.now(timezone.utc).isoformat()).replace(":", "-")
    agent_id = _safe_name(str(turn_record.get("agent_id") or "expert"))
    filename = f"{ts}_{agent_id}.md"
    path = logs_dir / filename

    content = (
        f"# Turn Log\n\n"
        f"- session_id: {session_id}\n"
        f"- agent_id: {turn_record.get('agent_id') or ''}\n"
        f"- timestamp: {turn_record.get('timestamp') or ''}\n"
        f"- skill_id: {turn_record.get('skill_id') or ''}\n\n"
        f"- full_message_ref: {turn_record.get('full_message_ref') or ''}\n\n"
        f"## Discussion Goal\n{turn_record.get('discussion_goal') or ''}\n\n"
        f"## Input Prompt Summary\n{turn_record.get('input_prompt_summary') or ''}\n\n"
        f"## Response Summary\n{turn_record.get('response_summary') or ''}\n\n"
        f"## Tool Result Summary\n{turn_record.get('tool_result_summary') or ''}\n"
    )
    path.write_text(content, encoding="utf-8")

    files = sorted(logs_dir.glob("*.md"), key=lambda p: p.name)
    overflow = max(0, len(files) - max(1, int(max_logs)))
    for p in files[:overflow]:
        try:
            p.unlink()
        except OSError:
            continue
    return str(path)


def append_expert_message_file(
    session_id: str,
    agent_id: str,
    timestamp: Optional[str],
    content: str,
    skill_id: str = "",
    workspace_root: Optional[Path] = None,
) -> str:
    """保存专家完整发言到 memory/messages，返回工作区相对路径。"""
    ws_root = _workspace_root(session_id, workspace_root=workspace_root)
    mem = _memory_root(session_id, workspace_root=workspace_root)
    messages_dir = mem / "messages"
    ts = (timestamp or datetime.now(timezone.utc).isoformat()).replace(":", "-")
    did = _safe_name(agent_id or "expert")
    p = messages_dir / f"{ts}_{did}.md"
    body = (
        f"# Expert Message\n\n"
        f"- session_id: {session_id}\n"
        f"- agent_id: {agent_id or ''}\n"
        f"- skill_id: {skill_id or ''}\n"
        f"- timestamp: {timestamp or ''}\n\n"
        f"## Content\n\n{content or ''}\n"
    )
    p.write_text(body, encoding="utf-8")
    return str(p.relative_to(ws_root)).replace("\\", "/")


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


def _goal_terms(goal: str) -> List[str]:
    terms = re.findall(r"[A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", goal or "")
    return [t.lower() for t in terms][:12]


def _score_log(content: str, target_agent_id: str, terms: List[str]) -> int:
    text = (content or "").lower()
    score = 0
    if target_agent_id and target_agent_id.lower() in text:
        score += 3
    for t in terms:
        if t in text:
            score += 1
    return score


def build_dispatch_context(
    session_id: str,
    target_agent_id: str,
    goal: str,
    k: int = 3,
    max_facts: int = 60,
    workspace_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """读取 memory/facts 与 memory/logs，返回派发上下文及渲染文本。"""
    mem = _memory_root(session_id, workspace_root=workspace_root)
    facts_file = mem / "facts.md"
    logs_dir = mem / "logs"

    facts: List[str] = []
    if facts_file.exists():
        for line in facts_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("- "):
                facts.append(line[2:].strip())
    facts = facts[-max(1, int(max_facts)) :]

    logs: List[Dict[str, str]] = []
    refs: List[str] = []
    terms = _goal_terms(goal)
    for p in sorted(logs_dir.glob("*.md"), key=lambda x: x.name, reverse=True):
        try:
            raw = p.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r"^- full_message_ref:\s*(.+?)\s*$", raw, flags=re.MULTILINE)
        full_ref = (m.group(1).strip() if m else "")
        score = _score_log(raw, target_agent_id, terms)
        logs.append(
            {
                "name": p.name,
                "score": str(score),
                "excerpt": _truncate(raw.replace("\n", " "), 360),
                "full_message_ref": full_ref,
            }
        )
    logs.sort(key=lambda x: (int(x["score"]), x["name"]), reverse=True)
    top_logs = logs[: max(1, int(k))]

    lines: List[str] = []
    if facts:
        lines.append("【关键事实】")
        lines.extend([f"- {f}" for f in facts[-10:]])
        lines.append("")
    if top_logs:
        lines.append("【相关历史摘录】")
        for idx, item in enumerate(top_logs, start=1):
            lines.append(f"{idx}. ({item['name']}) {item['excerpt']}")
            ref = (item.get("full_message_ref") or "").strip()
            if ref:
                refs.append(ref)
    if refs:
        lines.append("")
        lines.append("【可读取的历史发言文件】")
        for ref in list(dict.fromkeys(refs))[:5]:
            lines.append(f"- 【文件引用：{ref}】")
    rendered = "\n".join(lines).strip()

    return {
        "facts": facts,
        "logs": top_logs,
        "refs": list(dict.fromkeys(refs)),
        "rendered": rendered,
        "has_memory": bool(facts or top_logs),
    }
