"""Group-chat prompt assembly helpers for the host-to-expert contract."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from app.agent.group_chat_memory_prompt import build_checked_expert_action_prompt
from app.agent.platform_prompts import render_platform_prompt


DEFAULT_EXPERT_TASK = render_platform_prompt("expert.turn.default_task.v1", {})
DEFAULT_DISCUSSION_GOAL = render_platform_prompt("session.discussion_goal.default.v1", {})


@dataclass(frozen=True)
class PromptBundle:
    """Prepared prompt content plus small diagnostics for logs/tests."""

    user_content: str
    task_text: str
    debug: Dict[str, Any]


def _has_any_section(text: str, section_names: tuple[str, ...]) -> bool:
    return any(f"【{name}】" in text for name in section_names)


def build_expert_turn_prompt(
    *,
    session_id: str,
    target_agent_name: str,
    discussion_goal: str,
    user_message: str,
    memory_prompt: str,
    app_settings: Mapping[str, Any],
    next_action: Optional[str] = None,
) -> PromptBundle:
    """Build the HumanMessage content for one expert turn.

    `next_action` is the internal task text derived from the routing message.
    It stays visible to the expert while the latest user input remains explicit.
    """
    task_text = (next_action or "").strip() or DEFAULT_EXPERT_TASK
    current_user_input = (user_message or "").strip() or "（无）"
    memory_prompt_text = (memory_prompt or "").strip() or "（无）"

    if (next_action or "").strip():
        user_content = build_checked_expert_action_prompt(
            session_id,
            target_agent_name,
            (discussion_goal or "").strip(),
            memory_prompt_text,
            dict(app_settings or {}),
            host_next_action=task_text,
        ).strip()
        if task_text and task_text not in user_content:
            user_content = render_platform_prompt(
                "expert.turn.host_instruction_section.v1",
                {"host_instruction": task_text},
            ) + "\n\n" + user_content
        if not _has_any_section(user_content, ("本轮用户输入",)):
            user_content += "\n\n" + render_platform_prompt(
                "expert.turn.user_input_section.v1",
                {"current_user_input": current_user_input},
            )
        if not _has_any_section(user_content, ("最近讨论", "历史对话（供参考）", "最近几轮讨论内容")):
            user_content += "\n\n" + render_platform_prompt(
                "expert.turn.memory_prompt_section.v1",
                {"memory_prompt": memory_prompt_text},
            )
    else:
        user_content = render_platform_prompt(
            "expert.turn.user_content.v1",
            {
                "discussion_goal": (discussion_goal or "").strip() or DEFAULT_DISCUSSION_GOAL,
                "current_user_input": current_user_input,
                "memory_prompt": memory_prompt_text,
                "default_task": DEFAULT_EXPERT_TASK,
            },
        )

    debug = {
        "has_next_action": bool((next_action or "").strip()),
        "has_user_message": bool((user_message or "").strip()),
        "has_memory_prompt": bool((memory_prompt or "").strip()),
        "user_content_len": len(user_content),
        "task_text_len": len(task_text),
    }
    return PromptBundle(user_content=user_content, task_text=task_text, debug=debug)
