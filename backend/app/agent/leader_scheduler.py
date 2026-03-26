"""领导人 DHA 调度：决定 task_done 与 next_speaker"""
import asyncio
import json
import logging
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
    dha_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    available_to_add: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """构建领导人调度的系统提示词。available_to_add：当前不在群内的专家列表，主持人可建议邀请。"""
    dha_lines = []
    for d in dha_list:
        role = d.get("role") or "参与者"
        name = d.get("name") or d.get("dha_id", "")
        dha_id = d.get("dha_id", "")
        leader_mark = "（主持人）" if d.get("is_leader") else ""
        dha_lines.append(f"- {name} ({dha_id}){leader_mark}: {role}")
    dha_text = "\n".join(dha_lines)

    add_section = ""
    if available_to_add:
        add_lines = [f"- {d.get('name') or d.get('dha_id', '')} ({d.get('dha_id', '')}): {d.get('role') or '专家'}" for d in available_to_add[:30]]
        add_section = f"""
## 可邀请的新成员（当前不在群内）
若**当前参与者无法完成工作**（例如缺少某类专家、需要专业能力不在现有成员中），你可以建议用户邀请新成员。可邀请的专家列表：
{chr(10).join(add_lines)}

此时请在 JSON 中同时输出 **suggested_add_dha_ids**：要邀请的 dha_id 数组（从上面列表中选），并设 **next_speaker="user"**，由用户确认后添加成员再继续。格式示例：{{"task_done": true, "next_speaker": "user", "reason": "需要图片生成专家参与", "suggested_add_dha_ids": ["dha-440b26f8"]}}
"""

    return f"""你是群聊的主持人，负责协调讨论并指定下一发言人。

## 参与者
{dha_text}
{add_section}

## 讨论目标
{discussion_goal}

## 你能看到的内容
你将看到最近讨论内容，可能来自「关键事实 + 相关历史摘录」而非全量会话原文。请把这些内容视为你唯一可用上下文，不要假设你能访问完整历史。

## 你的任务
根据最近讨论内容，判断当前发言者是否完成任务，并指定下一发言人。

**判断规则（更偏向继续由专家协作完成，而不是回到用户）：**
- 若刚发言的专家尚未完成任务（需继续补充、调用工具、或回答不完整）→ task_done=false，next_speaker 通常为**另一位更合适的专家**或同一位专家的 dha_id（仅在确实需要该专家继续时）
- 若该专家已完成本轮任务 → task_done=true，next_speaker 为**下一位应发言的专家的 dha_id**（例如根据既定流程或你认为合适的人选）
- **当前成员无法完成工作时**：若缺少某类专家（如需要配图、核查、爬取等而群内没有对应专家），可输出 suggested_add_dha_ids（从「可邀请的新成员」中选 dha_id），并设 next_speaker="user"，让用户邀请新成员后再继续。
- **完成收敛规则（很重要）：**
  - 如果关键专家（例如本轮任务需要的 1–2 位）已经给出清晰、结构化的结论或修订结果，而最近几轮回复主要是在「反复向用户索要文本/文件」或重复说明自己的职责，则视为该轮任务已基本完成；
  - 此时应优先将发言权交还给用户（next_speaker="user"），让用户确认结果或提出新需求，而不是无限循环点名同一位专家；
  - 若你判断讨论已经完全圆满结束、没有必要继续任何专家发言 → 直接使用 next_speaker="end"，结束本轮讨论。
- 只有在确实无法由任何专家继续推进（必须等待用户提供全新目标或关键信息时），才使用 next_speaker="user"

**输出格式（仅输出 JSON，不要其他文字）：**
- 主持人只负责调度（决定 task_done / next_speaker / suggested_add_dha_ids），不负责给专家写补充指令。
- 当建议邀请新成员时，输出 suggested_add_dha_ids（dha_id 数组）并 next_speaker="user"。

格式示例：
{{"task_done": true, "next_speaker": "dha_id或user或end", "reason": "简短理由", "suggested_add_dha_ids": ["dha_id1"]（可选，仅当需要邀请新成员时）}}

next_speaker 必须是当前参与者列表中的 dha_id 之一，或 "user" 或 "end"。"""


def _single_dha_extra_instruction() -> str:
    """仅一位专家时的额外说明：主持人可持续指定同一专家，直到出结果再交还用户。"""
    return """
**【当前仅有一位专家】** 你可多次指定同一专家（next_speaker 仍为该 dha_id）继续完成任务；直到该专家产出最终结果再设 task_done=true 且 next_speaker="user"。勿在未出结果时过早交还用户。"""


