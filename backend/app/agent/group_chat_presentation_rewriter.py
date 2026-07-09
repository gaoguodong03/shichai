"""Frontend-only presentation rewrite for group chat assistant messages."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

from app.agent.messages import HumanMessage, SystemMessage  # type: ignore
from app.agent.platform_prompts import render_platform_prompt

logger = logging.getLogger(__name__)


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
        human_prompt = render_platform_prompt(
            "presentation.rewrite.user_prompt.v1",
            {
                "expert_system_prompt": expert_system_prompt or "（无）",
                "original_content": raw_content,
            },
        )
        response = await asyncio.wait_for(
            client.ainvoke(
                [
                    SystemMessage(content=render_platform_prompt("presentation.rewrite.v1", {})),
                    HumanMessage(content=human_prompt),
                ]
            ),
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
    body = assistant_msg.get("message") if isinstance(assistant_msg, dict) else None
    display_body = dict(body) if isinstance(body, dict) else {"content": ""}
    raw_content = str(display_body.get("content") or "")
    display_body["content"] = await _rewrite_content(
        llm=llm,
        expert_system_prompt=expert_system_prompt,
        raw_content=raw_content,
    )
    display_msg["message"] = display_body
    return display_msg
