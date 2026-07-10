"""Host scheduler runtime for the strict group-chat contract."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.agent.messages import HumanMessage, SystemMessage  # type: ignore
from app.agent.group_chat_expert_resolution import _llm_credential_notice_for_agent
from app.agent.group_host_decision import parse_strict_host_scheduler_output
from app.agent.platform_prompts import render_platform_prompt
from app.api.settings_app import load_app_settings
from app.core.security import get_current_user
from app.skills.loader import get_skills_loader_for_user

logger = logging.getLogger(__name__)


def _request_skills_loader():
    """Return the current user's Skill loader for host and expert runtime setup."""
    user = get_current_user()
    return get_skills_loader_for_user(user.username, user.ctx.skills_dir)


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
    blocks = ["当前会话成员：\n" + ("\n".join(member_lines) if member_lines else "（无）")]
    if add_lines:
        blocks.append("可建议邀请的专家：\n" + "\n".join(add_lines))
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
) -> Dict[str, Any]:
    """Ask the host LLM for the next scheduler decision and validate it strictly."""
    _ = (
        messages,
        orphan_session_agent_names,
        host_mode,
    )
    settings = load_app_settings() if app_settings is None else app_settings
    credential_notice = _llm_credential_notice_for_agent(host_agent, settings)
    if credential_notice:
        return {
            "current_phase": "awaiting_user",
            "next_speaker": "user",
            "next_action": credential_notice,
            "suggested_add_agent_names": None,
        }

    host_name = str(host_agent.get("name") or "四九").strip() or "四九"
    host_system = str(host_agent.get("system_prompt") or "").strip()
    host_skill_content = _load_host_skill_content(host_agent)
    system_parts = [
        host_system,
        host_skill_content,
        render_platform_prompt("host.system.boundary.v1", {}),
    ]
    if extra_system_prompt:
        system_parts.append(str(extra_system_prompt).strip())
    system_content = "\n\n".join(part for part in system_parts if part)

    current_phase = ""
    if isinstance(host_scheduler_state, dict):
        current_phase = str(host_scheduler_state.get("current_phase") or "").strip()
    prompt = render_platform_prompt(
        "host.select_next_speaker.v1",
        {
            "agent_names": _agent_catalog(agent_profiles, available_to_add),
            "current_phase": current_phase or "（无）",
            "user_message": user_message or discussion_goal or "（无）",
            "recent_history": recent_messages or "（无）",
        },
    )
    if last_speaker_agent_name:
        prompt += "\n\n" + render_platform_prompt(
            "host.previous_speaker.v1",
            {"last_speaker_agent_name": last_speaker_agent_name},
        )

    response = await llm.get_client().ainvoke([SystemMessage(content=system_content), HumanMessage(content=prompt)])
    raw = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw, list):
        raw = "".join(str(item) for item in raw)
    decision = parse_strict_host_scheduler_output(str(raw or ""), agent_profiles, host_mode="recruitment")
    state = {
        "current_phase": str(decision.get("current_phase") or "").strip(),
        "next_speaker": str(decision.get("next_speaker") or "").strip(),
        "next_action": str(decision.get("next_action") or "").strip(),
    }
    logger.info(
        "host_scheduler_decision session=%s host=%s next_speaker=%s current_phase=%s",
        group_session_id,
        host_name,
        state["next_speaker"],
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
    _ = (discussion_goal, recent_messages, all_instances, extra_system_prompt, group_session_id)
    return "当前会话还没有专家，请先邀请专家后继续。", None
