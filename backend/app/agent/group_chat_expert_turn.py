"""Expert single-turn execution for strict group-chat streams.

This module owns the expert astream loop, progress events, and tool-result
collection for one selected expert turn. Completion side effects are delegated
to the completion coordinator.
"""
from __future__ import annotations

import logging
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Literal

from app.agent.messages import AIMessage, HumanMessage  # type: ignore
from app.agent.llm_runtime_diagnostics import LLM_RESPONSE_INVALID, mark_latest_llm_call_failed
from app.agent.expert_completion_contract import (
    ExpertFinalStateProtocolError,
    select_expert_completion,
)
from app.agent.expert_completion_coordinator import coordinate_expert_completion
from app.agent.expert_runtime import build_expert_turn_runtime
from app.agent.group_chat_prompt_builder import build_expert_turn_prompt
from app.agent.group_chat_streaming import iter_with_keepalive, serialize_sse_event
from app.agent.group_context import messages_to_expert_context
from app.agent.session_prompt import build_shared_session_prompt
from app.agent.session_contracts import SseErrorEvent, SseProgressEvent, SseRouteEvent
from app.agent.session_runtime_logs import sanitize_runtime_failure_summary
from app.api.group_chat_state import (
    format_storage_timestamp,
    load_group_orchestration_state,
    update_group_run,
    write_group_orchestration_state,
)


logger = logging.getLogger(__name__)


@dataclass
class ExpertTurnOutcome:
    status: Literal["pending", "succeeded", "failed"] = "pending"
    execution_status: Literal["pending", "succeeded", "blocked", "failed"] = "pending"
    error_code: str = ""
    error_message: str = ""
    agent_turn: Literal["continue", "respond"] = "respond"
    skill_session: Literal["keep", "release"] = "release"
    skill: str = ""
    message_id: str = ""
    tool_results: list[dict[str, Any]] = field(default_factory=list)

    def succeed(
        self,
        *,
        agent_turn: Literal["continue", "respond"] = "respond",
        skill_session: Literal["keep", "release"] = "release",
        execution_status: Literal["succeeded", "blocked", "failed"] = "succeeded",
    ) -> None:
        self.status = "succeeded"
        self.execution_status = execution_status
        self.error_code = ""
        self.error_message = ""
        self.agent_turn = agent_turn
        self.skill_session = skill_session

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
    orchestration_state = load_group_orchestration_state(group_session_id)
    orchestration_state_before_build = deepcopy(orchestration_state)
    runtime = await build_expert_turn_runtime(
        agent_profile=agent_profile,
        agent_name=agent_name,
        group_session_id=group_session_id,
        discussion_goal=discussion_goal,
        messages=messages,
        session_item=session_item,
        orchestration_state=orchestration_state,
        app_settings=app_settings,
        round_user_text=user_text,
        extra_system_prompt=build_shared_session_prompt(app_settings, session_item),
        skills_loader=skills_loader,
        llm_resolver=llm_resolver,
    )
    if orchestration_state != orchestration_state_before_build:
        write_group_orchestration_state(group_session_id, orchestration_state)
    outcome.skill = str(runtime.skill or "").strip()
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
    tool_results = outcome.tool_results
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
        completion = select_expert_completion(final_content=final_content, tool_results=tool_results)
    except ExpertFinalStateProtocolError as exc:
        mark_latest_llm_call_failed(exc)
        logger.warning(
            "expert_final_state_invalid session=%s agent=%s skill=%s final_content=%r tool_results=%s",
            group_session_id,
            agent_name,
            runtime.skill,
            final_content[:2000],
            len(tool_results),
        )
        await update_group_run(group_session_id, run_id, phase="failed")
        safe_error_message = sanitize_runtime_failure_summary(str(exc))
        outcome.fail(code=LLM_RESPONSE_INVALID, message=safe_error_message)
        error = SseErrorEvent(
            type="error",
            run_id=run_id,
            code=LLM_RESPONSE_INVALID,
            message=safe_error_message,
        )
        yield serialize_sse_event("error", error.model_dump(exclude_none=True))
        return

    skill_session = completion.skill_session.action
    created_at = format_storage_timestamp()
    published_message_id = f"msg-{uuid.uuid4().hex[:8]}"
    applied = coordinate_expert_completion(
        completion=completion,
        orchestration_state=load_group_orchestration_state(group_session_id),
        agent_name=agent_name,
        skill=str(runtime.skill or ""),
        message_id=published_message_id,
        created_at=created_at,
        group_session_id=group_session_id,
        messages=messages,
        session_definitions=session_definitions,
        session_item=session_item,
        tool_results=tool_results,
    )
    outcome.message_id = published_message_id if applied.published is not None else ""
    if applied.published is not None:
        yield serialize_sse_event("message", applied.published.record)
    if applied.agent_turn.value == "continue_expert":
        await update_group_run(group_session_id, run_id, phase="finalizing")
        outcome.succeed(
            agent_turn="continue",
            skill_session="keep" if skill_session == "keep" else "release",
            execution_status=completion.execution.status,
        )
        return
    await update_group_run(group_session_id, run_id, phase="finalizing")
    outcome.succeed(
        agent_turn="respond",
        skill_session="keep" if skill_session == "keep" else "release",
        execution_status=completion.execution.status,
    )
