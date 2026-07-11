"""Strict group-chat streaming runtime.

The runtime follows docs/contracts/runtime-interface-contract.md directly:
requests are structured, host decisions use `next_action`, history messages use
the nested message contract, and SSE only emits route/progress/message/end/error.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, List

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.agent.group_chat_expert_resolution import _get_llm_for_agent, _last_user_message_text
from app.agent.group_chat_expert_turn import run_one_expert_turn
from app.agent.group_chat_host_messages import _build_host_pause_message, _build_host_recommendation_message
from app.agent.group_chat_host_runtime import _host_decide_by_agent, _host_only_respond_and_recommend, _request_skills_loader
from app.agent.group_chat_request_inputs import request_user_text, validate_attachments
from app.agent.group_chat_soft_stop import expert_turn_budget_exceeded
from app.agent.group_chat_streaming import end_event_payload, serialize_sse_event, stream_background_events
from app.agent.group_context import normalize_discussion_goal, scheduler_memory_prompt
from app.agent.group_chat_title_meta import _record_user_message_and_refresh_title
from app.agent.group_host_decision import _apply_decision_to_ctx, finalize_host_scheduler_decision
from app.agent.group_orchestration_fsm import resolve_group_entry_route
from app.agent.platform_prompts import render_platform_prompt
from app.agent.session_contracts import GroupChatRequest, SseEndEvent, SseErrorEvent
from app.api.agents import load_agent_instances
from app.api.group_chat_state import (
    build_session_payload,
    ensure_sessions_dir,
    finish_group_run,
    format_storage_timestamp,
    frontend_history_message,
    load_group_history,
    load_group_orchestration_state,
    load_session_definitions,
    register_group_run,
    save_group_history,
    save_session_definitions,
    write_group_orchestration_state,
)
from app.api.settings_app import load_app_settings
from app.core.init import ensure_mcp_and_skills_initialized
from app.core.security import get_current_user

logger = logging.getLogger(__name__)


def _dedupe_names(values: List[Any]) -> List[str]:
    """Return non-empty unique names while preserving order."""
    out: list[str] = []
    for raw in values or []:
        name = str(raw or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _host_snapshot_to_agent(session_item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the session `host` snapshot into the host runtime profile."""
    host = session_item.get("host") if isinstance(session_item.get("host"), dict) else {}
    skill_directory = str(host.get("skill_directory") or "").strip()
    return {
        "name": str(host.get("name") or "四九").strip() or "四九",
        "description": "群聊主持人",
        "llm_name": str(host.get("llm_name") or "").strip(),
        "system_prompt": str(host.get("system_prompt") or "").strip(),
        "skill_directory": skill_directory,
    }


