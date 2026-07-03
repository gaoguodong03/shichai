"""领导人专家调度：决定 current_phase、next_speaker 与 speaker_task。"""
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage

from app.agent.orchestrator_state import (
    DecisionSource,
    InterruptReason,
    OrchestrationDecision,
    OrchestrationPhase,
)
from app.agent.group_host_decision import (
    HOST_PROTOCOL_ERROR_MESSAGE,
    parse_strict_host_scheduler_output,
)
from app.agent.llm_client import should_log_full_prompts

logger = logging.getLogger(__name__)


def _build_leader_prompt(
    agent_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    available_to_add: Optional[List[Dict[str, Any]]] = None,
    *,
    allow_recruitment: bool = True,
) -> str:
    """构建领导人调度的最小提示词。"""
    can_recruit = allow_recruitment and not agent_list
    agent_lines = []
    for d in agent_list:
        description = d.get("description") or "参与者"
        name = str(d.get("name") or "").strip()
        if not name:
            continue
        agent_lines.append(f"- {name}: {description}")
    agent_text = "\n".join(agent_lines)

    add_section = ""
    if can_recruit and available_to_add:
        add_lines = [f"- {d.get('name') or ''}: {d.get('description') or '专家'}" for d in available_to_add[:30] if str(d.get("name") or "").strip()]
        add_section = f"""
## 可邀请的新成员（当前不在群内）
若**当前参与者无法完成工作**（例如缺少某类专家、需要专业能力不在现有成员中），你可以建议用户邀请新成员。可邀请的专家列表：
{chr(10).join(add_lines)}

        此时请在 JSON 中同时输出 **suggested_add_agent_names**：要邀请的 Agent 名称数组（从上面列表中选），并设 **next_speaker="user"**，由用户确认后添加成员再继续。格式示例：{{"current_phase": "招募确认", "next_speaker": "user", "speaker_task": "建议邀请图片生成专家参与，请用户确认是否添加。", "reason": "当前缺少图片生成能力", "suggested_add_agent_names": ["图片生成专家"]}}
"""

    recruit_rule = ""
    if can_recruit:
        recruit_rule = (
            '- **当前没有参与者时**：若需要专家协作，'
            '可输出 suggested_add_agent_names（从「可邀请的新成员」中选 Agent 名称），并设 next_speaker 为 "user"，让用户邀请新成员后再继续。\n'
        )
    elif allow_recruitment:
        recruit_rule = "- **当前已有参与者**：不要输出 suggested_add_agent_names，先在场内专家之间调度；若已完成或需用户补充，next_speaker=\"user\"。\n"
    scene_extra = ""
    if not allow_recruitment:
        scene_extra = "- **本场参与者名单已固定**：不要输出 suggested_add_agent_names；若缺能力，请 next_speaker=\"user\" 请用户调整场景或换话题。\n"

    recruit_output = ""
    if can_recruit:
        recruit_output = "- 建议邀请新成员时：输出 suggested_add_agent_names，next_speaker=\"user\"。\n"
    else:
        recruit_output = "- 不要输出 suggested_add_agent_names。\n"

    return f"""你是群聊主持人，只做调度，不代写专家正文，也不要为专家指定 Skill。
你必须只输出一个 JSON 对象，可以使用单个 ```json 代码块包裹；代码块外不得有任何文字。
字段只允许 current_phase、next_speaker、speaker_task、reason、suggested_add_agent_names。
不要输出 task_done、next_prompt、current_phase.txt、next_speaker.txt、speaker_task.txt 或其他字段。
当 next_speaker 是某专家时，speaker_task 必须是对方可直接执行的任务说明；next_speaker 只能是在场 Agent 名称或 \"user\" 或 \"end\"。

## 参与者
{agent_text}
{add_section}

## 任务目标
{discussion_goal}

## 最近上下文（摘要）
以下内容为对话与发言摘录，合起来视为唯一上下文。

## 本轮约束（与上文契约一致）
- next_speaker：在场 Agent 名称 | \"user\" | \"end\"。
- 点专家时须给出可执行的 speaker_task。
- 先判断任务目标是否已经完成：如果上一位专家已经给出明确答案、文件、查询结果或可交付结论，next_speaker 应为 \"user\" 或 \"end\"，不要再安排专家做“总结答复”或复述同一结果。
- 只有在仍缺关键信息、用户明确要求继续，或存在新的子任务时，才把 next_speaker 设为某个专家。
{recruit_rule}{scene_extra}
{recruit_output}
**本路径要求：仅输出严格 JSON**（必须包含 current_phase、next_speaker、speaker_task；可含 reason、suggested_add_agent_names）。"""


