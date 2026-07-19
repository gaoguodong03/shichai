"""Current-request expert turn control."""
from __future__ import annotations

from enum import Enum

from app.agent.expert_completion_contract import AgentTurnDirective


class AgentTurnResult(str, Enum):
    CONTINUE_EXPERT = "continue_expert"
    RETURN_TO_HOST = "return_to_host"


def apply_agent_turn(directive: AgentTurnDirective) -> AgentTurnResult:
    """Resolve the next in-request owner without reading or writing session state."""
    if directive.action == "continue":
        return AgentTurnResult.CONTINUE_EXPERT
    return AgentTurnResult.RETURN_TO_HOST
