"""Host decision runtime helpers for group chat."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, AIMessage  # type: ignore

from app.agent.group_chat_expert_resolution import (
    _get_llm_for_agent,
    _llm_credential_notice_for_agent,
    _pick_resolved_host_skill_id,
    _resolve_llm_provider_for_agent,
)
from app.agent.group_host_decision import (
    extract_candidate_agent_ids_from_text as _extract_candidate_agent_ids_from_text,
    extract_host_scheduler_state as _extract_host_scheduler_state,
    heuristic_recommend_agents as _heuristic_recommend_agents,
    host_decision_from_scheduler_state as _host_decision_from_scheduler_state,
    parse_host_response as _parse_host_response,
)
from app.agent.llm_client import build_llm_credential_notice, is_llm_credential_error_message
from app.agent.group_chat_host_messages import HOST_ZERO_EXPERT_RECOMMENDATION
from app.agent.skill_agent_runtime import create_skill_execution_agent
from app.api.settings_app import load_app_settings, normalize_host_profile
from app.core.scene_host import VIRTUAL_SCENE_HOST_ID
from app.core.security import get_current_user
from app.skills.loader import get_skills_loader_for_user

logger = logging.getLogger(__name__)


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
    """Log LLM request/response details without writing workspace artifacts."""

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


def _request_skills_loader():
    u = get_current_user()
    return get_skills_loader_for_user(u.username, u.ctx.skills_dir)


_HOST_DEFAULT_DUTY = (
    "你是群聊主持人，负责在当前群内专家之间做调度，输出 current_phase、next_speaker、speaker_task 决策，"
    "平台会根据调度结果生成固定主持话术，你不得代答、复述用户需求或补充说明。"
)

_HOST_SCHEDULER_STATE_INSTRUCTION = """

## 平台调度状态规则

你仍按主持人 Skill 判断下一步调度，你只需要在本轮回复中给出以下结构化结果：

