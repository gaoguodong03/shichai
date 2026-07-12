"""Expert single-turn execution for strict group-chat streams.

This module owns the expert astream loop, progress events, tool-result collection,
history persistence, orchestration-state updates, and group-chat tool trace
writing for one selected expert turn.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Literal

from app.agent.messages import AIMessage, HumanMessage  # type: ignore
from app.agent.expert_runtime import build_expert_turn_runtime
from app.agent.group_chat_prompt_builder import build_expert_turn_prompt
from app.agent.group_chat_skill_session import (
    ExpertFinalStateProtocolError,
    apply_skill_result_to_orchestration_state,
    message_from_expert_final_state,
    select_expert_final_state,
    skill_result_from_expert_final_state,
)
from app.agent.group_chat_streaming import iter_with_keepalive, serialize_sse_event
from app.agent.group_chat_tool_trace import record_group_chat_tool_trace
from app.agent.group_context import messages_to_expert_context
from app.agent.session_contracts import SseErrorEvent, SseProgressEvent, SseRouteEvent
from app.api.group_chat_state import (
    format_storage_timestamp,
    frontend_history_message,
    load_group_orchestration_state,
    save_group_history,
    save_session_definitions,
    update_group_run,
    write_group_orchestration_state,
)


logger = logging.getLogger(__name__)


@dataclass
class ExpertTurnOutcome:
    status: Literal["pending", "succeeded", "failed"] = "pending"
    error_code: str = ""
    error_message: str = ""

    def succeed(self) -> None:
        self.status = "succeeded"
        self.error_code = ""
        self.error_message = ""

    def fail(self, *, code: str, message: str) -> None:
        self.status = "failed"
        self.error_code = str(code or "expert_turn_failed").strip() or "expert_turn_failed"
        self.error_message = str(message or "Expert turn failed").strip() or "Expert turn failed"


async def run_one_expert_turn(
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
    outcome: ExpertTurnOutcome | None = None,
    skills_loader: Any | None = None,
    llm_resolver: Any | None = None,
) -> AsyncIterator[str]:
    """Run one expert and emit route/progress/message events."""
    outcome = outcome or ExpertTurnOutcome()
    agent_profile = agent_map[agent_name]
    if skills_loader is None:
        from app.agent.group_chat_host_runtime import _request_skills_loader

        skills_loader = _request_skills_loader()
    if llm_resolver is None:
        from app.agent.group_chat_expert_resolution import _get_llm_for_agent

        llm_resolver = lambda profile: _get_llm_for_agent(profile, app_settings)
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
        skills_loader=skills_loader,
        llm_resolver=llm_resolver,
    )
    if runtime.blocked:
        error_code = str((runtime.skill_route_diagnostics or {}).get("blocking_error") or "expert_runtime_blocked")
        error_message = f"Expert runtime blocked for {agent_name}"
        outcome.fail(code=error_code, message=error_message)
        error = SseErrorEvent(
            type="error",
            run_id=run_id,
            code=error_code,
            message=error_message,
        )
        yield serialize_sse_event("error", error.model_dump(exclude_none=True))
        return

    route = SseRouteEvent(type="route", run_id=run_id, agent_name=agent_name, skill=runtime.skill or None)
    await update_group_run(group_session_id, run_id, agent_name=agent_name, skill=runtime.skill, phase="agent_routed")
    yield serialize_sse_event("route", route.model_dump(exclude_none=True))

    prompt_bundle = build_expert_turn_prompt(
        session_id=group_session_id,
        target_agent_name=agent_name,
        discussion_goal=discussion_goal,
        user_message=user_text,
        memory_prompt=messages_to_expert_context(messages),
        app_settings=app_settings,
        next_action=next_action,
    )
    initial_state = {
        "messages": [HumanMessage(content=prompt_bundle.user_content)],
        "tools": runtime.tools,
        "workspace_id": group_session_id,
    }
    run_cfg = {"configurable": {"thread_id": f"group:{group_session_id}:{agent_name}:{uuid.uuid4().hex}"}}
    final_content = ""
    tool_results: list[dict[str, Any]] = []
    current_phase = "executing"
    await update_group_run(group_session_id, run_id, phase=current_phase)
    yield serialize_sse_event(
        "progress",
        SseProgressEvent(type="progress", run_id=run_id, phase=current_phase, agent_name=agent_name, skill=runtime.skill).model_dump(exclude_none=True),
    )
    async for stream_item in iter_with_keepalive(runtime.agent.astream(initial_state, config=run_cfg, stream_mode=["updates", "messages", "values"])):
        if not isinstance(stream_item, dict):
            continue
        event_type = str(stream_item.get("type") or "").strip()
        if event_type == "keepalive":
            yield serialize_sse_event(
                "progress",
                SseProgressEvent(type="progress", run_id=run_id, phase=current_phase, agent_name=agent_name, skill=runtime.skill).model_dump(exclude_none=True),
            )
            continue
        if event_type == "agent_step":
            message = stream_item.get("message")
            if isinstance(message, AIMessage):
                if getattr(message, "tool_calls", None):
                    current_phase = "tool_running"
                    await update_group_run(group_session_id, run_id, phase=current_phase)
                    yield serialize_sse_event(
                        "progress",
                        SseProgressEvent(type="progress", run_id=run_id, phase=current_phase, agent_name=agent_name, skill=runtime.skill).model_dump(exclude_none=True),
                    )
                else:
                    content = str(message.content if isinstance(message.content, str) else message.content or "").strip()
                    if content:
                        final_content = content
            continue
        if event_type == "tool_step":
            structured = stream_item.get("tool_results")
            if isinstance(structured, list):
                for item in structured:
                    if isinstance(item, dict) and item not in tool_results:
                        tool_results.append(item)
            continue

    try:
        final_state = select_expert_final_state(final_content=final_content, tool_results=tool_results)
    except ExpertFinalStateProtocolError as exc:
        logger.warning(
            "expert_final_state_invalid session=%s agent=%s skill=%s final_content=%r tool_results=%s",
            group_session_id,
            agent_name,
            runtime.skill,
            final_content[:2000],
            len(tool_results),
        )
        await update_group_run(group_session_id, run_id, phase="failed")
        outcome.fail(code="EXPERT_FINAL_STATE_INVALID", message=str(exc))
        error = SseErrorEvent(
            type="error",
            run_id=run_id,
            code="EXPERT_FINAL_STATE_INVALID",
            message=str(exc),
        )
        yield serialize_sse_event("error", error.model_dump(exclude_none=True))
        return

    message_body = message_from_expert_final_state(final_state)
    skill_result = skill_result_from_expert_final_state(final_state)
    orchestration_state = load_group_orchestration_state(group_session_id)
    if apply_skill_result_to_orchestration_state(
        orchestration_state,
        agent_name=agent_name,
        skill=runtime.skill,
        skill_result=skill_result,
        message=message_body,
    ):
        write_group_orchestration_state(group_session_id, orchestration_state)
    assistant_msg = {
        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
        "speaker": {"type": "expert", "agent_name": agent_name, "skill": runtime.skill},
        "message": message_body,
        "created_at": format_storage_timestamp(),
        "skill_result": skill_result,
    }
    assistant_msg = frontend_history_message(assistant_msg)
    record_group_chat_tool_trace(
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
    outcome.succeed()
    yield serialize_sse_event("message", assistant_msg)
