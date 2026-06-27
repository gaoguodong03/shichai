"""领导人专家调度：决定 current_phase、next_speaker 与 speaker_task。"""
import asyncio
import json
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
        role = d.get("role") or "参与者"
        name = d.get("name") or d.get("agent_id", "")
        agent_id = d.get("agent_id", "")
        leader_mark = "（主持人）" if d.get("is_leader") else ""
        agent_lines.append(f"- {name} ({agent_id}){leader_mark}: {role}")
    agent_text = "\n".join(agent_lines)

    add_section = ""
    if can_recruit and available_to_add:
        add_lines = [f"- {d.get('name') or d.get('agent_id', '')} ({d.get('agent_id', '')}): {d.get('role') or '专家'}" for d in available_to_add[:30]]
        add_section = f"""
## 可邀请的新成员（当前不在群内）
若**当前参与者无法完成工作**（例如缺少某类专家、需要专业能力不在现有成员中），你可以建议用户邀请新成员。可邀请的专家列表：
{chr(10).join(add_lines)}

此时请在 JSON 中同时输出 **suggested_add_agent_ids**：要邀请的 agent_id 数组（从上面列表中选），并设 **next_speaker="user"**，由用户确认后添加成员再继续。格式示例：{{"current_phase": "招募确认", "next_speaker": "user", "speaker_task": "建议邀请图片生成专家参与，请用户确认是否添加。", "suggested_add_agent_ids": ["agent-440b26f8"]}}
"""

    recruit_rule = ""
    if can_recruit:
        recruit_rule = (
            '- **当前没有参与者时**：若需要专家协作，'
            '可输出 suggested_add_agent_ids（从「可邀请的新成员」中选 agent_id），并设 next_speaker 为 "user"，让用户邀请新成员后再继续。\n'
        )
    elif allow_recruitment:
        recruit_rule = "- **当前已有参与者**：不要输出 suggested_add_agent_ids，先在场内专家之间调度；若已完成或需用户补充，next_speaker=\"user\"。\n"
    scene_extra = ""
    if not allow_recruitment:
        scene_extra = "- **本场参与者名单已固定**：不要输出 suggested_add_agent_ids；若缺能力，请 next_speaker=\"user\" 请用户调整场景或换话题。\n"

    recruit_output = ""
    if can_recruit:
        recruit_output = "- 建议邀请新成员时：输出 suggested_add_agent_ids，next_speaker=\"user\"。\n"
    else:
        recruit_output = "- 不要输出 suggested_add_agent_ids。\n"

    return f"""你是群聊主持人，只做调度，不代写专家正文，也不要为专家指定 Skill。
你必须输出一段 JSON（可用 ```json 包裹），字段至少包含：current_phase、next_speaker、speaker_task。
当 next_speaker 是某专家时，speaker_task 必须是对方可直接执行的任务说明；next_speaker 只能是在场 agent_id 或 \"user\" 或 \"end\"。

## 参与者
{agent_text}
{add_section}

## 任务目标
{discussion_goal}

## 最近上下文（摘要）
以下内容为对话与发言摘录，合起来视为唯一上下文。

## 本轮约束（与上文契约一致）
- next_speaker：在场 agent_id | \"user\" | \"end\"。
- 点专家时须给出可执行的 speaker_task。
- 先判断任务目标是否已经完成：如果上一位专家已经给出明确答案、文件、查询结果或可交付结论，next_speaker 应为 \"user\" 或 \"end\"，不要再安排专家做“总结答复”或复述同一结果。
- 只有在仍缺关键信息、用户明确要求继续，或存在新的子任务时，才把 next_speaker 设为某个专家。
{recruit_rule}{scene_extra}
{recruit_output}
**本路径要求：仅输出一段 JSON**（必须包含 current_phase、next_speaker、speaker_task；可含 suggested_add_agent_ids）。"""


