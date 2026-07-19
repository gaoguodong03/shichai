"""Shared project and scenario prompt assembly for one session."""
from __future__ import annotations

from typing import Any, Mapping

from app.agent.project_prompt import get_project_system_prompt


def get_session_scenario_prompt(session_item: Mapping[str, Any] | None) -> str:
    """Return the immutable scenario prompt snapshot stored on the session."""
    if not isinstance(session_item, Mapping):
        return ""
    return str(session_item.get("scenario_prompt") or "").strip()


def build_shared_session_prompt(
    app_settings: Mapping[str, Any] | None,
    session_item: Mapping[str, Any] | None,
) -> str:
    """Build project-first shared rules for host and expert calls."""
    parts = (
        get_project_system_prompt(app_settings),
        get_session_scenario_prompt(session_item),
    )
    return "\n\n".join(part for part in parts if part)
