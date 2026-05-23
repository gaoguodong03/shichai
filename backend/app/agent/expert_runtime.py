"""Expert runtime entrypoint.

An expert is stored as a DHA/profile dict, but this module gives one expert
turn a clear build path: resolve Skill -> build tools -> create executable agent.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage  # type: ignore

from app.agent.expert_self_awareness import build_expert_self_awareness_block
from app.agent.group_memory_store import append_llm_roundtrip
from app.agent.skill_agent_runtime import create_skill_execution_agent
from app.agent.group_orchestration_fsm import clear_skill_session_lock, locked_skill_id_for_expert
from app.agent.skill_session_contract import GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
from app.agent.tools_for_skill import build_tools_for_group_chat

logger = logging.getLogger(__name__)

LlmResolver = Callable[[Optional[Dict[str, Any]]], Any]
ToolBuilder = Callable[[Dict[str, Any], str, Optional[str]], Awaitable[List[Any]]]
AgentFactory = Callable[..., Any]


@dataclass
class ExpertTurnRuntime:
    """Callable-ish runtime bundle for a single expert turn."""

    agent_id: str
    dha: Dict[str, Any]
    skill_id: str = ""
    skill_content: str = ""
    skill_route_debug: Dict[str, Any] = field(default_factory=dict)
    tools: List[Any] = field(default_factory=list)
    llm: Any = None
    agent: Any = None

    @property
    def blocked(self) -> bool:
        return not self.skill_id or not self.skill_content or self.agent is None


def _last_user_message_text(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            return str(m.get("content") or "").strip()
    return ""


def _extract_json_object_from_llm_text(text: str) -> Optional[Dict[str, Any]]:
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    for opener in ("```json", "```"):
        if opener in s:
            try:
                inner = s.split(opener, 1)[1].split("```", 1)[0].strip()
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


async def expert_llm_pick_skill_id(
    llm: Any,
    skills_loader: Any,
    skill_ids: List[str],
    discussion_goal: str,
    messages: List[Dict[str, Any]],
    round_user_text: str,
    *,
    group_session_id: str = "",
    agent_id: str = "",
    llm_provider_id: str = "",
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Ask the expert model to choose exactly one loaded Skill."""
    debug: Dict[str, Any] = {"strategy": "expert_llm_pick", "scores": []}
    lines: List[str] = []
    for sid in skill_ids:
        sk = getattr(skills_loader, "skills", {}).get(sid)
        if sk:
            desc = (sk.description or "")[:800]
            nm = sk.name or sid
            lines.append(f'- skill_id="{sid}" | name="{nm}" | description="{desc}"')
        else:
            lines.append(f'- skill_id="{sid}" | （未加载元数据，仍须从 id 中选择）')
    catalog = "\n".join(lines)
    um = (round_user_text or "").strip() or _last_user_message_text(messages)
    sys_msg = (
        "你是专家的任务分发模块。只做一件事：根据讨论目标与本轮用户输入，"
        "从下方候选 Skill 中为该专家**恰好选一个** skill_id。\n"
        "必须只输出一个 JSON 对象，不要输出其他文字：\n"
        '{"selected_skill_id":"<从候选中复制的确切 skill_id>"}\n'
        "选择依据：用户任务与各 Skill 名称、描述的匹配度。"
    )
    human = (
        f"【讨论目标】\n{discussion_goal or '（无）'}\n\n"
        f"【本轮用户输入】\n{um or '（无）'}\n\n"
        f"【候选 Skill】\n{catalog}\n"
    )
    try:
        client = llm.get_client()
        out = await client.ainvoke([SystemMessage(content=sys_msg), HumanMessage(content=human)])
        raw = out.content if hasattr(out, "content") else str(out)
        if isinstance(raw, list):
            raw = "".join(str(x) for x in raw)
        if group_session_id:
            try:
                append_llm_roundtrip(
                    session_id=group_session_id,
                    phase="expert_skill_pick",
                    input_messages=[
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": human},
                    ],
                    output={"content": str(raw)},
                    agent_id=agent_id,
                    llm_provider_id=llm_provider_id,
                    model=str(getattr(llm, "model", "") or ""),
                )
            except Exception as trace_err:
                logger.warning(
                    "写入会话 LLM roundtrip 失败(tag=expert_skill_pick session=%s): %s",
                    group_session_id,
                    trace_err,
                )
        parsed = _extract_json_object_from_llm_text(str(raw))
        if parsed:
            picked = str(parsed.get("selected_skill_id") or "").strip()
            valid = {str(x).strip() for x in skill_ids}
            if picked and picked in valid:
                debug["selected_skill_id"] = picked
                return picked, debug
            debug["strategy"] = "expert_llm_pick_invalid_id"
            debug["invalid_pick"] = picked
        else:
            debug["strategy"] = "expert_llm_pick_parse_fail"
    except Exception as e:
        logger.warning("专家 Skill 选型 LLM 失败，将回退关键词路由: %s", e)
        if group_session_id:
            try:
                append_llm_roundtrip(
                    session_id=group_session_id,
                    phase="expert_skill_pick",
                    input_messages=[
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": human},
                    ],
                    output={},
                    agent_id=agent_id,
                    llm_provider_id=llm_provider_id,
                    model=str(getattr(llm, "model", "") or ""),
                    error={"type": type(e).__name__, "message": str(e)},
                )
            except Exception:
                pass
        debug["strategy"] = "expert_llm_pick_error"
        debug["error"] = str(e)
    return None, debug


