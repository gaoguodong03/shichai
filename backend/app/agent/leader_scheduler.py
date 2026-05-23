"""领导人专家调度：决定 task_done 与 next_speaker"""
import asyncio
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from app.agent.group_memory_store import append_llm_roundtrip

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
    agent_lines = []
    for d in agent_list:
        role = d.get("role") or "参与者"
        name = d.get("name") or d.get("agent_id", "")
        agent_id = d.get("agent_id", "")
        leader_mark = "（主持人）" if d.get("is_leader") else ""
        agent_lines.append(f"- {name} ({agent_id}){leader_mark}: {role}")
    agent_text = "\n".join(agent_lines)

    add_section = ""
    if allow_recruitment and available_to_add:
        add_lines = [f"- {d.get('name') or d.get('agent_id', '')} ({d.get('agent_id', '')}): {d.get('role') or '专家'}" for d in available_to_add[:30]]
        add_section = f"""
## 可邀请的新成员（当前不在群内）
若**当前参与者无法完成工作**（例如缺少某类专家、需要专业能力不在现有成员中），你可以建议用户邀请新成员。可邀请的专家列表：
{chr(10).join(add_lines)}

此时请在 JSON 中同时输出 **suggested_add_agent_ids**：要邀请的 agent_id 数组（从上面列表中选），并设 **next_speaker="user"**，由用户确认后添加成员再继续。格式示例：{{"task_done": true, "next_speaker": "user", "reason": "需要图片生成专家参与", "suggested_add_agent_ids": ["agent-440b26f8"]}}
"""

    recruit_rule = ""
    if allow_recruitment:
        recruit_rule = (
            '- **当前成员无法完成工作时**：若缺少某类专家（如需要配图、核查、爬取等而群内没有对应专家），'
            '可输出 suggested_add_agent_ids（从「可邀请的新成员」中选 agent_id），并设 next_speaker 为 "user"，让用户邀请新成员后再继续。\n'
        )
    scene_extra = ""
    if not allow_recruitment:
        scene_extra = "- **本场参与者名单已固定**：不要输出 suggested_add_agent_ids；若缺能力，请 next_speaker=\"user\" 请用户调整场景或换话题。\n"

    recruit_output = ""
    if allow_recruitment:
        recruit_output = "- 建议邀请新成员时：输出 suggested_add_agent_ids，next_speaker=\"user\"。\n"
    else:
        recruit_output = "- 不要输出 suggested_add_agent_ids。\n"

    return f"""你是群聊主持人，只做调度，不代写专家正文，也不要为专家指定 Skill。
你必须输出一段 JSON（可用 ```json 包裹），字段至少包含：task_done、next_speaker、reason。
当 next_speaker 是某专家时必须给出 next_prompt；next_speaker 只能是在场 agent_id 或 \"user\" 或 \"end\"。

## 参与者
{agent_text}
{add_section}

## 讨论目标
{discussion_goal}

## 最近讨论（摘要）
若开头另有「用户任务清单」段落，来自工作区 `memory/host_plan.md`（用户可编辑）；可对照讨论目标判断进度与 task_done。其余为对话与发言摘录，合起来视为唯一上下文。

## 本轮约束（与上文契约一致）
- next_speaker：在场 agent_id | \"user\" | \"end\"。
- 点专家时须给出可执行的 next_prompt。
{recruit_rule}{scene_extra}
{recruit_output}
**本路径要求：仅输出一段 JSON**（可含 task_done、next_speaker、reason、announcement、next_prompt、suggested_add_agent_ids）。"""


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
    调用领导人 LLM 决定：task_done、next_speaker。
    返回 {"task_done", "next_speaker", "reason", "announcement", "suggested_add_agent_ids"?(可选)}
    """
    allow_rec = orchestration_profile != "scene"
    system_prompt = _build_leader_prompt(
        agent_list,
        discussion_goal,
        recent_messages,
        available_to_add if allow_rec else [],
        allow_recruitment=allow_rec,
    )
    user_content = f"最近讨论内容：\n\n{recent_messages}\n\n"
    if last_speaker_agent_id:
        user_content += f"刚发言的专家：{last_speaker_agent_id}\n\n请判断该专家是否完成任务，并指定下一发言人。"
    else:
        user_content += "请指定第一个发言人（next_speaker 为某 agent_id）。此时 task_done 可设为 true。"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ]
    logger.info(
        "[LLM_ROUNDTRIP][leader_decide] system_prompt:\n%s\n\n[LLM_ROUNDTRIP][leader_decide] user_prompt:\n%s",
        system_prompt,
        user_content,
    )

    try:
        client = llm.get_client()
        response = await asyncio.wait_for(client.ainvoke(messages), timeout=30.0)
        content = (response.content or "").strip()
        logger.info("[LLM_ROUNDTRIP][leader_decide] model_output:\n%s", content)
        if group_session_id:
            try:
                append_llm_roundtrip(
                    session_id=group_session_id,
                    workspace_root=workspace_root,
                    phase="leader_decide",
                    input_messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    output={"content": content},
                    model=str(getattr(llm, "model", "") or ""),
                    llm_provider_id=llm_provider_id,
                )
            except Exception as e:
                logger.warning("写入会话 LLM roundtrip 失败(tag=leader_decide session=%s): %s", group_session_id, e)

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
            announcement = "讨论结束。"
        elif next_speaker and agent_list:
            for d in agent_list:
                if d.get("agent_id") == next_speaker:
                    name = d.get("name") or d.get("agent_id", next_speaker)
                    announcement = f"下面由 {name} 发言。"
                    break
            if not announcement:
                announcement = f"下面由 {next_speaker} 发言。"
        raw_np = data.get("next_prompt")
        next_prompt_val = str(raw_np).strip() if raw_np is not None and str(raw_np).strip() else None
        out = {
            "task_done": task_done,
            "next_speaker": next_speaker,
            "reason": reason,
            "announcement": announcement or reason,
            "next_prompt": next_prompt_val,
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
            next_prompt=next_prompt_val,
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
