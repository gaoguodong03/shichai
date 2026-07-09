"""Minimal Skill-session lock helpers used by expert runtime only."""
from __future__ import annotations

from typing import Any


def clear_skill_session_lock(session_item: dict[str, Any]) -> None:
    """Remove the optional cross-request Skill lock from a session snapshot."""
    session_item.pop("skill_session_owner_name", None)
    session_item.pop("skill_session_skill", None)


def locked_skill_for_expert(
    session_item: dict[str, Any],
    *,
    expert_agent_name: str,
    expert_skills: list[str],
) -> str | None:
    """Return the locked Skill only when it still belongs to the requested expert."""
    owner = str(session_item.get("skill_session_owner_name") or "").strip().casefold()
    skill = str(session_item.get("skill_session_skill") or "").strip()
    expert = str(expert_agent_name or "").strip().casefold()
    skills = {str(item).strip() for item in expert_skills if str(item).strip()}
    if owner and owner == expert and skill in skills:
        return skill
    return None
