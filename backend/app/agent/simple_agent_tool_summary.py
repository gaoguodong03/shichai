from __future__ import annotations

from typing import Any

from app.agent.messages import BaseMessage
from app.agent.simple_agent_finalization import (
    _align_final_response_with_written_workspace_paths,
    _deterministic_tool_summary_message,
)
from app.agent.simple_agent_messages import _looks_like_text_tool_call_protocol


def _final_response_or_tool_summary(
    response: BaseMessage,
    raw_outputs: list[str],
    tool_attempt_debug: list[dict[str, Any]],
) -> BaseMessage:
    """Return the final model response, or convert text tool-call protocol into a visible tool summary."""
    if not _looks_like_text_tool_call_protocol(response):
        return _align_final_response_with_written_workspace_paths(response, raw_outputs)
    tool_attempt_debug.append(
        {
            "source": "text_tool_call_protocol_final_summary",
            "matched": True,
            "content_preview": str(getattr(response, "content", "") or "").strip()[:240],
        }
    )
    return _align_final_response_with_written_workspace_paths(
        _deterministic_tool_summary_message(raw_outputs),
        raw_outputs,
    )
