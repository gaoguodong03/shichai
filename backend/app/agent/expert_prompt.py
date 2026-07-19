"""Expert long-term prompt defaults shared by routing and execution."""
from __future__ import annotations

from typing import Any, Mapping

from app.agent.platform_prompts import render_platform_prompt


def get_default_expert_system_prompt() -> str:
    """Return the editable cross-scene expert prompt."""
    return render_platform_prompt("expert.system.default.v1", {})


def get_expert_system_prompt(agent_profile: Mapping[str, Any] | None) -> str:
    """Return the configured expert prompt or the editable default."""
    if isinstance(agent_profile, Mapping):
        configured = str(agent_profile.get("system_prompt") or "").strip()
        if configured:
            return configured
    return get_default_expert_system_prompt()
