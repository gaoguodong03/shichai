from app.agent.agent_turn_controller import AgentTurnResult, apply_agent_turn
from app.agent.expert_completion_contract import AgentTurnDirective


def test_continue_returns_current_request_reentry_without_state():
    assert apply_agent_turn(AgentTurnDirective(action="continue")) is AgentTurnResult.CONTINUE_EXPERT


def test_respond_returns_control_to_host():
    assert apply_agent_turn(AgentTurnDirective(action="respond")) is AgentTurnResult.RETURN_TO_HOST
