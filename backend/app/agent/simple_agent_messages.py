from __future__ import annotations

import html
import os
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def _extract_text_content(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return str(content or "")


def _parse_dsml_tool_calls(text: str) -> list[dict[str, Any]]:
    """Parse Qwen/DeepSeek-style DSML tool-call text into LangChain tool_calls."""
    if "<｜｜DSML｜｜tool_calls>" not in (text or ""):
        return []
    calls: list[dict[str, Any]] = []
    invoke_re = re.compile(
        r'<｜｜DSML｜｜invoke\s+name="([^"]+)">\s*(.*?)</｜｜DSML｜｜invoke>',
        re.S,
    )
    param_re = re.compile(
        r'<｜｜DSML｜｜parameter\s+name="([^"]+)"(?:\s+[^>]*)?>(.*?)</｜｜DSML｜｜parameter>',
        re.S,
    )
    for idx, match in enumerate(invoke_re.finditer(text or "")):
        name = html.unescape((match.group(1) or "").strip())
        if not name:
            continue
        args: dict[str, Any] = {}
        for param in param_re.finditer(match.group(2) or ""):
            key = html.unescape((param.group(1) or "").strip())
            if not key:
                continue
            args[key] = html.unescape((param.group(2) or "").strip())
        calls.append({"name": name, "args": args, "id": f"dsml-tool-{idx}"})
    return calls


def _coerce_text_tool_calls_to_structured(message: BaseMessage) -> tuple[BaseMessage, dict[str, Any] | None]:
    if getattr(message, "tool_calls", None):
        return message, None
    text = _extract_text_content(message)
    calls = _parse_dsml_tool_calls(text)
    if not calls:
        return message, None
    coerced = AIMessage(content="", tool_calls=calls)
    debug = {
        "source": "dsml_text_tool_calls",
        "matched": True,
        "count": len(calls),
        "content_preview": text.strip()[:240],
    }
    return coerced, debug


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
