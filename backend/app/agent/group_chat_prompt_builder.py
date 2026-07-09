"""Group-chat prompt assembly helpers for the host-to-expert contract."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from app.agent.group_chat_memory_prompt import _build_checked_next_prompt


DEFAULT_EXPERT_TASK = "请紧扣讨论目标发言，不要偏离主题。"


@dataclass(frozen=True)
class PromptBundle:
    """Prepared prompt content plus small diagnostics for logs/tests."""

    user_content: str
    task_text: str
    debug: Dict[str, Any]


def _section(title: str, content: str) -> str:
    return f"【{title}】\n{content}"


def _has_any_section(text: str, section_names: tuple[str, ...]) -> bool:
    return any(f"【{name}】" in text for name in section_names)


def build_expert_turn_prompt(
    *,
    session_id: str,
    target_agent_name: str,
    discussion_goal: str,
    user_message: str,
    recent_context: str,
    app_settings: Mapping[str, Any],
    next_action: Optional[str] = None,
) -> PromptBundle:
    """Build the HumanMessage content for one expert turn.

    `next_action` is the host handoff contract. It must stay visible to the
    expert, while the latest user input stays explicit instead of only appearing
    inside a clipped history excerpt.
    """
    task_text = (next_action or "").strip() or DEFAULT_EXPERT_TASK
    current_user_input = (user_message or "").strip() or "（无）"
    context_text = (recent_context or "").strip() or "（无）"

    if (next_action or "").strip():
        user_content = _build_checked_next_prompt(
            session_id,
            target_agent_name,
            (discussion_goal or "").strip(),
            context_text,
            dict(app_settings or {}),
            decision_next_prompt=task_text,
        ).strip()
        if task_text and task_text not in user_content:
            user_content = _section(
                "主持人本轮指派（必须按此执行；与下方模板冲突时以本段为准）",
                task_text,
            ) + "\n\n" + user_content
        if not _has_any_section(user_content, ("本轮用户输入",)):
            user_content += "\n\n" + _section("本轮用户输入", current_user_input)
        if not _has_any_section(user_content, ("最近讨论", "历史对话（供参考）", "最近几轮讨论内容")):
            user_content += "\n\n" + _section("最近讨论", context_text)
    else:
        user_content = "\n\n".join(
            [
                _section("群聊讨论目标", (discussion_goal or "").strip() or "待用户提出讨论主题"),
                _section("本轮用户输入", current_user_input),
                _section("最近讨论", context_text),
                DEFAULT_EXPERT_TASK,
            ]
        )

    debug = {
        "has_next_action": bool((next_action or "").strip()),
        "has_user_message": bool((user_message or "").strip()),
        "has_recent_context": bool((recent_context or "").strip()),
        "user_content_len": len(user_content),
        "task_text_len": len(task_text),
    }
    return PromptBundle(user_content=user_content, task_text=task_text, debug=debug)
