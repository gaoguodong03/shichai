"""Strict group-chat streaming runtime.

The runtime follows docs/contracts/runtime-interface-contract.md directly:
requests are structured, host decisions use `next_action`, history messages use
the nested message contract, and SSE only emits route/progress/message/end/error.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.agent.messages import AIMessage, HumanMessage  # type: ignore
from app.agent.expert_runtime import build_expert_turn_runtime
from app.agent.group_chat_expert_resolution import _get_llm_for_agent, _last_user_message_text
from app.agent.group_chat_host_messages import _build_host_pause_message, _build_host_recommendation_message
from app.agent.group_chat_host_runtime import _host_decide_by_agent, _host_only_respond_and_recommend, _request_skills_loader
from app.agent.group_chat_prompt_builder import build_expert_turn_prompt
from app.agent.group_chat_skill_session import apply_skill_result_to_orchestration_state, skill_result_from_content
from app.agent.group_chat_streaming import iter_with_keepalive, stream_background_events
from app.agent.group_context import messages_to_expert_context, normalize_discussion_goal, scheduler_recent_context
from app.agent.group_chat_title_meta import _record_user_message_and_refresh_title
from app.agent.group_orchestration_fsm import resolve_group_entry_route
from app.agent.platform_prompts import render_platform_prompt
from app.agent.session_runtime_logs import append_tool_execution_logs
from app.agent.session_contracts import GroupChatRequest, SseEndEvent, SseErrorEvent, SseProgressEvent, SseRouteEvent, SseStartEvent
from app.agent.structured_output_contracts import ArtifactRef
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
    update_group_run,
    write_group_orchestration_state,
)
from app.api.settings_app import load_app_settings
from app.core.init import ensure_mcp_and_skills_initialized
from app.core.security import get_current_user

logger = logging.getLogger(__name__)

MAX_EXPERT_TURNS_PER_STREAM = 32


def _dedupe_names(values: List[Any]) -> List[str]:
    """Return non-empty unique names while preserving order."""
    out: list[str] = []
    for raw in values or []:
        name = str(raw or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _sse(event_type: str, payload: Dict[str, Any]) -> str:
    """Serialize one SSE event with UTF-8 JSON payload."""
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _end_event_payload(end: SseEndEvent) -> Dict[str, Any]:
    """Serialize end events without empty optional recruitment suggestions."""
    payload = end.model_dump(exclude_none=True)
    if not payload.get("suggested_add_agent_names"):
        payload.pop("suggested_add_agent_names", None)
    return payload


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


def _workspace_root(group_session_id: str) -> Path:
    """Return the workspace directory for a group session."""
    return ensure_sessions_dir() / group_session_id / "workspace"


def _validate_attachments(group_session_id: str, request: GroupChatRequest) -> None:
    """Reject attachment paths that are not existing files in the session workspace."""
    root = _workspace_root(group_session_id).resolve()
    for attachment in request.attachments or []:
        raw_path = str(attachment.path or "").strip()
        if raw_path.startswith("/") or ".." in Path(raw_path).parts:
            raise HTTPException(status_code=400, detail="Attachment path must stay inside the session workspace")
        path = (root / raw_path).resolve()
        if root not in path.parents and path != root:
            raise HTTPException(status_code=400, detail="Attachment path must stay inside the session workspace")
        if not path.is_file():
            raise HTTPException(status_code=400, detail=f"Attachment does not exist: {raw_path}")


def _attachment_prompt_lines(request: GroupChatRequest) -> str:
    """Render request attachments as a small prompt section without reading file contents."""
    lines: list[str] = []
    for item in request.attachments or []:
        name = item.name or Path(item.path).name
        lines.append(f"- {name}: {item.path}")
    return "\n".join(lines)


def _request_user_text(request: GroupChatRequest) -> str:
    """Build the expert-visible user input from structured request fields."""
    text = str(request.message or "").strip()
    attachment_lines = _attachment_prompt_lines(request)
    if attachment_lines:
        text = (text + "\n\n" if text else "") + render_platform_prompt(
            "user.attachments.section.v1",
            {"attachment_lines": attachment_lines},
        )
    return text.strip()


def _user_requests_recruitment(text: str) -> bool:
    """Return whether the current user turn explicitly asks to invite more experts."""
    value = str(text or "").strip()
    if not value:
        return False
    return any(token in value for token in ("邀请", "加人", "加入专家", "添加专家", "再加", "请加", "拉进来"))


def _finalize_suggested_add_agent_names(
    *,
    suggested: List[str],
    agent_names: List[str],
    available_to_add: List[Dict[str, Any]],
    user_text: str,
) -> List[str]:
    """Apply the recruitment contract before exposing suggestions to the frontend."""
    available = {
        str(item.get("name") or "").strip()
        for item in available_to_add or []
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    deduped: list[str] = []
    for raw in suggested or []:
        name = str(raw or "").strip()
        if name and name in available and name not in deduped:
            deduped.append(name)
    if not deduped:
        return []
    if agent_names and not _user_requests_recruitment(user_text):
        return []
    return deduped


def _collect_artifacts(tool_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collect artifact references emitted by tools into the public skill_result."""
    artifacts: list[dict[str, Any]] = []
    for result in tool_results or []:
        if not isinstance(result, dict):
            continue
        raw_artifacts = result.get("artifacts")
        if not isinstance(raw_artifacts, list):
            continue
        for item in raw_artifacts:
            if not isinstance(item, dict):
                continue
            public_ref = {
                "type": item.get("type"),
                "name": item.get("name"),
                "path": item.get("path"),
            }
            try:
                artifacts.append(ArtifactRef.model_validate(public_ref).model_dump())
            except Exception:
                continue
    return artifacts


