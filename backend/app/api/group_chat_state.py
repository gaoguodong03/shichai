"""Group-chat session state, history, archive, and runtime event helpers."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agent.group_orchestration_fsm import effective_orchestration_profile
from app.core.user_context import get_current_user_context

logger = logging.getLogger(__name__)

GROUP_META_FILE = "group_sessions_meta.json"
GROUP_HISTORY_PREFIX = "group_history_"
GROUP_SESSIONS_ROOT: Optional[Path] = None

ACTIVE_GROUP_RUNS: Dict[str, Dict[str, Any]] = {}
ACTIVE_GROUP_RUNS_LOCK = asyncio.Lock()
GROUP_SESSION_EVENT_SUBSCRIBERS: Dict[str, List[asyncio.Queue[Dict[str, Any]]]] = {}
GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK = asyncio.Lock()


def ensure_sessions_dir() -> Path:
    """Return the current user's isolated group-chat session directory."""
    if GROUP_SESSIONS_ROOT is not None:
        root = Path(GROUP_SESSIONS_ROOT).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise RuntimeError("缺少用户上下文，无法解析会话目录。")
    root = user_ctx.sessions_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


async def publish_group_session_event(
    group_session_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    event = {
        "type": event_type,
        "session_id": group_session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if payload:
        event.update(payload)
    async with GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
        queues = list(GROUP_SESSION_EVENT_SUBSCRIBERS.get(group_session_id) or [])
    stale: List[asyncio.Queue[Dict[str, Any]]] = []
    for queue in queues:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(event)
        except Exception:
            stale.append(queue)
    if stale:
        async with GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
            current = GROUP_SESSION_EVENT_SUBSCRIBERS.get(group_session_id) or []
            GROUP_SESSION_EVENT_SUBSCRIBERS[group_session_id] = [q for q in current if q not in stale]


def schedule_group_session_event(
    group_session_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    if not group_session_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(publish_group_session_event(group_session_id, event_type, payload))


def write_group_runtime_state(group_session_id: str, state: Optional[Dict[str, Any]]) -> None:
    meta = load_group_meta()
    item = meta.get(group_session_id)
    if item is None:
        return
    if state:
        item["runtime_state"] = state
    else:
        item.pop("runtime_state", None)
    save_group_meta(meta)
    schedule_group_session_event(
        group_session_id,
        "runtime_state",
        {"runtime_state": state or {"running": False}},
    )


def runtime_state_for_active_run(active: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "running": True,
        "run_id": str(active.get("run_id") or ""),
        "agent_name": str(active.get("agent_name") or ""),
        "skill": str(active.get("skill") or ""),
        "phase": str(active.get("phase") or "running"),
        "started_at": active.get("started_at") or "",
    }


def _runtime_state_stale_seconds() -> int:
    raw = (os.getenv("GROUP_RUNTIME_STATE_STALE_SECONDS") or "1800").strip()
    try:
        return max(0, int(raw))
    except Exception:
        return 1800


def _stored_runtime_state_is_stale(stored: Any) -> bool:
    if not isinstance(stored, dict) or stored.get("running") is not True:
        return False
    started_raw = str(stored.get("started_at") or "").strip()
    if not started_raw:
        return True
    try:
        started = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
    except Exception:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()
    return age >= _runtime_state_stale_seconds()


def runtime_state_for_session(group_session_id: str, meta_item: Dict[str, Any]) -> Dict[str, Any]:
    active = ACTIVE_GROUP_RUNS.get(group_session_id)
    if active:
        task = active.get("task")
        if isinstance(task, asyncio.Task) and task.done():
            run_id = str(active.get("run_id") or "")
            logger.warning(
                "group_chat_runtime_state_stale_done session=%s run_id=%s",
                group_session_id,
                run_id,
            )
            ACTIVE_GROUP_RUNS.pop(group_session_id, None)
            meta_item.pop("runtime_state", None)
            write_group_runtime_state(group_session_id, None)
        else:
            return runtime_state_for_active_run(active)
    stored = meta_item.get("runtime_state")
    if _stored_runtime_state_is_stale(stored):
        logger.warning(
            "group_chat_runtime_state_stale_stored session=%s run_id=%s phase=%s started_at=%s",
            group_session_id,
            str(stored.get("run_id") or "") if isinstance(stored, dict) else "",
            str(stored.get("phase") or "") if isinstance(stored, dict) else "",
            str(stored.get("started_at") or "") if isinstance(stored, dict) else "",
        )
        meta_item.pop("runtime_state", None)
        write_group_runtime_state(group_session_id, None)
        return {"running": False}
    return stored if isinstance(stored, dict) else {"running": False}


async def register_group_run(group_session_id: str, *, user_id: str, task: asyncio.Task[Any]) -> str:
    run_id = uuid.uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat()
    state = {
        "running": True,
        "run_id": run_id,
        "user_id": user_id,
        "agent_name": "",
        "skill": "",
        "phase": "routing",
        "started_at": started_at,
    }
    async with ACTIVE_GROUP_RUNS_LOCK:
        prev = ACTIVE_GROUP_RUNS.get(group_session_id)
        prev_task = prev.get("task") if isinstance(prev, dict) else None
        if isinstance(prev_task, asyncio.Task) and prev_task is not task and not prev_task.done():
            prev_task.cancel()
        ACTIVE_GROUP_RUNS[group_session_id] = {**state, "task": task}
    write_group_runtime_state(group_session_id, state)
    return run_id


async def update_group_run(group_session_id: str, run_id: str, **updates: Any) -> None:
    async with ACTIVE_GROUP_RUNS_LOCK:
        active = ACTIVE_GROUP_RUNS.get(group_session_id)
        if not active or str(active.get("run_id") or "") != run_id:
            return
        active.update({k: v for k, v in updates.items() if v is not None})
        state = {k: v for k, v in active.items() if k != "task"}
    write_group_runtime_state(group_session_id, state)


async def finish_group_run(group_session_id: str, run_id: str) -> None:
    async with ACTIVE_GROUP_RUNS_LOCK:
        active = ACTIVE_GROUP_RUNS.get(group_session_id)
        if not active or str(active.get("run_id") or "") != run_id:
            return
        ACTIVE_GROUP_RUNS.pop(group_session_id, None)
    write_group_runtime_state(group_session_id, None)


async def cancel_group_session_run(group_session_id: str, *, reason: str) -> bool:
    async with ACTIVE_GROUP_RUNS_LOCK:
        active = ACTIVE_GROUP_RUNS.get(group_session_id)
        task = active.get("task") if isinstance(active, dict) else None
    cancelled = False
    if isinstance(task, asyncio.Task) and not task.done():
        logger.info("group_chat_run_cancel session=%s reason=%s", group_session_id, reason)
        task.cancel()
        cancelled = True
        done, pending = await asyncio.wait({task}, timeout=2.0)
        for pending_task in pending:
            logger.warning("group_chat_run_cancel_pending session=%s reason=%s task=%s", group_session_id, reason, pending_task)
        for done_task in done:
            with suppress(asyncio.CancelledError, Exception):
                done_task.result()
    await finish_group_run(group_session_id, str((active or {}).get("run_id") or ""))
    return cancelled


def build_session_payload(session_id: str, meta_item: Dict[str, Any]) -> Dict[str, Any]:
    """Build the stable response shape used by the sessions API."""
    names = list(meta_item.get("agent_names", []))
    leader_name = meta_item.get("leader_agent_name", "")
    hc = meta_item.get("host_config")
    out = {
        "id": session_id,
        "title": meta_item.get("title", "新对话"),
        "agent_names": names,
        "leader_agent_name": leader_name,
        "created_at": meta_item.get("created_at", ""),
        "updated_at": meta_item.get("updated_at", ""),
        "runtime_state": runtime_state_for_session(session_id, meta_item),
    }
    if isinstance(hc, dict):
        out["host_config"] = hc
    system_prompt = str(meta_item.get("system_prompt") or "").strip()
    if system_prompt:
        out["system_prompt"] = system_prompt
    prof = str(meta_item.get("orchestration_profile") or "").strip().lower()
    if prof in ("recruitment", "scene"):
        out["orchestration_profile"] = prof
    else:
        out["orchestration_profile"] = effective_orchestration_profile(meta_item, agent_names=list(meta_item.get("agent_names") or []))
    return out


def load_group_meta() -> Dict[str, Dict[str, Any]]:
    path = ensure_sessions_dir() / GROUP_META_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def save_group_meta(meta: Dict[str, Dict[str, Any]], *, preserve_unmentioned: bool = True) -> None:
    path = ensure_sessions_dir() / GROUP_META_FILE
    data = meta
    if preserve_unmentioned and path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(current, dict):
                data = dict(current)
                for session_id, incoming_item in (meta or {}).items():
                    current_item = current.get(session_id)
                    if isinstance(current_item, dict) and isinstance(incoming_item, dict):
                        current_updated_at = str(current_item.get("updated_at") or "")
                        incoming_updated_at = str(incoming_item.get("updated_at") or "")
                        if current_updated_at and incoming_updated_at and current_updated_at > incoming_updated_at:
                            continue
                    data[session_id] = incoming_item
        except Exception:
            data = meta
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_group_history(group_session_id: str) -> List[Dict[str, Any]]:
    from app.session_state.paths import migrate_session_layout, resolve_history_path

    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        path = ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    else:
        migrate_session_layout(user_ctx, group_session_id)
        path = resolve_history_path(user_ctx, group_session_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def save_group_history(group_session_id: str, messages: List[Dict[str, Any]]) -> None:
    from app.session_state.paths import ensure_session_layout

    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        path = ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    else:
        layout = ensure_session_layout(user_ctx, group_session_id)
        path = layout.history
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
    schedule_group_session_event(
        group_session_id,
        "messages_updated",
        {"message_count": len(messages or [])},
    )
    try:
        from app.session_state.service import capture_session_checkpoint

        capture_session_checkpoint(group_session_id, reason="history_update")
    except Exception:
        logger.warning("session_state history checkpoint failed: %s", group_session_id, exc_info=True)


def cleanup_orphan_group_histories(meta: Dict[str, Dict[str, Any]]) -> int:
    """Remove orphan session history files and empty session directories."""
    from app.session_state.paths import LEGACY_WORKSPACES_DIR

    root = ensure_sessions_dir()
    valid_ids = set((meta or {}).keys())
    deleted = 0
    for p in root.glob(f"{GROUP_HISTORY_PREFIX}*.json"):
        sid = p.stem.replace(GROUP_HISTORY_PREFIX, "")
        if sid in valid_ids:
            continue
        try:
            p.unlink()
            deleted += 1
        except OSError:
            logger.warning("清理孤儿会话历史失败: %s", p, exc_info=True)
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        for child in root.iterdir():
            if not child.is_dir() or child.name in valid_ids:
                continue
            if child.name in (LEGACY_WORKSPACES_DIR,):
                continue
            try:
                shutil.rmtree(child)
                deleted += 1
            except OSError:
                logger.warning("清理孤儿会话目录失败: %s", child, exc_info=True)
    return deleted


def build_archive_segments(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group messages into archive segments by user turn, excluding host messages."""
    segments: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def _ensure_current() -> Dict[str, Any]:
        nonlocal current
        if current is None:
            current = {
                "user": None,
                "experts": {},
            }
        return current

    def _flush() -> None:
        nonlocal current
        if not current:
            current = None
            return
        has_user = bool(current.get("user"))
        experts = current.get("experts") or {}
        has_expert = any((v.get("messages") or []) for v in experts.values()) if isinstance(experts, dict) else False
        if has_user or has_expert:
            expert_list = []
            if isinstance(experts, dict):
                for _, v in experts.items():
                    if isinstance(v, dict):
                        expert_list.append(v)
            segments.append(
                {
                    "user": current.get("user"),
                    "experts": expert_list,
                }
            )
        current = None

    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = (m.get("role") or "").strip()
        if role == "host":
            continue
        if role == "user":
            _flush()
            cur = _ensure_current()
            cur["user"] = {
                "message_id": m.get("message_id"),
                "content": m.get("content") or "",
                "timestamp": m.get("timestamp"),
            }
            continue
        if role == "assistant":
            cur = _ensure_current()
            agent_name = (m.get("agent_name") or "").strip()
            if not agent_name:
                continue
            experts = cur.get("experts")
            if not isinstance(experts, dict):
                experts = {}
                cur["experts"] = experts
            if agent_name not in experts:
                experts[agent_name] = {"agent_name": agent_name, "messages": []}
            item = {
                "message_id": m.get("message_id"),
                "content": m.get("content") or "",
                "timestamp": m.get("timestamp"),
            }
            if m.get("skill") is not None:
                item["skill"] = m.get("skill")
            experts[agent_name]["messages"].append(item)

    _flush()
    return segments
