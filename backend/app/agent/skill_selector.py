"""技能选择：第一次调用大模型，仅给予 name+description，返回选中的 skill_id"""
import asyncio
import json
import logging
import time
from typing import List, Dict, Optional

from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)


def _build_skill_selection_prompt(skills: List[Dict[str, str]]) -> str:
    """构建技能列表文本，仅 name + description（若有）"""
    lines = []
    for s in skills:
        name = s.get("name", s.get("skill_id", ""))
        desc = s.get("description", "")
        if desc:
            lines.append(f"- {name}: {desc}")
        else:
            lines.append(f"- {name}")
    return "\n".join(lines)


async def select_skill(
    llm,
    user_message: str,
    skills: List[Dict[str, str]],
    history_summary: Optional[str] = None,
) -> Optional[str]:
    """
    第一次调用大模型：根据用户输入和技能列表（仅 name+description）选择技能。
    返回选中的 skill_id，若无法选择则返回 None。
    """
    if not skills:
        logger.warning("技能列表为空，无法选择")
        return None

    skill_list_text = _build_skill_selection_prompt(skills)
    skill_ids = [s.get("skill_id") for s in skills if s.get("skill_id")]

    system_prompt = """你是一个技能路由器。根据用户输入，从以下技能中选择最合适的一个。

可用技能（仅 name 和 description）：
{skill_list}

要求：
1. 只返回一个 skill_id，必须是上述技能之一。
2. 若无法确定使用哪个专用技能，返回 skill_id: default。
3. 必须严格按以下 JSON 格式回复，不要包含其他文字：
{{"skill_id": "技能ID"}}

技能 ID 对应关系：
{id_mapping}
""".format(
        skill_list=skill_list_text,
        id_mapping="\n".join(f"- {s.get('name')} -> {s.get('skill_id')}" for s in skills),
    )

    user_content = user_message.strip()
    if history_summary:
        user_content = f"历史对话摘要：\n{history_summary}\n\n当前用户输入：\n{user_content}"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ]

    logger.info("技能选择：第一次调用大模型（仅 name+description）")
    try:
        client = llm.get_client()
        t0 = time.perf_counter()
        response = await asyncio.wait_for(client.ainvoke(messages), timeout=30.0)
        logger.info(f"[TIMING] select_skill 内 ainvoke: {time.perf_counter() - t0:.2f}s")
        content = (response.content or "").strip()
        logger.info(f"技能选择 LLM 返回: {content[:300]}")

        # 解析 JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        # 尝试提取 {"skill_id": "xxx"}
        if "{" in content:
            start = content.find("{")
            content = content[start:]
        try:
            data = json.loads(content)
            sid = data.get("skill_id") or data.get("skillId")
            if sid and sid in skill_ids:
                logger.info(f"选中技能: {sid}")
                return sid
        except json.JSONDecodeError as e:
            logger.warning(f"技能选择 JSON 解析失败: {e}")
        return None
    except asyncio.TimeoutError:
        logger.error("技能选择 LLM 超时")
        return None
    except Exception as e:
        logger.error(f"技能选择异常: {e}", exc_info=True)
        return None
