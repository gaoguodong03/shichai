"""Group-chat session state, history, archive, and runtime event helpers."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.group_chat_archive import build_archive_segments
from app.agent.message_contracts import ChatMessageRecord, MessageBody
from app.agent.runtime_status import RuntimePhase
from app.core.user_context import get_current_user_context

logger = logging.getLogger(__name__)

GROUP_SESSIONS_ROOT: Optional[Path] = None

ACTIVE_GROUP_RUNS: Dict[str, Dict[str, Any]] = {}
ACTIVE_GROUP_RUNS_LOCK = asyncio.Lock()
GROUP_SESSION_EVENT_SUBSCRIBERS: Dict[str, List[asyncio.Queue[Dict[str, Any]]]] = {}
GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK = asyncio.Lock()
GROUP_SESSION_EVENT_TYPES = {"message", "runtime", "deleted", "error"}
RUNTIME_PHASES = {phase.value for phase in RuntimePhase}
STORAGE_TIMESTAMP_RE = re.compile(r"\d{16}")

def group_session_has_active_run(group_session_id: str) -> bool:
    """Return whether a session has a live run that must not be state-mutated."""
    active = ACTIVE_GROUP_RUNS.get(group_session_id)
    if not isinstance(active, dict):
        return False
    task = active.get("task")
    if isinstance(task, asyncio.Task):
        return not task.done()
    return active.get("running") is True


def reject_group_session_mutation_if_running(group_session_id: str, *, operation: str) -> None:
    """Reject clone/rollback/message deletion while the session is generating."""
    if group_session_has_active_run(group_session_id):
        raise HTTPException(
            status_code=409,
            detail=f"session is running; stop current run before {operation}",
        )


def _session_json_path(root: Path, session_id: str) -> Path:
    return root / session_id / "session.json"


def _runtime_json_path(root: Path, session_id: str) -> Path:
    return root / session_id / "runtime.json"


def _orchestration_json_path(root: Path, session_id: str) -> Path:
    return root / session_id / "orchestration_state.json"


def _clean_orchestration_state(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the current short-term orchestration contract groups."""
    out: Dict[str, Any] = {}
    raw_skill_sessions = raw.get("skill_sessions") if isinstance(raw.get("skill_sessions"), dict) else {}
    skill_sessions: Dict[str, Dict[str, str]] = {}
    for raw_agent_name, raw_binding in raw_skill_sessions.items():
        agent_name = str(raw_agent_name or "").strip()
        binding = raw_binding if isinstance(raw_binding, dict) else {}
        skill = str(binding.get("skill") or "").strip()
        if agent_name and skill:
            skill_sessions[agent_name] = {"skill": skill}
    if skill_sessions:
        out["skill_sessions"] = skill_sessions
    host_scheduler = raw.get("host_scheduler") if isinstance(raw.get("host_scheduler"), dict) else None
    if host_scheduler:
        current_phase = str(host_scheduler.get("current_phase") or "").strip()
        try:
            message = MessageBody.model_validate(host_scheduler.get("message") or {}).model_dump(
                exclude_none=True,
                exclude_defaults=True,
            )
        except ValidationError:
            message = None
        if current_phase and isinstance(message, dict) and str(message.get("content") or "").strip():
            row = {"current_phase": current_phase, "message": message}
            out["host_scheduler"] = row
    return out


