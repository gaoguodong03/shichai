from __future__ import annotations

import os
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def _extract_text_content(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return str(content or "")


_PLAIN_TEXT_TOOL_CALL_NAMES = {
    "write_workspace_file",
    "edit_workspace_file",
    "rename_workspace_file",
    "list_workspace_directory",
    "read_workspace_file",
    "read_file",
}


def _looks_like_text_tool_call_protocol(message: BaseMessage) -> bool:
    text = _extract_text_content(message).strip()
    if not text:
        return False
    if "<｜｜DSML｜｜tool_calls>" in text:
        return True
    if "\n" in text:
        return False
    stripped = (text or "").strip()
    return any(stripped.startswith(f"{name}(") for name in _PLAIN_TEXT_TOOL_CALL_NAMES)


def _has_visible_ai_text(messages: list[BaseMessage]) -> bool:
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        text = _extract_text_content(msg).strip()
        if text and not (getattr(msg, "tool_calls", None) or []):
            return True
    return False


def _last_user_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage):
            return _extract_text_content(msg).strip()
    return ""


def _ai_response_hit_output_limit(message: BaseMessage) -> bool:
    """Best-effort detection for provider-side max_tokens truncation."""
    values: list[Any] = []
    for attr in ("response_metadata", "additional_kwargs"):
        meta = getattr(message, attr, None)
        if isinstance(meta, dict):
            values.extend(
                meta.get(k)
                for k in (
                    "finish_reason",
                    "stop_reason",
                    "finishReason",
                    "stopReason",
                    "termination_reason",
                    "terminationReason",
                )
            )
            choices = meta.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    if isinstance(choice, dict):
                        values.append(choice.get("finish_reason"))
    normalized = {str(v or "").strip().lower() for v in values if v is not None}
    return bool(normalized & {"length", "max_tokens", "max_completion_tokens", "token_limit", "output_limit"})


def _continuation_instruction() -> HumanMessage:
    return HumanMessage(
        content=(
            "上一条回复因为输出长度限制中断了。请从中断处无缝续写，直接继续正文；"
            "不要重写前文，不要道歉，不要输出新的标题。"
        )
    )


def _max_output_continuations() -> int:
    raw = (os.getenv("LLM_OUTPUT_CONTINUATION_MAX_ROUNDS") or "2").strip()
    try:
        return max(0, min(5, int(raw)))
    except Exception:
        return 2