def _build_leader_prompt_with_single_hint(
    dha_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    available_to_add: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """构建领导人系统提示词；仅一位专家时追加单人场景说明。"""
    base = _build_leader_prompt(dha_list, discussion_goal, recent_messages, available_to_add)
    if len(dha_list) == 1:
        base += _single_dha_extra_instruction()
    return base


async def leader_decide(
    llm,
    dha_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    last_speaker_dha_id: Optional[str] = None,
    available_to_add: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    调用领导人 LLM 决定：task_done、next_speaker。
    返回 {"task_done", "next_speaker", "reason", "announcement", "suggested_add_dha_ids"?(可选)}
    """
    system_prompt = _build_leader_prompt_with_single_hint(
        dha_list, discussion_goal, recent_messages, available_to_add
    )
    user_content = f"最近讨论内容：\n\n{recent_messages}\n\n"
    if last_speaker_dha_id:
        user_content += f"刚发言的专家：{last_speaker_dha_id}\n\n请判断该专家是否完成任务，并指定下一发言人。"
    else:
        user_content += "请指定第一个发言人（next_speaker 为某 dha_id）。此时 task_done 可设为 true。"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ]

    try:
        client = llm.get_client()
        response = await asyncio.wait_for(client.ainvoke(messages), timeout=30.0)
        content = (response.content or "").strip()
        logger.info(f"领导人调度 LLM 返回: {content[:400]}")

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
        # 解析建议邀请的新成员（主持人完成不了工作时可建议新增）
        suggested_add_dha_ids = None
        raw_suggested = data.get("suggested_add_dha_ids")
        if isinstance(raw_suggested, list) and raw_suggested:
            suggested_add_dha_ids = [str(x).strip() for x in raw_suggested if x]
        elif isinstance(raw_suggested, str) and raw_suggested.strip():
            suggested_add_dha_ids = [raw_suggested.strip()]
        # 构建主持词 announcement，供前端展示
        announcement = ""
        if next_speaker == "user":
            announcement = "请用户补充或继续提问。"
            if suggested_add_dha_ids:
                announcement = "当前成员无法完成该工作，建议邀请新成员参与。请用户确认是否添加。"
        elif next_speaker == "end":
            announcement = "讨论结束。"
        elif next_speaker and dha_list:
            for d in dha_list:
                if d.get("dha_id") == next_speaker:
                    name = d.get("name") or d.get("dha_id", next_speaker)
                    announcement = f"下面由 {name} 发言。"
                    break
            if not announcement:
                announcement = f"下面由 {next_speaker} 发言。"
        out = {
            "task_done": task_done,
            "next_speaker": next_speaker,
            "reason": reason,
            "announcement": announcement or reason,
            "next_prompt": None,
        }
        if suggested_add_dha_ids:
            out["suggested_add_dha_ids"] = suggested_add_dha_ids
        phase = OrchestrationPhase.AWAITING_USER if next_speaker == "user" else (
            OrchestrationPhase.COMPLETED if next_speaker == "end" else OrchestrationPhase.EXECUTING
        )
        interrupt_reason = InterruptReason.NEED_RECRUIT_EXPERT if suggested_add_dha_ids else InterruptReason.NONE
        decision = OrchestrationDecision(
            task_done=bool(task_done),
            next_speaker=next_speaker,
            reason=reason,
            announcement=announcement or reason,
            next_prompt=None,
            suggested_add_dha_ids=suggested_add_dha_ids or [],
            phase=phase,
            owner_dha_id=next_speaker if next_speaker not in ("user", "end") else None,
            interrupt_reason=interrupt_reason,
            decision_source=DecisionSource.LEGACY,
            handoff_reason=reason or None,
        )
        return decision.to_dict()
    except Exception as e:
        logger.warning(f"领导人调度解析失败: {e}，回退为轮流")
        # 回退策略更加“激进”：优先继续由某个专家发言，而不是回到用户。
        if dha_list:
            # 若有上一位发言者，则优先让上一位或下一个专家继续；否则选列表中的第一个
            fallback = last_speaker_dha_id or dha_list[0].get("dha_id", "user")
        else:
            fallback = "user"
        announcement = "请用户补充或继续提问。"
        if fallback and fallback != "user":
            for d in dha_list:
                if d.get("dha_id") == fallback:
                    announcement = f"下面由 {d.get('name') or fallback} 发言。"
                    break
        decision = OrchestrationDecision(
            task_done=True,
            next_speaker=fallback,
            reason=f"解析失败: {e}",
            announcement=announcement,
            next_prompt=None,
            phase=OrchestrationPhase.AWAITING_USER if fallback == "user" else OrchestrationPhase.EXECUTING,
            owner_dha_id=fallback if fallback not in ("user", "end") else None,
            interrupt_reason=InterruptReason.CONFLICT_DETECTED,
            decision_source=DecisionSource.SYSTEM_GUARD,
            handoff_reason="leader_parse_failed",
        )
        return decision.to_dict()
