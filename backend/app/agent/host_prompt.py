"""Host long-term prompt defaults shared by settings and runtime snapshots."""
from __future__ import annotations

from app.agent.platform_prompts import render_platform_prompt


def get_default_host_system_prompt() -> str:
    """Return the editable pure-dispatch host prompt."""
    return render_platform_prompt("host.system.default.v1", {})
