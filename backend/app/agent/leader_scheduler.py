"""领导人 DHA 调度：决定 task_done 与 next_speaker"""
import asyncio
import json
import logging
from typing import List, Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)


def _build_leader_prompt(dha_list: List[Dict[str, Any]], discussion_goal: str, recent_messages: str) -> str:
    """构建领导人调度的系统提示词"""
    dha_lines = []
    for d in dha_list:
        role = d.get("role") or "参与者"
        name = d.get("name") or d.get("dha_id", "")
        dha_id = d.get("dha_id", "")
        leader_mark = "（主持人）" if d.get("is_leader") else ""
        dha_lines.append(f"- {name} ({dha_id}){leader_mark}: {role}")
    dha_text = "\n".join(dha_lines)

    return f"""你是群聊的主持人，负责协调讨论并指定下一发言人。

## 参与者
{dha_text}

## 讨论目标
{discussion_goal}

## 你的任务
根据最近讨论内容，判断当前发言者是否完成任务，并指定下一发言人。

**判断规则（更偏向继续由 DHA 协作完成，而不是回到用户）：**
- 若刚发言的 DHA 尚未完成任务（需继续补充、调用工具、或回答不完整）→ task_done=false，next_speaker 通常为**另一位更合适的 DHA** 或同一位 DHA 的 dha_id（仅在确实需要该 DHA 继续时）
- 若该 DHA 已完成本轮任务 → task_done=true，next_speaker 为**下一位应发言的 DHA 的 dha_id**（例如根据既定流程或你认为合适的专家）
- **完成收敛规则（很重要）：**
  - 如果关键专家（例如本轮任务需要的 1–2 位）已经给出清晰、结构化的结论或修订结果，而最近几轮回复主要是在「反复向用户索要文本/文件」或重复说明自己的职责，则视为该轮任务已基本完成；
  - 此时应优先将发言权交还给用户（next_speaker="user"），让用户确认结果或提出新需求，而不是无限循环点名同一位 DHA；
  - 若你判断讨论已经完全圆满结束、没有必要继续任何 DHA 发言 → 直接使用 next_speaker="end"，结束本轮讨论。
- 只有在确实无法由任何 DHA 继续推进（必须等待用户提供全新目标或关键信息时），才使用 next_speaker="user"

**输出格式（仅输出 JSON，不要其他文字）：**
- 当 next_speaker 为某 dha_id 时，必须同时输出 **next_prompt**：给该下一发言人的简要提示词。内容只包含：讨论目标 + 与「该 DHA 职责/当前步骤」相关的最近讨论摘要或关键信息（例如上一位的结论、需要该 DHA 接着做的事），**不要**整段复制全部讨论内容。
- 当 next_speaker 为 "user" 或 "end" 时，next_prompt 可省略或为空。

格式示例：
{{"task_done": true, "next_speaker": "dha_id或user或end", "reason": "简短理由", "next_prompt": "仅当 next_speaker 为 dha_id 时填写：讨论目标+与该 DHA 相关的关键信息，勿全文"}}

next_speaker 必须是上述列出的 dha_id 之一，或 "user" 或 "end"。"""


async def leader_decide(
    llm,
    dha_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    last_speaker_dha_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    调用领导人 LLM 决定：task_done、next_speaker，并为下一发言人生成精简的 next_prompt。
    返回 {"task_done": bool, "next_speaker": str, "reason": str, "announcement": str, "next_prompt": str|None}
    """
    system_prompt = _build_leader_prompt(dha_list, discussion_goal, recent_messages)
    user_content = f"最近讨论内容：\n\n{recent_messages}\n\n"
    if last_speaker_dha_id:
        user_content += f"刚发言的 DHA：{last_speaker_dha_id}\n\n请判断该 DHA 是否完成任务，并指定下一发言人。"
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
        next_prompt = (data.get("next_prompt") or "").strip()
        # 仅当 next_speaker 为某 dha_id 时，next_prompt 会传给该 DHA；为 user/end 时忽略
        if next_speaker in ("user", "end"):
            next_prompt = ""
        # 构建主持词 announcement，供前端展示
        announcement = ""
        if next_speaker == "user":
            announcement = "请用户补充或继续提问。"
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
        return {
            "task_done": task_done,
            "next_speaker": next_speaker,
            "reason": reason,
            "announcement": announcement or reason,
            "next_prompt": next_prompt or None,
        }
    except Exception as e:
        logger.warning(f"领导人调度解析失败: {e}，回退为轮流")
        # 回退策略更加“激进”：优先继续由某个 DHA 发言，而不是回到用户。
        if dha_list:
            # 若有上一位发言者，则优先让上一位 DHA 或下一个 DHA 继续；否则选列表中的第一个 DHA
            fallback = last_speaker_dha_id or dha_list[0].get("dha_id", "user")
        else:
            fallback = "user"
        announcement = "请用户补充或继续提问。"
        if fallback and fallback != "user":
            for d in dha_list:
                if d.get("dha_id") == fallback:
                    announcement = f"下面由 {d.get('name') or fallback} 发言。"
                    break
        return {
            "task_done": True,
            "next_speaker": fallback,
            "reason": f"解析失败: {e}",
            "announcement": announcement,
            "next_prompt": None,
        }