async def leader_decide(
    llm,
    agent_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    last_speaker_agent_id: Optional[str] = None,
    available_to_add: Optional[List[Dict[str, Any]]] = None,
    *,
    orchestration_profile: str = "recruitment",
    group_session_id: str = "",
    workspace_root: Optional[Path] = None,
    llm_provider_id: str = "",
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
    if last_speaker_agent_id:
        user_content += f"刚发言的专家：{last_speaker_agent_id}\n\n请判断该专家是否完成任务，并指定下一发言人。"
    else:
        user_content += "请指定第一个发言人，并给出 current_phase、next_speaker、speaker_task。"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ]
    logger.info(
        "[Prompt][LLM_ROUNDTRIP][leader_decide] system_prompt:\n%s\n\n[Prompt][LLM_ROUNDTRIP][leader_decide] user_prompt:\n%s",
        system_prompt,
        user_content,
    )

    try:
        client = llm.get_client()
        response = await asyncio.wait_for(client.ainvoke(messages), timeout=30.0)
        content = (response.content or "").strip()
        logger.info("[LLM_ROUNDTRIP][leader_decide] model_output:\n%s", content)

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        if "{" in content:
            start = content.find("{")
            content = content[start:]
        data = json.loads(content)
        task_done = data.get("task_done", True)
        next_speaker = (data.get("next_speaker") or "user").strip().lower()
        reason = data.get("reason", "")
        current_phase = str(data.get("current_phase") or "").strip()
        # 解析建议邀请的新成员（主持人完成不了工作时可建议新增）
        suggested_add_agent_ids = None
        raw_suggested = data.get("suggested_add_agent_ids")
        if isinstance(raw_suggested, list) and raw_suggested:
            suggested_add_agent_ids = [str(x).strip() for x in raw_suggested if x]
        elif isinstance(raw_suggested, str) and raw_suggested.strip():
            suggested_add_agent_ids = [raw_suggested.strip()]
        # 构建主持词 announcement，供前端展示
        announcement = ""
        if next_speaker == "user":
            announcement = "请用户补充或继续提问。"
            if suggested_add_agent_ids:
                announcement = "当前成员无法完成该工作，建议邀请新成员参与。请用户确认是否添加。"
        elif next_speaker == "end":
            announcement = "会话结束。"
        elif next_speaker and agent_list:
            for d in agent_list:
                if d.get("agent_id") == next_speaker:
                    name = d.get("name") or d.get("agent_id", next_speaker)
                    announcement = f"下面由 {name} 发言。"
                    break
            if not announcement:
                announcement = f"下面由 {next_speaker} 发言。"
        raw_task = data.get("speaker_task")
        if raw_task is None:
            raw_task = data.get("next_prompt")
        speaker_task = str(raw_task or "").strip()
        out = {
            "task_done": task_done,
            "next_speaker": next_speaker,
            "reason": reason,
            "announcement": announcement or reason,
            "next_prompt": None,
            "current_phase": current_phase,
            "speaker_task": speaker_task,
        }
        if suggested_add_agent_ids:
            out["suggested_add_agent_ids"] = suggested_add_agent_ids
        phase = OrchestrationPhase.AWAITING_USER if next_speaker == "user" else (
            OrchestrationPhase.COMPLETED if next_speaker == "end" else OrchestrationPhase.EXECUTING
        )
        interrupt_reason = InterruptReason.NEED_RECRUIT_EXPERT if suggested_add_agent_ids else InterruptReason.NONE
        decision = OrchestrationDecision(
            task_done=bool(task_done),
            next_speaker=next_speaker,
            reason=reason,
            announcement=announcement or reason,
            next_prompt=None,
            current_phase=current_phase,
            speaker_task=speaker_task,
            suggested_add_agent_ids=suggested_add_agent_ids or [],
            phase=phase,
            owner_agent_id=next_speaker if next_speaker not in ("user", "end") else None,
            interrupt_reason=interrupt_reason,
            decision_source=DecisionSource.LEGACY,
            handoff_reason=reason or None,
        )
        return decision.to_dict()
    except Exception as e:
        logger.warning(f"领导人调度解析失败: {e}，固定交还 user（由下轮主持人重试）")
        decision = OrchestrationDecision(
            task_done=True,
            next_speaker="user",
            reason=f"解析失败: {e}",
            announcement="请用户补充或继续提问。",
            next_prompt=None,
            phase=OrchestrationPhase.AWAITING_USER,
            owner_agent_id=None,
            interrupt_reason=InterruptReason.CONFLICT_DETECTED,
            decision_source=DecisionSource.SYSTEM_GUARD,
            handoff_reason="leader_parse_failed",
        )
        return decision.to_dict()
