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

GROUP_META_FILE = "index.json"
GROUP_SESSIONS_ROOT: Optional[Path] = None

ACTIVE_GROUP_RUNS: Dict[str, Dict[str, Any]] = {}
ACTIVE_GROUP_RUNS_LOCK = asyncio.Lock()
GROUP_SESSION_EVENT_SUBSCRIBERS: Dict[str, List[asyncio.Queue[Dict[str, Any]]]] = {}
GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK = asyncio.Lock()


def _session_json_path(root: Path, session_id: str) -> Path:
    return root / session_id / "session.json"


def _legacy_session_meta_path(root: Path, session_id: str) -> Path:
    return root / session_id / "meta.json"


def _runtime_json_path(root: Path, session_id: str) -> Path:
    return root / session_id / "runtime.json"


def _clean_session_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return the session definition shape that belongs in session.json."""
    out = dict(item or {})
    for key in (
        "runtime_state",
        "leader_agent_name",
        "host_config",
        "pending_owner_agent_name",
        "pending_skill",
        "pending_phase",
        "pending_required_user_fields",
        "pending_handoff_reason",
        "skill_session_owner_name",
        "skill_session_skill",
    ):
        out.pop(key, None)
    return out


def _read_json_object(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def format_storage_timestamp(value: datetime | None = None) -> str:
    dt = value or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%d%H%M%S") + f"{dt.microsecond // 10000:02d}"


def _speaker_from_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    speaker = msg.get("speaker")
    if isinstance(speaker, dict):
        out = {str(k): v for k, v in speaker.items() if v not in (None, "")}
        if out.get("type"):
            return out
    role = str(msg.get("role") or "").strip()
    if role == "user":
        return {"type": "user"}
    if role == "host":
        return {"type": "host"}
    if role == "assistant":
        out = {"type": "expert"}
        agent_name = str(msg.get("agent_name") or "").strip()
        skill = str(msg.get("skill") or "").strip()
        if agent_name:
            out["agent_name"] = agent_name
        if skill:
            out["skill"] = skill
        return out
    return {"type": role or "unknown"}


def _skill_result_from_legacy_tool_debug(msg: Dict[str, Any]) -> Dict[str, Any] | None:
    existing = msg.get("skill_result")
    if isinstance(existing, dict):
        return existing
    tool_debug = msg.get("tool_debug")
    if not isinstance(tool_debug, dict):
        return None
    state = tool_debug.get("skill_session_state")
    if not isinstance(state, dict):
        return None
    skill_session = str(state.get("skill_session") or "").strip()
    if not skill_session:
        return None
    out: Dict[str, Any] = {
        "execution_status": "succeeded",
        "next_action": {"skill_session": skill_session},
    }
    return out


def _canonical_history_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    speaker = _speaker_from_message(msg)
    out: Dict[str, Any] = {
        "message_id": msg.get("message_id"),
        "speaker": speaker,
        "content": msg.get("content") or "",
        "created_at": msg.get("created_at") or msg.get("timestamp") or "",
    }
    for key in (
        "client_message_id",
        "skill_route_debug",
        "expert_route_debug",
        "tool_raw_results",
        "debug",
    ):
        if msg.get(key) is not None:
            out[key] = msg.get(key)
    skill_result = _skill_result_from_legacy_tool_debug(msg)
    if skill_result is not None:
        out["skill_result"] = skill_result
    tool_debug = msg.get("tool_debug")
    if isinstance(tool_debug, dict):
        debug = out.get("debug") if isinstance(out.get("debug"), dict) else {}
        out["debug"] = {**debug, "tool_debug": tool_debug}
    return {k: v for k, v in out.items() if v is not None}


def _runtime_history_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(msg)
    speaker = _speaker_from_message(out)
    out["speaker"] = speaker
    if "timestamp" not in out and out.get("created_at") is not None:
        out["timestamp"] = out.get("created_at")
    speaker_type = str(speaker.get("type") or "").strip()
    if "role" not in out:
        if speaker_type == "expert":
            out["role"] = "assistant"
        elif speaker_type:
            out["role"] = speaker_type
    if "agent_name" not in out and speaker.get("agent_name") is not None:
        out["agent_name"] = speaker.get("agent_name")
    if "skill" not in out and speaker.get("skill") is not None:
        out["skill"] = speaker.get("skill")
    return out


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
        "timestamp": format_storage_timestamp(),
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
    root = ensure_sessions_dir()
    runtime_path = _runtime_json_path(root, group_session_id)
    if state:
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        with suppress(OSError):
            runtime_path.unlink()
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


def _parse_runtime_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 16 and text.isdigit():
        try:
            base = datetime.strptime(text[:14], "%Y%m%d%H%M%S")
            centiseconds = int(text[14:16])
            return base.replace(microsecond=centiseconds * 10000, tzinfo=timezone.utc)
        except Exception:
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stored_runtime_state_is_stale(stored: Any) -> bool:
    if not isinstance(stored, dict) or stored.get("running") is not True:
        return False
    started = _parse_runtime_timestamp(str(stored.get("started_at") or ""))
    if started is None:
        return True
    age = (datetime.now(timezone.utc) - started).total_seconds()
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
    stored = None
    with suppress(Exception):
        stored = _read_json_object(_runtime_json_path(ensure_sessions_dir(), group_session_id))
    stored = stored or meta_item.get("runtime_state")
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
    started_at = format_storage_timestamp()
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
    out = {
        "id": session_id,
        "title": meta_item.get("title", "新对话"),
        "title_auto_generated": meta_item.get("title_auto_generated"),
        "agent_names": names,
        "created_at": meta_item.get("created_at", ""),
        "updated_at": meta_item.get("updated_at", ""),
        "runtime_state": runtime_state_for_session(session_id, meta_item),
    }
    scenario_name = str(meta_item.get("scenario_name") or "").strip()
    if scenario_name:
        out["scenario_name"] = scenario_name
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
    root = ensure_sessions_dir()
    index_path = root / GROUP_META_FILE
    out: Dict[str, Dict[str, Any]] = {}
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                out = {str(k): v for k, v in data.items() if isinstance(v, dict)}
        except Exception:
            pass
    for child in root.iterdir():
        if not child.is_dir():
            continue
        session_path = child / "session.json"
        meta_path = child / "meta.json"
        read_path = session_path if session_path.exists() else meta_path
        if not read_path.exists():
            continue
        try:
            item = json.loads(read_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(item, dict):
            out[child.name] = item
    return out


def save_group_meta(meta: Dict[str, Dict[str, Any]], *, preserve_unmentioned: bool = True) -> None:
    root = ensure_sessions_dir()
    index_path = root / GROUP_META_FILE
    index_path.parent.mkdir(parents=True, exist_ok=True)
    data = {str(k): _clean_session_item(v) for k, v in (meta or {}).items() if isinstance(v, dict)}
    if preserve_unmentioned:
        try:
            current = load_group_meta()
            if isinstance(current, dict):
                data = dict(current)
                for session_id, incoming_item in (meta or {}).items():
                    current_item = current.get(session_id)
                    if isinstance(current_item, dict) and isinstance(incoming_item, dict):
                        current_updated_at = str(current_item.get("updated_at") or "")
                        incoming_updated_at = str(incoming_item.get("updated_at") or "")
                        if current_updated_at and incoming_updated_at and current_updated_at > incoming_updated_at:
                            continue
                    data[session_id] = _clean_session_item(incoming_item)
        except Exception:
            data = {str(k): _clean_session_item(v) for k, v in (meta or {}).items() if isinstance(v, dict)}
    index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for session_id, item in data.items():
        session_path = _session_json_path(root, session_id)
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_text(json.dumps(_clean_session_item(item), ensure_ascii=False, indent=2), encoding="utf-8")
    if not preserve_unmentioned:
        keep_ids = set(data)
        for child in root.iterdir():
            if child.is_dir() and child.name not in keep_ids:
                with suppress(OSError):
                    (child / "session.json").unlink()
                    (child / "meta.json").unlink()


def load_group_history(group_session_id: str) -> List[Dict[str, Any]]:
    from app.session_state.paths import ensure_session_layout, resolve_history_path

    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        path = ensure_sessions_dir() / group_session_id / "history.json"
    else:
        ensure_session_layout(user_ctx, group_session_id)
        path = resolve_history_path(user_ctx, group_session_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            return [_runtime_history_message(item) for item in data if isinstance(item, dict)]
        except Exception:
            pass
    return []


def save_group_history(group_session_id: str, messages: List[Dict[str, Any]]) -> None:
    from app.session_state.paths import ensure_session_layout

    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        path = ensure_sessions_dir() / group_session_id / "history.json"
    else:
        layout = ensure_session_layout(user_ctx, group_session_id)
        path = layout.history
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical_messages = [_canonical_history_message(item) for item in (messages or []) if isinstance(item, dict)]
    path.write_text(json.dumps(canonical_messages, ensure_ascii=False, indent=2), encoding="utf-8")
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
    root = ensure_sessions_dir()
    valid_ids = set((meta or {}).keys())
    deleted = 0
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        for child in root.iterdir():
            if not child.is_dir() or child.name in valid_ids:
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
