"""Frontend-only presentation rewrite for group chat assistant messages."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

from app.agent.messages import HumanMessage, SystemMessage  # type: ignore

logger = logging.getLogger(__name__)


PRESENTATION_REWRITE_PHASE = "presentation_rewriting"

_SYSTEM_PROMPT = """你是群聊前端展示层的表达整理器。

你的任务只是在不改变业务结果的前提下，把专家本轮原始回复整理成用户可读的 Markdown。

硬性规则：
- 只改变表达、排版、结构和语气，不新增事实、链接、路径、数量、状态或结论。
- 不删除用户判断任务所必需的信息；可以合并重复内容、压缩冗长正文。
- 不继续检索、不调用工具、不分析下一步执行方案。
- 不改变成功、失败、等待用户补充、需要确认等状态。
- 如果原文是 JSON、工具结果、Title/URL/Highlights 列表或混杂格式，整理成自然的中文说明、列表或表格。
- 只输出整理后的 Markdown 正文，不要解释你的改写过程。"""


def _response_text(response: Any) -> str:
    raw = response.content if hasattr(response, "content") else response
    if isinstance(raw, list):
        return "".join(str(x) for x in raw).strip()
    return str(raw or "").strip()


def _timeout_seconds() -> float:
    raw = os.getenv("GROUP_CHAT_PRESENTATION_REWRITE_TIMEOUT", "45")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 45.0


async def _rewrite_content(
    *,
    llm: Any,
    expert_system_prompt: str,
    raw_content: str,
) -> str:
    if not raw_content.strip() or llm is None:
        return raw_content

    try:
        client = llm.get_client() if hasattr(llm, "get_client") else llm
        human_prompt = (
            "【专家系统提示词】\n"
            f"{expert_system_prompt or '（无）'}\n\n"
            "【专家本轮原始回复】\n"
            f"{raw_content}\n\n"
            "请按系统规则输出前端最终展示文案。"
        )
        response = await asyncio.wait_for(
            client.ainvoke([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human_prompt)]),
            timeout=_timeout_seconds(),
        )
        rewritten = _response_text(response)
        return rewritten or raw_content
    except Exception:
        logger.warning("group chat presentation rewrite failed; falling back to raw content", exc_info=True)
        return raw_content


async def rewrite_assistant_message_for_display(
    *,
    assistant_msg: Dict[str, Any],
    llm: Any,
    expert_system_prompt: str,
) -> Dict[str, Any]:
    """Return a frontend display copy; never mutate the persisted assistant message."""
    display_msg = dict(assistant_msg)
    raw_content = str(assistant_msg.get("content") or "")
    display_msg["content"] = await _rewrite_content(
        llm=llm,
        expert_system_prompt=expert_system_prompt,
        raw_content=raw_content,
    )
    return display_msg
