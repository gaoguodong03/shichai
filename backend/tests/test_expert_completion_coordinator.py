from app.agent.agent_turn_controller import AgentTurnResult
from app.agent.expert_completion_contract import parse_expert_completion
from app.agent.expert_completion_coordinator import coordinate_expert_completion


def test_coordinator_applies_output_before_skill_session_and_agent_turn(monkeypatch):
    from app.agent import expert_completion_coordinator as coordinator

    order: list[str] = []

    def _publish(**_kwargs):
        order.append("output")
        return None

    def _apply_skill(_state, **_kwargs):
        order.append("skill_session")
        return False

    def _apply_turn(_directive):
        order.append("agent_turn")
        return AgentTurnResult.CONTINUE_EXPERT

    monkeypatch.setattr(coordinator, "publish_expert_output", _publish)
    monkeypatch.setattr(coordinator, "apply_skill_session", _apply_skill)
    monkeypatch.setattr(coordinator, "apply_agent_turn", _apply_turn)
    completion = parse_expert_completion(
        '{"execution_status":"succeeded","message":{"content":"阶段结果"},'
        '"next_action":{"agent_turn":"continue","skill_session":"keep"}}'
    )

    result = coordinate_expert_completion(
        completion=completion,
        orchestration_state={},
        agent_name="检索专家",
        skill="research",
        message_id="msg-1",
        created_at="2026071900000000",
        group_session_id="session-1",
        messages=[],
        session_definitions={},
        session_item={},
        tool_results=[],
    )

    assert order == ["output", "skill_session", "agent_turn"]
    assert result.agent_turn is AgentTurnResult.CONTINUE_EXPERT
