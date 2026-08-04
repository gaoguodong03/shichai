"""Pure text helpers for group-chat prompt and stop-condition context."""
from __future__ import annotations

import logging
import json
import re
from typing import Any, Dict, List

from app.agent.platform_prompts import render_platform_prompt

logger = logging.getLogger(__name__)


def _clip_context_message(content: str, max_chars_per_message: int) -> str:
    """Keep both opening context and closing delivery/status signals for long messages."""
    if len(content) <= max_chars_per_message:
        return content
    marker = "\n...[中间内容已截断]...\n"
    available = max_chars_per_message - len(marker)
    if available < 80:
        return content[:max_chars_per_message].rstrip() + "\n...[内容已截断]"
    head_len = available // 2
    tail_len = available - head_len
    return content[:head_len].rstrip() + marker + content[-tail_len:].lstrip()


def _message_content(message: Dict[str, Any]) -> str:
    """Read message text from the canonical nested shape."""
    if not isinstance(message, dict):
        return ""
    body = message.get("message")
    if isinstance(body, dict):
        return str(body.get("content") or "").strip()
    return ""


def _message_speaker(message: Dict[str, Any]) -> tuple[str, str]:
    """Return speaker type and agent name from a history record."""
    if not isinstance(message, dict):
        return "", ""
    speaker = message.get("speaker")
    if isinstance(speaker, dict):
        return str(speaker.get("type") or "").strip(), str(speaker.get("agent_name") or "").strip()
    return "", ""


def messages_to_context(
    messages: List[Dict[str, Any]],
    max_turns: int = 15,
    max_chars: int = 12000,
    max_chars_per_message: int = 1200,
) -> str:
    """Render recent group messages into a compact model-readable context."""
    recent = messages[-max_turns * 2:] if len(messages) > max_turns * 2 else messages
    lines = []
    for m in recent:
        role, agent_name = _message_speaker(m)
        content = _message_content(m)
        if not content:
            continue
        content = _clip_context_message(content, max_chars_per_message)
        if role == "user":
            lines.append(f"【用户】{content}")
        elif role == "host":
            lines.append(f"【主持人】{content}")
        else:
            name = agent_name or "助手"
            lines.append(f"【{name}】{content}")
    context = "\n\n".join(lines)
    if len(context) > max_chars:
        context = "...[较早历史已省略]\n\n" + context[-max_chars:]
    return context


def is_group_context_noise(content: str) -> bool:
    """Filter technical failure receipts that should not be fed back to experts."""
    s = (content or "").strip()
    if not s:
        return False
    noise_markers = (
        "抱歉，模型响应失败",
        "Error code: 400",
        "Error code: 404",
        "Error code: 500",
        "context length is only",
        "input_tokens",
        "gateway_tool_unavailable",
        "gateway executor error",
        "Model not found or no running instances available",
        "EngineCore encountered an issue",
        "技术原因导致",
        "工具暂时不可用",
        "系统暂时无法查询",
    )
    return any(marker in s for marker in noise_markers)


def messages_to_expert_context(messages: List[Dict[str, Any]]) -> str:
    """Build short expert context, deduping business text and dropping technical noise."""
    filtered: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    skipped = 0
    for m in messages or []:
        content = _message_content(m) if isinstance(m, dict) else ""
        if is_group_context_noise(content):
            skipped += 1
            continue
        role, agent_name = _message_speaker(m)
        key = (role, agent_name, content)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        filtered.append(m)
    context = messages_to_context(
        filtered,
        max_turns=3,
        max_chars=700,
        max_chars_per_message=240,
    )
    if context.strip():
        context = render_platform_prompt("expert.context.reference_notice.v1", {}) + "\n\n" + context
    if skipped:
        logger.debug("group_expert_context_noise_filtered skipped=%s kept=%s", skipped, len(filtered))
    return context


def scheduler_memory_prompt(group_session_id: str, messages: List[Dict[str, Any]]) -> str:
    """Build scheduler context while retaining only the latest host message."""
    _ = group_session_id
    history = messages or []
    latest_host_index = next(
        (
            index
            for index in range(len(history) - 1, -1, -1)
            if _message_speaker(history[index])[0] == "host"
        ),
        -1,
    )
    visible_messages = [
        message
        for index, message in enumerate(history)
        if _message_speaker(message)[0] != "host" or index == latest_host_index
    ]
    return messages_to_context(visible_messages)


def skill_sessions_to_host_context(skill_sessions: Dict[str, Any] | None) -> str:
    """Serialize validated Skill affinity as context, never as a route decision."""
    clean: Dict[str, Dict[str, str]] = {}
    for raw_agent_name, raw_binding in (skill_sessions or {}).items():
        agent_name = str(raw_agent_name or "").strip()
        binding = raw_binding if isinstance(raw_binding, dict) else {}
        skill = str(binding.get("skill") or "").strip()
        if agent_name and skill:
            clean[agent_name] = {"skill": skill}
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":")) if clean else "（无）"


def normalize_discussion_goal(raw: str, max_len: int = 200) -> str:
    """Strip frontend discussion-goal markers and cap prompt length."""
    if not raw or not isinstance(raw, str):
        return (raw or "").strip()[:max_len] if raw else ""
    s = (raw or "").strip()
    prefix = "【讨论目标】"
    if s.startswith(prefix):
        s = s[len(prefix) :].lstrip("\n ")
    return s[:max_len] if len(s) > max_len else s


def title_from_first_message(text: str, max_chars: int = 10) -> str:
    """Create a local fallback title from the first user message."""
    if not text or not isinstance(text, str):
        return ""
    s = text.strip()
    prefix = "【讨论目标】"
    if s.startswith(prefix):
        s = s[len(prefix) :].lstrip("\n ")
    first_line = s.split("\n")[0].strip() if s else ""
    if not first_line:
        return ""
    if len(first_line) > max_chars:
        return first_line[:max_chars].rstrip()
    return first_line


def shorten_text(text: str, max_chars: int = 1800) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rstrip() + "\n...[内容已截断]"


def normalize_compare_text(text: str) -> str:
    s = (text or "").lower()
    s = re.sub(r"[\s\r\n\t]+", "", s)
    s = re.sub(r"[`~!@#$%^&*()_\-+=\[\]{}\\|;:'\",.<>/?，。！？；：、“”‘’（）《》【】…·]", "", s)
    return s


def has_tool_failure(tool_results: List[Any], full_content: str) -> bool:
    parts = [str(full_content or "")]
    for item in tool_results or []:
        if isinstance(item, dict):
            parts.append(str(item.get("execution_status") or ""))
            parts.append(str(item.get("message") or ""))
            error_log = item.get("error_log")
            if isinstance(error_log, dict):
                parts.extend(str(error_log.get(key) or "") for key in ("message", "detail", "stderr", "traceback", "raw_output"))
        else:
            parts.append(str(item or ""))
    blob = "\n".join(parts).lower()
    fail_keys = (
        "执行错误", "error", "failed", "exception", "traceback", "timeout", "超时", "not found", "调用异常", "无法",
    )
    return any(k in blob for k in fail_keys)


def has_auto_continue_signal(content: str) -> bool:
    """Return true only for explicit same-agent auto-continue markers."""
    text = str(content or "").strip().lower()
    if not text:
        return False
    explicit_markers = (
        "[[AUTO_CONTINUE]]",
        "【自动继续】",
        "AUTO_CONTINUE",
        "继续执行",
        "继续处理",
    )
    return any(c.lower() in text for c in explicit_markers)