async def leader_decide(
    llm,
    agent_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    last_speaker_agent_name: Optional[str] = None,
    available_to_add: Optional[List[Dict[str, Any]]] = None,
    *,
    orchestration_profile: str = "recruitment",
    group_session_id: str = "",
    workspace_root: Optional[Path] = None,
    llm_name: str = "",
) -> Dict[str, Any]:
    """
    调用领导人 LLM 决定：current_phase、next_speaker、speaker_task。
    """
    allow_rec = orchestration_profile != "scene"
    system_prompt = _build_leader_prompt(
        agent_list,
        discussion_goal,
        recent_messages,
        available_to_add if allow_rec else [],
        allow_recruitment=allow_rec,
    )
    user_content = f"最近上下文：\n\n{recent_messages}\n\n"
    if last_speaker_agent_name:
        user_content += f"刚发言的专家：{last_speaker_agent_name}\n\n请判断该专家是否完成任务，并指定下一发言人。"
    else:
        user_content += "请指定第一个发言人，并给出 current_phase、next_speaker、speaker_task。"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ]
    if should_log_full_prompts():
        logger.info(
            "[Prompt][LLM_ROUNDTRIP][leader_decide] mode=full system_prompt:\n%s\n\n[Prompt][LLM_ROUNDTRIP][leader_decide] user_prompt:\n%s",
            system_prompt,
            user_content,
        )
    else:
        logger.info(
            "[Prompt][LLM_ROUNDTRIP][leader_decide] mode=summary session=%s system_chars=%s user_chars=%s",
            group_session_id,
            len(system_prompt),
            len(user_content),
        )

    try:
        client = llm.get_client()
        response = await asyncio.wait_for(client.ainvoke(messages), timeout=30.0)
        content = (response.content or "").strip()
        if should_log_full_prompts():
            logger.info("[LLM_ROUNDTRIP][leader_decide] mode=full model_output:\n%s", content)
        else:
            logger.info(
                "[LLM_ROUNDTRIP][leader_decide] mode=summary session=%s output_chars=%s",
                group_session_id,
                len(content),
            )

        decision = parse_strict_host_scheduler_output(
            content,
            agent_list,
            orchestration_profile=orchestration_profile,
        )
        if decision.get("interrupt_reason") == InterruptReason.PROTOCOL_ERROR.value:
            logger.warning(
                "leader_scheduler_protocol_error session=%s llm_name=%s output=%r reason=%s",
                group_session_id,
                llm_name,
                content[:1000],
                decision.get("reason"),
            )
        return decision
    except Exception as e:
        logger.warning(f"领导人调度解析失败: {e}，固定交还 user（由下轮主持人重试）")
        decision = OrchestrationDecision(
            task_done=True,
            next_speaker="user",
            reason=f"解析失败: {e}",
            announcement=HOST_PROTOCOL_ERROR_MESSAGE,
            next_prompt=None,
            phase=OrchestrationPhase.AWAITING_USER,
            owner_agent_name=None,
            interrupt_reason=InterruptReason.PROTOCOL_ERROR,
            decision_source=DecisionSource.SYSTEM_GUARD,
            handoff_reason="leader_parse_failed",
        )
        return decision.to_dict()
