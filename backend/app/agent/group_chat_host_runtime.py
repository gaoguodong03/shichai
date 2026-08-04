"""Host scheduler runtime for the strict group-chat contract."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.agent.messages import HumanMessage, SystemMessage  # type: ignore
from app.agent.group_chat_expert_resolution import _llm_credential_notice_for_agent
from app.agent.group_host_decision import (
    compose_host_scheduler_decision,
    heuristic_recommend_agents,
    host_protocol_error_decision,
    host_scheduler_decision_from_payload,
    host_speaker_selection_from_payload,
)
from app.agent.group_context import skill_sessions_to_host_context
from app.agent.platform_prompts import render_platform_prompt
from app.agent.structured_llm_output import invoke_pydantic_llm_output
from app.agent.structured_output_contracts import (
    HostMessagePayload,
    HostSchedulerDecisionPayload,
    HostSpeakerSelectionPayload,
    StructuredOutputProtocolError,
    build_host_speaker_selection_model,
)
from app.api.settings_app import load_app_settings
from app.core.security import get_current_user
from app.skills.loader import get_skills_loader_for_user

logger = logging.getLogger(__name__)


def _request_skills_loader():
    """Return the current user's Skill loader for host and expert runtime setup."""
    user = get_current_user()
    return get_skills_loader_for_user(user.user_id, user.ctx.skills_dir)


def _host_skill_directory(host_agent: Dict[str, Any]) -> str:
    """Resolve the host Skill directory from the session host snapshot."""
    return str(host_agent.get("skill_directory") or "").strip()