async def resolve_expert_skill(
    *,
    dha: Dict[str, Any],
    agent_id: str,
    discussion_goal: str,
    messages: List[Dict[str, Any]],
    meta_item: Dict[str, Any],
    app_settings: Dict[str, Any],
    round_user_text: str,
    skills_loader: Any,
    llm_resolver: LlmResolver,
    ignored_auto_skill_id: Optional[str] = None,
    group_session_id: str = "",
) -> Tuple[str, str, Dict[str, Any]]:
    """Resolve the Skill for one expert turn; locked Skill sessions win."""
    _ = app_settings, ignored_auto_skill_id
    skill_ids = [str(x).strip() for x in (dha.get("skill_ids") or []) if str(x).strip()]

    owner = str(meta_item.get("skill_session_owner_id") or "").strip().lower()
    locked_raw = str(meta_item.get("skill_session_skill_id") or "").strip()
    if owner == str(agent_id or "").strip().lower() and locked_raw and locked_raw not in skill_ids:
        clear_skill_session_lock(meta_item)

    locked = locked_skill_id_for_expert(meta_item, expert_agent_id=agent_id, expert_skill_ids=skill_ids)
    if locked:
        content = skills_loader.get_skill_full_content(locked)
        if content:
            return locked, content, {"strategy": "locked_skill_session", "selected_skill_id": locked}

    loaded_skill_ids = [sid for sid in skill_ids if skills_loader.get_skill_full_content(sid)]
    if not loaded_skill_ids:
        return "", "", {
            "strategy": "expert_skill_catalog_empty",
            "blocking_error": "expert_skill_content_missing",
            "strict_llm_required": True,
            "candidate_skill_ids": skill_ids,
        }

    if len(loaded_skill_ids) == 1:
        only_sid = loaded_skill_ids[0]
        content = skills_loader.get_skill_full_content(only_sid)
        if content:
            return only_sid, content, {"strategy": "single_loaded_skill", "selected_skill_id": only_sid}
        return "", "", {
            "strategy": "single_loaded_skill_missing_content",
            "blocking_error": "expert_skill_content_missing",
            "strict_llm_required": True,
            "candidate_skill_ids": loaded_skill_ids,
        }

    llm = llm_resolver(dha)
    picked, debug = await expert_llm_pick_skill_id(
        llm,
        skills_loader,
        loaded_skill_ids,
        discussion_goal,
        messages,
        round_user_text,
        group_session_id=group_session_id,
        agent_id=agent_id,
        llm_provider_id=str(dha.get("llm_provider_id") or app_settings.get("default_llm") or ""),
    )
    if picked:
        content = skills_loader.get_skill_full_content(picked)
        if content:
            debug["selected_skill_id"] = picked
            return picked, content, debug

    debug["strict_llm_required"] = True
    debug["blocking_error"] = "expert_skill_pick_llm_failed"
    return "", "", debug


async def build_expert_turn_runtime(
    *,
    dha: Dict[str, Any],
    agent_id: str,
    group_session_id: str,
    discussion_goal: str,
    messages: List[Dict[str, Any]],
    meta_item: Dict[str, Any],
    app_settings: Dict[str, Any],
    round_user_text: str,
    extra_system_prompt: str,
    skills_loader: Any,
    llm_resolver: LlmResolver,
    ignored_auto_skill_id: Optional[str] = None,
    tool_builder: ToolBuilder = build_tools_for_group_chat,
    agent_factory: AgentFactory = create_skill_execution_agent,
) -> ExpertTurnRuntime:
    """Build the executable expert turn runtime."""
    skill_id, base_skill_content, route_debug = await resolve_expert_skill(
        dha=dha,
        agent_id=agent_id,
        discussion_goal=discussion_goal,
        messages=messages,
        meta_item=meta_item,
        app_settings=app_settings,
        round_user_text=round_user_text,
        skills_loader=skills_loader,
        llm_resolver=llm_resolver,
        ignored_auto_skill_id=ignored_auto_skill_id,
        group_session_id=group_session_id,
    )
    runtime = ExpertTurnRuntime(
        agent_id=agent_id,
        dha=dha,
        skill_id=skill_id,
        skill_content=base_skill_content,
        skill_route_debug=route_debug,
    )
    if not skill_id or not base_skill_content:
        return runtime

    tools = await tool_builder(dha, group_session_id, skill_id)
    skill_content = base_skill_content
    dha_system = (dha.get("system_prompt") or "").strip()
    role = dha.get("role") or ""
    if dha_system:
        skill_content = f"{dha_system}\n\n{skill_content}"
    if role:
        skill_content = f"你的角色：{role}\n\n{skill_content}"
    skill_content += GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION

    llm = llm_resolver(dha)
    expert_self_awareness = build_expert_self_awareness_block(dha, skills_loader)
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
