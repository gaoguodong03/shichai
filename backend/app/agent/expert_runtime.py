"""Expert runtime entrypoint.

An expert is stored as an Agent/profile dict, but this module gives one expert
turn a clear build path: resolve Skill -> build tools -> create executable agent.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.agent.messages import HumanMessage, SystemMessage  # type: ignore

from app.agent.expert_self_awareness import build_expert_self_awareness_block
from app.agent.group_chat_expert_resolution import _last_user_message_text
from app.agent.skill_agent_runtime import create_skill_execution_agent
from app.agent.skill_session_locks import clear_skill_session_lock, locked_skill_for_expert
from app.agent.skill_session_contract import GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
from app.agent.structured_output_contracts import ExpertSkillSelectionPayload, parse_strict_pydantic_object
from app.agent.tools_for_skill import build_tools_for_group_chat
from app.agent.platform_prompts import render_platform_prompt

logger = logging.getLogger(__name__)

LlmResolver = Callable[[Optional[Dict[str, Any]]], Any]
ToolBuilder = Callable[[Dict[str, Any], str, Optional[str]], Awaitable[List[Any]]]
AgentFactory = Callable[..., Any]


@dataclass
class ExpertTurnRuntime:
    """Callable-ish runtime bundle for a single expert turn."""

    agent_name: str
    agent_profile: Dict[str, Any]
    skill: str = ""
    skill_content: str = ""
    skill_route_diagnostics: Dict[str, Any] = field(default_factory=dict)
    tools: List[Any] = field(default_factory=list)
    llm: Any = None
    agent: Any = None

    @property
    def blocked(self) -> bool:
        return not self.skill or not self.skill_content or self.agent is None


def _skill_directory_names(agent_profile: Dict[str, Any]) -> List[str]:
    rows = agent_profile.get("skills")
    if isinstance(rows, list):
        names: List[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            directory_name = str(row.get("directory_name") or "").strip()
            if directory_name:
                names.append(directory_name)
        return names
    return []


async def expert_llm_pick_skill(
    llm: Any,
    skills_loader: Any,
    skill_directories: List[str],
    discussion_goal: str,
    messages: List[Dict[str, Any]],
    round_user_text: str,
    *,
    group_session_id: str = "",
    agent_name: str = "",
    llm_name: str = "",
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Ask the expert model to choose exactly one loaded Skill."""
    debug: Dict[str, Any] = {"strategy": "expert_llm_pick", "scores": []}
    lines: List[str] = []
    for sid in skill_directories:
        sk = getattr(skills_loader, "skills", {}).get(sid)
        if sk:
            desc = (sk.description or "")[:800]
            nm = sk.name or sid
            lines.append(f'- skill="{sid}" | name="{nm}" | description="{desc}"')
        else:
            lines.append(f'- skill="{sid}" | （未加载元数据，仍须从 id 中选择）')
    catalog = "\n".join(lines)
    um = (round_user_text or "").strip() or _last_user_message_text(messages)
    sys_msg = render_platform_prompt(
        "expert.select_skill.v1",
        {
            "agent_name": agent_name,
            "agent_description": agent_profile.get("description") or "（无）",
            "discussion_goal": discussion_goal or "（无）",
            "user_prompt": um or "（无）",
            "skill_directories": catalog,
            "next_action": round_user_text or "（无）",
        },
    )
    human = "请按系统提示选择本轮唯一 Skill。"
    try:
        client = llm.get_client()
        out = await client.ainvoke([SystemMessage(content=sys_msg), HumanMessage(content=human)])
        raw = out.content if hasattr(out, "content") else str(out)
        if isinstance(raw, list):
            raw = "".join(str(x) for x in raw)
        parsed = parse_strict_pydantic_object(str(raw), ExpertSkillSelectionPayload)
        picked = parsed.selected_skill.strip()
        valid = {str(x).strip() for x in skill_directories}
        if picked and picked in valid:
            debug["selected_skill"] = picked
            return picked, debug
        debug["strategy"] = "expert_llm_pick_invalid_id"
        debug["invalid_pick"] = picked
    except Exception as e:
        logger.warning("专家 Skill 选型 LLM 失败，将回退关键词路由: %s", e)
        debug["strategy"] = "expert_llm_pick_error"
        debug["error"] = str(e)
    return None, debug


