"""Cross-request Skill affinity, isolated from routing and expert output."""
from __future__ import annotations

from typing import Any

from app.agent.expert_completion_contract import SkillSessionDirective


def _sessions(state: dict[str, Any]) -> dict[str, Any]:
    value = state.get("skill_sessions")
    return value if isinstance(value, dict) else {}


def _matching_expert_key(sessions: dict[str, Any], agent_name: str) -> str | None:
    expected = str(agent_name or "").strip().casefold()
    for key in sessions:
        if str(key).strip().casefold() == expected:
            return str(key)
    return None


def apply_skill_session(
    state: dict[str, Any],
    *,
    agent_name: str,
    skill: str,
    directive: SkillSessionDirective,
) -> bool:
    """Apply one expert's Skill binding without affecting other experts or routing."""
    clean_agent = str(agent_name or "").strip()
    clean_skill = str(skill or "").strip()
    current = _sessions(state)
    sessions = dict(current)
    existing_key = _matching_expert_key(sessions, clean_agent)

    if directive.action == "keep" and clean_agent and clean_skill:
        key = existing_key or clean_agent
        previous = sessions.get(key)
        sessions[key] = {"skill": clean_skill}
        state["skill_sessions"] = sessions
        return previous != sessions[key] or current != sessions

    if existing_key is None:
        return False
    sessions.pop(existing_key, None)
    if sessions:
        state["skill_sessions"] = sessions
    else:
        state.pop("skill_sessions", None)
    return True


def skill_session_for_expert(
    state: dict[str, Any],
    *,
    expert_agent_name: str,
    expert_skills: list[str],
) -> str | None:
    """Return a valid bound Skill and remove only this expert's stale binding."""
    sessions = _sessions(state)
    key = _matching_expert_key(sessions, expert_agent_name)
    if key is None:
        return None
    row = sessions.get(key) if isinstance(sessions.get(key), dict) else {}
    skill = str(row.get("skill") or "").strip()
    allowed = {str(item).strip() for item in expert_skills if str(item).strip()}
    if skill and skill in allowed:
        return skill
    updated = dict(sessions)
    updated.pop(key, None)
    if updated:
        state["skill_sessions"] = updated
    else:
        state.pop("skill_sessions", None)
    return None
