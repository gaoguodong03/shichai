"""Skill flow-control instruction shared by expert runtimes.

This module carries only the current `skill_result.next_action` instruction
surface. Cross-turn state is derived in `group_chat_skill_session.py` from
strict script stdout JSON or the documented hidden state block.
"""
from __future__ import annotations

from typing import Literal, TypedDict

from app.agent.platform_prompts import render_platform_prompt


class SkillNextActionDict(TypedDict):
    handoff: Literal["user", "host", "end"]
    resume: Literal["same_skill", "same_agent", "host", "none"]
    reason: Literal[
        "stage_gate",
        "missing_input",
        "user_confirmation",
        "stage_completed",
        "final_delivery",
        "failure",
        "protocol_error",
    ]
    instruction: str


DEFAULT_SKILL_NEXT_ACTION: SkillNextActionDict = {
    "handoff": "host",
    "resume": "none",
    "reason": "stage_completed",
    "instruction": "本轮专家回复已完成，请主持人判断下一步。",
}


GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION = render_platform_prompt("skill.session.state_instruction.v1", {})
