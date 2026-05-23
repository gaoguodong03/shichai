"""群聊 API - 多 DHA 群聊会话与消息"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import uuid
import difflib
import asyncio
from contextlib import suppress
from urllib.parse import parse_qs, unquote, urlparse
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional, Dict, Any, List, Tuple

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage  # type: ignore

from app.api.dha import load_dha_instances, enrich_dha_instances
from app.core.host_config import normalize_host_config_dict
from app.core.scene_host import VIRTUAL_SCENE_HOST_ID
from app.api.settings import (
    normalize_host_profile,
    load_api_secret_values,
    load_app_settings,
)
from app.api.files import get_workspace_root_path
from app.agent.llm_client import get_llm_from_config
from app.agent.skill_agent_runtime import create_skill_execution_agent
from app.agent.expert_runtime import build_expert_turn_runtime
from app.agent.leader_scheduler import leader_decide
from app.agent.group_memory_store import (
    append_llm_roundtrip,
    upsert_facts,
    build_dispatch_context,
)
from app.agent.orchestrator_state import (
    DecisionSource,
    InterruptReason,
    OrchestrationContext,
    OrchestrationDecision,
    OrchestrationPhase,
    build_end_payload,
)
from app.agent.orchestrator_reducer import apply_decision, move_to_interrupt, start_turn
from app.agent.orchestrator_audit import append_audit_event
from app.agent.hook_pipeline import HookPipeline, HookPriority, HookResult
from app.agent.file_ref_resolver import resolve_file_refs_in_text
from app.agent.tools_for_skill import build_tools_for_group_chat
from app.skills.loader import get_skills_loader_for_user
from app.core.init import ensure_mcp_and_skills_initialized
from app.core.feature_flags import is_feature_enabled
from app.core.user_context import get_current_user_context
from app.core.security import user_context_dependency, get_current_user
from app.core.scene_scheduler import finalize_host_scheduler_decision, RECRUIT_FIXED_MESSAGE
from app.agent.scene_runtime import SceneRuntime, pick_scene_host_skill_id
from app.agent.group_orchestration_fsm import (
    clear_skill_session_lock,
    default_orchestration_profile_for_new_session,
    effective_orchestration_profile,
    persist_skill_session_lock,
    resolve_group_entry_route,
    user_requests_exit_skill_session,
)
from app.agent.skill_session_contract import (
    resolve_skill_session_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["group_chat"], dependencies=[Depends(user_context_dependency)])

_SSE_AGENT_KEEPALIVE_INTERVAL_SEC = 15.0
_ACTIVE_GROUP_RUNS: Dict[str, Dict[str, Any]] = {}
_ACTIVE_GROUP_RUNS_LOCK = asyncio.Lock()
_GROUP_SESSION_EVENT_SUBSCRIBERS: Dict[str, List[asyncio.Queue[Dict[str, Any]]]] = {}
_GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK = asyncio.Lock()


async def _iter_with_keepalive(source: AsyncIterator[Any], *, interval_sec: float = _SSE_AGENT_KEEPALIVE_INTERVAL_SEC) -> AsyncIterator[Any]:
    """Yield upstream items, plus lightweight keepalive markers while the upstream is idle."""
    done = object()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def _pump() -> None:
        try:
            async for item in source:
                await queue.put(item)
        except Exception as exc:  # noqa: BLE001
            await queue.put(exc)
        finally:
            await queue.put(done)

    task = asyncio.create_task(_pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=max(0.001, float(interval_sec)))
            except asyncio.TimeoutError:
                yield {"type": "keepalive"}
                continue
            if item is done:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def _publish_group_session_event(group_session_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    event = {
        "type": event_type,
        "session_id": group_session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if payload:
        event.update(payload)
    async with _GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
        queues = list(_GROUP_SESSION_EVENT_SUBSCRIBERS.get(group_session_id) or [])
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
        async with _GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
            current = _GROUP_SESSION_EVENT_SUBSCRIBERS.get(group_session_id) or []
            _GROUP_SESSION_EVENT_SUBSCRIBERS[group_session_id] = [q for q in current if q not in stale]


def _schedule_group_session_event(group_session_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    if not group_session_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_publish_group_session_event(group_session_id, event_type, payload))


def _write_group_runtime_state(group_session_id: str, state: Optional[Dict[str, Any]]) -> None:
    meta = _load_group_meta()
    item = meta.get(group_session_id)
    if item is None:
        return
    if state:
        item["runtime_state"] = state
    else:
        item.pop("runtime_state", None)
    _save_group_meta(meta)
    _schedule_group_session_event(
        group_session_id,
        "runtime_state",
        {"runtime_state": state or {"running": False}},
    )


def _runtime_state_for_active_run(active: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "running": True,
        "run_id": str(active.get("run_id") or ""),
        "agent_id": str(active.get("agent_id") or ""),
        "skill_id": str(active.get("skill_id") or ""),
        "phase": str(active.get("phase") or "running"),
        "started_at": active.get("started_at") or "",
    }


def _runtime_state_for_session(group_session_id: str, meta_item: Dict[str, Any]) -> Dict[str, Any]:
    active = _ACTIVE_GROUP_RUNS.get(group_session_id)
    if active:
        task = active.get("task")
        if isinstance(task, asyncio.Task) and task.done():
            run_id = str(active.get("run_id") or "")
            logger.warning(
                "group_chat_runtime_state_stale_done session=%s run_id=%s",
                group_session_id,
                run_id,
            )
            _ACTIVE_GROUP_RUNS.pop(group_session_id, None)
            meta_item.pop("runtime_state", None)
            _write_group_runtime_state(group_session_id, None)
        else:
            return _runtime_state_for_active_run(active)
    stored = meta_item.get("runtime_state")
    return stored if isinstance(stored, dict) else {"running": False}


async def _register_group_run(group_session_id: str, *, user_id: str, task: asyncio.Task[Any]) -> str:
    run_id = uuid.uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat()
    state = {
        "running": True,
        "run_id": run_id,
        "user_id": user_id,
        "agent_id": "",
        "skill_id": "",
        "phase": "routing",
        "started_at": started_at,
    }
    async with _ACTIVE_GROUP_RUNS_LOCK:
        prev = _ACTIVE_GROUP_RUNS.get(group_session_id)
        prev_task = prev.get("task") if isinstance(prev, dict) else None
        if isinstance(prev_task, asyncio.Task) and prev_task is not task and not prev_task.done():
            prev_task.cancel()
        _ACTIVE_GROUP_RUNS[group_session_id] = {**state, "task": task}
    _write_group_runtime_state(group_session_id, state)
    return run_id


async def _update_group_run(group_session_id: str, run_id: str, **updates: Any) -> None:
    async with _ACTIVE_GROUP_RUNS_LOCK:
        active = _ACTIVE_GROUP_RUNS.get(group_session_id)
        if not active or str(active.get("run_id") or "") != run_id:
            return
        active.update({k: v for k, v in updates.items() if v is not None})
        state = {k: v for k, v in active.items() if k != "task"}
    _write_group_runtime_state(group_session_id, state)


async def _finish_group_run(group_session_id: str, run_id: str) -> None:
    async with _ACTIVE_GROUP_RUNS_LOCK:
        active = _ACTIVE_GROUP_RUNS.get(group_session_id)
        if not active or str(active.get("run_id") or "") != run_id:
            return
        _ACTIVE_GROUP_RUNS.pop(group_session_id, None)
    _write_group_runtime_state(group_session_id, None)


async def _cancel_group_session_run(group_session_id: str, *, reason: str) -> bool:
    async with _ACTIVE_GROUP_RUNS_LOCK:
        active = _ACTIVE_GROUP_RUNS.get(group_session_id)
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
    await _finish_group_run(group_session_id, str((active or {}).get("run_id") or ""))
    return cancelled


def _log_llm_roundtrip(
    tag: str,
    *,
    system_content: str,
    user_content: str,
    model_output: str,
    session_id: str = "",
    workspace_root: Optional[Path] = None,
    max_chars: int = 6000,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """统一打印 LLM 往返（用于排查主持/调度选人问题）。"""
    def _clip(s: str) -> str:
        t = str(s or "")
        return t if len(t) <= max_chars else (t[:max_chars] + f"\n... [truncated {len(t) - max_chars} chars]")

    logger.info(
        "[LLM_ROUNDTRIP][%s] system_prompt:\n%s\n\n[LLM_ROUNDTRIP][%s] user_prompt:\n%s\n\n[LLM_ROUNDTRIP][%s] model_output:\n%s",
        tag,
        _clip(system_content),
        tag,
        _clip(user_content),
        tag,
        _clip(model_output),
    )
    if session_id:
        extra = extra or {}
        try:
            append_llm_roundtrip(
                session_id=session_id,
                workspace_root=workspace_root,
                phase=tag,
                input_messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ],
                output={"content": model_output},
                agent_id=str(extra.get("agent_id") or ""),
                skill_id=str(extra.get("skill_id") or ""),
                llm_provider_id=str(extra.get("llm_provider_id") or ""),
                model=str(extra.get("model") or ""),
                run_id=str(extra.get("run_id") or ""),
                client_message_id=str(extra.get("client_message_id") or ""),
                tool_specs=extra.get("tool_specs") if isinstance(extra.get("tool_specs"), list) else [],
                extra={k: v for k, v in extra.items() if k not in {"agent_id", "skill_id", "llm_provider_id", "model", "run_id", "client_message_id", "tool_specs"}},
            )
        except Exception as e:
            logger.warning("写入会话 LLM roundtrip 失败(tag=%s session=%s): %s", tag, session_id, e)

GROUP_META_FILE = "group_sessions_meta.json"
GROUP_HISTORY_PREFIX = "group_history_"

# 已废弃：不再使用旧聊天占位专家；新建会话 0 个专家时由主持人先与用户交流并推荐专家加入
CHAT_AGENT_ID = "agent-chat"

def _request_skills_loader():
    u = get_current_user()
    return get_skills_loader_for_user(u.username, u.ctx.skills_dir)


async def _ensure_initialized():
    await ensure_mcp_and_skills_initialized()


def _safe_format_template(tpl: str, **kwargs) -> str:
    """安全渲染设置中的主持人模板。

    约定变量写法为 `{var}`。注意模板内可能包含 JSON 示例（大量 `{}`），
    因此不能直接使用 str.format（会把 JSON 大括号当成占位符并报错）。
    这里采用“只替换已知变量 token”的方式，保证不会因模板内容导致群聊中断。
    """
    out = str(tpl or "")
    for k, v in (kwargs or {}).items():
        out = out.replace("{" + str(k) + "}", "" if v is None else str(v))
    return out


def _ensure_sessions_dir() -> Path:
    """根据当前用户返回群聊会话目录，实现多用户隔离。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise RuntimeError("缺少用户上下文，无法解析会话目录。")
    root = user_ctx.sessions_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _normalize_agent_ids(
    legacy_ids: Optional[List[str]] = None,
    agent_ids: Optional[List[str]] = None,
    expert_ids: Optional[List[str]] = None,
) -> List[str]:
    """统一兼容字段优先级：expert_ids > agent_ids > legacy_ids。"""
    return list(expert_ids or agent_ids or legacy_ids or [])


def _name_key(name: Any) -> str:
    return str(name or "").strip().lower()


def _to_agent_style_id(raw_id: str) -> str:
    sid = str(raw_id or "").strip()
    if not sid:
        return sid
    if sid.startswith("agent-"):
        return sid
    return f"agent-{sid}"


def _build_preferred_agent_id_map(instances: List[Dict[str, Any]]) -> Dict[str, str]:
    """Build id->preferred-id mapping; prefer agent-* within same expert name."""
    name_to_ids: Dict[str, List[str]] = {}
    for d in instances or []:
        did = str(d.get("agent_id") or "").strip()
        if not did:
            continue
        key = _name_key(d.get("name") or did)
        name_to_ids.setdefault(key, [])
        if did not in name_to_ids[key]:
            name_to_ids[key].append(did)
    name_to_preferred: Dict[str, str] = {}
    for key, ids in name_to_ids.items():
        preferred = next((x for x in ids if x.startswith("agent-")), _to_agent_style_id(ids[0]))
        name_to_preferred[key] = preferred
    id_to_preferred: Dict[str, str] = {}
    for d in instances or []:
        did = str(d.get("agent_id") or "").strip()
        if not did:
            continue
        key = _name_key(d.get("name") or did)
        id_to_preferred[did] = name_to_preferred.get(key, did)
    return id_to_preferred


