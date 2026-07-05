"""Host decision runtime helpers for group chat."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agent.messages import HumanMessage, AIMessage  # type: ignore

from app.agent.group_chat_expert_resolution import (
    _get_llm_for_agent,
    _llm_credential_notice_for_agent,
    _pick_resolved_host_skill,
    _resolve_llm_config_for_agent,
)
from app.agent.group_host_decision import (
    extract_candidate_agent_names_from_text as _extract_candidate_agent_names_from_text,
    heuristic_recommend_agents as _heuristic_recommend_agents,
    parse_strict_host_scheduler_output as _parse_strict_host_scheduler_output,
)
from app.agent.llm_client import (
    build_llm_credential_notice,
    is_llm_credential_error_message,
    should_log_full_prompts,
)
from app.agent.group_chat_host_messages import HOST_ZERO_EXPERT_RECOMMENDATION
from app.agent.skill_agent_runtime import create_skill_execution_agent
from app.api.settings_app import load_app_settings, normalize_host_profile
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

    if should_log_full_prompts():
        logger.info(
            "[Prompt][LLM_ROUNDTRIP][%s] mode=full system_prompt:\n%s\n\n[Prompt][LLM_ROUNDTRIP][%s] user_prompt:\n%s\n\n[LLM_ROUNDTRIP][%s] model_output:\n%s",
            tag,
            _clip(system_content),
            tag,
            _clip(user_content),
            tag,
            _clip(model_output),
        )
        return
    logger.info(
        "[Prompt][LLM_ROUNDTRIP][%s] mode=summary session=%s system_chars=%s user_chars=%s output_chars=%s",
        tag,
        session_id,
        len(str(system_content or "")),
        len(str(user_content or "")),
        len(str(model_output or "")),
    )


def _request_skills_loader():
    u = get_current_user()
    return get_skills_loader_for_user(u.username, u.ctx.skills_dir)


def _load_host_skill_content(skills_loader: Any, skill: str) -> str:
    if not skill:
        return ""
    return str(skills_loader.get_skill_full_content(skill) or "").strip()


_HOST_DEFAULT_DUTY = (
    "你是群聊主持人，负责在当前群内专家之间做调度，输出 current_phase、next_speaker、speaker_task 决策，"
    "平台会根据调度结果生成固定主持话术，你不得代答、复述用户需求或补充说明。"
)

_HOST_SCHEDULER_STATE_INSTRUCTION = """

## 平台调度状态规则

你仍按主持人 Skill 判断下一步调度，你只需要在本轮回复中给出以下结构化结果：