async def group_chat_stream(group_session_id: str, request: GroupChatRequest):
    """Run one strict group-chat stream for a validated request."""
    await ensure_mcp_and_skills_initialized()
    session_definitions = load_session_definitions()
    if group_session_id not in session_definitions:
        raise HTTPException(status_code=404, detail="Group session not found")
    _validate_attachments(group_session_id, request)

    session_item = session_definitions[group_session_id]
    app_settings = load_app_settings()
    instances = [dict(item) for item in (load_agent_instances() or []) if isinstance(item, dict)]
    agent_map = {str(item.get("name") or "").strip(): item for item in instances if str(item.get("name") or "").strip()}
    session_agent_names = _dedupe_names(list(session_item.get("agent_names") or []))
    agent_names = [name for name in session_agent_names if name in agent_map]
    if request.target_agent_name and request.target_agent_name not in agent_names:
        raise HTTPException(status_code=400, detail="target_agent_name is not in current agent_names")

    messages = load_group_history(group_session_id)
    user_text = _request_user_text(request)
    _record_user_message_and_refresh_title(
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
        )
        try:
            yield _sse("start", SseStartEvent(type="start", run_id=run_id).model_dump())
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
            yield _sse("error", error.model_dump(exclude_none=True))
            end = SseEndEvent(type="end", run_id=run_id, phase="failed", waiting_for_user=True)
            yield _sse("end", _end_event_payload(end))
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
            scheduler_recent_context(group_session_id, messages),
            available_to_add,
            "",
            group_session_id,
        )
        suggested_add = _finalize_suggested_add_agent_names(
            suggested=[str(item).strip() for item in (picked or []) if str(item).strip()],
            agent_names=agent_names,
            available_to_add=available_to_add,
            user_text=user_text,
        )
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
        yield _sse("message", host_msg)
        phase = "recruiting" if suggested_add else "awaiting_user"
        end = SseEndEvent(
            type="end",
            run_id=run_id,
            phase=phase,
            waiting_for_user=True,
            suggested_add_agent_names=suggested_add,
        )
        yield _sse("end", _end_event_payload(end))
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
            scheduler_recent_context(group_session_id, messages),
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
        next_speaker = str(decision.get("next_speaker") or "user").strip()
        next_action = str(decision.get("next_action") or "").strip() or next_action
        suggested_add = _finalize_suggested_add_agent_names(
            suggested=[str(item).strip() for item in (decision.get("suggested_add_agent_names") or []) if str(item).strip()],
            agent_names=agent_names,
            available_to_add=available_to_add,
            user_text=user_text,
        )
        host_scheduler = {
            "current_phase": str(decision.get("current_phase") or "").strip(),
            "next_speaker": next_speaker,
            "next_action": next_action,
        }
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
            yield _sse("message", host_msg)
        phase = "completed" if next_speaker == "end" else ("recruiting" if suggested_add else "awaiting_user")
        end = SseEndEvent(
            type="end",
            run_id=run_id,
            phase=phase,
            waiting_for_user=next_speaker != "end",
            suggested_add_agent_names=suggested_add,
        )
        yield _sse("end", _end_event_payload(end))
        return

    if next_speaker not in agent_names:
        error = SseErrorEvent(
            type="error",
            run_id=run_id,
            code="invalid_next_speaker",
            message=f"Host selected an agent outside current agent_names: {next_speaker}",
        )
        yield _sse("error", error.model_dump(exclude_none=True))
        end = SseEndEvent(type="end", run_id=run_id, phase="failed", waiting_for_user=True)
        yield _sse("end", _end_event_payload(end))
        return

    turns = 0
    while next_speaker in agent_names:
        turns += 1
        if turns > MAX_EXPERT_TURNS_PER_STREAM:
            end = SseEndEvent(
                type="end",
                run_id=run_id,
                phase="awaiting_user",
                waiting_for_user=True,
                suggested_next_speaker=next_speaker,
            )
            yield _sse("end", _end_event_payload(end))
            return
        async for event in _run_one_expert_turn(
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
        ):
            yield event
        end = SseEndEvent(
            type="end",
            run_id=run_id,
            phase="awaiting_user",
            waiting_for_user=True,
            suggested_next_speaker=next_speaker,
        )
        yield _sse("end", _end_event_payload(end))
        return


