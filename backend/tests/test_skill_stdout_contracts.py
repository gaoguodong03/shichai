from __future__ import annotations

from app.agent.skill_session_contract import GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION


def test_skill_session_instruction_uses_current_stdout_fields():
    assert "`schema_version`、`execution_status`、`artifacts`、`next_action`" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "stdout 不再输出 `content`" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "MCP / HTTP / workspace 文件工具执行后，必须继续完成专家最终回复" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "[[SKILL_SESSION_STATE]]" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "expert_final_state.v2" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "handoff" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "resume" in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "workflow_state" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "succeeded|blocked|failed" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "respond|continue" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "keep|release" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "result_code" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
    assert "`message`" not in GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION
