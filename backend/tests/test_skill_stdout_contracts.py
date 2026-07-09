from __future__ import annotations

from app.agent.skill_session_contract import GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION


def test_skill_session_instruction_uses_current_stdout_fields():
    assert "`execution_status`、`content`、`artifacts`、`next_action`" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "result_code" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "`message`" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
