from app.agent.group_chat_soft_stop import expert_turn_budget_exceeded


def test_expert_turn_budget_exceeded_uses_contract_limit():
    assert expert_turn_budget_exceeded(32) is False
    assert expert_turn_budget_exceeded(33) is True
