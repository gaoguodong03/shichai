"""多 Agent 群聊流式运行时。"""
from __future__ import annotations

import logging
import uuid
import asyncio
from typing import Optional, Dict, Any, List, Tuple

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.agent.messages import HumanMessage, AIMessage  # type: ignore

from app.api.agents import load_agent_instances
from app.api.settings_app import load_app_settings, normalize_host_profile
from app.api.group_chat_state import (
    ACTIVE_GROUP_RUNS as _ACTIVE_GROUP_RUNS,
    GROUP_SESSION_EVENT_SUBSCRIBERS as _GROUP_SESSION_EVENT_SUBSCRIBERS,
    GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK as _GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK,
    build_session_payload as _build_session_payload,
    cancel_group_session_run as _cancel_group_session_run,
    cleanup_orphan_group_histories as _cleanup_orphan_group_histories,
    ensure_sessions_dir as _ensure_sessions_dir,
    finish_group_run as _finish_group_run,
    format_storage_timestamp,
    load_group_history as _load_group_history,
    load_session_definitions as _load_session_definitions,
    publish_group_session_event as _publish_group_session_event,
    register_group_run as _register_group_run,
    runtime_state_for_session as _runtime_state_for_session,
    save_group_history as _save_group_history,
    save_session_definitions as _save_session_definitions,
    update_group_run as _update_group_run,
)
from app.agent.group_context import (
    has_auto_continue_signal as _has_auto_continue_signal,
    is_group_context_noise as _is_group_context_noise,
    messages_to_context as _messages_to_context,
    messages_to_expert_context as _messages_to_expert_context,
    normalize_compare_text as _normalize_compare_text,
    normalize_discussion_goal as _normalize_discussion_goal,
    scheduler_recent_context as _scheduler_recent_context,
)
from app.agent.group_host_decision import (
    extract_explicit_requested_agent_names as _extract_explicit_requested_agent_names,
    extract_forced_at_mention_agent_name as _extract_forced_at_mention_agent_name,
    heuristic_recommend_agents as _heuristic_recommend_agents,
    user_requests_host_takeover as _user_requests_host_takeover,
)
from app.agent.expert_runtime import build_expert_turn_runtime
from app.agent.leader_scheduler import leader_decide
from app.agent.orchestrator_state import (
    DecisionSource,
    InterruptReason,
    OrchestrationContext,
    OrchestrationDecision,
    OrchestrationPhase,
    build_end_payload,
)
from app.agent.orchestrator_reducer import apply_decision, move_to_interrupt, start_turn
from app.agent.hook_pipeline import HookPipeline
from app.agent.group_chat_hooks import _NeedUserInputHeuristicHook, _ToolFailureHeuristicHook
from app.agent.file_ref_resolver import resolve_file_refs_in_text
from app.core.init import ensure_mcp_and_skills_initialized
from app.core.feature_flags import is_feature_enabled
from app.core.security import get_current_user
from app.core.scene_host import VIRTUAL_SCENE_HOST_ID
from app.core.scene_scheduler import finalize_host_scheduler_decision
from app.agent.scene_runtime import SceneRuntime, build_context_system_prompt, load_session_scenario_row
from app.agent.group_orchestration_fsm import (
    clear_skill_session_lock,
    resolve_group_entry_route,
    user_requests_exit_skill_session,
)
from app.agent.skill_session_contract import resolve_skill_session_state
from app.agent.group_chat_tool_trace import (
    append_workspace_image_preview_markdown as _append_workspace_image_preview_markdown,
    extract_sandbox_entry_trace as _extract_sandbox_entry_trace,
    extract_tool_calls_from_accumulated as _extract_tool_calls_from_accumulated,
)
from app.agent.group_chat_streaming import (
    SSE_AGENT_KEEPALIVE_INTERVAL_SEC as _SSE_AGENT_KEEPALIVE_INTERVAL_SEC,
    iter_with_keepalive as _iter_with_keepalive,
    stream_background_events as _stream_background_events,
)
from app.agent.group_chat_memory_prompt import _persist_group_memory_turn
from app.agent.group_chat_prompt_builder import build_expert_turn_prompt
from app.agent.group_chat_soft_stop import _evaluate_soft_stop
from app.agent.group_chat_tool_result_content import problem_tool_result_content
from app.agent.group_chat_expert_resolution import (
    _get_llm_for_agent,
    _last_user_message_text,
    _llm_credential_notice_for_agent,
    _resolve_llm_config_for_agent,
)
from app.agent.group_chat_skill_session import (
    _clear_completed_skill_session_lock_from_history,
    _has_bound_skill_introspection_direct_final,
    _should_handoff_to_host_after_expert,
    _store_skill_session_lock_for_turn,
)
from app.agent.group_chat_host_runtime import (
    _host_decide_by_agent,
    _host_only_respond_and_recommend,
    _request_skills_loader,
)
from app.agent.group_chat_host_messages import (
    _build_host_fallback_message,
    _build_host_next_speaker_message,
    _build_host_notice_message,
    _build_host_pause_message,
    _build_host_recommendation_message,
    _build_host_recruit_message,
)
from app.agent.llm_client import (
    build_llm_credential_notice,
    is_llm_credential_error_message,
    should_log_full_prompts,
)
from app.agent.group_chat_title_meta import (
    _infer_required_user_fields_for_skill,
    _record_user_message_and_refresh_title,
)

logger = logging.getLogger(__name__)


async def _prepare_display_assistant_message(
    *,
    assistant_msg: Dict[str, Any],
    llm: Any,
    expert_system_prompt: str,
) -> Dict[str, Any]:
    """Return the frontend display copy without an extra presentation LLM call."""
    _ = llm, expert_system_prompt
    return dict(assistant_msg)


def _log_expert_prompt(
    *,
    session_id: str,
    run_id: str,
    agent_name: str,
    skill: str,
    user_content: str,
) -> None:
    prompt = str(user_content or "")
    if should_log_full_prompts():
        logger.info(
            "[Prompt] mode=full group_chat_expert_prompt code=expert_prompt session=%s run_id=%s agent_name=%s skill=%s prompt_len=%s\n%s",
            session_id,
            run_id,
            agent_name,
            skill,
            len(prompt),
            prompt,
        )
        return
    logger.info(
        "[Prompt] mode=summary group_chat_expert_prompt code=expert_prompt session=%s run_id=%s agent_name=%s skill=%s prompt_len=%s",
        session_id,
        run_id,
        agent_name,
        skill,
        len(prompt),
    )


