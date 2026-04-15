"""Minimal audit logging helpers for orchestration flow."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.api.files import get_workspace_root_path


def _audit_file(session_id: str) -> Path:
    root = get_workspace_root_path(session_id)
    p = root / "memory" / "orchestrator_audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _truncate(s: str, max_len: int) -> str:
    t = (s or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _format_one_audit_line(event_type: str, payload: Dict[str, Any]) -> str:
    """将单条审计 JSON 压成一行可读摘要，供主持人对照进度。"""
    payload = payload or {}
    if event_type == "scheduler_decision":
        d = payload.get("decision") or {}
        ns = d.get("next_speaker")
        td = d.get("task_done")
        r = _truncate(str(d.get("reason") or ""), 220)
        np = _truncate(str(d.get("next_prompt") or ""), 180)
        parts = [f"调度 → {ns}", f"task_done={td}"]
        if r:
            parts.append(f"理由:{r}")
        if np:
            parts.append(f"指派:{np}")
        return "- " + " | ".join(parts)
    if event_type == "turn_started":
        sp = payload.get("speaker")
        return f"- 发言开始 → {sp}"
    if event_type == "hook_interrupt":
        reason = payload.get("reason") or payload.get("message") or ""
        return f"- 中断: {_truncate(str(reason), 120)}"
    if event_type == "fsm_skip_host_dispatch":
        ns = (payload.get("next_speaker") or "")
        return f"- 直派专家（跳过本轮主持人调度）→ {ns}"
    if event_type == "user_exit_skill_session":
        pv = _truncate(str(payload.get("preview") or ""), 160)
        return f"- 用户结束技能会话: {pv}" if pv else "- 用户结束技能会话"
    if event_type == "sandbox_session_created":
        sid = payload.get("sandbox_id") or ""
        backend = payload.get("runtime_backend") or ""
        dep = str(payload.get("dep_hash") or "")[:12]
        return f"- 沙箱创建: {sid} backend={backend} dep={dep}"
    if event_type == "sandbox_session_disposed":
        sid = payload.get("sandbox_id") or ""
        return f"- 沙箱回收: {sid}"
    if event_type == "sandbox_command_started":
        tool = payload.get("tool_name") or ""
        return f"- 沙箱执行开始: {tool}"
    if event_type == "sandbox_command_finished":
        tool = payload.get("tool_name") or ""
        elapsed = payload.get("elapsed_ms")
        return f"- 沙箱执行完成: {tool} ({elapsed}ms)"
    if event_type == "sandbox_command_failed":
        tool = payload.get("tool_name") or ""
        err = _truncate(str(payload.get("error") or ""), 100)
        return f"- 沙箱执行失败: {tool} err={err}"
    if event_type == "sandbox_command_timeout":
        tool = payload.get("tool_name") or ""
        return f"- 沙箱执行超时: {tool}"
    if event_type == "sandbox_mount_applied":
        fp = str(payload.get("mount_fingerprint") or "")[:12]
        n = len(payload.get("mounts") or []) if isinstance(payload.get("mounts"), list) else 0
        return f"- 沙箱挂载: fp={fp} mounts={n}"
    return f"- {event_type}"


def format_audit_for_host_prompt(
    session_id: str,
    *,
    max_lines: int = 80,
    max_chars: int = 14000,
) -> str:
    """
    读取 memory/orchestrator_audit.jsonl 尾部若干行，渲染为纯文本段落。
    供主持人 / 默认调度器判断「已执行步骤」与 task_done 时参考（类似计划清单的执行记录）。
    """
    p = _audit_file(session_id)
    if not p.exists():
        return ""
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    lines = lines[-max(1, int(max_lines)) :]
    out: List[str] = []
    for ln in lines:
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        et = str(rec.get("event_type") or "")
        pl = rec.get("payload")
        if not isinstance(pl, dict):
            pl = {}
        one = _format_one_audit_line(et, pl)
        if one:
            out.append(one)
    text = "\n".join(out).strip()
    if not text:
        return ""
    if len(text) > max_chars:
        text = "…\n" + text[-max_chars:]
    return text


def append_audit_event(session_id: str, event_type: str, payload: Dict[str, Any], turn_id: Optional[str] = None) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "turn_id": turn_id or "",
        "payload": payload or {},
    }
    p = _audit_file(session_id)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
