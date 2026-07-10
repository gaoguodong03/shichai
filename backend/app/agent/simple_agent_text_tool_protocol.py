"""Text-tool protocol retry and failure handling for SimpleAgent loops."""
from __future__ import annotations

from typing import Any

from app.agent.messages import AIMessage, BaseMessage, HumanMessage
from app.agent.platform_prompts import render_platform_prompt
from app.agent.simple_agent_messages import _extract_text_content

_TEXT_TOOL_PROTOCOL_RETRY_LIMIT = 1
_TEXT_TOOL_PROTOCOL_RETRY_INSTRUCTION = render_platform_prompt("agent.text_tool_protocol.retry.v1", {})
_TEXT_TOOL_PROTOCOL_FAILURE_CONTENT = render_platform_prompt("agent.text_tool_protocol.failure.v1", {})


def text_tool_protocol_failure_message() -> AIMessage:
    """Return the user-facing failure message after text-tool protocol retry is exhausted."""
    return AIMessage(content=_TEXT_TOOL_PROTOCOL_FAILURE_CONTENT)


def last_message_is_text_tool_protocol_retry(messages: list[BaseMessage]) -> bool:
    """Return whether the latest prompt is the platform retry instruction."""
    if not messages:
        return False
    last = messages[-1]
    return isinstance(last, HumanMessage) and _extract_text_content(last) == _TEXT_TOOL_PROTOCOL_RETRY_INSTRUCTION


def append_text_tool_protocol_retry_or_failure(
    *,
    response: BaseMessage,
    messages: list[BaseMessage],
    tool_attempt_debug: list[dict[str, Any]],
    retry_count: int,
) -> tuple[int, BaseMessage, bool]:
    """Append either the one allowed retry instruction or the final failure message."""
    content_preview = _extract_text_content(response).strip()[:240]
    if retry_count < _TEXT_TOOL_PROTOCOL_RETRY_LIMIT:
        next_retry_count = retry_count + 1
        retry_message = HumanMessage(content=_TEXT_TOOL_PROTOCOL_RETRY_INSTRUCTION)
        messages.append(retry_message)
        tool_attempt_debug.append(
            {
                "source": "text_tool_call_protocol_retry",
                "matched": True,
                "retry_count": next_retry_count,
                "content_preview": content_preview,
            }
        )
        return next_retry_count, retry_message, True
    failure_message = text_tool_protocol_failure_message()
    messages.append(failure_message)
    tool_attempt_debug.append(
        {
            "source": "text_tool_call_protocol_failed",
            "matched": True,
            "retry_count": retry_count,
            "content_preview": content_preview,
        }
    )
    return retry_count, failure_message, False