def _load_host_skill_content(host_agent: Dict[str, Any]) -> str:
    """Load host Skill text by directory name; missing content is a resource error for logs."""
    skill_directory = _host_skill_directory(host_agent)
    if not skill_directory:
        return ""
    try:
        return str(_request_skills_loader().get_skill_full_content(skill_directory) or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("host skill content unavailable skill=%s error=%s", skill_directory, exc)
        return ""


def _agent_catalog(
    agent_profiles: List[Dict[str, Any]],
    available_to_add: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Render current members and optional invitable experts for the scheduler prompt."""
    member_lines: list[str] = []
    for agent in agent_profiles or []:
        name = str(agent.get("name") or "").strip()
        if not name:
            continue
        description = str(agent.get("description") or "参与者").strip()
        member_lines.append(f"- {name}: {description}")
    add_lines: list[str] = []
    for agent in available_to_add or []:
        name = str(agent.get("name") or "").strip()
        if not name:
            continue
        description = str(agent.get("description") or "参与者").strip()
        add_lines.append(f"- {name}: {description}")
    blocks = [
        render_platform_prompt(
            "host.agent_catalog.members.v1",
            {"member_lines": "\n".join(member_lines) if member_lines else "（无）"},
        )
    ]
    if add_lines:
        blocks.append(
            render_platform_prompt(
                "host.agent_catalog.invitable.v1",
                {"invitable_lines": "\n".join(add_lines)},
            )
        )
    return "\n\n".join(blocks)


async def _host_decide_by_agent(
    llm: Any,
    host_agent: Dict[str, Any],
    agent_profiles: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    last_speaker_agent_name: Optional[str],
    extra_system_prompt: str,
    available_to_add: Optional[List[Dict[str, Any]]] = None,
    *,
    group_session_id: str = "",
    messages: Optional[List[Dict[str, Any]]] = None,
    app_settings: Optional[Dict[str, Any]] = None,
    user_message: str = "",
    orphan_session_agent_names: Optional[List[str]] = None,
    host_mode: str = "recruitment",
    session_item: Optional[Dict[str, Any]] = None,
    host_scheduler_state: Optional[Dict[str, Any]] = None,
    skill_sessions_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Ask the host LLM for the next scheduler decision and validate it strictly."""
    _ = (
        messages,
        orphan_session_agent_names,
    )
    settings = load_app_settings() if app_settings is None else app_settings
    credential_notice = _llm_credential_notice_for_agent(host_agent, settings)
    if credential_notice:
        return {
            "current_phase": "awaiting_user",
            "message": {"content": credential_notice, "target_agent_name": "user"},
            "suggested_add_agent_names": None,
        }

    host_name = str(host_agent.get("name") or "四九").strip() or "四九"
    host_system = str(host_agent.get("system_prompt") or "").strip()
    host_skill_content = _load_host_skill_content(host_agent)
    system_parts = [
        str(extra_system_prompt or "").strip(),
        host_system,
        host_skill_content,
    ]
    system_content = "\n\n".join(part for part in system_parts if part)

    current_phase = ""
    if isinstance(host_scheduler_state, dict):
        current_phase = str(host_scheduler_state.get("current_phase") or "").strip()
    allowed_target_agent_names = ["user", "end"] + [
        str(profile.get("name") or "").strip()
        for profile in agent_profiles or []
        if str(profile.get("name") or "").strip()
    ]
    selection_prompt = render_platform_prompt(
        "host.select_next_speaker.v1",
        {
            "agent_names": _agent_catalog(agent_profiles, available_to_add),
            "allowed_target_agent_names": json.dumps(allowed_target_agent_names, ensure_ascii=False),
            "current_phase": current_phase or "（无）",
            "user_message": user_message or discussion_goal or "（无）",
            "recent_history": recent_messages or "（无）",
            "skill_sessions": skill_sessions_to_host_context(skill_sessions_state),
        },
    )
    if last_speaker_agent_name:
        selection_prompt += "\n\n" + render_platform_prompt(
            "host.previous_speaker.v1",
            {"last_speaker_agent_name": last_speaker_agent_name},
        )

    client = llm.get_client()
    selection_system_content = "\n\n".join(
        part
        for part in (
            system_content,
            render_platform_prompt("host.select_next_speaker.system_protocol.v1", {}),
        )
        if part
    )
    selection_messages = [SystemMessage(content=selection_system_content), HumanMessage(content=selection_prompt)]
    selection_retry_prompt = selection_prompt + "\n\n" + render_platform_prompt(
        "host.select_next_speaker.protocol_retry.v1",
        {"allowed_target_agent_names": json.dumps(allowed_target_agent_names, ensure_ascii=False)},
    )
    selection_retry_messages = [
        SystemMessage(content=selection_system_content),
        HumanMessage(content=selection_retry_prompt),
    ]
    selection_model = build_host_speaker_selection_model(allowed_target_agent_names)

    def _validate_selection_payload(payload: HostSpeakerSelectionPayload) -> None:
        host_speaker_selection_from_payload(payload, agent_profiles, host_mode=host_mode)

    try:
        selection_payload = await invoke_pydantic_llm_output(
            client,
            selection_messages,
            selection_model,
            retry_messages=selection_retry_messages,
            post_validate=_validate_selection_payload,
            protocol_log_context={
                "operation": "host_speaker_selection",
                "group_session_id": group_session_id,
                "host_name": host_name,
                "host_mode": host_mode,
                "current_phase": current_phase or "（无）",
                "allowed_agent_names": [
                    str(profile.get("name") or "").strip()
                    for profile in agent_profiles or []
                    if str(profile.get("name") or "").strip()
                ],
            },
        )
        selection = host_speaker_selection_from_payload(selection_payload, agent_profiles, host_mode=host_mode)
        logger.info(
            "host_speaker_selection session=%s host=%s target_agent_name=%s current_phase=%s "
            "suggested_add_agent_names=%s",
            group_session_id,
            host_name,
            selection["target_agent_name"],
            selection["current_phase"],
            selection.get("suggested_add_agent_names") or [],
        )
        message_prompt = render_platform_prompt(
            "host.write_scheduler_message.v1",
            {
                "target_agent_name": selection["target_agent_name"],
                "current_phase": selection["current_phase"],
                "suggested_add_agent_names": json.dumps(
                    selection.get("suggested_add_agent_names") or [],
                    ensure_ascii=False,
                ),
                "user_message": user_message or discussion_goal or "（无）",
                "recent_history": recent_messages or "（无）",
            },
        )
        message_system_content = "\n\n".join(
            part
            for part in (
                system_content,
                render_platform_prompt("host.write_scheduler_message.system_protocol.v1", {}),
            )
            if part
        )
        message_messages = [SystemMessage(content=message_system_content), HumanMessage(content=message_prompt)]
        message_retry_prompt = message_prompt + "\n\n" + render_platform_prompt(
            "host.write_scheduler_message.protocol_retry.v1",
            {},
        )
        message_retry_messages = [
            SystemMessage(content=message_system_content),
            HumanMessage(content=message_retry_prompt),
        ]
        message_payload = await invoke_pydantic_llm_output(
            client,
            message_messages,
            HostMessagePayload,
            retry_messages=message_retry_messages,
            protocol_log_context={
                "operation": "host_message_generation",
                "group_session_id": group_session_id,
                "host_name": host_name,
                "host_mode": host_mode,
                "current_phase": selection["current_phase"],
                "target_agent_name": selection["target_agent_name"],
            },
        )
        logger.info(
            "host_message_generation_complete session=%s host=%s fixed_target_agent_name=%s "
            "content_chars=%s attachment_count=%s artifact_count=%s",
            group_session_id,
            host_name,
            selection["target_agent_name"],
            len(message_payload.content),
            len(message_payload.attachments),
            len(message_payload.artifacts),
        )
        combined = compose_host_scheduler_decision(selection, message_payload)
        decision_payload = HostSchedulerDecisionPayload.model_validate(combined)
        decision = host_scheduler_decision_from_payload(decision_payload, agent_profiles, host_mode=host_mode)
    except StructuredOutputProtocolError as exc:
        logger.warning(
            "host_scheduler_protocol_fallback session=%s host=%s host_mode=%s current_phase=%s reason=%s",
            group_session_id,
            host_name,
            host_mode,
            current_phase or "（无）",
            str(exc),
        )
        decision = host_protocol_error_decision(str(exc))
    state = {"current_phase": str(decision.get("current_phase") or "").strip()}
    message = decision.get("message") if isinstance(decision.get("message"), dict) else {}
    target_agent_name = str(message.get("target_agent_name") or "").strip()
    logger.info(
        "host_scheduler_decision session=%s host=%s target_agent_name=%s current_phase=%s",
        group_session_id,
        host_name,
        target_agent_name,
        state["current_phase"],
    )
    return decision


async def _host_only_respond_and_recommend(
    discussion_goal: str,
    recent_messages: str,
    all_instances: List[Dict[str, Any]],
    extra_system_prompt: str,
    group_session_id: str = "",
) -> tuple[str, Optional[List[str]]]:
    """Return a no-expert host notice; expert invitation is controlled by end payload."""
    _ = (recent_messages, extra_system_prompt, group_session_id)
    picked = heuristic_recommend_agents(discussion_goal, all_instances, max_n=3)
    return "当前会话还没有专家，请先邀请专家后继续。", picked