def _clean_session_definition(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return the session definition shape that belongs in session.json."""
    allowed = {
        "title",
        "title_auto_generated",
        "agent_names",
        "host",
        "scenario_prompt",
        "created_at",
        "updated_at",
    }
    out = {key: value for key, value in dict(item or {}).items() if key in allowed}
    host = out.get("host")
    if isinstance(host, dict):
        out["host"] = {
            key: host.get(key)
            for key in ("name", "llm_name", "system_prompt", "skill_directory")
            if key in host
        }
    elif "host" in out:
        out["host"] = {}
    for field in ("created_at", "updated_at"):
        if field in out:
            out[field] = _clean_storage_timestamp(out[field], field=field)
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


def _clean_storage_timestamp(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not STORAGE_TIMESTAMP_RE.fullmatch(text):
        raise ValueError(f"{field} must use YYYYMMDDHHmmssSS")
    try:
        datetime.strptime(text[:14], "%Y%m%d%H%M%S")
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYYMMDDHHmmssSS") from exc
    return text


def _canonical_history_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(msg, dict):
        raise ValueError("history message must be an object")
    try:
        record = ChatMessageRecord.model_validate(msg)
    except ValidationError as exc:
        raise ValueError("history message violates ChatMessageRecord") from exc
    return record.model_dump(exclude_none=True)


def frontend_history_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Return a UI-facing canonical message copy."""
    return _canonical_history_message(dict(msg or {}))


def _message_content(msg: Dict[str, Any]) -> str:
    """Read visible text from the current canonical message body."""
    body = msg.get("message") if isinstance(msg.get("message"), dict) else {}
    return str(body.get("content") or "")


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
    event_type = str(event_type or "").strip()
    if event_type not in GROUP_SESSION_EVENT_TYPES:
        raise ValueError(f"unsupported session event type: {event_type or '<empty>'}")
    event = {"__event_type": event_type}
    if event_type == "message" and payload:
        payload = frontend_history_message(payload)
    if event_type in {"runtime", "deleted"}:
        event["session_id"] = group_session_id
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


def _clean_runtime_state(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(state, dict):
        return {"running": False}
    allowed = {"running", "run_id", "agent_name", "skill", "phase", "started_at"}
    cleaned = {key: value for key, value in state.items() if key in allowed and value is not None}
    running = cleaned.get("running") is True
    if "phase" in cleaned:
        phase = _runtime_phase(cleaned.get("phase"), running=running)
        if phase:
            cleaned["phase"] = phase
        else:
            cleaned.pop("phase", None)
    elif running:
        cleaned["phase"] = "routing"
    return cleaned


def _runtime_phase(value: Any, *, running: bool) -> str:
    phase = str(value or "").strip()
    if phase in RUNTIME_PHASES:
        return phase
    return "routing" if running else ""


def write_group_runtime(
    group_session_id: str,
    state: Optional[Dict[str, Any]],
    *,
    notify_runtime: Optional[Dict[str, Any]] = None,
) -> None:
    session_definitions = load_session_definitions()
    item = session_definitions.get(group_session_id)
    if item is None:
        return
    root = ensure_sessions_dir()
    runtime_path = _runtime_json_path(root, group_session_id)
    clean_state = _clean_runtime_state(state)
    if state:
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(json.dumps(clean_state, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        with suppress(OSError):
            runtime_path.unlink()
    save_session_definitions(session_definitions)
    clean_notify_runtime = _clean_runtime_state(notify_runtime) if notify_runtime is not None else clean_state
    schedule_group_session_event(
        group_session_id,
        "runtime",
        {"runtime": clean_notify_runtime or {"running": False}},
    )


def load_group_orchestration_state(group_session_id: str) -> Dict[str, Any]:
    """Load refresh-safe short-term orchestration state for one session."""
    raw = _read_json_object(_orchestration_json_path(ensure_sessions_dir(), group_session_id))
    return _clean_orchestration_state(raw or {})


def write_group_orchestration_state(group_session_id: str, state: Optional[Dict[str, Any]]) -> None:
    """Write orchestration_state.json without copying old scheduler fields into session.json."""
    root = ensure_sessions_dir()
    path = _orchestration_json_path(root, group_session_id)
    clean = _clean_orchestration_state(state or {})
    if clean:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        with suppress(OSError):
            path.unlink()


def runtime_for_active_run(active: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "running": True,
        "run_id": str(active.get("run_id") or ""),
        "agent_name": str(active.get("agent_name") or ""),
        "skill": str(active.get("skill") or ""),
        "phase": _runtime_phase(active.get("phase"), running=True),
        "started_at": active.get("started_at") or "",
    }


def _runtime_stale_seconds() -> int:
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


def _stored_runtime_is_stale(stored: Any) -> bool:
    if not isinstance(stored, dict) or stored.get("running") is not True:
        return False
    started = _parse_runtime_timestamp(str(stored.get("started_at") or ""))
    if started is None:
        return True
    age = (datetime.now(timezone.utc) - started).total_seconds()
    return age >= _runtime_stale_seconds()


def runtime_for_session(group_session_id: str, session_item: Dict[str, Any]) -> Dict[str, Any]:
    active = ACTIVE_GROUP_RUNS.get(group_session_id)
    if active:
        task = active.get("task")
        if isinstance(task, asyncio.Task) and task.done():
            run_id = str(active.get("run_id") or "")
            logger.warning(
                "group_chat_runtime_stale_done session=%s run_id=%s",
                group_session_id,
                run_id,
            )
            ACTIVE_GROUP_RUNS.pop(group_session_id, None)
            write_group_runtime(group_session_id, None)
        else:
            return runtime_for_active_run(active)
    stored = None
    with suppress(Exception):
        stored = _read_json_object(_runtime_json_path(ensure_sessions_dir(), group_session_id))
    if _stored_runtime_is_stale(stored):
        logger.warning(
            "group_chat_runtime_stale_stored session=%s run_id=%s phase=%s started_at=%s",
            group_session_id,
            str(stored.get("run_id") or "") if isinstance(stored, dict) else "",
            str(stored.get("phase") or "") if isinstance(stored, dict) else "",
            str(stored.get("started_at") or "") if isinstance(stored, dict) else "",
        )
        failed_runtime = {"running": False, "phase": "failed"}
        write_group_runtime(group_session_id, None, notify_runtime=failed_runtime)
        return failed_runtime
    return _clean_runtime_state(stored) if isinstance(stored, dict) else {"running": False}


async def register_group_run(group_session_id: str, *, user_id: str, task: asyncio.Task[Any], turn_started_checkpoint_id: str | None = None) -> str:
    run_id = uuid.uuid4().hex
    started_at = format_storage_timestamp()
    state = {
        "running": True,
        "run_id": run_id,
        "agent_name": "",
        "skill": "",
        "phase": "routing",
        "started_at": started_at,
    }
    checkpoint_id = str(turn_started_checkpoint_id or "").strip()
    if checkpoint_id:
        state["turn_started_checkpoint_id"] = checkpoint_id
    async with ACTIVE_GROUP_RUNS_LOCK:
        prev = ACTIVE_GROUP_RUNS.get(group_session_id)
        prev_task = prev.get("task") if isinstance(prev, dict) else None
        if isinstance(prev_task, asyncio.Task) and prev_task is not task and not prev_task.done():
            prev_task.cancel()
        ACTIVE_GROUP_RUNS[group_session_id] = {**state, "task": task}
    write_group_runtime(group_session_id, state)
    return run_id


async def update_group_run(group_session_id: str, run_id: str, **updates: Any) -> None:
    async with ACTIVE_GROUP_RUNS_LOCK:
        active = ACTIVE_GROUP_RUNS.get(group_session_id)
        if not active or str(active.get("run_id") or "") != run_id:
            return
        active.update({k: v for k, v in updates.items() if v is not None})
        state = {k: v for k, v in active.items() if k != "task"}
    write_group_runtime(group_session_id, state)


async def finish_group_run(group_session_id: str, run_id: str) -> None:
    async with ACTIVE_GROUP_RUNS_LOCK:
        active = ACTIVE_GROUP_RUNS.get(group_session_id)
        if not active or str(active.get("run_id") or "") != run_id:
            return
        ACTIVE_GROUP_RUNS.pop(group_session_id, None)
    write_group_runtime(group_session_id, None)


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


def build_session_payload(session_id: str, session_item: Dict[str, Any]) -> Dict[str, Any]:
    """Build the stable response shape used by the sessions API."""
    clean_item = _clean_session_definition(session_item)
    names = list(clean_item.get("agent_names", []))
    out = {
        "id": session_id,
        "title": clean_item.get("title", "新对话"),
        "title_auto_generated": clean_item.get("title_auto_generated"),
        "agent_names": names,
        "host": dict(clean_item.get("host") or {}),
        "scenario_prompt": str(clean_item.get("scenario_prompt") or ""),
        "created_at": clean_item.get("created_at", ""),
        "updated_at": clean_item.get("updated_at", ""),
        "runtime": runtime_for_session(session_id, clean_item),
    }
    return out


def load_session_definitions() -> Dict[str, Dict[str, Any]]:
    """Load sessions by scanning sessions/{session_id}/session.json only."""
    root = ensure_sessions_dir()
    out: Dict[str, Dict[str, Any]] = {}
    for child in root.iterdir():
        if not child.is_dir():
            continue
        session_path = child / "session.json"
        if not session_path.exists():
            continue
        try:
            item = json.loads(session_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(item, dict):
            out[child.name] = _clean_session_definition(item)
    return out


def save_session_definitions(session_definitions: Dict[str, Dict[str, Any]], *, preserve_unmentioned: bool = True) -> None:
    """Persist each session definition to its own session.json file."""
    root = ensure_sessions_dir()
    data = {str(k): _clean_session_definition(v) for k, v in (session_definitions or {}).items() if isinstance(v, dict)}
    if preserve_unmentioned:
        try:
            current = load_session_definitions()
            if isinstance(current, dict):
                data = dict(current)
                for session_id, incoming_item in (session_definitions or {}).items():
                    current_item = current.get(session_id)
                    if isinstance(current_item, dict) and isinstance(incoming_item, dict):
                        current_updated_at = str(current_item.get("updated_at") or "")
                        incoming_updated_at = str(incoming_item.get("updated_at") or "")
                        if current_updated_at and incoming_updated_at and current_updated_at > incoming_updated_at:
                            continue
                    data[session_id] = _clean_session_definition(incoming_item)
        except Exception:
            data = {str(k): _clean_session_definition(v) for k, v in (session_definitions or {}).items() if isinstance(v, dict)}
    for session_id, item in data.items():
        session_path = _session_json_path(root, session_id)
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_text(json.dumps(_clean_session_definition(item), ensure_ascii=False, indent=2), encoding="utf-8")
    if not preserve_unmentioned:
        keep_ids = set(data)
        for child in root.iterdir():
            if child.is_dir() and child.name not in keep_ids:
                with suppress(OSError):
                    (child / "session.json").unlink()


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
            canonical_messages: List[Dict[str, Any]] = []
            for idx, item in enumerate(data):
                try:
                    canonical_messages.append(_canonical_history_message(item))
                except ValueError as exc:
                    raise ValueError(f"history message violates ChatMessageRecord at index {idx}") from exc
            return canonical_messages
        except (OSError, json.JSONDecodeError, TypeError):
            return []
    return []


def save_group_history(
    group_session_id: str,
    messages: List[Dict[str, Any]],
    *,
    checkpoint_trigger: str | None = "turn_started",
) -> Dict[str, Any] | None:
    from app.session_state.paths import ensure_session_layout

    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        path = ensure_sessions_dir() / group_session_id / "history.json"
    else:
        layout = ensure_session_layout(user_ctx, group_session_id)
        path = layout.history
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical_messages = [_canonical_history_message(item) for item in (messages or [])]
    path.write_text(json.dumps(canonical_messages, ensure_ascii=False, indent=2), encoding="utf-8")
    if canonical_messages:
        schedule_group_session_event(group_session_id, "message", canonical_messages[-1])
    checkpoint: Dict[str, Any] | None = None
    try:
        from app.session_state.service import capture_session_checkpoint

        if checkpoint_trigger:
            checkpoint = capture_session_checkpoint(group_session_id, trigger=checkpoint_trigger)
    except Exception:
        logger.warning("session_state history checkpoint failed: %s", group_session_id, exc_info=True)
    return checkpoint


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
