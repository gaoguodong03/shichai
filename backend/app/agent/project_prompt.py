"""Project-level prompt access for collaborative agent runtimes."""
from __future__ import annotations

from typing import Any, Mapping

from app.agent.platform_prompts import render_platform_prompt


def get_default_project_system_prompt() -> str:
    """Return the editable project prompt used when settings have no saved field."""
    return render_platform_prompt("project.system.default.v1", {})


def get_project_system_prompt(app_settings: Mapping[str, Any] | None) -> str:
    """Return the normalized project prompt stored in application settings."""
    if not isinstance(app_settings, Mapping):
        return ""
    return str(app_settings.get("system_prompt") or "").strip()
