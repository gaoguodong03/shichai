"""Skill flow-control instruction shared by expert runtimes.

This module carries only the current `skill_result.next_action` instruction
surface. Cross-turn state is derived in `group_chat_skill_session.py` from
strict `expert_final_state.v2`.
"""
from __future__ import annotations

from typing import Literal, TypedDict

from app.agent.platform_prompts import render_platform_prompt


class SkillNextActionDict(TypedDict):
    agent_turn: Literal["continue", "respond"]
    skill_session: Literal["keep", "release"]


DEFAULT_SKILL_NEXT_ACTION: SkillNextActionDict = {
    "agent_turn": "respond",
    "skill_session": "release",
}


GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION = render_platform_prompt("skill.session.state_instruction.v1", {})
