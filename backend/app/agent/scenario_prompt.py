"""Scenario-level prompt access for resource draft initialization."""
from __future__ import annotations

from app.agent.platform_prompts import render_platform_prompt


def get_default_scenario_system_prompt() -> str:
    """Return the editable default prompt for a new scenario resource."""
    return render_platform_prompt("scenario.system.default.v1", {})
