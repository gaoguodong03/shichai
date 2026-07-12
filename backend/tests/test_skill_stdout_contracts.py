from __future__ import annotations

from app.agent.skill_session_contract import GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION


def test_skill_session_instruction_uses_current_stdout_fields():
    assert "schema_version" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "execution_status" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "message" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "next_action" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "expert_final_state.v2" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "agent_turn" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "skill_session" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "[[SKILL_SESSION_STATE]]" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "handoff" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "resume" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "workflow_state" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "result_code" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