**只输出 JSON（可用 ```json 包裹），不要输出任何面向用户的自然语言。**

```json
{
  "current_phase": "阶段：xxxx",
  "next_speaker": "agent-xxxxxx",
  "speaker_task": "请根据用户目标完成本阶段任务"
}
```

`current_phase` 用于保存当前场景流程阶段；
`next_speaker` 写场景角色id、`"invite"` 、`"user"` 或 `"end"`。
`speaker_task` 平台会把它作为后台任务文本交给下一位发言人执行。
专家发言完成后，平台会先交回主持人调度；这里的 `next_speaker` 是主持人本次调度出的下一步目标，只能是场景内角色id、 `"invite"` 、`"user"` 或 `"end"`。
你必须先判断任务目标是否已经完成：如果上一位专家已经给出明确答案、文件、查询结果或可交付结论，就不要再安排专家做“总结答复”或复述同一结果。
任务已完成且整个会话应结束时：`current_phase` 写 `"end"`，且 `next_speaker` 写 `"end"`。
需要等待用户继续输入时：`next_speaker` 写 `"user"`（平台不会展示主持气泡）。
需要邀请新专家完成任务时：`next_speaker` 写 `"invite"`（平台不会展示主持气泡）。
只有在仍缺关键信息、用户明确要求继续，或存在新的子任务时，才把 `next_speaker` 设为某个专家。
"""


def _persist_host_scheduler_state_meta(meta_item: Optional[Dict[str, Any]], state: Dict[str, str]) -> None:
    if not isinstance(meta_item, dict):
        return
    previous = meta_item.get("scheduler_state")
    previous_state = previous if isinstance(previous, dict) else {}
    clean = {
        "current_phase": str(
            (state or {}).get("current_phase")
            or previous_state.get("current_phase")
            or ""
        ).strip(),
        "next_speaker": str((state or {}).get("next_speaker") or "").strip(),
        "speaker_task": str((state or {}).get("speaker_task") or "").strip(),
    }
    if any(clean.values()):
        meta_item["scheduler_state"] = clean
    else:
        meta_item.pop("scheduler_state", None)
    logger.info(
        "group_chat_scheduler_host_state_saved_to_meta phase_len=%s speaker_len=%s task_len=%s",
        len(clean["current_phase"]),
        len(clean["next_speaker"]),
        len(clean["speaker_task"]),
    )


async def _host_decide_by_agent(
    llm,
    host_agent: Dict[str, Any],
    agent_profiles: List[Dict[str, Any]],
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
    meta_item: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Run the host Agent skill and return a scheduler decision.

    The host must only decide routing; expert content remains owned by experts.
    """
    app_settings = app_settings or load_app_settings()
    hp_norm = normalize_host_profile(app_settings.get("host_profile") or {})
    host_display_name = str(hp_norm.get("display_name") or "四九").strip() or "四九"
    name = host_agent.get("name") or host_agent.get("agent_id", host_display_name)
    role = host_agent.get("role") or "群聊主持人"
    skill_ids = [str(x).strip() for x in (host_agent.get("skill_ids") or []) if str(x).strip()]
    resolved_skill_id = _pick_resolved_host_skill_id(skill_ids) if skill_ids else ""
    skill_content = f"你是 {name}，担任本群主持人。你的角色：{role}。\n\n{_HOST_DEFAULT_DUTY}\n\n{_HOST_SCHEDULER_STATE_INSTRUCTION.strip()}"
    host_system = (host_agent.get("system_prompt") or "").strip()
    if host_system:
        skill_content = f"{host_system}\n\n{skill_content}"

    agent_lines = []
    for d in agent_profiles:
        r = d.get("role") or "参与者"
        n = d.get("name") or d.get("agent_id", "")
        did = d.get("agent_id", "")
        agent_lines.append(f"- {n} ({did}): {r}")
    agent_text = "\n".join(agent_lines)
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
    can_show_invitable = (not scene_mode) and (not agent_profiles) and (not orphan_ids)
    mode_line = (
        "【模式】场景协作（名单固定，不建议补人）。\n\n"
        if scene_mode
        else (
            "【模式】新建会话（当前无人，可建议用户邀请专家）。\n\n"
            if can_show_invitable
            else "【模式】新建会话（当前已有参与者，先在场内调度）。\n\n"
        )
    )
    extra_policy = f"【可邀请专家列表】\n{available_text}\n\n" if can_show_invitable else ""

    user_content = (
        orphan_block
        + mode_line
        + f"【当前群聊参与者（next_speaker 写 agent_id）】\n{agent_text or '（暂无：请检查场景是否已选择协作专家，或专家是否已从库中删除）'}\n\n"
        f"【任务目标】\n{discussion_goal}\n\n"
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
    scheduler_state_meta = meta_item.get("scheduler_state") if isinstance(meta_item, dict) else None
    if scene_mode and isinstance(scheduler_state_meta, dict):
        phase = str(scheduler_state_meta.get("current_phase") or "").strip()
        speaker = str(scheduler_state_meta.get("next_speaker") or "").strip()
        task = str(scheduler_state_meta.get("speaker_task") or "").strip()
        if any((phase, speaker, task)):
            user_content += (
                "【后台调度状态】\n"
                f"current_phase: {phase or '（空）'}\n"
                f"next_speaker: {speaker or '（空）'}\n"
                f"speaker_task: {task or '（空）'}\n\n"
            )

    try:
        agent = create_skill_execution_agent(
            llm,
            [],
            skill_content,
            extra_system_prompt or "",
            synthesize_after_tools=False,
        )
        initial_state = {"messages": [HumanMessage(content=user_content)], "tools": []}
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
                "agent_id": str(host_agent.get("agent_id") or VIRTUAL_SCENE_HOST_ID),
                "skill_id": resolved_skill_id,
                "llm_provider_id": str(host_agent.get("llm_provider_id") or app_settings.get("default_llm") or ""),
                "model": str(getattr(llm, "model", "") or ""),
            },
        )
        scheduler_state = _extract_host_scheduler_state(content_str) if scene_mode else {}
        if scene_mode and any((scheduler_state.get("current_phase"), scheduler_state.get("next_speaker"), scheduler_state.get("speaker_task"))):
            _persist_host_scheduler_state_meta(meta_item, scheduler_state)
            state_decision = _host_decision_from_scheduler_state(scheduler_state, agent_profiles)
            if state_decision:
                logger.info(
                    "group_chat_scheduler_host_state_decision session=%s next_speaker=%s",
                    group_session_id,
                    state_decision.get("next_speaker"),
                )
                return state_decision
        parsed = _parse_host_response(content_str)
        if parsed:
            return parsed
        return None
    except Exception as e:
        err_text = str(e)
        if is_llm_credential_error_message(err_text):
            notice = _llm_credential_notice_for_agent(host_agent, app_settings)
            if not notice:
                provider_id, cfg = _resolve_llm_provider_for_agent(host_agent, app_settings)
                notice = build_llm_credential_notice(provider_id, cfg)
            return {
                "next_speaker": "user",
                "announcement": notice,
                "reason": "llm_credential_error",
                "interrupt_reason": "tool_unavailable",
            }
        logger.warning("主持人 Agent 调用失败，将回退到默认调度: %s", e)
        return None


async def _host_only_respond_and_recommend(
    discussion_goal: str,
    recent_messages: str,
    all_instances: List[Dict[str, Any]],
    extra_system_prompt: str,
    group_session_id: str = "",
) -> tuple[str, Optional[List[str]]]:
    """Respond as host when a group has no experts and recommend additions."""
    sl = _request_skills_loader()
    app_settings = load_app_settings()
    hp_norm = normalize_host_profile(app_settings.get("host_profile") or {})
    host_display_name = str(hp_norm.get("display_name") or "四九").strip() or "四九"
    host_system_prompt = str(hp_norm.get("system_prompt") or "").strip()
    host_skill_ids = [str(x).strip() for x in (hp_norm.get("skill_ids") or []) if str(x).strip()]
    skill_content = ""
    sid0 = ""
    if host_skill_ids:
        sid0 = _pick_resolved_host_skill_id(host_skill_ids)
        skill_content = str(sl.get_skill_full_content(sid0) or "") if sid0 else ""
    if not skill_content:
        skill_content = "你是群聊主持人，负责协调讨论并适时推荐合适的专家加入。"
    host_intro = f"你是 {host_display_name}，担任本群主持人。"
    system_content = ("\n\n".join([x for x in (host_system_prompt, host_intro, str(skill_content or "")) if str(x).strip()])).strip()
    agent_lines = []
    for d in all_instances:
        did = d.get("agent_id", "")
        name = d.get("name") or did
        role = d.get("role") or "参与者"
        agent_lines.append(f"- {name} ({did}): {role}")
    agent_text = "\n".join(agent_lines) if agent_lines else "（暂无可选专家）"
    notice = _llm_credential_notice_for_agent(None, app_settings)
    if notice:
        return notice, None
    llm = _get_llm_for_agent(None, app_settings)
    user_content = (
        f"【讨论目标/用户消息】\n{discussion_goal}\n\n"
        f"【最近对话】\n{recent_messages}\n\n"
        f"【可选专家列表】\n{agent_text}\n\n"
        "【建议策略】\n"
        "- 优先推荐 1~3 位最相关专家（按优先级排序）；\n"
        "- 只输出 JSON，包含 suggested_add_agent_ids；\n"
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
            fallback_ids = _heuristic_recommend_agents(discussion_goal, all_instances, max_n=3)
            return HOST_ZERO_EXPERT_RECOMMENDATION, fallback_ids or None
        text = content_str.strip()
        announcement = text
        suggested_add_agent_ids: Optional[List[str]] = None
        valid_ids = {d.get("agent_id") for d in all_instances if d.get("agent_id")}
        for sep in ("\n{", "{"):
            if sep in text:
                idx = text.find(sep) if sep == "{" else text.find(sep) + 1
                announcement = text[:idx].strip()
                for fence in ("```json", "```"):
                    if announcement.endswith(fence):
                        announcement = announcement[: -len(fence)].rstrip()
                json_str = text[idx:].strip()
                try:
                    data = json.loads(json_str)
                    ids_raw = data.get("suggested_add_agent_ids")
                    if isinstance(ids_raw, list) and ids_raw:
                        cleaned = [str(x).strip() for x in ids_raw if str(x).strip() in valid_ids]
                        if cleaned:
                            suggested_add_agent_ids = list(dict.fromkeys(cleaned))[:3]
                    if not suggested_add_agent_ids:
                        sid = (data.get("suggested_add_agent_id") or "").strip()
                        if sid and sid in valid_ids:
                            suggested_add_agent_ids = [sid]
                except Exception:
                    pass
                break
        if not suggested_add_agent_ids and valid_ids:
            found = _extract_candidate_agent_ids_from_text(text, all_instances, max_n=3)
            suggested_add_agent_ids = [x for x in found if x in valid_ids][:3]
        return HOST_ZERO_EXPERT_RECOMMENDATION, suggested_add_agent_ids
    except Exception as e:
        err_text = str(e)
        if is_llm_credential_error_message(err_text):
            provider_id, cfg = _resolve_llm_provider_for_agent(None, app_settings)
            return build_llm_credential_notice(provider_id, cfg), None
        logger.warning("主持人 0 成员推荐调用失败: %s", e)
        fallback_ids = _heuristic_recommend_agents(discussion_goal, all_instances, max_n=3)
        return HOST_ZERO_EXPERT_RECOMMENDATION, fallback_ids or None
