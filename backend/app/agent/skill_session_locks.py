"""Skill continuation helpers backed by orchestration_state.json."""
from __future__ import annotations

from typing import Any


def clear_skill_session_lock(orchestration_state: dict[str, Any]) -> None:
    """Remove the current continuation block from orchestration state."""
    orchestration_state.pop("continuation", None)


def locked_skill_for_expert(
    orchestration_state: dict[str, Any],
    *,
    expert_agent_name: str,
    expert_skills: list[str],
) -> str | None:
    """Return the continuation Skill only when it still belongs to the requested expert."""
    continuation = orchestration_state.get("continuation") if isinstance(orchestration_state.get("continuation"), dict) else {}
    if str(continuation.get("skill_policy") or "").strip() != "keep":
        return None
    owner = str(continuation.get("owner_agent_name") or "").strip().casefold()
    skill = str(continuation.get("skill") or "").strip()
    expert = str(expert_agent_name or "").strip().casefold()
    skills = {str(item).strip() for item in expert_skills if str(item).strip()}
    if owner and owner == expert and skill in skills:
        return skill
    return None