def _build_preferred_instances(
    instances: List[Dict[str, Any]],
    *,
    id_to_preferred: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Clone instances to canonical agent-* ids (one row per canonical id)."""
    preferred_to_row: Dict[str, Dict[str, Any]] = {}
    for d in instances or []:
        did = str(d.get("agent_id") or "").strip()
        if not did:
            continue
        preferred = id_to_preferred.get(did, did)
        row = dict(d)
        row["agent_id"] = preferred
        # Keep one canonical row; prefer the row already using canonical id.
        if preferred not in preferred_to_row or did == preferred:
            preferred_to_row[preferred] = row
    return list(preferred_to_row.values())


def _normalize_to_preferred_agent_ids(
    ids: List[str],
    *,
    id_to_preferred: Dict[str, str],
) -> List[str]:
    out: List[str] = []
    for raw in ids or []:
        sid = str(raw or "").strip()
        if not sid:
            continue
        preferred = id_to_preferred.get(sid, sid)
        if preferred not in out:
            out.append(preferred)
    return out


def _default_leader_agent_id(preferred_instances: List[Dict[str, Any]]) -> str:
    """兼容旧数据：is_leader 专家作为主持人（新会话应使用虚拟主持人）。"""
    for d in preferred_instances or []:
        if d.get("is_leader") and d.get("agent_id"):
            return str(d.get("agent_id")).strip()
    return ""


def _pick_resolved_host_skill_id(skill_ids: List[str]) -> str:
    """从 host_config.skill_ids 中选定本轮加载的 SKILL。

    历史行为是固定使用列表第一项；若用户写成 [group-host, group-host-webnovel]，
    会误只加载通用主持，网文专精从未生效。规则：优先任一带 `group-host-` 前缀的专精 id
    （如 group-host-webnovel），否则用列表首项；空列表表示主持人不绑定 Skill。
    """
    return pick_scene_host_skill_id(skill_ids)


def _maybe_upgrade_meta_to_scene_profile(meta_item: Dict[str, Any]) -> bool:
    """虚拟主持人 + 已配置场景 host_config + 场内有人时，将缺省/recruitment 升为 scene。"""
    _prof = str(meta_item.get("orchestration_profile") or "").strip().lower()
    _hc = meta_item.get("host_config")
    if str(meta_item.get("leader_agent_id") or "").strip() != VIRTUAL_SCENE_HOST_ID:
        return False
    if not (isinstance(_hc, dict) and (meta_item.get("agent_ids") or [])):
        return False
    if _prof in ("", "recruitment"):
        meta_item["orchestration_profile"] = "scene"
        return True
    return False


def _build_session_payload(session_id: str, meta_item: Dict[str, Any]) -> Dict[str, Any]:
    """统一会话输出结构。"""
    ids = list(meta_item.get("agent_ids", []))
    leader_id = meta_item.get("leader_agent_id", "")
    hc = meta_item.get("host_config")
    out = {
        "id": session_id,
        "title": meta_item.get("title", "新对话"),
        "agent_ids": ids,
        "expert_ids": ids,
        "leader_agent_id": leader_id,
        "speak_mode": meta_item.get("speak_mode", "auto"),
        "created_at": meta_item.get("created_at", ""),
        "updated_at": meta_item.get("updated_at", ""),
        "runtime_state": _runtime_state_for_session(session_id, meta_item),
    }
    if isinstance(hc, dict):
        out["host_config"] = hc
    prof = str(meta_item.get("orchestration_profile") or "").strip().lower()
    if prof in ("recruitment", "scene"):
        out["orchestration_profile"] = prof
    else:
        out["orchestration_profile"] = effective_orchestration_profile(meta_item, agent_ids=list(meta_item.get("agent_ids") or []))
    return out


def _load_group_meta() -> Dict[str, Dict[str, Any]]:
    path = _ensure_sessions_dir() / GROUP_META_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _save_group_meta(meta: Dict[str, Dict[str, Any]]) -> None:
    path = _ensure_sessions_dir() / GROUP_META_FILE
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_group_history(group_session_id: str) -> List[Dict[str, Any]]:
    path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def _save_group_history(group_session_id: str, messages: List[Dict[str, Any]]) -> None:
    path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
    _schedule_group_session_event(
        group_session_id,
        "messages_updated",
        {"message_count": len(messages or [])},
    )


def _cleanup_orphan_group_histories(meta: Dict[str, Dict[str, Any]]) -> int:
    """清理不在 meta 中的群聊历史文件，返回删除数量。"""
    root = _ensure_sessions_dir()
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
    return deleted


def _build_archive_segments(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将会话消息归档分段（按轮次）并按专家聚合，不包含主持人。

    轮次定义（尽量符合用户直觉）：
    - 遇到 user 消息，开启新一轮；
    - 在这一轮内收集后续 assistant（专家）发言（按 agent_id 分组，保留顺序）；
    - role=host 的消息跳过（不归档）。
    """
    segments: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def _ensure_current() -> Dict[str, Any]:
        nonlocal current
        if current is None:
            current = {
                "user": None,
                "experts": {},  # agent_id -> {agent_id, messages:[{message_id, content, timestamp, skill_id?}]}
            }
        return current

    def _flush():
        nonlocal current
        if not current:
            current = None
            return
        # 只要这一轮有 user 或有专家发言就保留
        has_user = bool(current.get("user"))
        experts = current.get("experts") or {}
        has_expert = any((v.get("messages") or []) for v in experts.values()) if isinstance(experts, dict) else False
        if has_user or has_expert:
            # experts 由 dict 转 list，保持插入顺序（Python 3.7+ dict 有序）
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
            agent_id = (m.get("agent_id") or "").strip()
            if not agent_id:
                continue
            experts = cur.get("experts")
            if not isinstance(experts, dict):
                experts = {}
                cur["experts"] = experts
            if agent_id not in experts:
                experts[agent_id] = {"agent_id": agent_id, "messages": []}
            item = {
                "message_id": m.get("message_id"),
                "content": m.get("content") or "",
                "timestamp": m.get("timestamp"),
            }
            if m.get("skill_id") is not None:
                item["skill_id"] = m.get("skill_id")
            experts[agent_id]["messages"].append(item)
            continue
        # 其他 role 忽略

    _flush()
    return segments


@router.get("/sessions/{group_session_id}/archive")
async def get_group_archive(group_session_id: str):
    """会话归档：按轮次分段，并展示每位专家发言（不包含主持人）。"""
    # 确保会话存在
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    messages = _load_group_history(group_session_id)
    segments = _build_archive_segments(messages)
    # agent_map 用于前端展示名字
    instances = load_dha_instances()
    agent_map = {
        d.get("agent_id"): {
            "name": d.get("name") or d.get("agent_id"),
            "role": d.get("role") or "",
            "avatar_url": str(d.get("avatar_url") or "").strip(),
        }
        for d in instances
        if d.get("agent_id")
    }
    return {"status": "ok", "data": {"segments": segments, "agent_map": agent_map, "expert_map": agent_map}}


def _messages_to_context(
    messages: List[Dict[str, Any]],
    max_turns: int = 15,
    max_chars: int = 12000,
    max_chars_per_message: int = 1200,
) -> str:
    """将群聊消息转为供领导人/DHA 使用的上下文字符串（带长度保护）。

    - 限制每条消息长度，避免单条工具结果把上下文撑爆
    - 限制总上下文长度，超限时仅保留尾部（最近信息优先）
    """
    recent = messages[-max_turns * 2:] if len(messages) > max_turns * 2 else messages
    lines = []
    for m in recent:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if len(content) > max_chars_per_message:
            content = content[:max_chars_per_message].rstrip() + "\n...[内容已截断]"
        agent_id = m.get("agent_id", "")
        if role == "user":
            lines.append(f"【用户】{content}")
        elif role == "host":
            lines.append(f"【主持人】{content}")
        else:
            name = agent_id or "助手"
            lines.append(f"【{name}】{content}")
    context = "\n\n".join(lines)
    if len(context) > max_chars:
        context = "...[较早历史已省略]\n\n" + context[-max_chars:]
    return context


def _is_group_context_noise(content: str) -> bool:
    """过滤不应再次喂给专家模型的技术错误回执，避免错误历史自我放大撑爆上下文。"""
    s = (content or "").strip()
    if not s:
        return False
    noise_markers = (
        "抱歉，模型响应失败",
        "Error code: 400",
        "Error code: 404",
        "Error code: 500",
        "context length is only",
        "input_tokens",
        "gateway_tool_unavailable",
        "gateway executor error",
        "Model not found or no running instances available",
        "EngineCore encountered an issue",
        "技术原因导致",
        "工具暂时不可用",
        "系统暂时无法查询",
    )
    return any(marker in s for marker in noise_markers)


def _messages_to_expert_context(messages: List[Dict[str, Any]]) -> str:
    """专家执行上下文：保留最近有效业务信息，剔除技术错误回执，并控制 4k 小模型预算。"""
    filtered: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    skipped = 0
    for m in messages or []:
        content = (m.get("content") or "").strip() if isinstance(m, dict) else ""
        if _is_group_context_noise(content):
            skipped += 1
            continue
        key = (str(m.get("role") or ""), str(m.get("agent_id") or ""), content)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        filtered.append(m)
    context = _messages_to_context(
        filtered,
        max_turns=3,
        max_chars=700,
        max_chars_per_message=240,
    )
    if skipped:
        logger.debug("group_expert_context_noise_filtered skipped=%s kept=%s", skipped, len(filtered))
    return context


def _scheduler_recent_context(group_session_id: str, messages: List[Dict[str, Any]]) -> str:
    """主持人调度上下文：仅使用最近对话摘录。"""
    _ = group_session_id
    return _messages_to_context(messages)


def _normalize_discussion_goal(raw: str, max_len: int = 200) -> str:
    """从用户消息中提取纯讨论目标，去掉前端的「【讨论目标】」前缀，避免在 prompt 中重复出现。"""
    if not raw or not isinstance(raw, str):
        return (raw or "").strip()[:max_len] if raw else ""
    s = (raw or "").strip()
    prefix = "【讨论目标】"
    if s.startswith(prefix):
        s = s[len(prefix) :].lstrip("\n ")
    return s[:max_len] if len(s) > max_len else s


def _title_from_first_message(text: str, max_chars: int = 10) -> str:
    """根据用户首次发送生成会话标题，约 max_chars 字以内。去掉【讨论目标】等前缀，取首行或截断。"""
    if not text or not isinstance(text, str):
        return ""
    s = text.strip()
    for prefix in ("【讨论目标】", "【给下一 DHA 的提示】"):
        if s.startswith(prefix):
            s = s[len(prefix) :].lstrip("\n ")
    first_line = s.split("\n")[0].strip() if s else ""
    if not first_line:
        return ""
    if len(first_line) > max_chars:
        return first_line[:max_chars].rstrip()
    return first_line


async def _ai_title_from_recent_user_messages(
    llm: Any,
    messages: List[Dict[str, Any]],
    max_chars: int = 18,
    max_user_messages: int = 6,
    group_session_id: str = "",
    llm_provider_id: str = "",
) -> str:
    """根据最近用户发言，AI 生成约 15 字主题（用于群聊标题）。"""
    try:
        user_texts: List[str] = []
        for m in reversed(messages or []):
            if not isinstance(m, dict):
                continue
            if (m.get("role") or "").strip() != "user":
                continue
            content = (m.get("content") or "").strip()
            if not content:
                continue
            user_texts.append(_normalize_discussion_goal(content))
            if len(user_texts) >= max_user_messages:
                break
        user_texts.reverse()
        if not user_texts:
            return ""

        client = llm.get_client()
        system_prompt = (
            "你是中文会议主题提取器。根据下面用户在群聊中的发言，提取当前讨论的核心主题。\n"
            "输出要求：\n"
            f"- 只输出“主题本身”，不要输出任何前缀（如：主题/讨论主题/群聊/标题/：）\n"
            f"- 中文主题，长度约 15 字（允许最多 {max_chars} 字）\n"
            "- 不要使用引号或括号，不要以句号/感叹号/问号结尾\n"
        )
        content = "最近用户发言：\n" + "\n\n".join([f"{i+1}. {t}" for i, t in enumerate(user_texts)])
        resp = await client.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=content)])
        raw = (getattr(resp, "content", "") or "").strip()
        if group_session_id:
            try:
                append_llm_roundtrip(
                    session_id=group_session_id,
                    phase="title_generation",
                    input_messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content},
                    ],
                    output={"content": raw},
                    llm_provider_id=llm_provider_id,
                    model=str(getattr(llm, "model", "") or ""),
                )
            except Exception as trace_err:
                logger.warning("写入会话 LLM roundtrip 失败(tag=title_generation session=%s): %s", group_session_id, trace_err)
        if not raw:
            return ""
        # 只取第一行，去掉常见前缀/标点
        s = raw.splitlines()[0].strip()
        s = re.sub(r"^(主题|讨论主题|标题|群聊主题|当前主题)\\s*[:：]\\s*", "", s)
        s = s.strip().strip("“”\"'（）()[]【】")
        while s and s[-1] in "。！？…":
            s = s[:-1].strip()
        if len(s) > max_chars:
            s = s[:max_chars].rstrip()
        return s
    except Exception as e:
        logger.error(f"AI 生成群聊主题失败: {e}", exc_info=True)
        return ""


