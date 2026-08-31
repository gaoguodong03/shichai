"""Platform-internal structured facts for the latest expert turn."""
from __future__ import annotations

from typing import Any


def build_last_expert_turn(
    *,
    agent_name: str,
    skill: str,
    execution_status: str,
    agent_turn: str,
    skill_session: str,
    message_id: str,
    user_message_id: str,
) -> dict[str, str]:
    """Build the short-lived snapshot consumed by host routing and entry checks."""
    return {
        "agent_name": str(agent_name or "").strip(),
        "skill": str(skill or "").strip(),
        "execution_status": str(execution_status or "").strip(),
        "agent_turn": str(agent_turn or "").strip(),
        "skill_session": str(skill_session or "").strip(),
        "message_id": str(message_id or "").strip(),
        "user_message_id": str(user_message_id or "").strip(),
    }


def clean_last_expert_turn(raw: Any) -> dict[str, str] | None:
    """Keep only valid platform-internal facts from the latest expert turn."""
    if not isinstance(raw, dict):
        return None
    allowed = {
        "agent_name",
        "skill",
        "execution_status",
        "agent_turn",
        "skill_session",
        "message_id",
        "user_message_id",
    }
    clean = {
        key: str(raw.get(key) or "").strip()
        for key in allowed
    }
    if not clean["agent_name"] or not clean["user_message_id"]:
        return None
    if clean["execution_status"] not in {"succeeded", "blocked", "failed"}:
        return None
    if clean["agent_turn"] not in {"continue", "respond"}:
        return None
    if clean["skill_session"] not in {"keep", "release"}:
        return None
    return clean