async def _run_one_expert_turn(
    *,
    group_session_id: str,
    run_id: str,
    session_definitions: Dict[str, Dict[str, Any]],
    session_item: Dict[str, Any],
    app_settings: Dict[str, Any],
    agent_map: Dict[str, Dict[str, Any]],
    agent_name: str,
    messages: List[Dict[str, Any]],
    discussion_goal: str,
    user_text: str,
    next_action: str,
) -> AsyncIterator[str]:
    """Run one expert and emit route/progress/message events."""
    agent_profile = agent_map[agent_name]
    runtime = await build_expert_turn_runtime(
        agent_profile=agent_profile,
        agent_name=agent_name,
        group_session_id=group_session_id,
        discussion_goal=discussion_goal,
        messages=messages,
        session_item=session_item,
        orchestration_state=load_group_orchestration_state(group_session_id),
        app_settings=app_settings,
        round_user_text=user_text,
        extra_system_prompt="",
        skills_loader=_request_skills_loader(),
        llm_resolver=lambda profile: _get_llm_for_agent(profile, app_settings),
    )
    if runtime.blocked:
        error = SseErrorEvent(
            type="error",
            run_id=run_id,
            code=str((runtime.skill_route_diagnostics or {}).get("blocking_error") or "expert_runtime_blocked"),
            message=f"Expert runtime blocked for {agent_name}",
        )
        yield _sse("error", error.model_dump(exclude_none=True))
        return

    route = SseRouteEvent(type="route", run_id=run_id, agent_name=agent_name, skill=runtime.skill or None)
    await update_group_run(group_session_id, run_id, agent_name=agent_name, skill=runtime.skill, phase="agent_routed")
    yield _sse("route", route.model_dump(exclude_none=True))

    prompt_bundle = build_expert_turn_prompt(
        session_id=group_session_id,
        target_agent_name=agent_name,
        discussion_goal=discussion_goal,
        user_message=user_text,
        recent_context=messages_to_expert_context(messages),
        app_settings=app_settings,
        next_action=next_action,
    )
    initial_state = {
        "messages": [HumanMessage(content=prompt_bundle.user_content)],
        "tools": runtime.tools,
        "workspace_id": group_session_id,
    }
    run_cfg = {"configurable": {"thread_id": f"group:{group_session_id}:{agent_name}:{uuid.uuid4().hex}"}}
    accumulated: list[str] = []
    tool_results: list[dict[str, Any]] = []
    current_phase = "executing"
    await update_group_run(group_session_id, run_id, phase=current_phase)
    yield _sse(
        "progress",
        SseProgressEvent(type="progress", run_id=run_id, phase=current_phase, agent_name=agent_name, skill=runtime.skill).model_dump(exclude_none=True),
    )
    async for stream_item in iter_with_keepalive(runtime.agent.astream(initial_state, config=run_cfg, stream_mode=["updates", "messages", "values"])):
        if not isinstance(stream_item, dict):
            continue
        event_type = str(stream_item.get("type") or "").strip()
        if event_type == "keepalive":
            yield _sse(
                "progress",
                SseProgressEvent(type="progress", run_id=run_id, phase=current_phase, agent_name=agent_name, skill=runtime.skill).model_dump(exclude_none=True),
            )
            continue
        if event_type == "agent_step":
            message = stream_item.get("message")
            if isinstance(message, AIMessage):
                content = str(message.content if isinstance(message.content, str) else message.content or "").strip()
                if content and content not in accumulated:
                    accumulated.append(content)
                if getattr(message, "tool_calls", None):
                    current_phase = "tool_running"
                    await update_group_run(group_session_id, run_id, phase=current_phase)
                    yield _sse(
                        "progress",
                        SseProgressEvent(type="progress", run_id=run_id, phase=current_phase, agent_name=agent_name, skill=runtime.skill).model_dump(exclude_none=True),
                    )
            continue
        if event_type == "tool_step":
            structured = stream_item.get("tool_results")
            if isinstance(structured, list):
                for item in structured:
                    if isinstance(item, dict) and item not in tool_results:
                        tool_results.append(item)
            continue

    content = "\n\n".join(part for part in accumulated if part).strip()
    if not content:
        content = "模型没有返回可展示的文字内容。"
    has_failed = any(item.get("execution_status") == "failed" for item in tool_results if isinstance(item, dict))
    has_blocked = any(item.get("execution_status") == "blocked" for item in tool_results if isinstance(item, dict))
    status = "failed" if has_failed else "blocked" if has_blocked else "succeeded"
    artifacts = _collect_artifacts(tool_results)
    skill_result = skill_result_from_content(
        status=status,
        content=content,
        artifacts=artifacts,
        tool_results=tool_results,
    )
    content = str(skill_result.get("content") or content or "无可展示内容。")
    orchestration_state = load_group_orchestration_state(group_session_id)
    if apply_skill_result_to_orchestration_state(
        orchestration_state,
        agent_name=agent_name,
        skill=runtime.skill,
        skill_result=skill_result,
    ):
        write_group_orchestration_state(group_session_id, orchestration_state)
    assistant_msg = {
        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
        "speaker": {"type": "expert", "agent_name": agent_name, "skill": runtime.skill},
        "message": {"content": content},
        "created_at": format_storage_timestamp(),
        "skill_result": skill_result,
    }
    assistant_msg = frontend_history_message(assistant_msg)
    append_tool_execution_logs(
        group_session_id,
        message_id=str(assistant_msg.get("message_id") or ""),
        agent_name=agent_name,
        skill=str(runtime.skill or ""),
        tool_results=tool_results,
    )
    messages.append(assistant_msg)
    save_group_history(group_session_id, messages, checkpoint_trigger="turn_completed")
    session_item["updated_at"] = format_storage_timestamp()
    save_session_definitions(session_definitions)
    await update_group_run(group_session_id, run_id, phase="finalizing")
    yield _sse("message", assistant_msg)