def _schedule_group_title_refresh(
    group_session_id: str,
    messages_snapshot: List[Dict[str, Any]],
    *,
    max_chars: int = 18,
    max_user_messages: int = 6,
) -> None:
    """后台刷新群聊标题，避免标题 LLM 阻塞主对话链路。"""
    session_id = (group_session_id or "").strip()
    if not session_id:
        return

    async def _runner() -> None:
        started = time.perf_counter()
        try:
            app_settings = load_app_settings()
            llm_provider_id = app_settings.get("default_llm", "qwen")
            secrets = load_api_secret_values()
            llm = get_llm_from_config(llm_provider_id, app_settings.get("llm_providers"), secrets)
            ai_title = await _ai_title_from_recent_user_messages(
                llm,
                messages_snapshot,
                max_chars=max_chars,
                max_user_messages=max_user_messages,
                group_session_id=session_id,
                llm_provider_id=str(llm_provider_id or ""),
            )
            if not ai_title:
                logger.info(
                    "group_chat_title_background_skip session=%s reason=empty elapsed_ms=%s",
                    session_id,
                    int((time.perf_counter() - started) * 1000),
                )
                return
            latest_meta = _load_group_meta()
            meta_item = latest_meta.get(session_id)
            if not isinstance(meta_item, dict):
                return
            current_title = (meta_item.get("title") or "").strip()
            placeholder_titles = ("新对话", "新群聊", "")
            is_template_title = current_title.startswith("多Agent协作 ·")
            title_auto_generated = meta_item.get("title_auto_generated")
            if title_auto_generated is None:
                title_auto_generated = current_title in placeholder_titles or is_template_title or len(current_title) <= 12
            if not (title_auto_generated or current_title in placeholder_titles or is_template_title):
                logger.info(
                    "group_chat_title_background_skip session=%s reason=manual_title title=%r",
                    session_id,
                    current_title,
                )
                return
            meta_item["title"] = ai_title
            meta_item["title_auto_generated"] = True
            _save_group_meta(latest_meta)
            logger.debug(
                "group_chat_title_background_done session=%s title=%r elapsed_ms=%s",
                session_id,
                ai_title,
                int((time.perf_counter() - started) * 1000),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("group_chat_title_background_failed session=%s err=%s", session_id, e)

    asyncio.create_task(_runner())


def _title_refresh_every_user_message() -> bool:
    return (os.getenv("GROUP_CHAT_TITLE_REFRESH_EVERY_MESSAGE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _build_next_prompt_fallback(discussion_goal: str, context: str) -> str:
    """当主持人未输出 next_prompt 时使用的默认提示词模板。
    刻意给出较完整的最近讨论内容，便于下一位专家（尤其是配图/生成类）有足够信息执行。"""
    return (
        f"【群聊讨论目标】\n{discussion_goal}\n\n"
        f"【最近几轮讨论内容（按时间顺序，含用户与各位专家的发言要点）】\n{context}\n\n"
        "【你这一轮的任务】\n"
        "1. 先用 1～3 句话总结当前讨论已达成的结论或共识。\n"
        "2. 结合你的角色与专长，完成本轮的 1～2 个具体子任务；可从上方「最近几轮讨论内容」中摘取关键信息（链接、主题、用户偏好、已有文案等）直接使用。\n"
        "3. 若涉及生成图片/配图/封面：请根据讨论中的文案或要点确定配图主题与风格，并说明所需尺寸或数量（若已提及）。\n"
        "4. 仅输出你本轮可交付结果，不要在正文中安排下一位角色。\n\n"
        "【输出要求】信息量充足、紧扣目标；可分条书写；避免大段照抄全文，侧重提炼与执行。"
    )


def _get_group_memory_settings(app_settings: Dict[str, Any]) -> Dict[str, Any]:
    cfg = app_settings.get("group_memory") if isinstance(app_settings, dict) else {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "max_logs": int(cfg.get("max_logs", 20)),
        "max_facts": int(cfg.get("max_facts", 60)),
        "dispatch_top_k": int(cfg.get("dispatch_top_k", 3)),
    }


def _extract_facts_from_response(text: str, max_items: int = 4) -> List[str]:
    s = (text or "").strip()
    if not s:
        return []
    lines: List[str] = []
    for line in s.splitlines():
        t = line.strip()
        if not t:
            continue
        if t.startswith(("-", "*", "1.", "2.", "3.", "4.", "5.")):
            t = t.lstrip("-*0123456789. ").strip()
        if len(t) < 6:
            continue
        lines.append(t[:220])
        if len(lines) >= max_items:
            break
    if lines:
        return lines
    compact = s.replace("\n", " ")
    chunks = [x.strip() for x in re.split(r"[。；;.!?！？]", compact) if x.strip()]
    return [c[:220] for c in chunks[:max_items]]


def _persist_group_memory_turn(
    *,
    session_id: str,
    msg: Dict[str, Any],
    discussion_goal: str,
    input_prompt_summary: str,
    app_settings: Dict[str, Any],
    workspace_root: Optional[Path] = None,
) -> None:
    """从可见专家发言中维护 facts.md；排障日志由 llm_roundtrips.jsonl 独立承担。"""
    mem = _get_group_memory_settings(app_settings)
    if not mem["enabled"]:
        return
    role = str((msg or {}).get("role") or "").strip()
    if role != "assistant":
        return
    content = str((msg or {}).get("content") or "").strip()
    if not content:
        return
    facts_delta = _extract_facts_from_response(content)
    if facts_delta:
        upsert_facts(
            session_id=session_id,
            facts_delta=facts_delta,
            max_facts=mem["max_facts"],
            workspace_root=workspace_root,
        )


def _build_next_prompt_with_memory(
    session_id: str,
    target_agent_id: str,
    discussion_goal: str,
    context: str,
    app_settings: Dict[str, Any],
    decision_next_prompt: Optional[str] = None,
) -> str:
    mem = _get_group_memory_settings(app_settings)
    if not mem["enabled"]:
        return (decision_next_prompt or "").strip() or _build_next_prompt_fallback(discussion_goal, context)

    dispatch = {"has_memory": False, "rendered": ""}
    try:
        dispatch = build_dispatch_context(
            session_id=session_id,
            target_agent_id=target_agent_id,
            goal=discussion_goal,
            k=mem["dispatch_top_k"],
            max_facts=mem["max_facts"],
        )
    except Exception:
        logger.warning("group memory read failed", exc_info=True)

    if dispatch.get("has_memory"):
        # 必须保留主持人点名时的 next_prompt；否则记忆摘录（多为上一阶段文案/事实）会盖过「生图/配图」等本轮指派。
        chunks: List[str] = []
        host_line = (decision_next_prompt or "").strip()
        if host_line:
            chunks.append(
                "【主持人本轮指派（必须按此执行；与下方记忆摘录冲突时以本段为准）】\n" + host_line
            )
        chunks.extend(
            [
                f"【群聊讨论目标】\n{discussion_goal}",
                "【任务要求】\n请先用 1-2 句复述当前你要完成的子任务，再输出可执行结果；若信息不足，先提出最小补充问题（最多 2 个）。",
                str(dispatch.get("rendered") or "").strip(),
            ]
        )
        chunks.append("【输出要求】\n聚焦执行，不复读整段历史；不要在正文中指定下一位角色。")
        return "\n\n".join([c for c in chunks if c])

    return (decision_next_prompt or "").strip() or _build_next_prompt_fallback(discussion_goal, context)


def _shorten_text(text: str, max_chars: int = 1800) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rstrip() + "\n...[内容已截断]"


def _normalize_compare_text(text: str) -> str:
    s = (text or "").lower()
    s = re.sub(r"[\s\r\n\t]+", "", s)
    s = re.sub(r"[`~!@#$%^&*()_\-+=\[\]{}\\|;:'\",.<>/?，。！？；：、“”‘’（）《》【】…·]", "", s)
    return s


def _ensure_structured_next_prompt(
    prompt: str,
    discussion_goal: str,
    context: str,
    target_agent_id: str,
    *,
    host_round_instruction: Optional[str] = None,
) -> str:
    """轻量校验 next_prompt 结构，不足时补齐关键段落，避免专家空转。"""
    p = (prompt or "").strip()
    context_excerpt = _shorten_text(context, max_chars=1600)
    hi = (host_round_instruction or "").strip()
    host_already_in_p = bool(
        hi
        and (
            "【主持人本轮指派" in p
            or "主持人本轮指派" in p
            or (len(hi) >= 20 and hi[: min(80, len(hi))] in p)
        )
    )
    has_goal = ("【群聊讨论目标】" in p) or ("讨论目标" in p)
    has_input = any(
        k in p
        for k in (
            "【最近讨论】",
            "【最近几轮讨论内容",
            "【输入依据】",
            "【上下文】",
            "【已知信息】",
            "【关键事实】",
        )
    )
    has_output_format = any(k in p for k in ("【输出格式】", "【输出要求】", "格式要求", "请按以下格式"))
    has_boundary = any(k in p for k in ("【边界条件】", "若信息不足", "不要", "禁止", "最多"))
    has_delivery = any(k in p for k in ("【交付标准】", "【完成标准】", "验收标准", "达标"))
    compact_len = len(_normalize_compare_text(p))
    missing_core = sum([not has_goal, not has_input, not has_output_format])

    host_anchor = ""
    if hi and not host_already_in_p:
        host_anchor = (
            "【主持人本轮指派（必须按此执行；与下方模板冲突时以本段为准）】\n" + hi + "\n\n"
        )

    # 缺失较多或内容过短时，构建可执行的结构化模板（保留主持人点名指令）
    if (not p) or compact_len < 120 or missing_core >= 2:
        parts: List[str] = []
        if host_anchor:
            parts.append(host_anchor.rstrip())
        parts.extend(
            [
                f"【群聊讨论目标】\n{discussion_goal}",
                f"【输入依据】\n{context_excerpt}",
                "【你本轮要完成的事情】\n"
                "1. 先用 1-2 句确认你理解的子任务；\n"
                "2. 直接输出可执行结果（不是泛泛解释）；\n"
                "3. 只交付本轮结果，不要在正文中指定下一位角色。",
            ]
        )
        parts.extend(
            [
                "【输出格式】\n- 使用分点输出；\n- 每点尽量包含“动作 + 结果”；\n- 涉及链接/参数请显式写出。",
                "【边界条件】\n- 信息不足时，仅提出最多 2 个最小补充问题；\n- 不要复读整段历史，不要偏离讨论目标。",
                "【交付标准】\n- 结论清晰、可执行。",
            ]
        )
        return "\n\n".join(parts)

    parts = [p]
    if not has_goal:
        parts.append(f"【群聊讨论目标】\n{discussion_goal}")
    if not has_input:
        parts.append(f"【输入依据】\n{context_excerpt}")
    if not has_output_format:
        parts.append("【输出格式】\n请分点给出“动作 + 结果”，必要时给出链接/参数。")
    if not has_boundary:
        parts.append("【边界条件】\n若信息不足，仅提出最多 2 个最小补充问题；不要复读整段历史。")
    if not has_delivery:
        parts.append("【交付标准】\n输出应可直接执行，并能让下一位专家无歧义接力。")
    return "\n\n".join(parts)


def _build_checked_next_prompt(
    session_id: str,
    target_agent_id: str,
    discussion_goal: str,
    context: str,
    app_settings: Dict[str, Any],
    decision_next_prompt: Optional[str] = None,
) -> str:
    raw = _build_next_prompt_with_memory(
        session_id=session_id,
        target_agent_id=target_agent_id,
        discussion_goal=discussion_goal,
        context=context,
        app_settings=app_settings,
        decision_next_prompt=decision_next_prompt,
    )
    return _ensure_structured_next_prompt(
        prompt=raw,
        discussion_goal=discussion_goal,
        context=context,
        target_agent_id=target_agent_id,
        host_round_instruction=decision_next_prompt,
    )


def _looks_like_conclusion_text(text: str) -> bool:
    s = (text or "").lower()
    keys = (
        "结论", "总结", "综上", "最终", "已完成", "完成了", "没有更多", "无法继续", "请用户补充", "建议用户",
    )
    return any(k in s for k in keys)


def _has_tool_failure(tool_raw_results: List[str], full_content: str) -> bool:
    blob = "\n".join([str(x or "") for x in (tool_raw_results or [])] + [str(full_content or "")]).lower()
    fail_keys = (
        "执行错误", "error", "failed", "exception", "traceback", "timeout", "超时", "not found", "调用异常", "无法",
    )
    return any(k in blob for k in fail_keys)


def _evaluate_soft_stop(
    state: Dict[str, Any],
    current_speaker: str,
    full_content: str,
    tool_raw_results: List[str],
) -> Optional[str]:
    """软判停：连续低增量/重复结论/工具连续失败时提前暂停。"""
    prev_content = str(state.get("prev_content") or "")
    prev_speaker = str(state.get("prev_speaker") or "")
    cur_norm = _normalize_compare_text(full_content)
    prev_norm = _normalize_compare_text(prev_content)
    same_speaker = bool(prev_speaker and prev_speaker == current_speaker)

    if not same_speaker:
        state["low_increment_streak"] = 0
        state["repeat_conclusion_streak"] = 0

    if same_speaker and cur_norm and prev_norm:
        sim = difflib.SequenceMatcher(a=prev_norm[:1600], b=cur_norm[:1600]).ratio()
        low_increment = sim >= 0.88
        repeat_conclusion = sim >= 0.82 and _looks_like_conclusion_text(prev_content) and _looks_like_conclusion_text(full_content)
        state["low_increment_streak"] = int(state.get("low_increment_streak", 0)) + 1 if low_increment else 0
        state["repeat_conclusion_streak"] = int(state.get("repeat_conclusion_streak", 0)) + 1 if repeat_conclusion else 0
    else:
        state["low_increment_streak"] = 0
        state["repeat_conclusion_streak"] = 0

    has_fail = _has_tool_failure(tool_raw_results, full_content)
    state["tool_failure_streak"] = int(state.get("tool_failure_streak", 0)) + 1 if has_fail else 0
    state["prev_content"] = full_content
    state["prev_speaker"] = current_speaker

    if int(state.get("tool_failure_streak", 0)) >= 2:
        return "连续两轮出现工具执行失败/异常，建议先由用户确认或调整任务。"
    if int(state.get("repeat_conclusion_streak", 0)) >= 2:
        return "连续两轮输出结论高度重复，继续自动运行收益较低。"
    if int(state.get("low_increment_streak", 0)) >= 2:
        return "连续两轮内容增量较低，建议暂停并由用户确认下一步。"
    return None


def _has_auto_continue_signal(content: str) -> bool:
    """自动模式下判断专家是否明确表达“将继续执行下一步”。

    仅当出现明显继续推进信号时，才让同一专家在同一条流里自动连跑下一轮；
    否则默认交还用户，避免访谈类/问答类 skill 连续自说自话。
    """
    text = str(content or "").strip().lower()
    if not text:
        return False
    # 继续信号必须足够“显式”，避免把常见写作措辞（如“我将继续…”）误判为需要自动连跑下一轮。
    # 如需让专家在同一条流中自动连跑，请让其输出以下任一明确标记。
    explicit_markers = (
        "[[AUTO_CONTINUE]]",
        "【自动继续】",
        "AUTO_CONTINUE",
        "继续执行",
        "继续处理",
    )
    return any(c.lower() in text for c in explicit_markers)


def _append_workspace_image_preview_markdown(content: str, tool_raw_results: List[str]) -> str:
    """若工具结果中包含工作区图片下载链接，则自动补一段 Markdown 图片预览。"""
    if not tool_raw_results:
        return content
    urls: List[str] = []
    for raw in tool_raw_results:
        if not raw:
            continue
        for u in re.findall(r"/api/workspaces/[^\s)]+/files/download\?path=[^\s)]+", raw):
            urls.append(u)
    if not urls:
        return content
    image_urls = []
    for u in urls:
        lu = u.lower()
        if any(ext in lu for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg")):
            image_urls.append(u)
    if not image_urls:
        return content
    seen = set()
    unique_urls = []
    for u in image_urls:
        if u in seen:
            continue
        seen.add(u)
        unique_urls.append(u)
    base_text = content or ""
    # 模型正文里常会复述脚本的「下载链接」或自写「点击下载」；避免再叠一段相同 URL。
    filtered: List[str] = []
    for u in unique_urls:
        if u in base_text:
            continue
        try:
            q = parse_qs(urlparse(u).query)
            paths = q.get("path") or []
            if paths and unquote(paths[0]) in base_text:
                continue
        except Exception:
            pass
        filtered.append(u)
    unique_urls = filtered
    if not unique_urls:
        return content
    blocks = []
    for i, u in enumerate(unique_urls, start=1):
        # 仅追加 Markdown 图片行；下载文案由模型/脚本输出即可，避免与「点击下载图片」重复堆叠
        blocks.append(f"![生成图片{i}]({u})")
    extra = "\n\n".join(blocks)
    if extra in base_text:
        return content
    base = (content or "").rstrip()
    return f"{base}\n\n---\n\n{extra}" if base else extra


def _extract_tool_calls_from_accumulated(accumulated_chunks: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for chunk in accumulated_chunks or []:
        s = str(chunk or "")
        if "```json" not in s:
            continue
        try:
            block = s.split("```json", 1)[1].split("```", 1)[0].strip()
            obj = json.loads(block)
            if isinstance(obj, dict) and str(obj.get("action") or "").strip().lower() == "tool_call":
                out.append(
                    {
                        "tool": obj.get("tool"),
                        "arguments": obj.get("arguments") if isinstance(obj.get("arguments"), dict) else obj.get("arguments"),
                    }
                )
        except Exception:
            continue
    return out


def _extract_sandbox_entry_trace(raw_outputs: List[str]) -> List[Dict[str, Any]]:
    traces: List[Dict[str, Any]] = []
    for item in raw_outputs or []:
        s = str(item or "").strip()
        if not s:
            continue
        try:
            obj = json_module.loads(s)
            if isinstance(obj, dict):
                trace = obj.get("_sandbox_trace")
                if isinstance(trace, dict):
                    traces.append(trace)
        except Exception:
            continue
    return traces


def _get_llm_for_dha(dha: Optional[Dict[str, Any]], app_settings: Dict[str, Any]) -> Any:
    """按 DHA 的 llm_provider_id 或应用默认创建 LLM"""
    provider = (dha.get("llm_provider_id") or "").strip() if dha else ""
    if not provider:
        provider = app_settings.get("default_llm", "qwen")
    secrets = load_api_secret_values()
    return get_llm_from_config(provider, app_settings.get("llm_providers"), secrets)


def _get_dha_skill_content(dha: Dict[str, Any]) -> str:
    """获取 DHA 的技能内容（按 skill_ids 取第一个或 default）"""
    sl = _request_skills_loader()
    skill_ids = dha.get("skill_ids") or []
    if skill_ids:
        for sid in skill_ids:
            content = sl.get_skill_full_content(sid)
            if content:
                return content
    return sl.get_skill_full_content("default") or "你是通用助手，直接回答用户问题。"


def _last_user_message_text(messages: List[Dict[str, Any]]) -> str:
    """取最近一条用户消息全文，用于多 skill 路由。"""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            return str(m.get("content") or "").strip()
    return ""


def _resolve_dha_skill_id_and_content(
    dha: Dict[str, Any],
    discussion_goal: str,
    messages: List[Dict[str, Any]],
    ignored_skill_id: Optional[str] = None,
) -> tuple[str, str, Dict[str, Any]]:
    """当 DHA 绑定多个 skill 时，由 SkillsLoader 按各 SKILL 的 name/description（及 skill_id）与上下文的匹配度选型；无信号时回退列表顺序。

    气泡上的 skill 标签、落盘用的 skill_id 应与实际注入的 SKILL 一致；不在此文件维护场景关键词表。
    """
    sl = _request_skills_loader()
    skill_ids = [str(x).strip() for x in (dha.get("skill_ids") or []) if str(x).strip()]
    debug_info: Dict[str, Any] = {"strategy": "unknown", "scores": [], "selected_skill_id": None}
    if not skill_ids:
        c = sl.get_skill_full_content("default") or "你是通用助手，直接回答用户问题。"
        debug_info.update({"strategy": "default_no_skill_ids", "selected_skill_id": "default"})
        return "default", c, debug_info

    def _first_available_content(ids: List[str]) -> Optional[Tuple[str, str]]:
        for sid in ids:
            c = sl.get_skill_full_content(sid)
            if c:
                return sid, c
        return None

    if len(skill_ids) == 1:
        sid = skill_ids[0]
        got = _first_available_content([sid])
        if got:
            debug_info.update({"strategy": "single_skill", "selected_skill_id": got[0]})
            return got[0], got[1], debug_info
        c = sl.get_skill_full_content("default") or "你是通用助手，直接回答用户问题。"
        debug_info.update({"strategy": "single_skill_missing_content_fallback_default", "selected_skill_id": "default"})
        return "default", c, debug_info

    last_user = _last_user_message_text(messages)
    combined = f"{discussion_goal or ''}\n{last_user}".strip()
    route_debug = sl.pick_best_skill_with_debug(combined, skill_ids)
    picked = (route_debug.get("selected_skill_id") or "").strip() or None
    debug_info.update(route_debug)
    ignored_sid = (ignored_skill_id or "").strip()
    if picked and ignored_sid and picked == ignored_sid:
        # 用户点击“忽略自动切换”后，本轮应重做并避开上次命中的 skill。
        ranked = route_debug.get("scores") or []
        if isinstance(ranked, list):
            alt = next(
                (
                    str(item.get("skill_id") or "").strip()
                    for item in ranked
                    if isinstance(item, dict)
                    and str(item.get("skill_id") or "").strip()
                    and str(item.get("skill_id") or "").strip() != ignored_sid
                    and float(item.get("score") or 0.0) > 0.0
                ),
                "",
            )
            if alt:
                picked = alt
                debug_info["strategy"] = f"{debug_info.get('strategy') or 'unknown'}_ignore_override"
                debug_info["selected_skill_id"] = alt
    if picked:
        got = _first_available_content([picked])
        if got:
            debug_info["selected_skill_id"] = got[0]
            return got[0], got[1], debug_info

    # 回退：列表顺序第一个有内容的 skill（与旧版 _get_dha_skill_content 一致）
    fallback_ids = [sid for sid in skill_ids if not ignored_sid or sid != ignored_sid]
    got = _first_available_content(fallback_ids)
    if got:
        debug_info["strategy"] = f"{debug_info.get('strategy') or 'unknown'}_fallback_first_available"
        debug_info["selected_skill_id"] = got[0]
        return got[0], got[1], debug_info
    c = sl.get_skill_full_content("default") or "你是通用助手，直接回答用户问题。"
    debug_info["strategy"] = f"{debug_info.get('strategy') or 'unknown'}_fallback_default_content"
    debug_info["selected_skill_id"] = skill_ids[0] if skill_ids else "default"
    return (skill_ids[0] if skill_ids else "default"), c, debug_info


def _extract_json_object_from_llm_text(text: str) -> Optional[Dict[str, Any]]:
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    if "```json" in s:
        try:
            inner = s.split("```json", 1)[1].split("```", 1)[0].strip()
            obj = json.loads(inner)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
    if "```" in s:
        try:
            inner = s.split("```", 1)[1].split("```", 1)[0].strip()
            if inner.startswith("json"):
                inner = inner[4:].strip()
            obj = json.loads(inner)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
    try:
        lo = s.find("{")
        hi = s.rfind("}")
        if lo >= 0 and hi > lo:
            obj = json.loads(s[lo : hi + 1])
            return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    return None


def _parse_host_response(content: str) -> Optional[Dict[str, Any]]:
    """解析主持人 DHA 的回复，提取主持词与 JSON。

    期望 JSON 字段（可选）：
    - task_done: bool
    - next_speaker: "user" 或某 agent_id
    - reason / announcement: str
    - suggested_add_agent_ids: [agent_id, ...] 或 suggested_add_agent_id: agent_id
    - suggested_order: [agent_id, ...]
    """
    if not content or not content.strip():
        return None
    text = content.strip()
    announcement = ""
    json_str = ""
    if "```json" in text:
        parts = text.split("```json", 1)
        announcement = (parts[0] or "").strip()
        rest = parts[1].split("```", 1)[0].strip() if len(parts) > 1 else ""
        json_str = rest
    elif "```" in text:
        parts = text.split("```", 2)
        announcement = (parts[0] or "").strip()
        if len(parts) >= 2:
            json_str = (parts[1] or "").strip()
    else:
        for sep in ("\n{", "{"):
            if sep in text:
                idx = text.find(sep) if sep == "{" else text.find(sep) + 1
                announcement = text[:idx].strip()
                json_str = text[idx:].strip()
                break
        else:
            return None
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
        task_done = data.get("task_done", True)
        next_speaker = (data.get("next_speaker") or "user").strip().lower()
        reason = data.get("reason", "")
        # 主持人建议邀请的成员（可选）
        suggested_add_agent_ids = None
        ids_raw = data.get("suggested_add_expert_ids")
        if not isinstance(ids_raw, list) or not ids_raw:
            ids_raw = data.get("suggested_add_agent_ids")
        if isinstance(ids_raw, list) and ids_raw:
            cleaned = [str(x).strip() for x in ids_raw if str(x).strip()]
            if cleaned:
                suggested_add_agent_ids = list(dict.fromkeys(cleaned))
        if not suggested_add_agent_ids:
            sid = (data.get("suggested_add_expert_id") or data.get("suggested_add_agent_id") or "").strip()
            if sid:
                suggested_add_agent_ids = [sid]
        suggested_order = data.get("suggested_order")  # 首轮任务规划：建议的 DHA 运行顺序
        if isinstance(suggested_order, list):
            suggested_order = [str(x).strip().lower() for x in suggested_order if str(x).strip()]
        else:
            suggested_order = None
        phase = (data.get("phase") or "").strip().lower() or None
        owner_agent_id = (data.get("owner_agent_id") or "").strip() or None
        interrupt_reason = (data.get("interrupt_reason") or "").strip().lower() or None
        decision_source = (data.get("decision_source") or "").strip().lower() or "legacy"
        handoff_reason = (data.get("handoff_reason") or "").strip() or None
        required_user_fields = data.get("required_user_fields")
        if not isinstance(required_user_fields, list):
            required_user_fields = []
        if not announcement and reason:
            announcement = reason
        raw_np = data.get("next_prompt")
        next_prompt_val: Optional[str] = None
        if raw_np is not None and str(raw_np).strip():
            next_prompt_val = str(raw_np).strip()
        return {
            "task_done": task_done,
            "next_speaker": next_speaker,
            "reason": reason,
            "announcement": announcement or "请下一位发言。",
            "next_prompt": next_prompt_val,
            "suggested_order": suggested_order,
            "suggested_add_agent_ids": suggested_add_agent_ids,
            "suggested_add_expert_ids": suggested_add_agent_ids,
            "phase": phase,
            "owner_agent_id": owner_agent_id,
            "interrupt_reason": interrupt_reason,
            "decision_source": decision_source,
            "handoff_reason": handoff_reason,
            "required_user_fields": required_user_fields,
        }
    except Exception:
        return None


def _user_requests_host_takeover(
    message: str,
    *,
    explicit_flag: Optional[bool],
    host_display_name: str = "四九",
) -> bool:
    """Only allow host orchestration when user explicitly asks for host."""
    if explicit_flag is True:
        return True
    text = str(message or "").strip()
    if not text:
        return False
    host_name = (host_display_name or "四九").strip()
    lowered = text.lower()
    if "@主持人" in text or "@四九" in text or (host_name and f"@{host_name}" in text):
        return True
    host_aliases = ["主持人", "四九"]
    if host_name and host_name not in host_aliases:
        host_aliases.append(host_name)
    alias_pattern = "|".join([re.escape(x) for x in host_aliases if x])
    # Natural-language takeover must include explicit summon intent, not mere mention.
    summon_patterns = [
        rf"(请|让|由|麻烦|需要)?\s*({alias_pattern})\s*(来|接管|安排|协调|分配|调度|负责|处理|决策)",
        rf"(请|让|由|麻烦|需要)\s*({alias_pattern})\b",
    ]
    for pat in summon_patterns:
        if re.search(pat, text, flags=re.I):
            return True
    if host_name and host_name.lower() in lowered and re.search(r"(接管|安排|协调|分配|调度|负责|处理|决策)", text):
        return True
    return False


def _heuristic_recommend_dhas(
    discussion_goal: str, all_instances: List[Dict[str, Any]], max_n: Optional[int] = None
) -> List[str]:
    """0 成员时兜底推荐：用简单关键词匹配 name/role，返回 agent_id 列表（去重、保序）。

    max_n 为 None 时返回尽可能多的候选（按匹配度排序）。
    """
    goal = (discussion_goal or "").strip().lower()
    scored = []
    for d in all_instances or []:
        did = (d.get("agent_id") or "").strip()
        if not did:
            continue
        name = str(d.get("name") or "").lower()
        role = str(d.get("role") or "").lower()
        hay = f"{did} {name} {role}"
        score = 0
        # 朴素：目标词命中越多越靠前
        for token in (goal.replace("，", " ").replace("。", " ").replace(",", " ").split() if goal else []):
            if token and token in hay:
                score += 3
        # 常见意图兜底
        if any(k in goal for k in ("天气", "气温", "下雨", "预报")) and any(k in hay for k in ("天气", "气象")):
            score += 5
        if any(k in goal for k in ("写", "文案", "公众号", "文章", "标题")) and any(k in hay for k in ("写作", "文案", "编辑", "公众号", "内容")):
            score += 5
        if any(k in goal for k in ("图", "封面", "配图", "logo", "海报")) and any(k in hay for k in ("设计", "封面", "配图", "海报", "图像", "logo")):
            score += 5
        if any(k in goal for k in ("数据", "报表", "分析", "表格", "excel")) and any(k in hay for k in ("数据", "分析", "报表", "excel")):
            score += 5
        scored.append((score, did))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [did for s, did in scored if s > 0]
    if max_n is not None:
        picked = picked[: max(0, int(max_n))]
    if not picked:
        # 仍然没有命中：选前 max_n 个
        for d in all_instances or []:
            did = (d.get("agent_id") or "").strip()
            if did and did not in picked:
                picked.append(did)
            if max_n is not None and len(picked) >= max_n:
                break
    if max_n is not None:
        return picked[:max(0, int(max_n))]
    return picked


def _extract_candidate_agent_ids_from_text(
    text: str,
    all_instances: List[Dict[str, Any]],
    *,
    max_n: int = 2,
) -> List[str]:
    """从主持人自然语言正文中提取候选专家（支持 agent_id/name/role 子串映射）。"""
    t = (text or "").strip().lower()
    if not t:
        return []
    out: List[str] = []
    # 1) 先提取显式 agent_id
    for aid in re.findall(r"agent-[a-zA-Z0-9\-]+", t, flags=re.I):
        s = str(aid or "").strip()
        if s:
            out.append(s)
        if len(out) >= max_n:
            return list(dict.fromkeys(out))[:max_n]
    # 2) 再按名称/角色映射回 agent_id
    for d in all_instances or []:
        did = str(d.get("agent_id") or "").strip()
        if not did:
            continue
        name = str(d.get("name") or "").strip().lower()
        role = str(d.get("role") or "").strip().lower()
        if name and name in t:
            out.append(did)
        elif role and role in t:
            out.append(did)
        if len(out) >= max_n:
            break
    return list(dict.fromkeys(out))[:max_n]


def _extract_explicit_requested_agent_ids(user_text: str, all_instances: List[Dict[str, Any]]) -> List[str]:
    """从用户文本中提取明确点名的专家（按 agent_id/name 精确包含匹配）。"""
    text = (user_text or "").strip().lower()
    if not text:
        return []
    out: List[str] = []
    for d in all_instances or []:
        did = (d.get("agent_id") or "").strip()
        if not did:
            continue
        name = str(d.get("name") or "").strip()
        did_hit = did.lower() in text
        name_hit = bool(name) and (name.lower() in text)
        if did_hit or name_hit:
            out.append(did)
    return list(dict.fromkeys(out))


def _extract_forced_at_mention_agent_id(user_text: str, all_instances: List[Dict[str, Any]]) -> Optional[str]:
    """仅当用户消息开头使用 @专家 时，强制指定下一位专家。"""
    text = (user_text or "").strip()
    if not text.startswith("@"):
        return None
    m = re.match(r"^\s*@([^\s，。,；;：:！!？?\)\]】】]+)", text, flags=re.I)
    if not m:
        return None
    mention = (m.group(1) or "").strip().lower()
    if not mention:
        return None
    for d in all_instances or []:
        did = str(d.get("agent_id") or "").strip()
        name = str(d.get("name") or "").strip()
        role = str(d.get("role") or "").strip()
        if not did:
            continue
        candidates = {
            did.lower(),
            _to_agent_style_id(did).lower(),
            did.replace("agent-", "").lower(),
        }
        if name:
            candidates.add(name.lower())
        if role:
            candidates.add(role.lower())
        if mention in candidates:
            return did
    return None


def _skill_requires_confirmation_gate(skill_content: str) -> bool:
    """从 skill 文本中判断是否存在分阶段且需用户确认的流程门控。"""
    s = (skill_content or "").lower()
    if not s:
        return False
    has_stages = ("stage 1" in s and "stage 2" in s) or ("阶段" in s and ("步骤" in s or "流程" in s))
    requires_confirm = ("ask if" in s) or ("wait for user confirmation" in s) or ("用户确认" in s) or ("请确认" in s)
    return has_stages and requires_confirm


def _infer_required_user_fields_for_skill(skill_content: str, model_output: str) -> List[Dict[str, Any]]:
    """当 skill 流程需要用户确认且当前输出进入交互点时，产出统一 required_user_fields。"""
    if not _skill_requires_confirmation_gate(skill_content):
        return []
    text = (model_output or "").strip()
    if not text:
        return []
    has_question = ("?" in text) or ("？" in text) or ("请确认" in text) or ("是否" in text) or ("请补充" in text)
    if not has_question:
        return []
    return [
        {
            "key": "workflow_user_confirmation",
            "label": "请确认是否按当前流程继续，或补充缺失信息",
            "required": True,
        }
    ]


async def _host_decide_by_dha(
    llm,
    host_dha: Dict[str, Any],
    dha_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    last_speaker_agent_id: Optional[str],
    extra_system_prompt: str,
    available_to_add: Optional[List[Dict[str, Any]]] = None,
    *,
    group_session_id: str = "",
    messages: Optional[List[Dict[str, Any]]] = None,
    app_settings: Optional[Dict[str, Any]] = None,
    pending_owner_agent_id: str = "",
    pending_skill_id: str = "",
    user_message: str = "",
    orphan_session_agent_ids: Optional[List[str]] = None,
    orchestration_profile: str = "recruitment",
) -> Optional[Dict[str, Any]]:
    """
    由主持人 DHA 执行主持技能，返回 {task_done, next_speaker, reason, announcement, next_prompt?}。
    失败时返回 None，调用方应回退到 leader_decide。
    orchestration_profile==scene 时不注入可邀请名单与补人策略。
    """
    app_settings = app_settings or load_app_settings()
    hp_norm = normalize_host_profile(app_settings.get("host_profile") or {})
    host_display_name = str(hp_norm.get("display_name") or "四九").strip() or "四九"
    name = host_dha.get("name") or host_dha.get("agent_id", host_display_name)
    role = host_dha.get("role") or "群聊主持人"
    sl = _request_skills_loader()
    msgs = list(messages or [])
    skill_ids = [str(x).strip() for x in (host_dha.get("skill_ids") or []) if str(x).strip()]
    resolved_skill_id = ""
    if not skill_ids:
        skill_content = "你是群聊主持人，负责在当前群内专家之间做调度，输出主持说明与 next_speaker/next_prompt 决策，不代替专家完成专业正文。"
    else:
        # 多 Skill 时优先专精（如 group-host-webnovel），避免 [group-host, …] 首位锁死通用主持
        sid0 = _pick_resolved_host_skill_id(skill_ids)
        resolved_skill_id = sid0
        skill_content = sl.get_skill_full_content(sid0) if sid0 else ""
        if not (skill_content or "").strip():
            skill_content = "你是群聊主持人，负责在当前群内专家之间做调度，输出主持说明与 next_speaker/next_prompt 决策，不代替专家完成专业正文。"
    skill_content = f"你是 {name}，担任本群主持人。你的角色：{role}。\n\n{skill_content}"
    host_system = (host_dha.get("system_prompt") or "").strip()
    if host_system:
        skill_content = f"{host_system}\n\n{skill_content}"

    dha_lines = []
    for d in dha_list:
        r = d.get("role") or "参与者"
        n = d.get("name") or d.get("agent_id", "")
        did = d.get("agent_id", "")
        dha_lines.append(f"- {n} ({did}): {r}")
    dha_text = "\n".join(dha_lines)
    orphan_ids = [str(x).strip() for x in (orphan_session_agent_ids or []) if str(x).strip()]
    orphan_block = ""
    if orphan_ids:
        orphan_block = (
            "【重要】会话 meta 里记录了以下协作专家 ID，但在当前账号专家库中已不存在（可能已删除或从未同步），"
            "这些 ID **不能**作为 next_speaker："
            + ", ".join(orphan_ids)
            + "。请提示用户到「资源中心 → 场景」重新选择协作专家。"
            "若仍有其他参与者在上方列表中，应优先安排他们，**不要**仅因上述失效 ID 就建议邀请新人。\n\n"
        )

    # 可邀请的专家列表：主持人用它来输出 suggested_add_agent_ids
    add_lines = []
    for d in (available_to_add or []):
        did = (d.get("agent_id") or "").strip()
        if not did:
            continue
        n = (d.get("name") or did) if isinstance(d.get("name") or did, str) else did
        r = d.get("role") or "参与者"
        add_lines.append(f"- {n} ({did}): {r}")
    available_text = "\n".join(add_lines) if add_lines else "（暂无可邀请专家）"
    scene_mode = str(orchestration_profile or "").strip().lower() == "scene"
    mode_line = (
        "【模式】场景协作（名单固定，不建议补人）。\n\n"
        if scene_mode
        else "【模式】新建会话（可在必要时建议用户邀请专家）。\n\n"
    )
    extra_policy = "" if scene_mode else (f"【可邀请专家列表】\n{available_text}\n\n")

    user_content = (
        orphan_block
        + mode_line
        + f"【当前群聊参与者（next_speaker 必须使用以下 agent_id 之一）】\n{dha_text or '（暂无：请检查场景是否已选择协作专家，或专家是否已从库中删除）'}\n\n"
        f"【讨论目标】\n{discussion_goal}\n\n"
        "【主持人决策上下文（对话与发言摘录）】\n"
        f"{recent_messages}\n\n"
        + extra_policy
    )
    if (user_message or "").strip():
        user_content += f"【本轮用户输入】\n{user_message.strip()}\n\n"
    if pending_owner_agent_id:
        user_content += (
            f"【待续跑状态】上一轮等待用户补充时锁定的专家 pending_owner_agent_id={pending_owner_agent_id}"
            + (f"，pending_skill_id={pending_skill_id}" if pending_skill_id else "")
            + "。你可决定仍由该专家继续或改派他人。\n\n"
        )
    if last_speaker_agent_id:
        user_content += f"【刚发言的专家】{last_speaker_agent_id}\n\n"
    else:
        user_content += "【当前为首轮】尚无上一位专家发言。\n\n"

    try:
        tools: List[Any] = []
        if group_session_id:
            tools = await build_tools_for_group_chat(host_dha, group_session_id, resolved_skill_id=resolved_skill_id)
        agent = create_skill_execution_agent(
            llm, tools, skill_content, extra_system_prompt or ""
        )
        initial_state = {"messages": [HumanMessage(content=user_content)], "tools": tools}
        run_cfg = {"configurable": {"thread_id": f"host-decide:{uuid.uuid4().hex}"}}
        final_state = await agent.ainvoke(initial_state, config=run_cfg)
        out_msgs = final_state.get("messages", [])
        content_str = ""
        for m in reversed(out_msgs):
            if isinstance(m, AIMessage):
                content_str = str(m.content) if isinstance(m.content, str) else str(m.content or "")
                break
        _log_llm_roundtrip(
            "host_decide",
            system_content=(extra_system_prompt or "") + "\n\n" + skill_content,
            user_content=user_content,
            model_output=content_str,
            session_id=group_session_id,
            extra={
                "agent_id": str(host_dha.get("agent_id") or VIRTUAL_SCENE_HOST_ID),
                "skill_id": resolved_skill_id,
                "llm_provider_id": str(host_dha.get("llm_provider_id") or app_settings.get("default_llm") or ""),
                "model": str(getattr(llm, "model", "") or ""),
            },
        )
        return _parse_host_response(content_str)
    except Exception as e:
        logger.warning("主持人 DHA 调用失败，将回退到默认调度: %s", e)
        return None


async def _host_only_respond_and_recommend(
    discussion_goal: str,
    recent_messages: str,
    all_instances: List[Dict[str, Any]],
    extra_system_prompt: str,
    group_session_id: str = "",
) -> tuple[str, Optional[List[str]]]:
    """
    当前群聊 0 个成员时：主持人回复用户并推荐 1~3 位专家加入（等待用户确认）。
    返回 (主持人回复正文, suggested_add_agent_ids 或 None)。
    """
    sl = _request_skills_loader()
    app_settings = load_app_settings()
    hp_norm = normalize_host_profile(app_settings.get("host_profile") or {})
    host_display_name = str(hp_norm.get("display_name") or "四九").strip() or "四九"
    host_system_prompt = str(hp_norm.get("system_prompt") or "").strip()
    host_skill_ids = [str(x).strip() for x in (hp_norm.get("skill_ids") or []) if str(x).strip()]
    skill_content = ""
    if host_skill_ids:
        sid0 = _pick_resolved_host_skill_id(host_skill_ids)
        skill_content = str(sl.get_skill_full_content(sid0) or "") if sid0 else ""
    if not skill_content:
        skill_content = "你是群聊主持人，负责协调讨论并适时推荐合适的专家加入。"
    host_intro = f"你是 {host_display_name}，担任本群主持人。"
    system_content = ("\n\n".join([x for x in (host_system_prompt, host_intro, str(skill_content or "")) if str(x).strip()])).strip()
    dha_lines = []
    for d in all_instances:
        did = d.get("agent_id", "")
        if did == CHAT_AGENT_ID:
            continue
        name = d.get("name") or did
        role = d.get("role") or "参与者"
        dha_lines.append(f"- {name} ({did}): {role}")
    dha_text = "\n".join(dha_lines) if dha_lines else "（暂无可选专家）"
    llm = _get_llm_for_dha(None, app_settings)
    user_content = (
        f"【讨论目标/用户消息】\n{discussion_goal}\n\n"
        f"【最近对话】\n{recent_messages}\n\n"
        f"【可选专家列表】\n{dha_text}\n\n"
        "【建议策略】\n"
        "- 优先推荐 1~3 位最相关专家（按优先级排序）；\n"
        "- 推荐后先等待用户确认邀请。\n\n"
    )
    agent = create_skill_execution_agent(llm, [], system_content, extra_system_prompt or "")
    initial_state = {"messages": [HumanMessage(content=user_content)], "tools": []}
    try:
        run_cfg = {"configurable": {"thread_id": f"host-zero:{uuid.uuid4().hex}"}}
        final_state = await agent.ainvoke(initial_state, config=run_cfg)
        out_msgs = final_state.get("messages", [])
        content_str = ""
        for m in reversed(out_msgs):
            if isinstance(m, AIMessage):
                content_str = str(m.content) if isinstance(m.content, str) else str(m.content or "")
                break
        _log_llm_roundtrip(
            "host_zero_recommend",
            system_content=(extra_system_prompt or "") + "\n\n" + system_content,
            user_content=user_content,
            model_output=content_str,
            session_id=group_session_id,
            extra={
                "agent_id": VIRTUAL_SCENE_HOST_ID,
                "skill_id": sid0 if host_skill_ids else "",
                "llm_provider_id": str(app_settings.get("default_llm") or ""),
                "model": str(getattr(llm, "model", "") or ""),
            },
        )
        if not content_str or not content_str.strip():
            # LLM 没输出：直接兜底推荐
            fallback_ids = _heuristic_recommend_dhas(discussion_goal, all_instances, max_n=3)
            return "我已收到您的需求，建议先邀请以下专家加入讨论。", fallback_ids or None
        text = content_str.strip()
        announcement = text
        suggested_add_agent_ids: Optional[List[str]] = None
        valid_ids = {d.get("agent_id") for d in all_instances if d.get("agent_id")}
        for sep in ("\n{", "{"):
            if sep in text:
                idx = text.find(sep) if sep == "{" else text.find(sep) + 1
                announcement = text[:idx].strip()
                # 去掉正文末尾可能残留的 ```json 或 ``` 代码块标记，避免在前端展示出多余的 “```json”
                for fence in ("```json", "```"):
                    if announcement.endswith(fence):
                        announcement = announcement[: -len(fence)].rstrip()
                json_str = text[idx:].strip()
                try:
                    data = json.loads(json_str)
                    ids_raw = data.get("suggested_add_expert_ids")
                    if not isinstance(ids_raw, list) or not ids_raw:
                        ids_raw = data.get("suggested_add_agent_ids")
                    if isinstance(ids_raw, list) and ids_raw:
                        # 过滤合法 id，去重并限制最多 3 位（优先最相关）
                        cleaned = [str(x).strip() for x in ids_raw if str(x).strip() in valid_ids]
                        if cleaned:
                            # 保持顺序去重
                            suggested_add_agent_ids = list(dict.fromkeys(cleaned))[:3]
                    if not suggested_add_agent_ids:
                        sid = (data.get("suggested_add_expert_id") or data.get("suggested_add_agent_id") or "").strip()
                        if sid and sid in valid_ids:
                            suggested_add_agent_ids = [sid]
                except Exception:
                    pass
                break
        # 若 JSON 未解析出推荐列表，从正文中提取 agent_id/name/role 映射作为备用
        if not suggested_add_agent_ids and valid_ids:
            found = _extract_candidate_agent_ids_from_text(text, all_instances, max_n=3)
            suggested_add_agent_ids = [x for x in found if x in valid_ids][:3]
        return announcement or text, suggested_add_agent_ids
    except Exception as e:
        logger.warning("主持人 0 成员推荐调用失败: %s", e)
        fallback_ids = _heuristic_recommend_dhas(discussion_goal, all_instances, max_n=3)
        return "我已收到您的需求，建议先邀请以下专家加入讨论。", fallback_ids or None


class _NeedUserInputHeuristicHook:
    name = "need_user_input_heuristic"
    priority = HookPriority.ORCHESTRATOR_GUARD

    async def run(self, payload: Dict[str, Any]) -> HookResult:
        req = payload.get("required_user_fields")
        if isinstance(req, list) and req:
            return HookResult(
                allow=False,
                interrupt_reason=InterruptReason.NEED_USER_INPUT,
                message="expert_requires_user_confirmation",
                metadata={"required_user_fields": req},
            )
        text = str(payload.get("full_content") or "")
        if not text.strip():
            return HookResult(allow=True)
        markers = (
            "请提供",
            "请补充",
            "还需要你",
            "需要你提供",
            "请确认",
            "请上传",
            "请给我",
            "请告诉我",
        )
        if any(m in text for m in markers):
            fields = payload.get("required_user_fields")
            if not isinstance(fields, list):
                fields = [{"key": "user_input", "label": "请补充必要信息", "required": True}]
            return HookResult(
                allow=False,
                interrupt_reason=InterruptReason.NEED_USER_INPUT,
                message="expert_need_user_input",
                metadata={"required_user_fields": fields},
            )
        return HookResult(allow=True)


class _ToolFailureHeuristicHook:
    name = "tool_failure_heuristic"
    priority = HookPriority.POLICY_GUARD

    async def run(self, payload: Dict[str, Any]) -> HookResult:
        raw = payload.get("tool_raw_results") or []
        if not isinstance(raw, list):
            raw = [str(raw)]
        text = "\n".join([str(x or "") for x in raw])
        if ("执行错误" in text) or ("error" in text.lower() and "tool" in text.lower()):
            return HookResult(
                allow=False,
                interrupt_reason=InterruptReason.TOOL_UNAVAILABLE,
                message="tool_execution_failed",
                metadata={},
            )
        return HookResult(allow=True)


# ========== Pydantic 模型 ==========


class GroupSessionUpdate(BaseModel):
    title: Optional[str] = None
    speak_mode: Optional[str] = None
    leader_agent_id: Optional[str] = None  # 场景主持人；虚拟 id 见 VIRTUAL_SCENE_HOST_ID；空字符串表示清空
    host_config: Optional[Dict[str, Any]] = None  # 虚拟主持人配置（skill_ids / system_prompt / llm 等）
    orchestration_profile: Optional[str] = None  # recruitment | scene
    add_agent_ids: Optional[List[str]] = None  # 向已有群聊追加 Agent
    remove_agent_ids: Optional[List[str]] = None  # 从群聊中移除 Agent
    add_expert_ids: Optional[List[str]] = None  # 兼容字段：add_expert_ids
    remove_expert_ids: Optional[List[str]] = None  # 兼容字段：remove_expert_ids


class GroupChatRequest(BaseModel):
    message: Optional[str] = None
    client_message_id: Optional[str] = None
    override_next_speaker: Optional[str] = None  # agent_id | "user" | null
    action: Optional[str] = None  # "continue" 继续下一轮
    custom_prompt: Optional[str] = None  # 手动模式下，可由前端传入自定义给下一发言人的提示词（覆盖默认生成）
    host_takeover_requested: Optional[bool] = None  # 仅在用户明确提到主持人时才允许主持人调度
    ignore_auto_expert_id: Optional[str] = None  # 点击“忽略自动切换”后，重做时排除该专家
    ignore_auto_skill_id: Optional[str] = None  # 点击“忽略自动切换”后，重做时排除该技能


class GroupPromptPreviewRequest(BaseModel):
    """前端在 manual 模式下预览（并可编辑）某个专家下一轮发言时将收到的提示词内容。"""

    agent_id: Optional[str] = None
    expert_id: Optional[str] = None


# ========== 统一会话用内部接口（供 api/sessions 复用） ==========


def create_session_internal(
    title: str = "新对话",
    agent_ids: Optional[List[str]] = None,
    expert_ids: Optional[List[str]] = None,
    speak_mode: str = "auto",
    leader_agent_id: Optional[str] = None,
    host_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """创建一条会话（默认虚拟场景主持人 + host_config；兼容旧版真实 DHA leader）。"""
    instances = load_dha_instances()
    id_to_preferred = _build_preferred_agent_id_map(instances)
    valid_ids = set(id_to_preferred.values())
    resolved_ids = _normalize_agent_ids(
        legacy_ids=agent_ids,
        agent_ids=agent_ids,
        expert_ids=expert_ids,
    )
    resolved_ids = _normalize_to_preferred_agent_ids(resolved_ids, id_to_preferred=id_to_preferred)
    for did in resolved_ids:
        if did not in valid_ids:
            raise HTTPException(status_code=400, detail=f"专家 {did} 不存在")
    leader_resolved = ""
    meta_host_config: Optional[Dict[str, Any]] = None
    raw_lid = str(leader_agent_id or "").strip()
    if host_config is not None:
        meta_host_config = normalize_host_config_dict(host_config)
        leader_resolved = VIRTUAL_SCENE_HOST_ID
    elif raw_lid:
        if raw_lid == VIRTUAL_SCENE_HOST_ID:
            leader_resolved = VIRTUAL_SCENE_HOST_ID
        else:
            ln = _normalize_to_preferred_agent_ids([raw_lid], id_to_preferred=id_to_preferred)
            leader_resolved = ln[0] if ln else ""
            if leader_resolved and leader_resolved not in valid_ids:
                raise HTTPException(status_code=400, detail=f"主持人 {leader_resolved} 不存在")
    else:
        leader_resolved = VIRTUAL_SCENE_HOST_ID
    gsid = f"group-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    meta = _load_group_meta()
    raw_title = (title or "").strip()
    placeholder_titles = {"新对话", "新群聊", ""}
    title_auto_generated = raw_title in placeholder_titles or raw_title.startswith("多Agent协作 ·")
    row: Dict[str, Any] = {
        "title": title or "新对话",
        "title_auto_generated": title_auto_generated,
        "agent_ids": resolved_ids,
        "leader_agent_id": leader_resolved,
        "speak_mode": (speak_mode or "auto").strip().lower(),
        "created_at": now,
        "updated_at": now,
    }
    if meta_host_config is not None:
        row["host_config"] = meta_host_config
    row["orchestration_profile"] = default_orchestration_profile_for_new_session(agent_ids=resolved_ids)
    meta[gsid] = row
    _save_group_meta(meta)
    _save_group_history(gsid, [])
    # 工作区目录延后创建：仅在用户首次使用工作区（列表/上传/导出等）时由 files API 或 export 创建
    return _build_session_payload(gsid, meta[gsid])


def export_session_to_markdown(session_id: str, filename: Optional[str] = None) -> tuple:
    """将会话历史导出为 Markdown 到该会话工作区。历史来自 group_history。返回 (rel_path, download_url)。"""
    from app.api.files import get_workspace_root

    messages = _load_group_history(session_id)
    if not messages:
        raise HTTPException(status_code=400, detail="会话无消息，无法导出")
    lines = ["# 对话导出\n", f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "---\n"]
    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        agent_id = msg.get("agent_id", "")
        if role == "user":
            lines.append("## 用户\n\n")
        elif role == "host":
            lines.append("## 主持人\n\n")
        else:
            label = agent_id or "助手"
            lines.append(f"## {label}\n\n")
        lines.append(content)
        lines.append("\n\n")
    md = "".join(lines)
    ws_root = get_workspace_root(session_id)
    fn = filename or f"session-{session_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    fn = fn.replace("..", "").replace("/", "")
    if not fn.endswith(".md"):
        fn += ".md"
    filepath = ws_root / fn
    filepath.write_text(md, encoding="utf-8")
    rel = str(filepath.relative_to(ws_root)).replace("\\", "/")
    return rel, f"/api/workspaces/{session_id}/files/download?path={rel}"


# ========== 群聊实现（供 api/sessions 复用；对外仅 /api/sessions/*）==========


async def preview_next_speaker_prompt(group_session_id: str, body: GroupPromptPreviewRequest):
    """
    预览指定 DHA 作为下一发言人时，将要收到的用户侧提示词（HumanMessage 内容）。

    仅用于前端 manual 模式下展示/编辑提示词，不实际触发 LLM 调用。
    """
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    m = meta[group_session_id]
    session_meta = m
    instances = load_dha_instances()
    id_to_preferred = _build_preferred_agent_id_map(instances)
    agent_ids = _normalize_to_preferred_agent_ids(list(m.get("agent_ids", [])), id_to_preferred=id_to_preferred)
    target_raw = (body.agent_id or body.expert_id or body.agent_id or "").strip()
    target_agent_id = _normalize_to_preferred_agent_ids([target_raw], id_to_preferred=id_to_preferred)
    target_agent_id = target_agent_id[0] if target_agent_id else ""
    if target_agent_id not in agent_ids:
        raise HTTPException(status_code=400, detail="专家不在该群聊中")

    messages = _load_group_history(group_session_id)

    # 讨论目标：优先使用最近一条用户消息，避免会话继续时沿用旧目标导致专家跑偏。
    discussion_goal = _normalize_discussion_goal(_last_user_message_text(messages))
    if not discussion_goal:
        discussion_goal = "待用户提出讨论主题"

    # 与实际调用时保持一致的上下文拼接逻辑
    context = _messages_to_context(messages)
    user_content = (
        f"【群聊讨论目标】\n{discussion_goal}\n\n"
        f"【最近讨论】\n{context}\n\n"
        "请紧扣讨论目标发言，不要偏离主题。"
    )

    return {"status": "ok", "data": {"prompt": user_content}}


async def get_group_session(group_session_id: str):
    """获取群聊详情与消息。"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    m = meta[group_session_id]
    if _maybe_upgrade_meta_to_scene_profile(m):
        _save_group_meta(meta)
    messages = _load_group_history(group_session_id)
    instances = load_dha_instances()
    id_to_preferred = _build_preferred_agent_id_map(instances)
    preferred_instances = _build_preferred_instances(instances, id_to_preferred=id_to_preferred)
    preferred_instances = await enrich_dha_instances(preferred_instances, workspace_id=group_session_id)
    agent_map_raw = {d.get("agent_id"): d for d in preferred_instances if d.get("agent_id")}
    # 统一输出 agent-*。
    normalized_messages = []
    for msg in messages:
        row = dict(msg or {})
        did = str(row.get("agent_id") or "").strip()
        if did:
            row["agent_id"] = id_to_preferred.get(did, _to_agent_style_id(did))
        normalized_messages.append(row)
    messages = normalized_messages
    agent_ids_in_group = set(_normalize_to_preferred_agent_ids(list(m.get("agent_ids", [])), id_to_preferred=id_to_preferred))
    m["agent_ids"] = list(agent_ids_in_group)
    agent_ids_in_messages = {msg.get("agent_id") for msg in messages if msg.get("agent_id")}
    relevant_ids = agent_ids_in_group | agent_ids_in_messages
    lad = str(m.get("leader_agent_id") or "").strip()
    if lad:
        lad_n = _normalize_to_preferred_agent_ids([lad], id_to_preferred=id_to_preferred)
        if lad_n:
            relevant_ids = relevant_ids | {lad_n[0]}
    agent_map = {
        k: {
            "name": v.get("name") or "",
            "role": v.get("role") or "",
            "avatar_url": str(v.get("avatar_url") or "").strip(),
            "is_leader": v.get("is_leader", False),
            "file_capabilities": v.get("file_capabilities") or {},
            "file_capability_labels": v.get("file_capability_labels") or [],
            "url_capability": bool(v.get("url_capability")),
        }
        for k, v in agent_map_raw.items()
        if k in relevant_ids
    }
    app_settings_gs = load_app_settings()
    hp_gs = normalize_host_profile(app_settings_gs.get("host_profile") or {})
    host_dn = str(hp_gs.get("display_name") or "四九").strip() or "四九"
    if VIRTUAL_SCENE_HOST_ID in relevant_ids or str(m.get("leader_agent_id") or "").strip() == VIRTUAL_SCENE_HOST_ID:
        agent_map[VIRTUAL_SCENE_HOST_ID] = {
            "name": host_dn,
            "role": "群聊场景主持人",
            "is_leader": True,
            "file_capabilities": {},
            "file_capability_labels": [],
            "url_capability": True,
        }
    return {
        "status": "ok",
        "data": {
            **_build_session_payload(group_session_id, m),
            "messages": messages,
            "agent_map": agent_map,
            "expert_map": agent_map,
            "runtime_state": _runtime_state_for_session(group_session_id, m),
        },
    }


async def group_session_events_stream(group_session_id: str):
    """会话事件推送流：用于页面恢复/多标签页时主动同步运行态与新消息。"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")

    async def event_gen():
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=32)
        async with _GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
            subscribers = _GROUP_SESSION_EVENT_SUBSCRIBERS.setdefault(group_session_id, [])
            subscribers.append(queue)
        try:
            snapshot = {
                "type": "snapshot",
                "session_id": group_session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "runtime_state": _runtime_state_for_session(group_session_id, meta.get(group_session_id) or {}),
            }
            yield f"event: session_update\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_SSE_AGENT_KEEPALIVE_INTERVAL_SEC)
                except asyncio.TimeoutError:
                    yield f"event: keepalive\ndata: {json.dumps({'type': 'keepalive'}, ensure_ascii=False)}\n\n"
                    continue
                yield f"event: session_update\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            async with _GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
                current = _GROUP_SESSION_EVENT_SUBSCRIBERS.get(group_session_id) or []
                _GROUP_SESSION_EVENT_SUBSCRIBERS[group_session_id] = [q for q in current if q is not queue]
                if not _GROUP_SESSION_EVENT_SUBSCRIBERS[group_session_id]:
                    _GROUP_SESSION_EVENT_SUBSCRIBERS.pop(group_session_id, None)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def update_group_session(group_session_id: str, body: GroupSessionUpdate):
    """更新群聊：重命名、发言模式、追加 DHA 等。若会话不在 meta 中但请求为邀请（add_agent_ids），则自动创建该会话条目以避免 404。"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        if body.add_agent_ids:
            now = datetime.now(timezone.utc).isoformat()
            meta[group_session_id] = {
                "title": "新群聊",
                "title_auto_generated": True,
                "agent_ids": [],
                "leader_agent_id": VIRTUAL_SCENE_HOST_ID,
                "speak_mode": "auto",
                "orchestration_profile": "recruitment",
                "created_at": now,
                "updated_at": now,
            }
            _save_group_meta(meta)
            path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
            if not path.exists():
                _save_group_history(group_session_id, [])
        else:
            raise HTTPException(status_code=404, detail="Group session not found")
    if body.title is not None and str(body.title).strip():
        next_title = body.title.strip()
        meta[group_session_id]["title"] = next_title
        # 兼容历史前端自动模板标题：仍视为“自动生成”，允许后续被主题标题覆盖
        if next_title.startswith("多Agent协作 ·") or next_title in {"新对话", "新群聊", ""}:
            meta[group_session_id]["title_auto_generated"] = True
        else:
            # 用户主动修改标题后，停止自动主题覆盖
            meta[group_session_id]["title_auto_generated"] = False
    if body.speak_mode is not None and body.speak_mode.strip().lower() in ("auto", "manual"):
        meta[group_session_id]["speak_mode"] = body.speak_mode.strip().lower()
    if body.host_config is not None:
        meta[group_session_id]["host_config"] = normalize_host_config_dict(body.host_config)
        meta[group_session_id]["leader_agent_id"] = VIRTUAL_SCENE_HOST_ID
        # 写入场景型 host_config 即视为「场景协作」，避免仍停留在 recruitment 导致误招募
        meta[group_session_id]["orchestration_profile"] = "scene"
    elif body.leader_agent_id is not None:
        instances = load_dha_instances()
        id_to_preferred = _build_preferred_agent_id_map(instances)
        raw_l = str(body.leader_agent_id).strip()
        if not raw_l:
            meta[group_session_id]["leader_agent_id"] = ""
            meta[group_session_id].pop("host_config", None)
        else:
            lid = _normalize_to_preferred_agent_ids([raw_l], id_to_preferred=id_to_preferred)
            lid = lid[0] if lid else ""
            valid_ids = {d.get("agent_id") for d in instances if d.get("agent_id")}
            if lid and lid not in valid_ids and lid != VIRTUAL_SCENE_HOST_ID:
                raise HTTPException(status_code=400, detail=f"主持人 {lid} 不存在")
            meta[group_session_id]["leader_agent_id"] = lid
            if lid != VIRTUAL_SCENE_HOST_ID:
                meta[group_session_id].pop("host_config", None)
    if body.orchestration_profile is not None:
        op = str(body.orchestration_profile).strip().lower()
        if op not in ("recruitment", "scene"):
            raise HTTPException(status_code=400, detail="orchestration_profile must be recruitment or scene")
        meta[group_session_id]["orchestration_profile"] = op
    add_ids = (
        body.add_expert_ids
        if body.add_expert_ids is not None
        else body.add_agent_ids
    )
    remove_ids = (
        body.remove_expert_ids
        if body.remove_expert_ids is not None
        else body.remove_agent_ids
    )
    if add_ids or remove_ids:
        instances = load_dha_instances()
        id_to_preferred = _build_preferred_agent_id_map(instances)
        preferred_instances = _build_preferred_instances(instances, id_to_preferred=id_to_preferred)
        id_to_name = {
            d.get("agent_id"): (d.get("name") or d.get("agent_id"))
            for d in preferred_instances
            if d.get("agent_id")
        }
        valid_ids = {d.get("agent_id") for d in preferred_instances if d.get("agent_id")}
        current = set(
            _normalize_to_preferred_agent_ids(
                list(meta[group_session_id].get("agent_ids", [])),
                id_to_preferred=id_to_preferred,
            )
        )
        add_ids_norm = _normalize_to_preferred_agent_ids(list(add_ids or []), id_to_preferred=id_to_preferred)
        remove_ids_norm = _normalize_to_preferred_agent_ids(list(remove_ids or []), id_to_preferred=id_to_preferred)
        before_ids = set(current)
        newly_added_ids: List[str] = []
        if add_ids_norm:
            for did in add_ids_norm:
                if did not in valid_ids:
                    raise HTTPException(status_code=400, detail=f"专家 {did} 不存在")
                if did not in current:
                    newly_added_ids.append(did)
                current.add(did)
            current.discard(CHAT_AGENT_ID)
        if remove_ids_norm:
            for did in remove_ids_norm:
                current.discard(did)
        meta[group_session_id]["agent_ids"] = list(current)
        # 成员变更：邀请 / 移出各写入一条系统提示（合并一次读写历史）
        unique_added = (
            list(
                dict.fromkeys(
                    [x for x in newly_added_ids if x in current and x not in before_ids],
                )
            )
            if newly_added_ids
            else []
        )
        unique_removed = (
            list(dict.fromkeys([x for x in remove_ids_norm if x in before_ids]))
            if remove_ids_norm
            else []
        )
        if unique_added or unique_removed:
            messages = _load_group_history(group_session_id)
            for did in unique_added:
                display_name = id_to_name.get(did, did)
                messages.append(
                    {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host",
                        "content": f"已邀请“{display_name}”加入会话",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "event_type": "member_joined",
                        "joined_agent_ids": [did],
                    }
                )
            for did in unique_removed:
                display_name = id_to_name.get(did, did)
                messages.append(
                    {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host",
                        "content": f"已将“{display_name}”移出会话",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "event_type": "member_left",
                        "left_agent_ids": [did],
                    }
                )
            _save_group_history(group_session_id, messages)
    if _maybe_upgrade_meta_to_scene_profile(meta[group_session_id]):
        pass
    meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_group_meta(meta)
    return {"status": "ok", "data": _build_session_payload(group_session_id, meta[group_session_id])}


async def delete_group_session(group_session_id: str):
    """删除群聊会话：同时删除 meta、群聊历史文件与该会话的工作区目录。"""
    current_user = get_current_user()
    await _cancel_group_session_run(group_session_id, reason="session_deleted")
    try:
        from app.agent.sandbox_workspace_access import get_shared_sandbox_service

        await get_shared_sandbox_service().dispose_session(group_session_id, turn_id="session_deleted")
    except Exception:
        logger.warning("删除群聊 %s 时取消沙箱会话失败。", group_session_id, exc_info=True)
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    del meta[group_session_id]
    _save_group_meta(meta)
    # 删除群聊历史
    path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    if path.exists():
        path.unlink()
    # 顺手清理孤儿历史（避免旧残留持续堆积）
    _cleanup_orphan_group_histories(meta)
    # 删除该会话对应的工作区目录（若存在）
    try:
        ws_root = get_workspace_root_path(group_session_id, user=current_user)
        if ws_root.exists() and ws_root.is_dir():
            shutil.rmtree(ws_root)
    except Exception:
        logger.warning("删除群聊 %s 的 workspace 目录失败，可手动清理。", group_session_id, exc_info=True)
    return {"status": "ok", "data": {"id": group_session_id, "deleted": True}}


async def stop_group_session_run(group_session_id: str):
    """停止某个群聊会话当前正在运行的流式任务。"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    cancelled = await _cancel_group_session_run(group_session_id, reason="user_stop")
    try:
        from app.agent.sandbox_workspace_access import get_shared_sandbox_service

        await get_shared_sandbox_service().dispose_session(group_session_id, turn_id="user_stop")
    except Exception:
        logger.warning("停止群聊 %s 时取消沙箱会话失败。", group_session_id, exc_info=True)
    return {"status": "ok", "data": {"id": group_session_id, "cancelled": cancelled}}


async def delete_group_message(group_session_id: str, message_id: str):
    """从会话列表和会话历史中彻底删除一条消息（含专家发言），避免污染下一轮 DHA 的上下文。"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    messages = _load_group_history(group_session_id)
    before = len(messages)
    messages = [m for m in messages if m.get("message_id") != message_id]
    if len(messages) == before:
        raise HTTPException(status_code=404, detail="Message not found")
    _save_group_history(group_session_id, messages)
    return {"status": "ok", "data": {"message_id": message_id, "deleted": True}}


async def group_chat_stream(group_session_id: str, request: GroupChatRequest):
    """群聊流式对话：用户消息或继续下一轮，支持 override_next_speaker"""
    logger.debug(
        "group_chat_stream_enter session=%s override=%r action=%r has_message=%s",
        group_session_id,
        request.override_next_speaker,
        request.action,
        bool((request.message or "").strip()),
    )
    await _ensure_initialized()

    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    m = meta[group_session_id]
    session_meta = m
    instances = load_dha_instances()
    id_to_preferred = _build_preferred_agent_id_map(instances)
    preferred_instances = _build_preferred_instances(instances, id_to_preferred=id_to_preferred)
    agent_ids = _normalize_to_preferred_agent_ids(list(m.get("agent_ids", [])), id_to_preferred=id_to_preferred)
    m["agent_ids"] = list(agent_ids)
    leader_agent_id = _normalize_to_preferred_agent_ids([m.get("leader_agent_id", "")], id_to_preferred=id_to_preferred)
    leader_agent_id = leader_agent_id[0] if leader_agent_id else ""
    dha_map = {d.get("agent_id"): d for d in preferred_instances}
    agent_ids = _normalize_to_preferred_agent_ids(list(agent_ids or []), id_to_preferred=id_to_preferred)
    dha_list = [d for d in preferred_instances if d.get("agent_id") in agent_ids]
    # 会话 meta 里有 id，但专家库中已不存在（删档/换库）→ 主持人侧参与者列表会空，易误判「要补人」
    orphan_session_agent_ids = [str(aid) for aid in agent_ids if str(aid).strip() and str(aid).strip() not in dha_map]
    # 当前不在群内的专家，主持人可在「完成不了工作」时建议邀请（不含场景主持人四九）
    available_to_add = [
        d
        for d in preferred_instances
        if d.get("agent_id")
        and d.get("agent_id") not in agent_ids
        and d.get("agent_id") != CHAT_AGENT_ID
        and (not leader_agent_id or d.get("agent_id") != leader_agent_id)
    ]

    messages = _load_group_history(group_session_id)
    app_settings = load_app_settings()
    hp_norm = normalize_host_profile(app_settings.get("host_profile") or {})
    hc_meta = m.get("host_config") if isinstance(m.get("host_config"), dict) else {}
    hc_dn = str(hc_meta.get("display_name") or "").strip()
    host_display_name = hc_dn or str(hp_norm.get("display_name") or "四九").strip() or "四九"
    pending_owner_agent_id = (m.get("pending_owner_agent_id") or "").strip().lower()
    pending_skill_id = (m.get("pending_skill_id") or "").strip()
    user_message = (request.message or "").strip()
    custom_prompt = (request.custom_prompt or "").strip()
    had_file_ref_tag = ("【文件引用：" in user_message) or ("【文件引用：" in custom_prompt)
    file_refs_resolved_in_request = False
    # 默认在服务端把【文件引用】展开为正文片段拼入用户消息，避免专家仅看到标签却未主动调用读文件工具。
    # 若上下文过大或需强制走工具链，可设置环境变量 FILE_REF_SERVER_RESOLVE_ENABLED=false 关闭。
    if is_feature_enabled("FILE_REF_SERVER_RESOLVE_ENABLED", default=True):
        user_message = resolve_file_refs_in_text(user_message, group_session_id)
        custom_prompt = resolve_file_refs_in_text(custom_prompt, group_session_id)
        file_refs_resolved_in_request = ("【文件内容已解析】" in user_message) or ("【文件内容已解析】" in custom_prompt)

    explicit_requested_agent_ids = _extract_explicit_requested_agent_ids(user_message, preferred_instances) if user_message else []
    explicit_requested_agent_ids = _normalize_to_preferred_agent_ids(explicit_requested_agent_ids, id_to_preferred=id_to_preferred)
    forced_at_mention_agent_id = _extract_forced_at_mention_agent_id(user_message, preferred_instances) if user_message else None
    forced_at_mention_agent_id = (
        id_to_preferred.get(forced_at_mention_agent_id, _to_agent_style_id(forced_at_mention_agent_id))
        if forced_at_mention_agent_id
        else None
    )
    ignored_auto_expert_id = (request.ignore_auto_expert_id or "").strip().lower()
    ignored_auto_expert_id = id_to_preferred.get(ignored_auto_expert_id, _to_agent_style_id(ignored_auto_expert_id)) if ignored_auto_expert_id else ""
    ignored_auto_skill_id = (request.ignore_auto_skill_id or "").strip()
    ignored_expert_ids_set: set[str] = {ignored_auto_expert_id} if ignored_auto_expert_id else set()
    host_takeover_requested = _user_requests_host_takeover(
        user_message,
        explicit_flag=request.host_takeover_requested,
        host_display_name=host_display_name,
    )

    # 用户消息
    if user_message:
        client_message_id = (request.client_message_id or "").strip()
        duplicate_user_message = bool(
            client_message_id
            and any(
                msg.get("role") == "user" and str(msg.get("client_message_id") or "").strip() == client_message_id
                for msg in messages
            )
        )
        first_user_message = not any(m.get("role") == "user" for m in messages)
        if not duplicate_user_message:
            user_msg = {
                "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                "role": "user",
                "content": user_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if client_message_id:
                user_msg["client_message_id"] = client_message_id
            messages.append(user_msg)
            _save_group_history(group_session_id, messages)
            meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

        current_title = (meta[group_session_id].get("title") or "").strip()
        placeholder_titles = ("新对话", "新群聊", "")
        is_template_title = current_title.startswith("多Agent协作 ·")
        title_auto_generated = meta[group_session_id].get("title_auto_generated")
        if title_auto_generated is None:
            # 兼容历史：若标题较短或仍是占位符，则视为“自动生成的标题”，允许覆盖更新
            title_auto_generated = current_title in placeholder_titles or is_template_title or len(current_title) <= 12

        # 标题精修会额外占用一次 LLM。默认只在首条/占位标题时跑，避免每轮消息和专家主流程抢模型延迟。
        should_refresh_title = bool(
            not duplicate_user_message
            and (
                current_title in placeholder_titles
                or is_template_title
                or (first_user_message and title_auto_generated)
                or (title_auto_generated and _title_refresh_every_user_message())
            )
        )
        if should_refresh_title:
            if first_user_message and (current_title in placeholder_titles or is_template_title):
                # 热路径只做本地兜底标题；AI 精修在后台完成，不阻塞 @专家 路由。
                auto_title = _title_from_first_message(user_message, max_chars=10)
                if auto_title:
                    meta[group_session_id]["title"] = auto_title
                    meta[group_session_id]["title_auto_generated"] = True
        _save_group_meta(meta)
        if should_refresh_title:
            _schedule_group_title_refresh(
                group_session_id,
                list(messages),
                max_chars=18,
                max_user_messages=6,
            )

    # 上一发言人（用于主持人/领导人判断 task_done；排除主持人本人，只计参与讨论的 DHA）
    last_speaker_agent_id = None
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("agent_id") and msg.get("agent_id") != leader_agent_id:
            last_speaker_agent_id = msg.get("agent_id")
            break

    # 讨论目标：优先使用最近一条用户消息，避免会话继续时沿用旧目标导致专家跑偏。
    discussion_goal = _normalize_discussion_goal(_last_user_message_text(messages))
    if not discussion_goal:
        discussion_goal = "待用户提出讨论主题"

    # 已废弃：不再提供全局 system_prompt；主持人提示词改为在主持人 DHA（is_leader）实例上维护
    extra_system_prompt = ""
    # speak_mode 仍可由会话 API 写入 meta（前端/习惯）；群聊调度已统一单一路径，不再按 manual/auto 分支。

    scene_runtime = SceneRuntime.from_group_session(
        session_id=group_session_id,
        meta_item=m,
        agent_ids=agent_ids,
        dha_map=dha_map,
        app_host_profile=hp_norm,
        available_to_add=available_to_add,
    )
    host_dha = scene_runtime.host_profile
    stream_user = (get_current_user().username or "").strip()

    import json as json_module

    async def event_gen():
        nonlocal last_speaker_agent_id, agent_ids, dha_list, available_to_add, host_takeover_requested
        current_task = asyncio.current_task()
        run_id = await _register_group_run(
            group_session_id,
            user_id=stream_user,
            task=current_task if current_task is not None else asyncio.create_task(asyncio.sleep(0)),
        )
        meta_item: Dict[str, Any] = meta[group_session_id]
        orch_profile = scene_runtime.orchestration_profile
        available_for_scheduler = scene_runtime.available_to_add_for_scheduler
        custom_prompt_used = False  # custom_prompt 仅对本次请求的首个 DHA 生效
        dha_turns = 0  # 本次流中 DHA 总发言轮次
        orch_ctx = OrchestrationContext(
            session_id=group_session_id,
            phase=OrchestrationPhase.PLANNING,
            owner_agent_id=last_speaker_agent_id,
            decision_source=DecisionSource.LEGACY,
        )
        start_turn(orch_ctx, phase=OrchestrationPhase.PLANNING, owner_agent_id=last_speaker_agent_id, source=DecisionSource.LEGACY)
        soft_stop_state: Dict[str, Any] = {
            "prev_content": "",
            "prev_speaker": "",
            "low_increment_streak": 0,
            "repeat_conclusion_streak": 0,
            "tool_failure_streak": 0,
        }
        client_disconnected = False
        try:
            required_user_fields: List[Dict[str, Any]] = []
            latest_handoff_reason: Optional[str] = None
            resume_target_agent_id: Optional[str] = last_speaker_agent_id
            current_skill_id_for_pending = pending_skill_id
            post_turn_hooks = HookPipeline([_ToolFailureHeuristicHook(), _NeedUserInputHeuristicHook()])

            def _audit(event_type: str, payload: Dict[str, Any]) -> None:
                try:
                    append_audit_event(group_session_id, event_type, payload, turn_id=orch_ctx.turn_id)
                except Exception:
                    logger.debug("audit append skipped", exc_info=True)

            def _apply_decision_to_ctx(decision: Dict[str, Any]) -> None:
                nonlocal latest_handoff_reason, resume_target_agent_id
                phase_val = str(decision.get("phase") or OrchestrationPhase.PLANNING.value)
                interrupt_val = str(decision.get("interrupt_reason") or InterruptReason.NONE.value)
                source_val = str(decision.get("decision_source") or DecisionSource.LEGACY.value)
                phase = OrchestrationPhase(phase_val) if phase_val in {p.value for p in OrchestrationPhase} else OrchestrationPhase.PLANNING
                interrupt = InterruptReason(interrupt_val) if interrupt_val in {r.value for r in InterruptReason} else InterruptReason.NONE
                source = DecisionSource(source_val) if source_val in {s.value for s in DecisionSource} else DecisionSource.LEGACY
                parsed = OrchestrationDecision(
                    task_done=bool(decision.get("task_done", True)),
                    next_speaker=(decision.get("next_speaker") or "user"),
                    reason=(decision.get("reason") or ""),
                    announcement=(decision.get("announcement") or ""),
                    next_prompt=decision.get("next_prompt"),
                    suggested_add_agent_ids=(decision.get("suggested_add_agent_ids") or []),
                    phase=phase,
                    owner_agent_id=decision.get("owner_agent_id"),
                    interrupt_reason=interrupt,
                    decision_source=source,
                    handoff_reason=decision.get("handoff_reason"),
                    required_user_fields=decision.get("required_user_fields") or [],
                )
                apply_decision(orch_ctx, parsed)
                required_user_fields[:] = list(parsed.required_user_fields or [])
                latest_handoff_reason = parsed.handoff_reason
                resume_target_agent_id = parsed.owner_agent_id
                _audit("scheduler_decision", {"decision": decision, "ctx": orch_ctx.to_dict()})

            def _persist_pending_state(end_payload: Dict[str, Any]) -> None:
                nonlocal current_skill_id_for_pending
                waiting = bool(end_payload.get("waiting_for_user"))
                interrupt = str(end_payload.get("interrupt_reason") or "")
                resume = str(end_payload.get("resume_target_agent_id") or "").strip().lower()
                required = end_payload.get("required_user_fields") or []
                should_keep_pending = (
                    waiting
                    and resume in agent_ids
                    and (
                        interrupt in (InterruptReason.NEED_USER_INPUT.value, InterruptReason.NEED_MORE_CONTEXT.value)
                        or bool(required)
                    )
                )
                if should_keep_pending:
                    meta_item["pending_owner_agent_id"] = resume
                    meta_item["pending_skill_id"] = current_skill_id_for_pending or ""
                    meta_item["pending_phase"] = str(end_payload.get("phase") or "")
                    meta_item["pending_required_user_fields"] = required if isinstance(required, list) else []
                    meta_item["pending_handoff_reason"] = str(end_payload.get("handoff_reason") or "")
                else:
                    meta_item.pop("pending_owner_agent_id", None)
                    meta_item.pop("pending_skill_id", None)
                    meta_item.pop("pending_phase", None)
                    meta_item.pop("pending_required_user_fields", None)
                    meta_item.pop("pending_handoff_reason", None)
                meta_item["updated_at"] = datetime.now(timezone.utc).isoformat()
                _save_group_meta(meta)

            yield f"event: start\ndata: {json_module.dumps({'type': 'start'})}\n\n"

            def _host_bubble_skill_id() -> str:
                """供前端气泡展示「skill: xxx」；与会话 meta / 主持人 DHA 的 skill_ids 一致。"""
                return scene_runtime.host_bubble_skill_id()

            def _persist_host_memory(host_msg: Dict[str, Any]) -> None:
                try:
                    _persist_group_memory_turn(
                        session_id=group_session_id,
                        msg=host_msg,
                        discussion_goal=discussion_goal,
                        input_prompt_summary=(user_message or custom_prompt or discussion_goal),
                        app_settings=app_settings,
                    )
                except Exception:
                    logger.warning("group memory write failed for host turn", exc_info=True)

            next_speaker = None
            expert_route_debug_for_turn: Dict[str, Any] = {}
            scheduler_next_prompt: Optional[str] = None

            # 0 个 DHA：主持人为先，主持人回复用户并推荐若干 DHA 加入（不再使用 Chat）
            if len(agent_ids) == 0:
                recent = _scheduler_recent_context(group_session_id, messages)
                all_instances = [d for d in preferred_instances if d.get("agent_id") and d.get("agent_id") != CHAT_AGENT_ID]
                picked: List[str] = []
                valid_ids = {d.get("agent_id") for d in all_instances if d.get("agent_id")}
                # 0 专家场景始终由主持人先回复并给出推荐，避免任何非 LLM 的短路分支
                host_content, suggested_add_agent_ids = await _host_only_respond_and_recommend(
                    discussion_goal, recent, all_instances, extra_system_prompt, group_session_id
                )
                suggested_add_agent_ids = suggested_add_agent_ids or []
                picked = list(dict.fromkeys([x for x in suggested_add_agent_ids if x in valid_ids]))[:3]
                if not picked:
                    auto_picked = _heuristic_recommend_dhas(discussion_goal, all_instances, max_n=3)
                    picked = list(dict.fromkeys([x for x in auto_picked if x in valid_ids]))[:3]
                host_msg = {
                    "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                    "role": "host",
                    "content": host_content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "skill_id": _host_bubble_skill_id(),
                }
                if picked:
                    host_msg["suggested_add_agent_ids"] = picked
                    host_msg["suggested_add_expert_ids"] = picked
                messages.append(host_msg)
                _save_group_history(group_session_id, messages)
                _persist_host_memory(host_msg)
                meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                _save_group_meta(meta)
                yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                end_payload = build_end_payload(
                    waiting_for_user=True,
                    phase=OrchestrationPhase.AWAITING_USER,
                    interrupt_reason=InterruptReason.NONE,
                    resume_target_agent_id=resume_target_agent_id,
                    required_user_fields=required_user_fields,
                    turn_id=orch_ctx.turn_id,
                    token_version=orch_ctx.token_version,
                    handoff_reason=latest_handoff_reason,
                )
                if picked:
                    end_payload["suggested_add_agent_ids"] = picked
                    end_payload["suggested_add_expert_ids"] = picked
                _persist_pending_state(end_payload)
                yield f"event: end\ndata: {json_module.dumps(end_payload, ensure_ascii=False)}\n\n"
                return

            had_skill_lock = bool(str(meta_item.get("skill_session_owner_id") or "").strip())
            if user_requests_exit_skill_session(user_message) and had_skill_lock:
                clear_skill_session_lock(meta_item)
                _save_group_meta(meta)
                _audit("user_exit_skill_session", {"preview": (user_message or "")[:200]})

            entry_route = resolve_group_entry_route(
                meta_item=meta_item,
                agent_ids=agent_ids,
                host_takeover_requested=host_takeover_requested,
                override_next_speaker=request.override_next_speaker,
                ignore_auto_expert_id=ignored_auto_expert_id or "",
            )
            if not entry_route.skip_host_dispatch:
                clear_skill_session_lock(meta_item)
                _save_group_meta(meta)

            if forced_at_mention_agent_id and forced_at_mention_agent_id in agent_ids:
                logger.debug("group_chat_route_branch=forced_at_mention session=%s next=%s", group_session_id, forced_at_mention_agent_id)
                clear_skill_session_lock(meta_item)
                _save_group_meta(meta)
                next_speaker = forced_at_mention_agent_id
                orch_ctx.phase = OrchestrationPhase.EXECUTING
                orch_ctx.owner_agent_id = forced_at_mention_agent_id
                _audit(
                    "forced_at_mention_speaker",
                    {
                        "next_speaker": forced_at_mention_agent_id,
                        "ctx": orch_ctx.to_dict(),
                    },
                )
            elif explicit_requested_agent_ids and any(aid in agent_ids for aid in explicit_requested_agent_ids):
                logger.debug("group_chat_route_branch=explicit_requested session=%s ids=%s", group_session_id, ",".join(explicit_requested_agent_ids or []))
                # 用户显式点名场内专家时优先直达，避免被上一轮 skill 锁误续跑到其他专家。
                requested_in_room = [aid for aid in explicit_requested_agent_ids if aid in agent_ids]
                if requested_in_room:
                    clear_skill_session_lock(meta_item)
                    _save_group_meta(meta)
                    next_speaker = requested_in_room[0]
                    orch_ctx.phase = OrchestrationPhase.EXECUTING
                    orch_ctx.owner_agent_id = next_speaker
                    _audit(
                        "explicit_named_speaker",
                        {
                            "requested_ids": explicit_requested_agent_ids,
                            "next_speaker": next_speaker,
                            "ctx": orch_ctx.to_dict(),
                        },
                    )
            elif explicit_requested_agent_ids:
                # 用户点名了不在当前场景成员中的专家（常见于切场景后沿用旧 @专家）。
                # 记录后继续走主持人调度，不在该分支短路。
                logger.debug(
                    "group_chat_explicit_requested_not_in_room session=%s requested=%s room=%s",
                    group_session_id,
                    ",".join(explicit_requested_agent_ids or []),
                    ",".join(agent_ids or []),
                )
            elif entry_route.skip_host_dispatch and entry_route.direct_expert_id:
                logger.debug(
                    "group_chat_route_branch=skip_host_dispatch session=%s next=%s",
                    group_session_id,
                    entry_route.direct_expert_id,
                )
                next_speaker = entry_route.direct_expert_id
                orch_ctx.phase = OrchestrationPhase.EXECUTING
                orch_ctx.owner_agent_id = entry_route.direct_expert_id
                _audit(
                    "fsm_skip_host_dispatch",
                    {"next_speaker": next_speaker, "ctx": orch_ctx.to_dict()},
                )
            elif request.override_next_speaker is not None and str(request.override_next_speaker).strip():
                logger.debug(
                    "group_chat_route_branch=override session=%s override=%s",
                    group_session_id,
                    str(request.override_next_speaker).strip().lower(),
                )
                next_speaker = str(request.override_next_speaker).strip().lower()
                if next_speaker == "user":
                    orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                    payload = build_end_payload(
                        waiting_for_user=True,
                        phase=orch_ctx.phase,
                        interrupt_reason=InterruptReason.NONE,
                        resume_target_agent_id=resume_target_agent_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                    )
                    _persist_pending_state(payload)
                    yield f"event: end\ndata: {json_module.dumps(payload)}\n\n"
                    return
                if next_speaker == "end":
                    orch_ctx.phase = OrchestrationPhase.COMPLETED
                    payload = build_end_payload(
                        waiting_for_user=False,
                        discussion_ended=True,
                        phase=orch_ctx.phase,
                        interrupt_reason=InterruptReason.NONE,
                        resume_target_agent_id=resume_target_agent_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                    )
                    _persist_pending_state(payload)
                    yield f"event: end\ndata: {json_module.dumps(payload)}\n\n"
                    return
                if next_speaker and next_speaker not in agent_ids:
                    next_speaker = None
                if next_speaker in agent_ids:
                    orch_ctx.phase = OrchestrationPhase.EXECUTING
                    orch_ctx.owner_agent_id = next_speaker
            elif request.override_next_speaker is not None:
                # 兼容前端偶发传入空串：应视作“未指定 override”，继续走主持人正常调度，
                # 而不是让 next_speaker 落成空值导致后续无可执行专家。
                logger.debug(
                    "group_chat_stream 忽略空 override_next_speaker: session=%s raw=%r",
                    group_session_id,
                    request.override_next_speaker,
                )
            else:
                logger.debug("group_chat_route_branch=host_scheduler session=%s", group_session_id)
                # 唯一调度路径（不再区分 speak_mode manual/auto；流程由 Skill 锁与主持人 JSON 表达）
                recent = _scheduler_recent_context(group_session_id, messages)
                decision = None
                logger.info(
                    "group_chat_scheduler_enter session=%s profile=%s agent_count=%s has_host=%s pending_owner=%s pending_skill=%s user_msg_len=%s",
                    group_session_id,
                    orch_profile,
                    len(agent_ids or []),
                    bool(host_dha),
                    pending_owner_agent_id,
                    pending_skill_id,
                    len((user_message or "").strip()),
                )
                if leader_agent_id and host_dha:
                    llm_host = _get_llm_for_dha(host_dha, app_settings)
                    decision = await _host_decide_by_dha(
                        llm_host,
                        host_dha,
                        dha_list,
                        discussion_goal,
                        recent,
                        last_speaker_agent_id,
                        extra_system_prompt,
                        available_for_scheduler,
                        group_session_id=group_session_id,
                        messages=messages,
                        app_settings=app_settings,
                        pending_owner_agent_id=pending_owner_agent_id,
                        pending_skill_id=pending_skill_id,
                        user_message=user_message,
                        orphan_session_agent_ids=orphan_session_agent_ids,
                        orchestration_profile=orch_profile,
                    )
                    logger.info(
                        "group_chat_scheduler_host_decide_done session=%s decision_none=%s next_speaker=%s reason=%s",
                        group_session_id,
                        decision is None,
                        (decision or {}).get("next_speaker") if isinstance(decision, dict) else "",
                        (decision or {}).get("reason") if isinstance(decision, dict) else "",
                    )
                if decision is None:
                    logger.info("group_chat_scheduler_fallback_to_leader_decide session=%s", group_session_id)
                    default_llm_provider_id = str(app_settings.get("default_llm") or "")
                    llm_default = _get_llm_for_dha(None, app_settings)
                    decision = await leader_decide(
                        llm_default,
                        dha_list,
                        discussion_goal,
                        recent,
                        last_speaker_agent_id,
                        available_for_scheduler,
                        orchestration_profile=orch_profile,
                        group_session_id=group_session_id,
                        llm_provider_id=default_llm_provider_id,
                    )
                    logger.info(
                        "group_chat_scheduler_leader_decide_done session=%s next_speaker=%s reason=%s",
                        group_session_id,
                        (decision or {}).get("next_speaker") if isinstance(decision, dict) else "",
                        (decision or {}).get("reason") if isinstance(decision, dict) else "",
                    )
                decision = finalize_host_scheduler_decision(
                    decision,
                    agent_ids=agent_ids,
                    dha_list=dha_list,
                    available_to_add=available_for_scheduler,
                    last_speaker_agent_id=last_speaker_agent_id,
                    user_message=user_message,
                    explicit_requested_agent_ids=explicit_requested_agent_ids,
                    orchestration_profile=orch_profile,
                )
                logger.info(
                    "group_chat_scheduler_decision_finalized session=%s next_speaker=%s interrupt_reason=%s suggested_add=%s required_fields=%s",
                    group_session_id,
                    (decision or {}).get("next_speaker") if isinstance(decision, dict) else "",
                    (decision or {}).get("interrupt_reason") if isinstance(decision, dict) else "",
                    len(list((decision or {}).get("suggested_add_agent_ids") or [])) if isinstance(decision, dict) else 0,
                    len(list((decision or {}).get("required_user_fields") or [])) if isinstance(decision, dict) else 0,
                )
                _apply_decision_to_ctx(decision)
                announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                suggested_add = list(decision.get("suggested_add_agent_ids") or [])
                # 由主持人/调度明确给出下一位发言人。
                # 不再根据 task_done 强制让上一位 DHA 连续发言，
                # 每一小轮都回到主持人决策，再由 decision["next_speaker"] 指定下一位。
                next_speaker = decision.get("next_speaker", "user")
                np_auto = decision.get("next_prompt") if isinstance(decision, dict) else None
                if isinstance(np_auto, str) and np_auto.strip():
                    scheduler_next_prompt = np_auto.strip()
                # 主持人建议新增成员时：仅给出推荐，等待用户确认邀请
                if suggested_add:
                    host_content = RECRUIT_FIXED_MESSAGE
                    next_speaker = "user"
                    orch_ctx.phase = OrchestrationPhase.RECRUITING
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host",
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "skill_id": _host_bubble_skill_id(),
                        "suggested_add_agent_ids": suggested_add,
                        "suggested_add_expert_ids": suggested_add,
                    }
                    if leader_agent_id:
                        host_msg["agent_id"] = leader_agent_id
                    messages.append(host_msg)
                    _save_group_history(group_session_id, messages)
                    _persist_host_memory(host_msg)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                # 主持人点名后，当前轮次继续执行被点名专家发言，避免用户看到“将安排发言”却无下文。
                if next_speaker in agent_ids:
                    next_dha = dha_map.get(next_speaker)
                    next_name = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                    # 优先展示主持人在 JSON 外撰写的主持说明（announcement）；勿仅用固定模板覆盖技能产出
                    _ann = (announcement or "").strip()
                    _short = f"下面由 {next_name} 发言。"
                    _generic_host = frozenset(
                        {"", "请下一位发言。", "请下一位发言", "请下一位发言。 "}
                    )
                    host_content = _short if not _ann or _ann in _generic_host else _ann
                    # 若主持人给了 suggested_order，但 announcement 未展开具体顺序，
                    # 则补一段可读列表，避免前端只看到“以下是我的安排：”这类半句。
                    raw_order = decision.get("suggested_order")
                    if isinstance(raw_order, list) and raw_order:
                        ordered_names: List[str] = []
                        for aid in raw_order:
                            sid = str(aid or "").strip()
                            if not sid:
                                continue
                            d = dha_map.get(sid)
                            ordered_names.append((d.get("name") or sid) if d else sid)
                        if ordered_names:
                            has_list_marker = ("1." in host_content) or ("- " in host_content)
                            if not has_list_marker:
                                lines = [f"{idx + 1}. {nm}" for idx, nm in enumerate(ordered_names[:5])]
                                host_content = (host_content.rstrip() + "\n\n" + "建议顺序：\n" + "\n".join(lines)).strip()
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host",
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "skill_id": _host_bubble_skill_id(),
                    }
                    if leader_agent_id:
                        host_msg["agent_id"] = leader_agent_id
                    messages.append(host_msg)
                    next_dha = dha_map.get(next_speaker)
                    host_msg["next_dha_name"] = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                    if decision.get("suggested_order"):
                        host_msg["suggested_order"] = decision["suggested_order"]
                    _save_group_history(group_session_id, messages)
                    _persist_host_memory(host_msg)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                    orch_ctx.phase = OrchestrationPhase.EXECUTING
                    orch_ctx.owner_agent_id = next_speaker
                elif next_speaker in ("user", "end"):
                    # 当主持人决策本轮交还用户或结束时，也应把 announcement 落成可见消息，
                    # 否则前端只看到用户连续发言，误以为“无响应”。
                    _ann = (announcement or "").strip()
                    _generic_host = frozenset(
                        {"", "请下一位发言。", "请下一位发言", "请下一位发言。 "}
                    )
                    if (not _ann or _ann in _generic_host) and next_speaker == "user":
                        # 兜底：调度返回 user 但未给可见说明时，仍输出一条主持人提示，
                        # 避免 UI 上呈现为“发送后无任何反馈”。
                        reason_text = str(decision.get("reason") or "").strip()
                        if reason_text:
                            _ann = f"已暂停自动推进：{reason_text}\n\n请补充更具体要求，或直接指定下一位专家继续。"
                        else:
                            _ann = "已暂停自动推进，请补充更具体要求，或直接指定下一位专家继续。"
                    if _ann and _ann not in _generic_host:
                        host_msg = {
                            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                            "role": "host",
                            "content": _ann,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "skill_id": _host_bubble_skill_id(),
                        }
                        if leader_agent_id:
                            host_msg["agent_id"] = leader_agent_id
                        messages.append(host_msg)
                        _save_group_history(group_session_id, messages)
                        _persist_host_memory(host_msg)
                        yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                    if next_speaker == "user":
                        orch_ctx.phase = OrchestrationPhase.AWAITING_USER

            if not next_speaker:
                # 兜底：当调度链路未产出 next_speaker 时，写入可见主持人消息，避免 UI 只看到用户自说自话。
                fallback_host = {
                    "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                    "role": "host",
                    "content": "主持人暂未选出下一位专家，已暂停自动推进。请补充更具体要求，或直接指定下一位专家继续。",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "skill_id": _host_bubble_skill_id(),
                    "meta": {"reason": "next_speaker_missing"},
                }
                if leader_agent_id:
                    fallback_host["agent_id"] = leader_agent_id
                messages.append(fallback_host)
                _save_group_history(group_session_id, messages)
                _persist_host_memory(fallback_host)
                _save_group_meta(meta)
                yield f"event: message\ndata: {json_module.dumps(fallback_host, ensure_ascii=False)}\n\n"

            while orch_ctx.phase == OrchestrationPhase.EXECUTING and next_speaker and next_speaker in agent_ids:
                # 在自动或手动模式下，单次流中专家发言超过一定轮次（默认 32）时强制停下来，让用户确认是否继续，
                # 避免在服务器上长时间无限循环。
                if dha_turns >= 32:
                    move_to_interrupt(orch_ctx, InterruptReason.TIMEOUT_OR_BUDGET_EXCEEDED)
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker=next_speaker,
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=InterruptReason.TIMEOUT_OR_BUDGET_EXCEEDED,
                        resume_target_agent_id=resume_target_agent_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                        extra={"turns_limit_reached": True},
                    )
                    _persist_pending_state(end_data)
                    yield f"event: end\ndata: {json_module.dumps(end_data)}\n\n"
                    return
                round_next_prompt = scheduler_next_prompt
                scheduler_next_prompt = None
                dha_turns += 1
                start_turn(
                    orch_ctx,
                    phase=OrchestrationPhase.EXECUTING,
                    owner_agent_id=next_speaker,
                    source=DecisionSource.EXPERT,
                )
                resume_target_agent_id = next_speaker
                _audit("turn_started", {"speaker": next_speaker, "turn_index": dha_turns, "ctx": orch_ctx.to_dict()})
                dha = dha_map.get(next_speaker)
                if not dha:
                    move_to_interrupt(orch_ctx, InterruptReason.NEED_MORE_CONTEXT)
                    next_speaker = "user"
                    break

                expert_runtime = await build_expert_turn_runtime(
                    dha=dha,
                    agent_id=next_speaker,
                    group_session_id=group_session_id,
                    discussion_goal=discussion_goal,
                    messages=messages,
                    meta_item=meta_item,
                    app_settings=app_settings,
                    round_user_text=user_message,
                    extra_system_prompt=extra_system_prompt,
                    skills_loader=_request_skills_loader(),
                    llm_resolver=lambda d: _get_llm_for_dha(d, app_settings),
                    ignored_auto_skill_id=ignored_auto_skill_id,
                )
                resolved_skill_id = expert_runtime.skill_id
                skill_content = expert_runtime.skill_content
                skill_route_debug = expert_runtime.skill_route_debug
                logger.info(
                    "group_chat_expert_runtime_resolved code=expert_runtime_resolved session=%s run_id=%s agent_id=%s skill_id=%s skill_loaded=%s tool_count=%s skill_strategy=%s blocking_error=%s",
                    group_session_id,
                    run_id,
                    next_speaker,
                    resolved_skill_id,
                    bool(skill_content),
                    len(list(getattr(expert_runtime, "tools", []) or [])),
                    str((skill_route_debug or {}).get("strategy") if isinstance(skill_route_debug, dict) else ""),
                    str((skill_route_debug or {}).get("blocking_error") if isinstance(skill_route_debug, dict) else ""),
                )
                if (
                    isinstance(skill_route_debug, dict)
                    and skill_route_debug.get("strict_llm_required")
                    and (not resolved_skill_id or not skill_content)
                ):
                    move_to_interrupt(orch_ctx, InterruptReason.NEED_USER_INPUT)
                    err_code = str(skill_route_debug.get("blocking_error") or "expert_skill_pick_llm_failed")
                    if err_code == "expert_skill_content_missing":
                        err_msg = (
                            "当前专家的可用技能未正确加载，暂时无法继续执行。"
                            "请检查该专家的 skill 配置后重试，或由主持人改派其他专家。"
                        )
                    else:
                        err_msg = (
                            "当前专家的技能选择依赖 LLM，但本轮选择失败，已停止自动执行。"
                            "请重试，或由主持人重新安排下一步。"
                        )
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host",
                        "content": err_msg,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "skill_id": _host_bubble_skill_id(),
                        "meta": {
                            "error_code": err_code,
                            "agent_id": next_speaker,
                            "skill_route_debug": skill_route_debug,
                        },
                    }
                    if leader_agent_id:
                        host_msg["agent_id"] = leader_agent_id
                    messages.append(host_msg)
                    _save_group_history(group_session_id, messages)
                    _persist_host_memory(host_msg)
                    _save_group_meta(meta)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker="user",
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=InterruptReason.NEED_USER_INPUT,
                        resume_target_agent_id=next_speaker,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=err_msg,
                        extra={"error_code": err_code},
                    )
                    _persist_pending_state(end_data)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return
                tools = expert_runtime.tools
                agent = expert_runtime.agent
                route_event = {
                    "type": "route",
                    "agent_id": next_speaker,
                    "skill_id": resolved_skill_id,
                    "expert_route_debug": expert_route_debug_for_turn if isinstance(expert_route_debug_for_turn, dict) else {},
                    "skill_route_debug": skill_route_debug if isinstance(skill_route_debug, dict) else {},
                }
                await _update_group_run(
                    group_session_id,
                    run_id,
                    agent_id=next_speaker,
                    skill_id=resolved_skill_id,
                    phase="agent_routed",
                )
                logger.info(
                    "group_chat_route_emit code=expert_route_emit session=%s run_id=%s agent_id=%s skill_id=%s tool_count=%s",
                    group_session_id,
                    run_id,
                    next_speaker,
                    resolved_skill_id,
                    len(list(tools or [])),
                )
                yield f"event: route\ndata: {json_module.dumps(route_event, ensure_ascii=False)}\n\n"
                context = _messages_to_expert_context(messages)
                if not custom_prompt_used and custom_prompt:
                    user_content = custom_prompt
                    custom_prompt_used = True
                elif round_next_prompt:
                    user_content = _build_checked_next_prompt(
                        group_session_id,
                        next_speaker,
                        discussion_goal,
                        context,
                        app_settings,
                        decision_next_prompt=round_next_prompt,
                    )
                else:
                    user_content = (
                        f"【群聊讨论目标】\n{discussion_goal}\n\n"
                        f"【最近讨论】\n{context}\n\n"
                        "请紧扣讨论目标发言，不要偏离主题。"
                    )
                # 避免重复拼接历史：如果默认输入中已包含“最近讨论/历史对话”，则不再追加。
                uc = (user_content or "").strip()
                if (
                    ("【历史对话（供参考）】" not in uc)
                    and ("【最近几轮讨论内容" not in uc)
                    and ("【最近讨论】" not in uc)
                    and ("【关键事实】" not in uc)
                    and ("【用户任务清单】" not in uc)
                ):
                    uc = uc + "\n\n【历史对话（供参考）】\n" + context
                user_content = uc
                initial_state = {"messages": [HumanMessage(content=user_content)], "tools": tools}
                run_cfg = {"configurable": {"thread_id": f"group:{group_session_id}:{next_speaker}:{uuid.uuid4().hex}"}}

                accumulated = []
                accumulated_raw_tool_results: List[str] = []
                accumulated_tool_calls_trace: List[Dict[str, Any]] = []
                tool_attempt_debug: List[Dict[str, Any]] = []
                # 这些 content 事件只携带状态 phase，会被前端消费为状态栏文案，不进入最终聊天气泡。
                _agent_waiting_status = ""
                _tool_running_status = ""
                _file_resolving_status = ""
                _file_resolved_status = ""
                should_emit_preparing_hint = had_file_ref_tag and file_refs_resolved_in_request
                emitted_tool_pending_hint = False
                # 仅在请求里包含并成功解析了【文件引用】时展示文件引用状态；
                # memory 检索、普通推理、工具执行等流程不显示该文案。
                if should_emit_preparing_hint:
                    yield f"event: content\ndata: {json_module.dumps({'text': _file_resolving_status, 'agent_id': next_speaker, 'meta': {'phase': 'file_resolving'}}, ensure_ascii=False)}\n\n"
                    yield f"event: content\ndata: {json_module.dumps({'text': _file_resolved_status, 'agent_id': next_speaker, 'meta': {'phase': 'file_resolved'}}, ensure_ascii=False)}\n\n"
                try:
                    logger.info(
                        "group_chat_agent_stream_start code=agent_stream_start session=%s run_id=%s agent_id=%s skill_id=%s user_content_len=%s tool_count=%s",
                        group_session_id,
                        run_id,
                        next_speaker,
                        resolved_skill_id,
                        len(user_content or ""),
                        len(list(tools or [])),
                    )
                    async for stream_item in _iter_with_keepalive(
                        agent.astream(initial_state, config=run_cfg, stream_mode=["updates", "messages", "values"])
                    ):
                        if not isinstance(stream_item, dict):
                            continue
                        ev_type = str(stream_item.get("type") or "").strip()
                        if ev_type == "keepalive":
                            keepalive_phase = "tool_running" if emitted_tool_pending_hint else "agent_waiting"
                            yield f"event: content\ndata: {json_module.dumps({'text': _agent_waiting_status, 'agent_id': next_speaker, 'meta': {'phase': keepalive_phase}}, ensure_ascii=False)}\n\n"
                            continue
                        if ev_type == "agent_step":
                            msg_obj = stream_item.get("message")
                            if isinstance(msg_obj, AIMessage):
                                has_tool_calls = hasattr(msg_obj, "tool_calls") and msg_obj.tool_calls
                                content_str = str(msg_obj.content) if isinstance(msg_obj.content, str) else str(msg_obj.content or "")
                                if content_str.strip() and content_str not in accumulated:
                                    accumulated.append(content_str)
                                    yield f"event: content\ndata: {json_module.dumps({'text': content_str, 'agent_id': next_speaker, 'meta': {}}, ensure_ascii=False)}\n\n"
                                if has_tool_calls:
                                    # Keep tool call payloads in internal traces only.
                                    # 脚本/API（如生图）可能数十秒无 token；在真正执行工具前再推一行提示。
                                    if not emitted_tool_pending_hint:
                                        emitted_tool_pending_hint = True
                                        logger.info(
                                            "group_chat_tool_running code=agent_tool_calls_detected session=%s run_id=%s agent_id=%s skill_id=%s tool_call_count=%s",
                                            group_session_id,
                                            run_id,
                                            next_speaker,
                                            resolved_skill_id,
                                            len(list(msg_obj.tool_calls or [])),
                                        )
                                        await _update_group_run(group_session_id, run_id, phase="tool_running")
                                        yield f"event: content\ndata: {json_module.dumps({'text': _tool_running_status, 'agent_id': next_speaker, 'meta': {'phase': 'tool_running'}}, ensure_ascii=False)}\n\n"
                            continue
                        if ev_type == "tool_step":
                            tad = stream_item.get("tool_attempt_debug")
                            if isinstance(tad, list):
                                for item in tad:
                                    if item not in tool_attempt_debug:
                                        tool_attempt_debug.append(item)
                            # Keep tool step messages internal; avoid leaking raw execution output in UI bubble.
                            tool_msgs = stream_item.get("tool_messages")
                            if isinstance(tool_msgs, list):
                                pass
                            tcalls = stream_item.get("tool_calls")
                            if isinstance(tcalls, list):
                                for call in tcalls:
                                    if isinstance(call, dict) and call not in accumulated_tool_calls_trace:
                                        accumulated_tool_calls_trace.append(call)
                                logger.info(
                                    "group_chat_tool_step code=agent_tool_step session=%s run_id=%s agent_id=%s skill_id=%s tool_call_count=%s raw_result_count=%s",
                                    group_session_id,
                                    run_id,
                                    next_speaker,
                                    resolved_skill_id,
                                    len(tcalls),
                                    len(accumulated_raw_tool_results),
                                )
                            tro = stream_item.get("tool_raw_outputs")
                            if isinstance(tro, list):
                                for raw_str in tro:
                                    s = str(raw_str or "")
                                    if s and s not in accumulated_raw_tool_results:
                                        accumulated_raw_tool_results.append(s)
                                logger.info(
                                    "group_chat_tool_outputs code=agent_tool_outputs session=%s run_id=%s agent_id=%s skill_id=%s raw_result_count=%s raw_result_lens=%s",
                                    group_session_id,
                                    run_id,
                                    next_speaker,
                                    resolved_skill_id,
                                    len(accumulated_raw_tool_results),
                                    [len(str(x or "")) for x in accumulated_raw_tool_results[-5:]],
                                )
                            continue
                        if ev_type == "final_step":
                            tad = stream_item.get("tool_attempt_debug")
                            if isinstance(tad, list):
                                for item in tad:
                                    if item not in tool_attempt_debug:
                                        tool_attempt_debug.append(item)
                            continue
                except Exception as stream_err:
                    logger.exception("群聊 agent astream 失败（无回退）: %s", stream_err)
                    tool_attempt_debug.append({"source": "stream_error", "matched": False, "error": str(stream_err)})

                # 多轮 agent_step（含工具前后多段 AIMessage）用空行拼接，避免「…sandbox…」后直接续写无换行
                full_content = "\n\n".join(str(x) for x in accumulated if str(x).strip()) if accumulated else ""
                if (not full_content.strip()) and accumulated_raw_tool_results:
                    full_content = "工具已执行完成，但模型没有返回可展示的文字总结。请查看本轮工具结果，或继续追问让我基于结果整理。"
                if not full_content.strip():
                    full_content = "模型没有返回可展示的文字内容，请稍后重试或换一个模型。"
                full_content = _append_workspace_image_preview_markdown(full_content, accumulated_raw_tool_results)
                content_tool_calls_trace = _extract_tool_calls_from_accumulated(accumulated)
                tool_calls_trace = accumulated_tool_calls_trace or content_tool_calls_trace
                skill_session_tool_names = [
                    str(call.get("tool") or call.get("name") or "")
                    for call in (accumulated_tool_calls_trace or [])
                    if isinstance(call, dict)
                ]
                skill_session_state = resolve_skill_session_state(
                    full_content,
                    accumulated_raw_tool_results,
                    tool_names=skill_session_tool_names or None,
                )
                skill_session_completed = skill_session_state.over is True
                full_content = skill_session_state.display_content
                sandbox_entry_trace = _extract_sandbox_entry_trace(accumulated_raw_tool_results)
                skill_id = resolved_skill_id if dha else "default"
                current_skill_id_for_pending = skill_id
                logger.info(
                    "group_chat_agent_stream_done code=agent_stream_done session=%s run_id=%s agent_id=%s skill_id=%s content_len=%s tool_call_count=%s raw_result_count=%s sandbox_trace=%s",
                    group_session_id,
                    run_id,
                    next_speaker,
                    skill_id,
                    len(full_content or ""),
                    len(tool_calls_trace or []),
                    len(accumulated_raw_tool_results or []),
                    sandbox_entry_trace,
                )
                assistant_msg = {
                    "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                    "role": "assistant",
                    "agent_id": next_speaker,
                    "content": full_content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "skill_id": skill_id,
                }
                if isinstance(skill_route_debug, dict):
                    assistant_msg["skill_route_debug"] = skill_route_debug
                if isinstance(expert_route_debug_for_turn, dict) and expert_route_debug_for_turn:
                    assistant_msg["expert_route_debug"] = expert_route_debug_for_turn
                inferred_required_fields = _infer_required_user_fields_for_skill(skill_content, full_content)
                if inferred_required_fields:
                    assistant_msg["required_user_fields"] = inferred_required_fields
                if accumulated_raw_tool_results:
                    assistant_msg["tool_raw_results"] = accumulated_raw_tool_results
                assistant_msg["tool_debug"] = {
                    "tool_calls": tool_calls_trace,
                    "tool_attempt_debug": tool_attempt_debug,
                    "raw_result_count": len(accumulated_raw_tool_results or []),
                    "has_tool_call": bool(tool_calls_trace),
                    "has_raw_result": bool(accumulated_raw_tool_results),
                    "skill_session_state": {
                        "over": skill_session_state.over,
                        "source": skill_session_state.source,
                    },
                    "note": "no_tool_call_detected" if not tool_calls_trace else "",
                }
                try:
                    append_llm_roundtrip(
                        session_id=group_session_id,
                        phase="expert_turn",
                        input_messages=[
                            {"role": "system", "content": skill_content},
                            {"role": "user", "content": user_content},
                        ],
                        output={
                            "content": full_content,
                            "tool_calls": tool_calls_trace,
                        },
                        agent_id=next_speaker,
                        skill_id=skill_id,
                        llm_provider_id=str((dha or {}).get("llm_provider_id") or app_settings.get("default_llm") or ""),
                        model=str(getattr(llm, "model", "") or ""),
                        extra={
                            "has_tool_call": bool(tool_calls_trace),
                            "raw_result_count": len(accumulated_raw_tool_results or []),
                            "tool_attempt_count": len(tool_attempt_debug or []),
                            "tool_raw_outputs": accumulated_raw_tool_results,
                        },
                    )
                except Exception as e:
                    logger.warning("写入会话 LLM roundtrip 失败(tag=expert_turn session=%s): %s", group_session_id, e)
                messages.append(assistant_msg)
                _save_group_history(group_session_id, messages)
                meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                _save_group_meta(meta)
                # 专家回合自动落盘：失败不影响主对话链路
                try:
                    _persist_group_memory_turn(
                        session_id=group_session_id,
                        msg=assistant_msg,
                        discussion_goal=discussion_goal,
                        input_prompt_summary=user_content,
                        app_settings=app_settings,
                    )
                except Exception:
                    logger.warning("group memory write failed", exc_info=True)
                yield f"event: message\ndata: {json_module.dumps(assistant_msg, ensure_ascii=False)}\n\n"
                # skill 输出命中“需要用户补充/确认”时，立即中断并保持当前专家 owner；
                # 不再回到主持人二次分发，避免出现“skill 未结束却断链”。
                if inferred_required_fields:
                    move_to_interrupt(orch_ctx, InterruptReason.NEED_USER_INPUT)
                    required_user_fields = list(inferred_required_fields)
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker="user",
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=InterruptReason.NEED_USER_INPUT,
                        resume_target_agent_id=next_speaker,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                    )
                    _persist_pending_state(end_data)
                    if skill_session_completed:
                        clear_skill_session_lock(meta_item)
                    else:
                        persist_skill_session_lock(meta_item, owner_agent_id=next_speaker, skill_id=skill_id)
                    _save_group_meta(meta)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return
                hook_output = await post_turn_hooks.run(
                    {
                        "session_id": group_session_id,
                        "agent_id": next_speaker,
                        "skill_id": skill_id,
                        "full_content": full_content,
                        "tool_raw_results": accumulated_raw_tool_results,
                        "required_user_fields": assistant_msg.get("required_user_fields") or [],
                    }
                )
                if not hook_output.allow:
                    move_to_interrupt(orch_ctx, hook_output.interrupt_reason)
                    required_user_fields = list(hook_output.merged_metadata.get("required_user_fields") or required_user_fields)
                    _audit(
                        "hook_interrupt",
                        {
                            "reason": hook_output.interrupt_reason.value,
                            "message": hook_output.message,
                            "trace": [x.__dict__ for x in hook_output.trace],
                            "ctx": orch_ctx.to_dict(),
                        },
                    )
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker="user",
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=hook_output.interrupt_reason,
                        resume_target_agent_id=resume_target_agent_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=hook_output.message or latest_handoff_reason,
                    )
                    _persist_pending_state(end_data)
                    if skill_session_completed:
                        clear_skill_session_lock(meta_item)
                    else:
                        persist_skill_session_lock(meta_item, owner_agent_id=resume_target_agent_id or next_speaker, skill_id=skill_id)
                    _save_group_meta(meta)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return
                soft_stop_reason = _evaluate_soft_stop(
                    state=soft_stop_state,
                    current_speaker=next_speaker,
                    full_content=full_content,
                    tool_raw_results=accumulated_raw_tool_results,
                )
                if soft_stop_reason:
                    logger.info(
                        "群聊软判停触发: session=%s speaker=%s turns=%s reason=%s metrics=%s",
                        group_session_id,
                        next_speaker,
                        dha_turns,
                        soft_stop_reason,
                        {
                            "low_increment_streak": soft_stop_state.get("low_increment_streak", 0),
                            "repeat_conclusion_streak": soft_stop_state.get("repeat_conclusion_streak", 0),
                            "tool_failure_streak": soft_stop_state.get("tool_failure_streak", 0),
                        },
                    )
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker="user",
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=InterruptReason.NEED_USER_INPUT,
                        resume_target_agent_id=resume_target_agent_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                        extra={"soft_stop": True, "soft_stop_reason": soft_stop_reason},
                    )
                    _persist_pending_state(end_data)
                    if skill_session_completed:
                        clear_skill_session_lock(meta_item)
                    else:
                        persist_skill_session_lock(meta_item, owner_agent_id=next_speaker, skill_id=skill_id)
                    _save_group_meta(meta)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return

                last_speaker_agent_id = next_speaker
                if skill_session_completed:
                    clear_skill_session_lock(meta_item)
                else:
                    persist_skill_session_lock(meta_item, owner_agent_id=next_speaker, skill_id=skill_id)
                _save_group_meta(meta)
                if _has_auto_continue_signal(full_content):
                    continue
                orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                end_data = build_end_payload(
                    waiting_for_user=True,
                    suggested_next_speaker="user",
                    phase=OrchestrationPhase.AWAITING_USER,
                    interrupt_reason=InterruptReason.NONE,
                    resume_target_agent_id=next_speaker,
                    required_user_fields=required_user_fields,
                    turn_id=orch_ctx.turn_id,
                    token_version=orch_ctx.token_version,
                    handoff_reason=latest_handoff_reason,
                )
                _persist_pending_state(end_data)
                yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                return

            if next_speaker == "end":
                orch_ctx.phase = OrchestrationPhase.COMPLETED
                clear_skill_session_lock(meta_item)
                payload = build_end_payload(
                    waiting_for_user=False,
                    discussion_ended=True,
                    phase=orch_ctx.phase,
                    interrupt_reason=InterruptReason.NONE,
                    resume_target_agent_id=resume_target_agent_id,
                    required_user_fields=required_user_fields,
                    turn_id=orch_ctx.turn_id,
                    token_version=orch_ctx.token_version,
                    handoff_reason=latest_handoff_reason,
                )
                _persist_pending_state(payload)
                _save_group_meta(meta)
                yield f"event: end\ndata: {json_module.dumps(payload)}\n\n"
            else:
                if orch_ctx.phase == OrchestrationPhase.EXECUTING:
                    orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                end_data = build_end_payload(
                    waiting_for_user=True,
                    suggested_next_speaker=next_speaker,
                    phase=orch_ctx.phase,
                    interrupt_reason=orch_ctx.interrupt_reason if orch_ctx.interrupt_reason != InterruptReason.NONE else InterruptReason.NONE,
                    resume_target_agent_id=resume_target_agent_id,
                    required_user_fields=required_user_fields,
                    turn_id=orch_ctx.turn_id,
                    token_version=orch_ctx.token_version,
                    handoff_reason=latest_handoff_reason,
                )
                _persist_pending_state(end_data)
                yield f"event: end\ndata: {json_module.dumps(end_data)}\n\n"

        except asyncio.CancelledError:
            client_disconnected = True
            logger.info("群聊流式输出已取消 session=%s run_id=%s", group_session_id, run_id)
            raise
        except Exception as e:
            logger.exception("群聊流式输出异常")
            yield f"event: error\ndata: {json_module.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            try:
                payload = build_end_payload(
                    waiting_for_user=True,
                    phase=OrchestrationPhase.AWAITING_USER,
                    interrupt_reason=InterruptReason.TOOL_UNAVAILABLE,
                    handoff_reason="stream_error",
                    extra={"error": str(e)},
                )
                yield f"event: end\ndata: {json_module.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception:
                logger.exception("群聊流式异常 end 事件生成失败")
        finally:
            if not client_disconnected:
                await _finish_group_run(group_session_id, run_id)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
