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
        leader_mark = "（领导人）" if d.get("is_leader") else ""
        dha_lines.append(f"- {name} ({dha_id}){leader_mark}: {role}")
    dha_text = "\n".join(dha_lines)

    return f"""你是群聊讨论的主持人（领导人）。当前群聊中有以下 DHA 参与者：

{dha_text}

讨论目标：{discussion_goal}

请根据最近讨论内容，判断：
1. 若刚发言的 DHA 尚未完成其本轮任务（例如需要继续补充、调用工具、或回答不完整），则 task_done=false，让该 DHA 继续发言。
2. 若该 DHA 已完成本轮任务，则 task_done=true，并指定 next_speaker 为下一个应发言的 DHA（dha_id），或 "user" 表示等待用户输入，或 "end" 表示讨论结束。

**必须**严格按以下 JSON 格式回复，不要包含其他文字：
{{"task_done": true或false, "next_speaker": "dha_id或user或end", "reason": "简短理由"}}

注意：next_speaker 必须是上述 dha_id 之一，或 "user" 或 "end"。"""


async def leader_decide(
    llm,
    dha_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    last_speaker_dha_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    调用领导人 LLM 决定：task_done 与 next_speaker。
    返回 {"task_done": bool, "next_speaker": str, "reason": str}
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
        return {"task_done": task_done, "next_speaker": next_speaker, "reason": reason}
    except Exception as e:
        logger.warning(f"领导人调度解析失败: {e}，回退为轮流")
        fallback = "user"
        if not last_speaker_dha_id and dha_list:
            fallback = dha_list[0].get("dha_id", "user")
        return {"task_done": True, "next_speaker": fallback, "reason": f"解析失败: {e}"}