**只输出一个 JSON 对象**，可以使用单个 ```json 代码块包裹；代码块外不得有任何文字。

```json
{
  "current_phase": "阶段：xxxx",
  "next_speaker": "专家名称",
  "speaker_task": "请根据用户目标完成本阶段任务",
  "reason": "简短调度原因"
}
```

`current_phase` 用于保存当前场景流程阶段；
`next_speaker` 写场景内 Agent 名称、`"invite"` 、`"user"` 或 `"end"`。
`speaker_task` 平台会把它作为后台任务文本交给下一位发言人执行。
字段只允许 `current_phase`、`next_speaker`、`speaker_task`、`reason`、`suggested_add_agent_names`；不要输出 `task_done`、`next_prompt`、`current_phase.txt`、`next_speaker.txt`、`speaker_task.txt`。
专家发言完成后，平台会先交回主持人调度；这里的 `next_speaker` 是主持人本次调度出的下一步目标，只能是场景内 Agent 名称、 `"invite"` 、`"user"` 或 `"end"`。
你必须先判断任务目标是否已经完成：如果上一位专家已经给出明确答案、文件、查询结果或可交付结论，就不要再安排专家做“总结答复”或复述同一结果。
任务已完成且整个会话应结束时：`current_phase` 写 `"end"`，且 `next_speaker` 写 `"end"`。
需要等待用户继续输入时：`next_speaker` 写 `"user"`（平台不会展示主持气泡）。
需要邀请新专家完成任务时：`next_speaker` 写 `"invite"`（平台不会展示主持气泡）。
只有在仍缺关键信息、用户明确要求继续，或存在新的子任务时，才把 `next_speaker` 设为某个专家。
"""


def _persist_host_scheduler_state(session_item: Optional[Dict[str, Any]], state: Dict[str, str]) -> None:
    if not isinstance(session_item, dict):
        return
    previous = session_item.get("scheduler_state")
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
        session_item["scheduler_state"] = clean
    else:
        session_item.pop("scheduler_state", None)
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
    last_speaker_agent_name: Optional[str],
    extra_system_prompt: str,
    available_to_add: Optional[List[Dict[str, Any]]] = None,
    *,
    group_session_id: str = "",
    messages: Optional[List[Dict[str, Any]]] = None,
    app_settings: Optional[Dict[str, Any]] = None,
    pending_owner_agent_name: str = "",
    pending_skill: str = "",
    user_message: str = "",
    orphan_session_agent_names: Optional[List[str]] = None,
    orchestration_profile: str = "recruitment",
    session_item: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Run the host Agent skill and return a scheduler decision.

    The host must only decide routing; expert content remains owned by experts.
    """
    app_settings = app_settings or load_app_settings()
    hp_norm = normalize_host_profile(app_settings.get("host_profile") or {})
    host_display_name = str(hp_norm.get("leader_agent_name") or "四九").strip() or "四九"
    name = host_agent.get("name") or host_display_name
    description = host_agent.get("description") or "群聊主持人"
    skill_directories = [
        str(x.get("directory_name") or "").strip()
        for x in (host_agent.get("skills") or [])
        if isinstance(x, dict) and str(x.get("directory_name") or "").strip()
    ]
    resolved_skill = _pick_resolved_host_skill(skill_directories) if skill_directories else ""
    host_skill_content = ""
    if resolved_skill:
        host_skill_content = _load_host_skill_content(_request_skills_loader(), resolved_skill)
    skill_sections = [
        f"你是 {name}，担任本群主持人。你的职责：{description}。",
        host_skill_content,
        _HOST_DEFAULT_DUTY,
        _HOST_SCHEDULER_STATE_INSTRUCTION.strip(),
    ]
    skill_content = "\n\n".join(section for section in skill_sections if section)
    host_system = (host_agent.get("system_prompt") or "").strip()
    if host_system:
        skill_content = f"{host_system}\n\n{skill_content}"

    agent_lines = []
    for d in agent_profiles:
        r = d.get("description") or "参与者"
        n = str(d.get("name") or "").strip()
        if n:
            agent_lines.append(f"- {n}: {r}")
    agent_text = "\n".join(agent_lines)
    orphan_names = [str(x).strip() for x in (orphan_session_agent_names or []) if str(x).strip()]
    orphan_block = ""
    if orphan_names:
        orphan_block = (
            "【重要】会话定义里记录了以下协作专家名称，但在当前账号专家库中已不存在（可能已删除或从未同步），"
            "这些名称 **不能**作为 next_speaker："
            + ", ".join(orphan_names)
            + "。请提示用户到「资源中心 → 场景」重新选择协作专家。"
            "若仍有其他参与者在上方列表中，应优先安排他们，**不要**仅因上述失效名称就建议邀请新人。\n\n"
        )

    add_lines = []
    for d in (available_to_add or []):
        n = str(d.get("name") or "").strip()
        if not n:
            continue
        r = d.get("description") or "参与者"
        add_lines.append(f"- {n}: {r}")
    available_text = "\n".join(add_lines) if add_lines else "（暂无可邀请专家）"
    scene_mode = str(orchestration_profile or "").strip().lower() == "scene"
    can_show_invitable = (not scene_mode) and (not agent_profiles) and (not orphan_names)
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
        + f"【当前群聊参与者（next_speaker 写 Agent 名称）】\n{agent_text or '（暂无：请检查场景是否已选择协作专家，或专家是否已从库中删除）'}\n\n"
        f"【任务目标】\n{discussion_goal}\n\n"
        "【主持人决策上下文（对话与发言摘录）】\n"
        f"{recent_messages}\n\n"
        + extra_policy
    )
    if (user_message or "").strip():
        user_content += f"【本轮用户输入】\n{user_message.strip()}\n\n"
    if pending_owner_agent_name:
        user_content += (
            f"【待续跑状态】上一轮等待用户补充时锁定的专家 pending_owner_agent_name={pending_owner_agent_name}"
            + (f"，pending_skill={pending_skill}" if pending_skill else "")
            + "。你可决定仍由该专家继续或改派他人。\n\n"
        )
    if last_speaker_agent_name:
        user_content += f"【刚发言的专家】{last_speaker_agent_name}\n\n"
    else:
        user_content += "【当前为首轮】尚无上一位专家发言。\n\n"
    scheduler_state_snapshot = session_item.get("scheduler_state") if isinstance(session_item, dict) else None
    if scene_mode and isinstance(scheduler_state_snapshot, dict):
        phase = str(scheduler_state_snapshot.get("current_phase") or "").strip()
        speaker = str(scheduler_state_snapshot.get("next_speaker") or "").strip()
        task = str(scheduler_state_snapshot.get("speaker_task") or "").strip()
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
                "agent_name": str(host_agent.get("name") or host_display_name),
                "skill": resolved_skill,
                "llm_name": str(host_agent.get("llm_name") or app_settings.get("default_llm") or ""),
                "model": str(getattr(llm, "model", "") or ""),
            },
        )
        parsed = _parse_strict_host_scheduler_output(
            content_str,
            agent_profiles,
            orchestration_profile=orchestration_profile,
        )
        if parsed.get("interrupt_reason") == "protocol_error":
            logger.warning(
                "group_chat_scheduler_host_protocol_error session=%s agent=%s model_output=%r reason=%s",
                group_session_id,
                str(host_agent.get("name") or host_display_name),
                content_str[:1000],
                parsed.get("reason"),
            )
            return parsed
        scheduler_state = {
            "current_phase": str(parsed.get("current_phase") or "").strip(),
            "next_speaker": str(parsed.get("next_speaker") or "").strip(),
            "speaker_task": str(parsed.get("speaker_task") or "").strip(),
        }
        if any(scheduler_state.values()):
            _persist_host_scheduler_state(session_item, scheduler_state)
        logger.info(
            "group_chat_scheduler_host_state_decision session=%s next_speaker=%s",
            group_session_id,
            parsed.get("next_speaker"),
        )
        return parsed
    except Exception as e:
        err_text = str(e)
        if is_llm_credential_error_message(err_text):
            notice = _llm_credential_notice_for_agent(host_agent, app_settings)
            if not notice:
                llm_name, cfg = _resolve_llm_config_for_agent(host_agent, app_settings)
                notice = build_llm_credential_notice(llm_name, cfg)
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
    host_display_name = str(hp_norm.get("leader_agent_name") or "四九").strip() or "四九"
    host_system_prompt = str(hp_norm.get("system_prompt") or "").strip()
    host_skill_directory = str(hp_norm.get("skill_directory") or "").strip()
    skill_content = ""
    sid0 = ""
    if host_skill_directory:
        sid0 = _pick_resolved_host_skill([host_skill_directory])
        skill_content = str(sl.get_skill_full_content(sid0) or "") if sid0 else ""
    if not skill_content:
        skill_content = "你是群聊主持人，负责协调讨论并适时推荐合适的专家加入。"
    host_intro = f"你是 {host_display_name}，担任本群主持人。"
    system_content = ("\n\n".join([x for x in (host_system_prompt, host_intro, str(skill_content or "")) if str(x).strip()])).strip()
    agent_lines = []
    for d in all_instances:
        name = str(d.get("name") or "").strip()
        if not name:
            continue
        description = d.get("description") or "参与者"
        agent_lines.append(f"- {name}: {description}")
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
        "- 只输出 JSON，包含 suggested_add_agent_names；\n"
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
                "agent_name": host_display_name,
                "skill": sid0,
                "llm_name": str(app_settings.get("default_llm") or ""),
                "model": str(getattr(llm, "model", "") or ""),
            },
        )
        if not content_str or not content_str.strip():
            fallback_ids = _heuristic_recommend_agents(discussion_goal, all_instances, max_n=3)
            return HOST_ZERO_EXPERT_RECOMMENDATION, fallback_ids or None
        text = content_str.strip()
        announcement = text
        suggested_add_agent_names: Optional[List[str]] = None
        valid_names = {str(d.get("name") or "").strip() for d in all_instances if str(d.get("name") or "").strip()}
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
                    names_raw = data.get("suggested_add_agent_names")
                    if isinstance(names_raw, list) and names_raw:
                        cleaned = [str(x).strip() for x in names_raw if str(x).strip() in valid_names]
                        if cleaned:
                            suggested_add_agent_names = list(dict.fromkeys(cleaned))[:3]
                    if not suggested_add_agent_names:
                        name = (data.get("suggested_add_agent_name") or "").strip()
                        if name and name in valid_names:
                            suggested_add_agent_names = [name]
                except Exception:
                    pass
                break
        if not suggested_add_agent_names and valid_names:
            found = _extract_candidate_agent_names_from_text(text, all_instances, max_n=3)
            suggested_add_agent_names = [x for x in found if x in valid_names][:3]
        return HOST_ZERO_EXPERT_RECOMMENDATION, suggested_add_agent_names
    except Exception as e:
        err_text = str(e)
        if is_llm_credential_error_message(err_text):
            llm_name, cfg = _resolve_llm_config_for_agent(None, app_settings)
            return build_llm_credential_notice(llm_name, cfg), None
        logger.warning("主持人 0 成员推荐调用失败: %s", e)
        fallback_ids = _heuristic_recommend_agents(discussion_goal, all_instances, max_n=3)
        return HOST_ZERO_EXPERT_RECOMMENDATION, fallback_ids or None