async def group_chat_stream(group_session_id: str, request: GroupChatRequest):
    """Run one strict group-chat stream for a validated request."""
    await ensure_mcp_and_skills_initialized()
    session_definitions = load_session_definitions()
    if group_session_id not in session_definitions:
        raise HTTPException(status_code=404, detail="Group session not found")
    validate_attachments(group_session_id, request, sessions_root=ensure_sessions_dir())

    session_item = session_definitions[group_session_id]
    app_settings = load_app_settings()
    instances = [dict(item) for item in (load_agent_instances() or []) if isinstance(item, dict)]
    agent_map = {str(item.get("name") or "").strip(): item for item in instances if str(item.get("name") or "").strip()}
    session_agent_names = _dedupe_names(list(session_item.get("agent_names") or []))
    agent_names = [name for name in session_agent_names if name in agent_map]
    if request.target_agent_name and request.target_agent_name not in agent_names:
        raise HTTPException(status_code=400, detail="target_agent_name is not in current agent_names")

    messages = load_group_history(group_session_id)
    user_text = request_user_text(request)
    turn_started_checkpoint_id = _record_user_message_and_refresh_title(
        group_session_id=group_session_id,
        session_definitions=session_definitions,
        messages=messages,
        user_message=str(request.message or "").strip(),
        client_message_id=request.client_message_id,
        attachments=[item.model_dump(exclude_none=True) for item in (request.attachments or [])],
        target_agent_name=request.target_agent_name,
    )
    messages = load_group_history(group_session_id)
    discussion_goal = (
        normalize_discussion_goal(_last_user_message_text(messages))
        or normalize_discussion_goal(user_text)
        or render_platform_prompt("session.discussion_goal.default.v1", {})
    )
    stream_user = (get_current_user().user_id or "").strip()

    async def run_events() -> AsyncIterator[str]:
        current_task = asyncio.current_task()
        run_id = await register_group_run(
            group_session_id,
            user_id=stream_user,
            task=current_task if current_task is not None else asyncio.create_task(asyncio.sleep(0)),
            turn_started_checkpoint_id=turn_started_checkpoint_id,
        )
        try:
            async for event in _run_contract_events(
                group_session_id=group_session_id,
                request=request,
                run_id=run_id,
                session_definitions=session_definitions,
                session_item=session_item,
                app_settings=app_settings,
                agent_map=agent_map,
                agent_names=agent_names,
                messages=messages,
                discussion_goal=discussion_goal,
                user_text=user_text,
            ):
                yield event
        except Exception as exc:  # noqa: BLE001
            logger.exception("group chat stream failed session=%s run_id=%s", group_session_id, run_id)
            error = SseErrorEvent(type="error", run_id=run_id, code="runtime_error", message=str(exc) or exc.__class__.__name__)
            yield serialize_sse_event("error", error.model_dump(exclude_none=True))
            end = SseEndEvent(type="end", run_id=run_id, phase="failed", waiting_for_user=True)
            yield serialize_sse_event("end", end_event_payload(end))
        finally:
            await finish_group_run(group_session_id, run_id)

    return StreamingResponse(
        stream_background_events(run_events()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _run_contract_events(
    *,
    group_session_id: str,
    request: GroupChatRequest,
    run_id: str,
    session_definitions: Dict[str, Dict[str, Any]],
    session_item: Dict[str, Any],
    app_settings: Dict[str, Any],
    agent_map: Dict[str, Dict[str, Any]],
    agent_names: List[str],
    messages: List[Dict[str, Any]],
    discussion_goal: str,
    user_text: str,
) -> AsyncIterator[str]:
    """Produce the contract SSE sequence for host routing and expert execution."""
    agent_profiles = [agent_map[name] for name in agent_names if name in agent_map]
    available_to_add = [item for item in agent_map.values() if str(item.get("name") or "").strip() not in agent_names]
    host_agent = _host_snapshot_to_agent(session_item)
    host_name = str(host_agent.get("name") or "四九").strip() or "四九"
    if not agent_names:
        content, picked = await _host_only_respond_and_recommend(
            discussion_goal,
            scheduler_memory_prompt(group_session_id, messages),
            available_to_add,
            "",
            group_session_id,
        )
        finalized = finalize_host_scheduler_decision(
            {
                "current_phase": "招募",
                "next_speaker": "user",
                "next_action": content,
                "suggested_add_agent_names": [str(item).strip() for item in (picked or []) if str(item).strip()],
            },
            agent_names=agent_names,
            available_to_add=available_to_add,
            user_text=user_text,
        )
        suggested_add = list(finalized.get("suggested_add_agent_names") or [])
        host_msg = _build_host_recommendation_message(
            skill=str(host_agent.get("skill_directory") or ""),
            content=content,
            picked=suggested_add,
            host_agent_name=host_name,
        )
        host_msg = frontend_history_message(host_msg)
        messages.append(host_msg)
        save_group_history(group_session_id, messages, checkpoint_trigger="turn_completed")
        session_item["updated_at"] = format_storage_timestamp()
        save_session_definitions(session_definitions)
        yield serialize_sse_event("message", host_msg)
        phase = "recruiting" if suggested_add else "awaiting_user"
        end = SseEndEvent(
            type="end",
            run_id=run_id,
            phase=phase,
            waiting_for_user=True,
            suggested_add_agent_names=suggested_add,
        )
        yield serialize_sse_event("end", end_event_payload(end))
        return
    orchestration_state = load_group_orchestration_state(group_session_id)
    host_scheduler = dict(orchestration_state.get("host_scheduler") or {}) if isinstance(orchestration_state.get("host_scheduler"), dict) else {}

    next_action = user_text or render_platform_prompt("expert.turn.default_next_action.v1", {})
    entry_route, route_state_changed = resolve_group_entry_route(
        request=request,
        orchestration_state=orchestration_state,
        agent_names=agent_names,
        host_name=host_name,
        default_next_action=next_action,
    )
    next_speaker = ""
    if entry_route:
        next_speaker = str(entry_route["next_speaker"]).strip()
        next_action = str(entry_route["next_action"]).strip() or next_action
    if route_state_changed:
        write_group_orchestration_state(group_session_id, orchestration_state)
    suggested_add: list[str] = []
    if not next_speaker:
        decision = await _host_decide_by_agent(
            _get_llm_for_agent(host_agent, app_settings),
            host_agent,
            agent_profiles,
            discussion_goal,
            scheduler_memory_prompt(group_session_id, messages),
            None,
            "",
            available_to_add,
            group_session_id=group_session_id,
            messages=messages,
            app_settings=app_settings,
            user_message=user_text,
            session_item=session_item,
            host_scheduler_state=host_scheduler,
        )
        decision = finalize_host_scheduler_decision(
            decision,
            agent_names=agent_names,
            available_to_add=available_to_add,
            user_text=user_text,
        )
        applied_decision = _apply_decision_to_ctx(decision, default_next_action=next_action)
        next_speaker = str(applied_decision["next_speaker"])
        next_action = str(applied_decision["next_action"])
        suggested_add = list(applied_decision["suggested_add_agent_names"])
        host_scheduler = dict(applied_decision["host_scheduler"])
        orchestration_state["host_scheduler"] = host_scheduler
        write_group_orchestration_state(group_session_id, orchestration_state)
        save_session_definitions(session_definitions)

    if next_speaker in {"user", "end"}:
        host_msg = _build_host_pause_message(
            skill=str(host_agent.get("skill_directory") or ""),
            next_speaker=next_speaker,
            current_phase=str(host_scheduler.get("current_phase") or ""),
            next_action=next_action,
            host_agent_name=host_name,
        )
        if host_msg:
            host_msg = frontend_history_message(host_msg)
            messages.append(host_msg)
            save_group_history(group_session_id, messages, checkpoint_trigger="turn_completed")
            session_item["updated_at"] = format_storage_timestamp()
            save_session_definitions(session_definitions)
            yield serialize_sse_event("message", host_msg)
        phase = "completed" if next_speaker == "end" else ("recruiting" if suggested_add else "awaiting_user")
        end = SseEndEvent(
            type="end",
            run_id=run_id,
            phase=phase,
            waiting_for_user=next_speaker != "end",
            suggested_add_agent_names=suggested_add,
        )
        yield serialize_sse_event("end", end_event_payload(end))
        return

    if next_speaker not in agent_names:
        error = SseErrorEvent(
            type="error",
            run_id=run_id,
            code="invalid_next_speaker",
            message=f"Host selected an agent outside current agent_names: {next_speaker}",
        )
        yield serialize_sse_event("error", error.model_dump(exclude_none=True))
        end = SseEndEvent(type="end", run_id=run_id, phase="failed", waiting_for_user=True)
        yield serialize_sse_event("end", end_event_payload(end))
        return

    turns = 0
    while next_speaker in agent_names:
        turns += 1
        if expert_turn_budget_exceeded(turns):
            end = SseEndEvent(
                type="end",
                run_id=run_id,
                phase="timeout_or_budget_exceeded",
                waiting_for_user=True,
                suggested_next_speaker=next_speaker,
            )
            yield serialize_sse_event("end", end_event_payload(end))
            return
        async for event in run_one_expert_turn(
            group_session_id=group_session_id,
            run_id=run_id,
            session_definitions=session_definitions,
            session_item=session_item,
            app_settings=app_settings,
            agent_map=agent_map,
            agent_name=next_speaker,
            messages=messages,
            discussion_goal=discussion_goal,
            user_text=user_text,
            next_action=next_action,
            skills_loader=_request_skills_loader(),
            llm_resolver=lambda profile: _get_llm_for_agent(profile, app_settings),
        ):
            yield event
        end = SseEndEvent(
            type="end",
            run_id=run_id,
            phase="awaiting_user",
            waiting_for_user=True,
            suggested_next_speaker=next_speaker,
        )
        yield serialize_sse_event("end", end_event_payload(end))
        return