def _dedupe_names(values: List[Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in values or []:
        name = str(raw or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


class GroupChatRequest(BaseModel):
    message: Optional[str] = None
    client_message_id: Optional[str] = None


async def group_chat_stream(group_session_id: str, request: GroupChatRequest):
    """群聊流式对话：用户消息或继续下一轮。"""
    logger.debug(
        "group_chat_stream_enter session=%s has_message=%s",
        group_session_id,
        bool((request.message or "").strip()),
    )
    await ensure_mcp_and_skills_initialized()

    session_definitions = _load_session_definitions()
    if group_session_id not in session_definitions:
        raise HTTPException(status_code=404, detail="Group session not found")
    session_item = session_definitions[group_session_id]
    instances = load_agent_instances()
    preferred_instances = [dict(d) for d in instances or [] if str((d or {}).get("name") or "").strip()]
    agent_names = _dedupe_names(list(session_item.get("agent_names", [])))
    session_item["agent_names"] = list(agent_names)
    leader_agent_name = str(session_item.get("leader_agent_name") or "").strip() or VIRTUAL_SCENE_HOST_ID
    agent_map = {str(d.get("name") or "").strip(): d for d in preferred_instances if str(d.get("name") or "").strip()}
    agent_names = [name for name in agent_names if name in agent_map]
    agent_profiles = [agent_map[name] for name in agent_names if name in agent_map]
    # 会话定义里有名称，但专家库中已不存在（删档/换库）→ 主持人侧参与者列表会空，易误判「要补人」
    orphan_session_agent_names = [str(name) for name in session_item.get("agent_names", []) if str(name).strip() and str(name).strip() not in agent_map]
    # 当前不在群内的专家，主持人可在「完成不了工作」时建议邀请。
    available_to_add = [
        d
        for d in preferred_instances
        if str(d.get("name") or "").strip()
        and str(d.get("name") or "").strip() not in agent_names
        and (not leader_agent_name or str(d.get("name") or "").strip() != leader_agent_name)
    ]

    messages = _load_group_history(group_session_id)
    app_settings = load_app_settings()
    hp_norm = normalize_host_profile(app_settings.get("host_profile") or {})
    scenario_row = load_session_scenario_row(session_item)
    host_config_row = scenario_row.get("host_config") if isinstance(scenario_row.get("host_config"), dict) else {}
    if not host_config_row:
        host_config_row = session_item.get("host_config") if isinstance(session_item.get("host_config"), dict) else {}
    hc_dn = str(host_config_row.get("leader_agent_name") or "").strip()
    host_display_name = hc_dn or str(hp_norm.get("leader_agent_name") or "四九").strip() or "四九"
    pending_owner_agent_name = (session_item.get("pending_owner_agent_name") or "").strip()
    pending_skill = (session_item.get("pending_skill") or "").strip()
    user_message = (request.message or "").strip()
    had_file_ref_tag = "【文件引用：" in user_message
    file_refs_resolved_in_request = False
    # 默认在服务端把【文件引用】展开为正文片段拼入用户消息，避免专家仅看到标签却未主动调用读文件工具。
    # 若上下文过大或需强制走工具链，可设置环境变量 FILE_REF_SERVER_RESOLVE_ENABLED=false 关闭。
    if is_feature_enabled("FILE_REF_SERVER_RESOLVE_ENABLED", default=True):
        user_message = resolve_file_refs_in_text(user_message, group_session_id)
        file_refs_resolved_in_request = "【文件内容已解析】" in user_message

    explicit_requested_agent_names = _extract_explicit_requested_agent_names(user_message, preferred_instances) if user_message else []
    forced_at_mention_agent_name = _extract_forced_at_mention_agent_name(user_message, preferred_instances) if user_message else None
    host_takeover_by_text = _user_requests_host_takeover(
        user_message,
        explicit_flag=None,
        host_display_name=host_display_name,
    )

    if user_message:
        _record_user_message_and_refresh_title(
            group_session_id=group_session_id,
            session_definitions=session_definitions,
            messages=messages,
            user_message=user_message,
            client_message_id=(request.client_message_id or "").strip(),
        )

    # 上一发言人（用于主持人/领导人判断 task_done；排除主持人本人，只计参与讨论的 Agent）
    last_speaker_agent_name = None
    for msg in reversed(messages):
        speaker = msg.get("speaker") if isinstance(msg.get("speaker"), dict) else {}
        speaker_agent_name = str(speaker.get("agent_name") or "").strip()
        if speaker.get("type") == "expert" and speaker_agent_name and speaker_agent_name != leader_agent_name:
            last_speaker_agent_name = speaker_agent_name
            break

    # 讨论目标：优先使用最近一条用户消息，避免会话继续时沿用旧目标导致专家跑偏。
    discussion_goal = _normalize_discussion_goal(_last_user_message_text(messages))
    if not discussion_goal:
        discussion_goal = "待用户提出讨论主题"

    extra_system_prompt = build_context_system_prompt(app_settings=app_settings, session_item=session_item)

    scene_runtime = SceneRuntime.from_group_session(
        session_id=group_session_id,
        session_item=session_item,
        agent_names=agent_names,
        agent_map=agent_map,
        app_host_profile=hp_norm,
        available_to_add=available_to_add,
    )
    host_agent = scene_runtime.host_profile
    stream_user = (get_current_user().username or "").strip()

    import json as json_module

    async def run_events():
        nonlocal last_speaker_agent_name, agent_names, agent_profiles, available_to_add, host_takeover_by_text
        current_task = asyncio.current_task()
        run_id = await _register_group_run(
            group_session_id,
            user_id=stream_user,
            task=current_task if current_task is not None else asyncio.create_task(asyncio.sleep(0)),
        )
        session_item: Dict[str, Any] = session_definitions[group_session_id]
        orch_profile = scene_runtime.orchestration_profile
        available_for_scheduler = scene_runtime.available_to_add_for_scheduler
        agent_turns = 0  # 本次流中 Agent 总发言轮次
        orch_ctx = OrchestrationContext(
            session_id=group_session_id,
            phase=OrchestrationPhase.PLANNING,
            owner_agent_name=last_speaker_agent_name,
            decision_source=DecisionSource.LEGACY,
        )
        start_turn(orch_ctx, phase=OrchestrationPhase.PLANNING, owner_agent_name=last_speaker_agent_name, source=DecisionSource.LEGACY)
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
            resume_target_agent_name: Optional[str] = last_speaker_agent_name
            current_skill_for_pending = pending_skill
            post_turn_hooks = HookPipeline([_ToolFailureHeuristicHook(), _NeedUserInputHeuristicHook()])

            def _apply_decision_to_ctx(decision: Dict[str, Any]) -> None:
                nonlocal latest_handoff_reason, resume_target_agent_name
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
                    current_phase=(decision.get("current_phase") or ""),
                    speaker_task=(decision.get("speaker_task") or ""),
                    suggested_add_agent_names=(decision.get("suggested_add_agent_names") or []),
                    phase=phase,
                    owner_agent_name=decision.get("owner_agent_name"),
                    interrupt_reason=interrupt,
                    decision_source=source,
                    handoff_reason=decision.get("handoff_reason"),
                    required_user_fields=decision.get("required_user_fields") or [],
                )
                apply_decision(orch_ctx, parsed)
                required_user_fields[:] = list(parsed.required_user_fields or [])
                latest_handoff_reason = parsed.handoff_reason
                resume_target_agent_name = parsed.owner_agent_name

            def _persist_pending_state(end_payload: Dict[str, Any]) -> None:
                nonlocal current_skill_for_pending
                waiting = bool(end_payload.get("waiting_for_user"))
                interrupt = str(end_payload.get("interrupt_reason") or "")
                resume = str(end_payload.get("resume_target_agent_name") or "").strip()
                required = end_payload.get("required_user_fields") or []
                should_keep_pending = (
                    waiting
                    and resume in agent_names
                    and (
                        interrupt in (InterruptReason.NEED_USER_INPUT.value, InterruptReason.NEED_MORE_CONTEXT.value)
                        or bool(required)
                    )
                )
                if should_keep_pending:
                    session_item["pending_owner_agent_name"] = resume
                    session_item["pending_skill"] = current_skill_for_pending or ""
                    session_item["pending_phase"] = str(end_payload.get("phase") or "")
                    session_item["pending_required_user_fields"] = required if isinstance(required, list) else []
                    session_item["pending_handoff_reason"] = str(end_payload.get("handoff_reason") or "")
                else:
                    session_item.pop("pending_owner_agent_name", None)
                    session_item.pop("pending_skill", None)
                    session_item.pop("pending_phase", None)
                    session_item.pop("pending_required_user_fields", None)
                    session_item.pop("pending_handoff_reason", None)
                session_item["updated_at"] = format_storage_timestamp()
                _save_session_definitions(session_definitions)

            yield f"event: start\ndata: {json_module.dumps({'type': 'start'})}\n\n"

            def _persist_host_memory(host_msg: Dict[str, Any]) -> None:
                try:
                    _persist_group_memory_turn(
                        session_id=group_session_id,
                        msg=host_msg,
                        discussion_goal=discussion_goal,
                        input_prompt_summary=(user_message or discussion_goal),
                        app_settings=app_settings,
                    )
                except Exception:
                    logger.warning("group memory write failed for host turn", exc_info=True)

            def _record_host_message(host_msg: Dict[str, Any]) -> str:
                messages.append(host_msg)
                _save_group_history(group_session_id, messages)
                _persist_host_memory(host_msg)
                return f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"

            def _credential_notice_for_agent(agent_profile: Optional[Dict[str, Any]]) -> Optional[str]:
                return _llm_credential_notice_for_agent(agent_profile, app_settings)

            def _build_credential_abort_events(
                agent_profile: Optional[Dict[str, Any]],
                *,
                error_code: str = "llm_credential_error",
            ) -> Optional[List[str]]:
                notice = _credential_notice_for_agent(agent_profile)
                if not notice:
                    return None
                host_msg = _build_host_notice_message(
                    skill=scene_runtime.host_bubble_skill(),
                    content=notice,
                    leader_agent_name=leader_agent_name,
                    meta={"error_code": error_code},
                )
                end_payload = build_end_payload(
                    waiting_for_user=True,
                    phase=OrchestrationPhase.AWAITING_USER,
                    interrupt_reason=InterruptReason.TOOL_UNAVAILABLE,
                    resume_target_agent_name=resume_target_agent_name,
                    required_user_fields=required_user_fields,
                    turn_id=orch_ctx.turn_id,
                    token_version=orch_ctx.token_version,
                    handoff_reason=notice,
                    extra={"error_code": error_code},
                )
                _persist_pending_state(end_payload)
                return [
                    _record_host_message(host_msg),
                    f"event: end\ndata: {json_module.dumps(end_payload, ensure_ascii=False)}\n\n",
                ]

            async def _handoff_to_host_scheduler_after_expert() -> Tuple[str, List[str]]:
                """After a completed expert turn, let the host choose the next owner in the same stream."""
                nonlocal scheduler_next_prompt
                emitted: List[str] = []
                recent = _scheduler_recent_context(group_session_id, messages)
                decision = None
                logger.info(
                    "group_chat_post_expert_scheduler_enter session=%s profile=%s agent_count=%s has_host=%s last_speaker=%s",
                    group_session_id,
                    orch_profile,
                    len(agent_names or []),
                    bool(host_agent),
                    last_speaker_agent_name,
                )
                abort_events = _build_credential_abort_events(host_agent if host_agent else None)
                if abort_events:
                    emitted.extend(abort_events)
                    return "user", emitted
                if leader_agent_name and host_agent:
                    llm_host = _get_llm_for_agent(host_agent, app_settings)
                    decision = await _host_decide_by_agent(
                        llm_host,
                        host_agent,
                        agent_profiles,
                        discussion_goal,
                        recent,
                        last_speaker_agent_name,
                        extra_system_prompt,
                        available_for_scheduler,
                        group_session_id=group_session_id,
                        messages=messages,
                        app_settings=app_settings,
                        pending_owner_agent_name=str(session_item.get("skill_session_owner_name") or "").strip(),
                        pending_skill=str(session_item.get("skill_session_skill") or "").strip(),
                        user_message="",
                        orphan_session_agent_names=orphan_session_agent_names,
                        orchestration_profile=orch_profile,
                        session_item=session_item,
                    )
                    logger.info(
                        "group_chat_post_expert_host_decide_done session=%s decision_none=%s next_speaker=%s reason=%s",
                        group_session_id,
                        decision is None,
                        (decision or {}).get("next_speaker") if isinstance(decision, dict) else "",
                        (decision or {}).get("reason") if isinstance(decision, dict) else "",
                    )
                if decision is None:
                    logger.info("group_chat_post_expert_fallback_to_leader_decide session=%s", group_session_id)
                    default_llm_name = str(app_settings.get("default_llm") or "")
                    llm_default = _get_llm_for_agent(None, app_settings)
                    decision = await leader_decide(
                        llm_default,
                        agent_profiles,
                        discussion_goal,
                        recent,
                        last_speaker_agent_name,
                        available_for_scheduler,
                        orchestration_profile=orch_profile,
                        group_session_id=group_session_id,
                        llm_name=default_llm_name,
                    )
                decision = finalize_host_scheduler_decision(
                    decision,
                    agent_names=agent_names,
                    agent_profiles=agent_profiles,
                    available_to_add=available_for_scheduler,
                    last_speaker_agent_name=last_speaker_agent_name,
                    user_message="",
                    explicit_requested_agent_names=[],
                    orchestration_profile=orch_profile,
                )
                logger.info(
                    "group_chat_post_expert_decision_finalized session=%s next_speaker=%s interrupt_reason=%s suggested_add=%s",
                    group_session_id,
                    (decision or {}).get("next_speaker") if isinstance(decision, dict) else "",
                    (decision or {}).get("interrupt_reason") if isinstance(decision, dict) else "",
                    len(list((decision or {}).get("suggested_add_agent_names") or [])) if isinstance(decision, dict) else 0,
                )
                _apply_decision_to_ctx(decision)
                announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                suggested_add = list(decision.get("suggested_add_agent_names") or [])
                resolved_next = str(decision.get("next_speaker") or "user").strip() or "user"
                np_auto = decision.get("speaker_task") if isinstance(decision, dict) else None
                if isinstance(np_auto, str) and np_auto.strip():
                    scheduler_next_prompt = np_auto.strip()

                if suggested_add:
                    resolved_next = "user"
                    orch_ctx.phase = OrchestrationPhase.RECRUITING
                    host_msg = _build_host_recruit_message(
                        skill=scene_runtime.host_bubble_skill(),
                        suggested_add=suggested_add,
                        leader_agent_name=leader_agent_name,
                    )
                    if host_msg:
                        emitted.append(_record_host_message(host_msg))
                    return resolved_next, emitted

                if resolved_next in agent_names:
                    host_msg = _build_host_next_speaker_message(
                        skill=scene_runtime.host_bubble_skill(),
                        next_speaker=resolved_next,
                        agent_map=agent_map,
                        announcement=announcement,
                        current_phase=decision.get("current_phase"),
                        speaker_task=decision.get("speaker_task"),
                        suggested_order=decision.get("suggested_order"),
                        leader_agent_name=leader_agent_name,
                    )
                    emitted.append(_record_host_message(host_msg))
                    orch_ctx.phase = OrchestrationPhase.EXECUTING
                    orch_ctx.owner_agent_name = resolved_next
                    return resolved_next, emitted

                if resolved_next in ("user", "end"):
                    host_msg = _build_host_pause_message(
                        skill=scene_runtime.host_bubble_skill(),
                        next_speaker=resolved_next,
                        announcement=announcement,
                        current_phase=decision.get("current_phase"),
                        reason=decision.get("reason"),
                        speaker_task=decision.get("speaker_task"),
                        leader_agent_name=leader_agent_name,
                    )
                    if host_msg:
                        emitted.append(_record_host_message(host_msg))
                    if resolved_next == "user":
                        orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                    elif resolved_next == "end":
                        orch_ctx.phase = OrchestrationPhase.COMPLETED
                    return resolved_next, emitted

                if resolved_next == "invite":
                    orch_ctx.phase = OrchestrationPhase.RECRUITING
                    return "user", emitted

                return "user", emitted

            next_speaker = None
            route_source = "unset"
            expert_route_debug_for_turn: Dict[str, Any] = {}
            scheduler_next_prompt: Optional[str] = None

            # 0 个 Agent：主持人为先，主持人回复用户并推荐若干 Agent 加入（不再使用 Chat）
            if len(agent_names) == 0:
                abort_events = _build_credential_abort_events(None)
                if abort_events:
                    for event in abort_events:
                        yield event
                    return
                recent = _scheduler_recent_context(group_session_id, messages)
                all_instances = [d for d in preferred_instances if str(d.get("name") or "").strip()]
                picked: List[str] = []
                valid_names = {str(d.get("name") or "").strip() for d in all_instances if str(d.get("name") or "").strip()}
                # 0 专家场景始终由主持人先回复并给出推荐，避免任何非 LLM 的短路分支
                host_content, suggested_add_agent_names = await _host_only_respond_and_recommend(
                    discussion_goal, recent, all_instances, extra_system_prompt, group_session_id
                )
                suggested_add_agent_names = suggested_add_agent_names or []
                picked = list(dict.fromkeys([x for x in suggested_add_agent_names if x in valid_names]))[:3]
                if not picked:
                    auto_picked = _heuristic_recommend_agents(discussion_goal, all_instances, max_n=3)
                    picked = list(dict.fromkeys([x for x in auto_picked if x in valid_names]))[:3]
                host_msg = _build_host_recommendation_message(
                    skill=scene_runtime.host_bubble_skill(),
                    content=host_content,
                    picked=picked,
                )
                host_event = _record_host_message(host_msg)
                session_definitions[group_session_id]["updated_at"] = format_storage_timestamp()
                _save_session_definitions(session_definitions)
                yield host_event
                end_payload = build_end_payload(
                    waiting_for_user=True,
                    phase=OrchestrationPhase.AWAITING_USER,
                    interrupt_reason=InterruptReason.NONE,
                    resume_target_agent_name=resume_target_agent_name,
                    required_user_fields=required_user_fields,
                    turn_id=orch_ctx.turn_id,
                    token_version=orch_ctx.token_version,
                    handoff_reason=latest_handoff_reason,
                )
                if picked:
                    end_payload["suggested_add_agent_names"] = picked
                _persist_pending_state(end_payload)
                yield f"event: end\ndata: {json_module.dumps(end_payload, ensure_ascii=False)}\n\n"
                return

            if _clear_completed_skill_session_lock_from_history(session_item, messages):
                _save_session_definitions(session_definitions)

            had_skill_lock = bool(str(session_item.get("skill_session_owner_name") or "").strip())
            if (user_requests_exit_skill_session(user_message) or host_takeover_by_text) and had_skill_lock:
                clear_skill_session_lock(session_item)
                _save_session_definitions(session_definitions)

            entry_route = resolve_group_entry_route(
                session_item=session_item,
                agent_names=agent_names,
                user_message=user_message,
            )
            if not entry_route.skip_host_dispatch:
                clear_skill_session_lock(session_item)
                _save_session_definitions(session_definitions)

            if forced_at_mention_agent_name and forced_at_mention_agent_name in agent_names:
                logger.debug("group_chat_route_branch=forced_at_mention session=%s next=%s", group_session_id, forced_at_mention_agent_name)
                clear_skill_session_lock(session_item)
                _save_session_definitions(session_definitions)
                next_speaker = forced_at_mention_agent_name
                route_source = "forced_at_mention"
                orch_ctx.phase = OrchestrationPhase.EXECUTING
                orch_ctx.owner_agent_name = forced_at_mention_agent_name
            elif explicit_requested_agent_names and any(aid in agent_names for aid in explicit_requested_agent_names):
                logger.debug("group_chat_route_branch=explicit_requested session=%s ids=%s", group_session_id, ",".join(explicit_requested_agent_names or []))
                # 用户显式点名场内专家时优先直达，避免被上一轮 skill 锁误续跑到其他专家。
                requested_in_room = [aid for aid in explicit_requested_agent_names if aid in agent_names]
                if requested_in_room:
                    clear_skill_session_lock(session_item)
                    _save_session_definitions(session_definitions)
                    next_speaker = requested_in_room[0]
                    route_source = "explicit_requested"
                    orch_ctx.phase = OrchestrationPhase.EXECUTING
                    orch_ctx.owner_agent_name = next_speaker
            elif explicit_requested_agent_names:
                # 用户点名了不在当前场景成员中的专家（常见于切场景后沿用旧 @专家）。
                # 记录后继续走主持人调度，不在该分支短路。
                logger.debug(
                    "group_chat_explicit_requested_not_in_room session=%s requested=%s room=%s",
                    group_session_id,
                    ",".join(explicit_requested_agent_names or []),
                    ",".join(agent_names or []),
                )
            elif entry_route.skip_host_dispatch and entry_route.direct_agent_name:
                logger.debug(
                    "group_chat_route_branch=skip_host_dispatch session=%s next=%s",
                    group_session_id,
                    entry_route.direct_agent_name,
                )
                next_speaker = entry_route.direct_agent_name
                route_source = "skip_host_dispatch"
                orch_ctx.phase = OrchestrationPhase.EXECUTING
                orch_ctx.owner_agent_name = entry_route.direct_agent_name
            else:
                logger.debug("group_chat_route_branch=host_scheduler session=%s", group_session_id)
                route_source = "host_scheduler"
                abort_events = _build_credential_abort_events(host_agent if host_agent else None)
                if abort_events:
                    for event in abort_events:
                        yield event
                    return
                # 统一调度路径：流程由 Skill 锁与主持人 JSON 表达。
                recent = _scheduler_recent_context(group_session_id, messages)
                decision = None
                logger.info(
                    "group_chat_scheduler_enter session=%s profile=%s agent_count=%s has_host=%s pending_owner=%s pending_skill=%s user_msg_len=%s",
                    group_session_id,
                    orch_profile,
                    len(agent_names or []),
                    bool(host_agent),
                    pending_owner_agent_name,
                    pending_skill,
                    len((user_message or "").strip()),
                )
                if leader_agent_name and host_agent:
                    llm_host = _get_llm_for_agent(host_agent, app_settings)
                    decision = await _host_decide_by_agent(
                        llm_host,
                        host_agent,
                        agent_profiles,
                        discussion_goal,
                        recent,
                        last_speaker_agent_name,
                        extra_system_prompt,
                        available_for_scheduler,
                        group_session_id=group_session_id,
                        messages=messages,
                        app_settings=app_settings,
                        pending_owner_agent_name=pending_owner_agent_name,
                        pending_skill=pending_skill,
                        user_message=user_message,
                        orphan_session_agent_names=orphan_session_agent_names,
                        orchestration_profile=orch_profile,
                        session_item=session_item,
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
                    default_llm_name = str(app_settings.get("default_llm") or "")
                    llm_default = _get_llm_for_agent(None, app_settings)
                    decision = await leader_decide(
                        llm_default,
                        agent_profiles,
                        discussion_goal,
                        recent,
                        last_speaker_agent_name,
                        available_for_scheduler,
                        orchestration_profile=orch_profile,
                        group_session_id=group_session_id,
                        llm_name=default_llm_name,
                    )
                    logger.info(
                        "group_chat_scheduler_leader_decide_done session=%s next_speaker=%s reason=%s",
                        group_session_id,
                        (decision or {}).get("next_speaker") if isinstance(decision, dict) else "",
                        (decision or {}).get("reason") if isinstance(decision, dict) else "",
                    )
                decision = finalize_host_scheduler_decision(
                    decision,
                    agent_names=agent_names,
                    agent_profiles=agent_profiles,
                    available_to_add=available_for_scheduler,
                    last_speaker_agent_name=last_speaker_agent_name,
                    user_message=user_message,
                    explicit_requested_agent_names=explicit_requested_agent_names,
                    orchestration_profile=orch_profile,
                )
                logger.info(
                    "group_chat_scheduler_decision_finalized session=%s next_speaker=%s interrupt_reason=%s suggested_add=%s required_fields=%s",
                    group_session_id,
                    (decision or {}).get("next_speaker") if isinstance(decision, dict) else "",
                    (decision or {}).get("interrupt_reason") if isinstance(decision, dict) else "",
                    len(list((decision or {}).get("suggested_add_agent_names") or [])) if isinstance(decision, dict) else 0,
                    len(list((decision or {}).get("required_user_fields") or [])) if isinstance(decision, dict) else 0,
                )
                _apply_decision_to_ctx(decision)
                announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                suggested_add = list(decision.get("suggested_add_agent_names") or [])
                next_speaker = decision.get("next_speaker", "user")
                np_auto = decision.get("speaker_task") if isinstance(decision, dict) else None
                if isinstance(np_auto, str) and np_auto.strip():
                    scheduler_next_prompt = np_auto.strip()
                if suggested_add:
                    next_speaker = "user"
                    route_source = "host_scheduler_recruit"
                    orch_ctx.phase = OrchestrationPhase.RECRUITING
                    host_msg = _build_host_recruit_message(
                        skill=scene_runtime.host_bubble_skill(),
                        suggested_add=suggested_add,
                        leader_agent_name=leader_agent_name,
                    )
                    if host_msg:
                        yield _record_host_message(host_msg)
                if next_speaker in agent_names:
                    host_msg = _build_host_next_speaker_message(
                        skill=scene_runtime.host_bubble_skill(),
                        next_speaker=next_speaker,
                        agent_map=agent_map,
                        announcement=announcement,
                        current_phase=decision.get("current_phase"),
                        speaker_task=decision.get("speaker_task"),
                        suggested_order=decision.get("suggested_order"),
                        leader_agent_name=leader_agent_name,
                    )
                    yield _record_host_message(host_msg)
                    orch_ctx.phase = OrchestrationPhase.EXECUTING
                    orch_ctx.owner_agent_name = next_speaker
                elif next_speaker in ("user", "end"):
                    host_msg = _build_host_pause_message(
                        skill=scene_runtime.host_bubble_skill(),
                        next_speaker=next_speaker,
                        announcement=announcement,
                        current_phase=decision.get("current_phase"),
                        reason=decision.get("reason"),
                        speaker_task=decision.get("speaker_task"),
                        leader_agent_name=leader_agent_name,
                    )
                    if host_msg:
                        yield _record_host_message(host_msg)
                    if next_speaker == "user":
                        orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                elif next_speaker == "invite":
                    orch_ctx.phase = OrchestrationPhase.RECRUITING

            if not next_speaker:
                route_source = "fallback_no_next_speaker"
                fallback_host = _build_host_fallback_message(
                    skill=scene_runtime.host_bubble_skill(),
                    leader_agent_name=leader_agent_name,
                )
                if fallback_host:
                    fallback_event = _record_host_message(fallback_host)
                    _save_session_definitions(session_definitions)
                    yield fallback_event

            logger.info(
                "group_chat_route_decided session=%s run_id=%s route_source=%s next_speaker=%s phase=%s skip_host_dispatch=%s had_skill_lock=%s pending_owner=%s pending_skill=%s",
                group_session_id,
                run_id,
                route_source,
                next_speaker or "",
                getattr(orch_ctx.phase, "value", str(orch_ctx.phase)),
                bool(getattr(entry_route, "skip_host_dispatch", False)),
                had_skill_lock,
                pending_owner_agent_name,
                pending_skill,
            )

            while orch_ctx.phase == OrchestrationPhase.EXECUTING and next_speaker and next_speaker in agent_names:
                if agent_turns >= 32:
                    move_to_interrupt(orch_ctx, InterruptReason.TIMEOUT_OR_BUDGET_EXCEEDED)
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker=next_speaker,
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=InterruptReason.TIMEOUT_OR_BUDGET_EXCEEDED,
                        resume_target_agent_name=resume_target_agent_name,
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
                agent_turns += 1
                start_turn(
                    orch_ctx,
                    phase=OrchestrationPhase.EXECUTING,
                    owner_agent_name=next_speaker,
                    source=DecisionSource.EXPERT,
                )
                resume_target_agent_name = next_speaker
                agent_profile = agent_map.get(next_speaker)
                if not agent_profile:
                    move_to_interrupt(orch_ctx, InterruptReason.NEED_MORE_CONTEXT)
                    next_speaker = "user"
                    break

                abort_events = _build_credential_abort_events(agent_profile)
                if abort_events:
                    for event in abort_events:
                        yield event
                    return

                expert_runtime = await build_expert_turn_runtime(
                    agent_profile=agent_profile,
                    agent_name=next_speaker,
                    group_session_id=group_session_id,
                    discussion_goal=discussion_goal,
                    messages=messages,
                    session_item=session_item,
                    app_settings=app_settings,
                    round_user_text=user_message,
                    extra_system_prompt=extra_system_prompt,
                    skills_loader=_request_skills_loader(),
                    llm_resolver=lambda d: _get_llm_for_agent(d, app_settings),
                )
                resolved_skill = expert_runtime.skill
                skill_content = expert_runtime.skill_content
                skill_route_debug = expert_runtime.skill_route_debug
                logger.info(
                    "group_chat_expert_runtime_resolved code=expert_runtime_resolved session=%s run_id=%s agent_name=%s skill=%s skill_loaded=%s tool_count=%s skill_strategy=%s blocking_error=%s",
                    group_session_id,
                    run_id,
                    next_speaker,
                    resolved_skill,
                    bool(skill_content),
                    len(list(getattr(expert_runtime, "tools", []) or [])),
                    str((skill_route_debug or {}).get("strategy") if isinstance(skill_route_debug, dict) else ""),
                    str((skill_route_debug or {}).get("blocking_error") if isinstance(skill_route_debug, dict) else ""),
                )
                if (
                    isinstance(skill_route_debug, dict)
                    and skill_route_debug.get("strict_llm_required")
                    and (not resolved_skill or not skill_content)
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
                    host_msg = _build_host_notice_message(
                        skill=scene_runtime.host_bubble_skill(),
                        content=err_msg,
                        leader_agent_name=leader_agent_name,
                        meta={
                            "error_code": err_code,
                            "agent_name": next_speaker,
                            "skill_route_debug": skill_route_debug,
                        },
                    )
                    host_event = _record_host_message(host_msg)
                    _save_session_definitions(session_definitions)
                    yield host_event
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker="user",
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=InterruptReason.NEED_USER_INPUT,
                        resume_target_agent_name=next_speaker,
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
                    "agent_name": next_speaker,
                    "skill": resolved_skill,
                    "expert_route_debug": expert_route_debug_for_turn if isinstance(expert_route_debug_for_turn, dict) else {},
                    "skill_route_debug": skill_route_debug if isinstance(skill_route_debug, dict) else {},
                }
                await _update_group_run(
                    group_session_id,
                    run_id,
                    agent_name=next_speaker,
                    skill=resolved_skill,
                    phase="agent_routed",
                )
                logger.info(
                    "group_chat_route_emit code=expert_route_emit session=%s run_id=%s agent_name=%s skill=%s tool_count=%s",
                    group_session_id,
                    run_id,
                    next_speaker,
                    resolved_skill,
                    len(list(tools or [])),
                )
                yield f"event: route\ndata: {json_module.dumps(route_event, ensure_ascii=False)}\n\n"
                context = _messages_to_expert_context(messages)
                prompt_bundle = build_expert_turn_prompt(
                    session_id=group_session_id,
                    target_agent_name=next_speaker,
                    discussion_goal=discussion_goal,
                    user_message=user_message,
                    recent_context=context,
                    app_settings=app_settings,
                    speaker_task=round_next_prompt,
                )
                user_content = prompt_bundle.user_content
                task_text_for_workspace = prompt_bundle.task_text
                _log_expert_prompt(
                    session_id=group_session_id,
                    run_id=run_id,
                    agent_name=next_speaker,
                    skill=resolved_skill,
                    user_content=user_content,
                )
                initial_state = {
                    "messages": [HumanMessage(content=user_content)],
                    "tools": tools,
                    "workspace_id": group_session_id,
                }
                run_cfg = {"configurable": {"thread_id": f"group:{group_session_id}:{next_speaker}:{uuid.uuid4().hex}"}}

                accumulated = []
                accumulated_raw_tool_results: List[str] = []
                accumulated_tool_results: List[Dict[str, Any]] = []
                accumulated_tool_calls_trace: List[Dict[str, Any]] = []
                tool_attempt_debug: List[Dict[str, Any]] = []
                _agent_waiting_status = ""
                _tool_running_status = ""
                _file_resolving_status = ""
                _file_resolved_status = ""
                should_emit_preparing_hint = had_file_ref_tag and file_refs_resolved_in_request
                emitted_tool_pending_hint = False
                emitted_agent_generating_hint = False
                if should_emit_preparing_hint:
                    yield f"event: content\ndata: {json_module.dumps({'text': _file_resolving_status, 'agent_name': next_speaker, 'meta': {'phase': 'file_resolving'}}, ensure_ascii=False)}\n\n"
                    yield f"event: content\ndata: {json_module.dumps({'text': _file_resolved_status, 'agent_name': next_speaker, 'meta': {'phase': 'file_resolved'}}, ensure_ascii=False)}\n\n"
                try:
                    logger.info(
                        "group_chat_agent_stream_start code=agent_stream_start session=%s run_id=%s agent_name=%s skill=%s user_content_len=%s tool_count=%s",
                        group_session_id,
                        run_id,
                        next_speaker,
                        resolved_skill,
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
                            yield f"event: content\ndata: {json_module.dumps({'text': _agent_waiting_status, 'agent_name': next_speaker, 'meta': {'phase': keepalive_phase}}, ensure_ascii=False)}\n\n"
                            continue
                        if ev_type == "agent_step":
                            msg_obj = stream_item.get("message")
                            if isinstance(msg_obj, AIMessage):
                                has_tool_calls = hasattr(msg_obj, "tool_calls") and msg_obj.tool_calls
                                content_str = str(msg_obj.content) if isinstance(msg_obj.content, str) else str(msg_obj.content or "")
                                if content_str.strip() and content_str not in accumulated:
                                    accumulated.append(content_str)
                                    if not emitted_agent_generating_hint:
                                        emitted_agent_generating_hint = True
                                        yield f"event: content\ndata: {json_module.dumps({'text': _agent_waiting_status, 'agent_name': next_speaker, 'meta': {'phase': 'assistant_generating'}}, ensure_ascii=False)}\n\n"
                                if has_tool_calls:
                                    if not emitted_tool_pending_hint:
                                        emitted_tool_pending_hint = True
                                        logger.info(
                                            "group_chat_tool_running code=agent_tool_calls_detected session=%s run_id=%s agent_name=%s skill=%s tool_call_count=%s",
                                            group_session_id,
                                            run_id,
                                            next_speaker,
                                            resolved_skill,
                                            len(list(msg_obj.tool_calls or [])),
                                        )
                                        await _update_group_run(group_session_id, run_id, phase="tool_running")
                                        yield f"event: content\ndata: {json_module.dumps({'text': _tool_running_status, 'agent_name': next_speaker, 'meta': {'phase': 'tool_running'}}, ensure_ascii=False)}\n\n"
                            continue
                        if ev_type == "tool_step":
                            tad = stream_item.get("tool_attempt_debug")
                            if isinstance(tad, list):
                                for item in tad:
                                    if item not in tool_attempt_debug:
                                        tool_attempt_debug.append(item)
                            tcalls = stream_item.get("tool_calls")
                            if isinstance(tcalls, list):
                                for call in tcalls:
                                    if isinstance(call, dict) and call not in accumulated_tool_calls_trace:
                                        accumulated_tool_calls_trace.append(call)
                                logger.info(
                                    "group_chat_tool_step code=agent_tool_step session=%s run_id=%s agent_name=%s skill=%s tool_call_count=%s raw_result_count=%s",
                                    group_session_id,
                                    run_id,
                                    next_speaker,
                                    resolved_skill,
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
                                    "group_chat_tool_outputs code=agent_tool_outputs session=%s run_id=%s agent_name=%s skill=%s raw_result_count=%s raw_result_lens=%s",
                                    group_session_id,
                                    run_id,
                                    next_speaker,
                                    resolved_skill,
                                    len(accumulated_raw_tool_results),
                                    [len(str(x or "")) for x in accumulated_raw_tool_results[-5:]],
                                )
                            structured_results = stream_item.get("tool_results")
                            if isinstance(structured_results, list):
                                for result in structured_results:
                                    if isinstance(result, dict) and result not in accumulated_tool_results:
                                        accumulated_tool_results.append(result)
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
                problem_tool_content = problem_tool_result_content(accumulated_tool_results)
                if (not full_content.strip()) and problem_tool_content:
                    full_content = problem_tool_content
                if (not full_content.strip()) and accumulated_tool_results:
                    full_content = "工具执行成功，但专家没有生成最终回复。请继续追问，让专家基于本轮工具结果整理。"
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
                skill_session_signals = skill_session_state.signals
                skill_introspection_meta_answer = _has_bound_skill_introspection_direct_final(tool_attempt_debug)
                sandbox_entry_trace = _extract_sandbox_entry_trace(accumulated_raw_tool_results)
                skill = resolved_skill if agent_profile else "default"
                current_skill_for_pending = skill
                logger.info(
                    "group_chat_agent_stream_done code=agent_stream_done session=%s run_id=%s agent_name=%s skill=%s content_len=%s tool_call_count=%s raw_result_count=%s skill_session_over=%s phase=%s interrupt_reason=%s resume_target=%s sandbox_trace=%s",
                    group_session_id,
                    run_id,
                    next_speaker,
                    skill,
                    len(full_content or ""),
                    len(tool_calls_trace or []),
                    len(accumulated_raw_tool_results or []),
                    skill_session_state.over,
                    getattr(orch_ctx.phase, "value", str(orch_ctx.phase)),
                    getattr(orch_ctx.interrupt_reason, "value", str(orch_ctx.interrupt_reason)),
                    resume_target_agent_name,
                    sandbox_entry_trace,
                )
                has_failed_tool = any(
                    isinstance(item, dict) and item.get("execution_status") == "failed"
                    for item in accumulated_tool_results
                )
                has_needs_input_tool = any(
                    isinstance(item, dict) and item.get("execution_status") == "needs_input"
                    for item in accumulated_tool_results
                )
                inferred_required_fields = _infer_required_user_fields_for_skill(skill_content, full_content)
                execution_status = (
                    "needs_input"
                    if inferred_required_fields or has_needs_input_tool
                    else "failed"
                    if has_failed_tool and full_content == problem_tool_content
                    else "succeeded"
                )
                assistant_msg = {
                    "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                    "speaker": {"type": "expert", "agent_name": next_speaker, "skill": skill},
                    "content": full_content,
                    "created_at": format_storage_timestamp(),
                    "skill_result": {
                        "execution_status": execution_status,
                        "result_code": execution_status,
                        "next_action": {
                            "agent_turn": "ask_user" if execution_status == "needs_input" else "respond",
                            "skill_session": "release" if skill_session_state.over is True else "keep",
                        },
                    },
                    "tool_results": accumulated_tool_results,
                }
                routing: Dict[str, Any] = {}
                if isinstance(skill_route_debug, dict):
                    routing["skill_route_debug"] = skill_route_debug
                if isinstance(expert_route_debug_for_turn, dict) and expert_route_debug_for_turn:
                    routing["expert_route_debug"] = expert_route_debug_for_turn
                if routing:
                    assistant_msg["routing"] = routing
                if inferred_required_fields:
                    assistant_msg["required_user_fields"] = inferred_required_fields
                assistant_msg["debug"] = {
                    "tool_trace": [
                        {
                            "event": "tool_runtime",
                            "data": {
                                "tool_calls": tool_calls_trace,
                                "tool_attempt_debug": tool_attempt_debug,
                                "raw_result_count": len(accumulated_raw_tool_results or []),
                                "has_tool_call": bool(tool_calls_trace),
                                "has_raw_result": bool(accumulated_raw_tool_results),
                                "skill_session_state": {
                                    "skill_session": (
                                        "release"
                                        if skill_session_state.over is True
                                        else "keep"
                                        if skill_session_state.over is False
                                        else None
                                    ),
                                    "source": skill_session_state.source,
                                    "signals": {
                                        "assistant_state_block": skill_session_signals.assistant_state_block
                                        if skill_session_signals
                                        else None,
                                        "script_stdout": skill_session_signals.script_stdout if skill_session_signals else None,
                                    },
                                },
                                "note": "no_tool_call_detected" if not tool_calls_trace else "",
                            },
                        }
                    ]
                }
                display_assistant_msg = await _prepare_display_assistant_message(
                    assistant_msg=assistant_msg,
                    llm=expert_runtime.llm,
                    expert_system_prompt=str(agent_profile.get("system_prompt") or ""),
                )
                messages.append(assistant_msg)
                _save_group_history(group_session_id, messages)
                session_definitions[group_session_id]["updated_at"] = format_storage_timestamp()
                _save_session_definitions(session_definitions)
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
                yield f"event: message\ndata: {json_module.dumps(display_assistant_msg, ensure_ascii=False)}\n\n"
                if skill_introspection_meta_answer:
                    clear_skill_session_lock(session_item)
                    session_definitions[group_session_id]["updated_at"] = format_storage_timestamp()
                    _save_session_definitions(session_definitions)
                    orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker="user",
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=InterruptReason.NONE,
                        resume_target_agent_name=None,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                    )
                    _persist_pending_state(end_data)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return
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
                        resume_target_agent_name=next_speaker,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                    )
                    _persist_pending_state(end_data)
                    _store_skill_session_lock_for_turn(
                        session_item,
                        owner_agent_name=next_speaker,
                        skill=skill,
                        skill_session_over=skill_session_state.over,
                        force_keep=True,
                    )
                    _save_session_definitions(session_definitions)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return
                hook_output = await post_turn_hooks.run(
                    {
                        "session_id": group_session_id,
                        "agent_name": next_speaker,
                        "skill": skill,
                        "full_content": full_content,
                        "tool_results": accumulated_tool_results,
                        "required_user_fields": assistant_msg.get("required_user_fields") or [],
                    }
                )
                if not hook_output.allow:
                    move_to_interrupt(orch_ctx, hook_output.interrupt_reason)
                    required_user_fields = list(hook_output.merged_metadata.get("required_user_fields") or required_user_fields)
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker="user",
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=hook_output.interrupt_reason,
                        resume_target_agent_name=resume_target_agent_name,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=hook_output.message or latest_handoff_reason,
                    )
                    _persist_pending_state(end_data)
                    _store_skill_session_lock_for_turn(
                        session_item,
                        owner_agent_name=resume_target_agent_name or next_speaker,
                        skill=skill,
                        skill_session_over=skill_session_state.over,
                        force_keep=True,
                    )
                    _save_session_definitions(session_definitions)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return
                soft_stop_reason = _evaluate_soft_stop(
                    state=soft_stop_state,
                    current_speaker=next_speaker,
                    full_content=full_content,
                    tool_results=accumulated_tool_results,
                )
                if soft_stop_reason:
                    logger.info(
                        "群聊软判停触发: session=%s speaker=%s turns=%s reason=%s metrics=%s",
                        group_session_id,
                        next_speaker,
                        agent_turns,
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
                        resume_target_agent_name=resume_target_agent_name,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                        extra={"soft_stop": True, "soft_stop_reason": soft_stop_reason},
                    )
                    _persist_pending_state(end_data)
                    _store_skill_session_lock_for_turn(
                        session_item,
                        owner_agent_name=next_speaker,
                        skill=skill,
                        skill_session_over=skill_session_state.over,
                    )
                    _save_session_definitions(session_definitions)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return

                last_speaker_agent_name = next_speaker
                _store_skill_session_lock_for_turn(
                    session_item,
                    owner_agent_name=next_speaker,
                    skill=skill,
                    skill_session_over=skill_session_state.over,
                )
                _save_session_definitions(session_definitions)
                if _should_handoff_to_host_after_expert(
                    orchestration_profile=orch_profile,
                    skill_session_over=skill_session_state.over,
                    has_auto_continue_signal=_has_auto_continue_signal(full_content),
                ):
                    previous_speaker = next_speaker
                    handoff_next, handoff_events = await _handoff_to_host_scheduler_after_expert()
                    for chunk in handoff_events:
                        yield chunk
                    if handoff_next in agent_names:
                        if handoff_next != previous_speaker:
                            clear_skill_session_lock(session_item)
                            _save_session_definitions(session_definitions)
                        next_speaker = handoff_next
                        continue
                    if handoff_next == "end":
                        clear_skill_session_lock(session_item)
                        _save_session_definitions(session_definitions)
                    next_speaker = handoff_next or "user"
                    break
                orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                end_data = build_end_payload(
                    waiting_for_user=True,
                    suggested_next_speaker="user",
                    phase=OrchestrationPhase.AWAITING_USER,
                    interrupt_reason=InterruptReason.NONE,
                    resume_target_agent_name=next_speaker,
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
                clear_skill_session_lock(session_item)
                payload = build_end_payload(
                    waiting_for_user=False,
                    discussion_ended=True,
                    phase=orch_ctx.phase,
                    interrupt_reason=InterruptReason.NONE,
                    resume_target_agent_name=resume_target_agent_name,
                    required_user_fields=required_user_fields,
                    turn_id=orch_ctx.turn_id,
                    token_version=orch_ctx.token_version,
                    handoff_reason=latest_handoff_reason,
                )
                _persist_pending_state(payload)
                _save_session_definitions(session_definitions)
                yield f"event: end\ndata: {json_module.dumps(payload)}\n\n"
            else:
                if orch_ctx.phase == OrchestrationPhase.EXECUTING:
                    orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                end_data = build_end_payload(
                    waiting_for_user=True,
                    suggested_next_speaker=next_speaker,
                    phase=orch_ctx.phase,
                    interrupt_reason=orch_ctx.interrupt_reason if orch_ctx.interrupt_reason != InterruptReason.NONE else InterruptReason.NONE,
                    resume_target_agent_name=resume_target_agent_name,
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
            err_text = str(e)
            if is_llm_credential_error_message(err_text):
                llm_name, cfg = _resolve_llm_config_for_agent(host_agent if host_agent else None, app_settings)
                notice = build_llm_credential_notice(llm_name, cfg)
                host_msg = _build_host_notice_message(
                    skill=scene_runtime.host_bubble_skill(),
                    content=notice,
                    leader_agent_name=leader_agent_name,
                    meta={"error_code": "llm_credential_error", "error": err_text},
                )
                messages.append(host_msg)
                _save_group_history(group_session_id, messages)
                yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
            else:
                yield f"event: error\ndata: {json_module.dumps({'error': err_text}, ensure_ascii=False)}\n\n"
            try:
                payload = build_end_payload(
                    waiting_for_user=True,
                    phase=OrchestrationPhase.AWAITING_USER,
                    interrupt_reason=InterruptReason.TOOL_UNAVAILABLE,
                    handoff_reason="stream_error",
                    extra={"error": err_text},
                )
                yield f"event: end\ndata: {json_module.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception:
                logger.exception("群聊流式异常 end 事件生成失败")
        finally:
            if not client_disconnected:
                await _finish_group_run(group_session_id, run_id)

    return StreamingResponse(
        _stream_background_events(run_events()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