async def resolve_expert_skill(
    *,
    agent_profile: Dict[str, Any],
    agent_name: str,
    discussion_goal: str,
    messages: List[Dict[str, Any]],
    session_item: Dict[str, Any],
    orchestration_state: Optional[Dict[str, Any]] = None,
    app_settings: Dict[str, Any],
    round_user_text: str,
    skills_loader: Any,
    llm_resolver: LlmResolver,
    group_session_id: str = "",
) -> Tuple[str, str, Dict[str, Any]]:
    """Resolve the Skill for one expert turn; locked Skill sessions win."""
    _ = app_settings
    skill_directories = _skill_directory_names(agent_profile)
    orchestration_state = orchestration_state if isinstance(orchestration_state, dict) else {}

    continuation = orchestration_state.get("continuation") if isinstance(orchestration_state.get("continuation"), dict) else {}
    owner = str(continuation.get("owner_agent_name") or "").strip().casefold()
    locked_raw = str(continuation.get("skill") or "").strip()
    if owner == str(agent_name or "").strip().casefold() and locked_raw and locked_raw not in skill_directories:
        clear_skill_session_lock(orchestration_state)

    locked = locked_skill_for_expert(orchestration_state, expert_agent_name=agent_name, expert_skills=skill_directories)
    if locked:
        content = skills_loader.get_skill_full_content(locked)
        if content:
            return locked, content, {"strategy": "locked_skill_session", "selected_skill": locked}

    loaded_skills = [sid for sid in skill_directories if skills_loader.get_skill_full_content(sid)]
    if not loaded_skills:
        return "", "", {
            "strategy": "expert_skill_catalog_empty",
            "blocking_error": "expert_skill_content_missing",
            "strict_llm_required": True,
            "candidate_skills": skill_directories,
        }

    if len(loaded_skills) == 1:
        only_sid = loaded_skills[0]
        content = skills_loader.get_skill_full_content(only_sid)
        if content:
            return only_sid, content, {"strategy": "single_loaded_skill", "selected_skill": only_sid}
        return "", "", {
            "strategy": "single_loaded_skill_missing_content",
            "blocking_error": "expert_skill_content_missing",
            "strict_llm_required": True,
            "candidate_skills": loaded_skills,
        }

    llm = llm_resolver(agent_profile)
    picked, debug = await expert_llm_pick_skill(
        llm,
        skills_loader,
        loaded_skills,
        discussion_goal,
        messages,
        round_user_text,
        group_session_id=group_session_id,
        agent_name=agent_name,
        llm_name=str(agent_profile.get("llm_name") or app_settings.get("default_llm") or ""),
    )
    if picked:
        content = skills_loader.get_skill_full_content(picked)
        if content:
            debug["selected_skill"] = picked
            return picked, content, debug

    debug["strict_llm_required"] = True
    debug["blocking_error"] = "expert_skill_pick_llm_failed"
    return "", "", debug


async def build_expert_turn_runtime(
    *,
    agent_profile: Dict[str, Any],
    agent_name: str,
    group_session_id: str,
    discussion_goal: str,
    messages: List[Dict[str, Any]],
    session_item: Dict[str, Any],
    orchestration_state: Optional[Dict[str, Any]] = None,
    app_settings: Dict[str, Any],
    round_user_text: str,
    extra_system_prompt: str,
    skills_loader: Any,
    llm_resolver: LlmResolver,
    tool_builder: ToolBuilder = build_tools_for_group_chat,
    agent_factory: AgentFactory = create_skill_execution_agent,
) -> ExpertTurnRuntime:
    """Build the executable expert turn runtime."""
    skill, base_skill_content, route_debug = await resolve_expert_skill(
        agent_profile=agent_profile,
        agent_name=agent_name,
        discussion_goal=discussion_goal,
        messages=messages,
        session_item=session_item,
        orchestration_state=orchestration_state,
        app_settings=app_settings,
        round_user_text=round_user_text,
        skills_loader=skills_loader,
        llm_resolver=llm_resolver,
        group_session_id=group_session_id,
    )
    runtime = ExpertTurnRuntime(
        agent_name=agent_name,
        agent_profile=agent_profile,
        skill=skill,
        skill_content=base_skill_content,
        skill_route_diagnostics=route_debug,
    )
    if not skill or not base_skill_content:
        return runtime

    tools = await tool_builder(agent_profile, group_session_id, skill)
    skill_content = base_skill_content
    agent_system = (agent_profile.get("system_prompt") or "").strip()
    description = agent_profile.get("description") or ""
    if agent_system:
        skill_content = f"{agent_system}\n\n{skill_content}"
    if description:
        skill_content = f"你的职责：{description}\n\n{skill_content}"
    skill_content += GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION

    llm = llm_resolver(agent_profile)
    expert_self_awareness = build_expert_self_awareness_block(agent_profile, skills_loader)
    agent = agent_factory(
        llm,
        tools,
        skill_content,
        extra_system_prompt,
        expert_self_awareness=expert_self_awareness,
    )
    runtime.skill_content = skill_content
    runtime.tools = tools
    runtime.llm = llm
    runtime.agent = agent
    return runtime
