import json

import pytest

from app.agent.group_chat_skill_session import (
    ExpertFinalStateProtocolError,
    apply_skill_result_to_orchestration_state,
    message_from_expert_final_state,
    select_expert_final_state,
    skill_result_from_expert_final_state,
)


def v2_payload(
    *,
    content="本轮专家回复已完成。",
    execution_status="succeeded",
    artifacts=None,
    agent_turn="respond",
    skill_session="release",
):
    return {
        "schema_version": "expert_final_state.v2",
        "execution_status": execution_status,
        "message": {
            "content": content,
            "attachments": [],
            "artifacts": artifacts or [],
        },
        "next_action": {
            "agent_turn": agent_turn,
            "skill_session": skill_session,
        },
    }


def test_select_expert_final_state_from_finalizer_content():
    payload = v2_payload(
        content="资料已整理完成。",
        artifacts=[{"type": "markdown", "name": "资料", "path": "materials.md"}],
    )

    final_state = select_expert_final_state(final_content=json.dumps(payload, ensure_ascii=False), tool_results=[])

    assert message_from_expert_final_state(final_state) == {
        "content": "资料已整理完成。",
        "artifacts": [{"type": "markdown", "name": "资料", "path": "materials.md"}],
    }
    assert skill_result_from_expert_final_state(final_state) == {
        "execution_status": "succeeded",
        "next_action": {"agent_turn": "respond", "skill_session": "release"},
    }


def test_select_expert_final_state_from_script_stdout_tool_result():
    stdout_payload = v2_payload(
        content="脚本已生成报告。",
        artifacts=[{"type": "file", "name": "报告", "path": "reports/report.md"}],
        skill_session="keep",
    )

    final_state = select_expert_final_state(
        final_content="",
        tool_results=[
            {
                "tool_call": {"id": "call-1", "name": "run_skill_script", "kind": "script"},
                "execution_status": "succeeded",
                "message": "脚本完成",
                "output": {
                    "stdout": json.dumps(stdout_payload, ensure_ascii=False),
                },
            }
        ],
    )

    assert final_state.message.content == "脚本已生成报告。"
    assert final_state.message.artifacts[0].path == "reports/report.md"
    assert final_state.next_action.skill_session == "keep"


def test_conflicting_finalizer_and_script_stdout_fails_protocol():
    with pytest.raises(ExpertFinalStateProtocolError, match="互相冲突"):
        select_expert_final_state(
            final_content=json.dumps(v2_payload(content="finalizer"), ensure_ascii=False),
            tool_results=[
                {
                    "tool_call": {"id": "call-1", "name": "run_skill_script", "kind": "script"},
                    "execution_status": "succeeded",
                    "message": "脚本完成",
                    "output": {
                        "stdout": json.dumps(v2_payload(content="script"), ensure_ascii=False),
                    },
                }
            ],
        )


def test_invalid_script_stdout_fails_protocol():
    with pytest.raises(ExpertFinalStateProtocolError, match="脚本 stdout 不符合平台协议"):
        select_expert_final_state(
            final_content="",
            tool_results=[
                {
                    "tool_call": {"id": "call-1", "name": "run_skill_script", "kind": "script"},
                    "execution_status": "succeeded",
                    "message": "脚本完成",
                    "output": {
                        "stdout": '{"schema_version":"expert_final_state.v2","execution_status":"succeeded","artifacts":[]}',
                    },
                }
            ],
        )


def test_keep_skill_session_writes_vnext_continuation_message():
    orchestration_state = {"host_scheduler": {"current_phase": "资料搜集", "message": {"content": "旧指令"}}}
    skill_result = {
        "execution_status": "succeeded",
        "next_action": {"agent_turn": "respond", "skill_session": "keep"},
    }
    message = {
        "content": "请用户确认资料范围，确认后继续生成大纲。",
        "artifacts": [{"type": "markdown", "name": "资料", "path": "materials.md"}],
    }

    changed = apply_skill_result_to_orchestration_state(
        orchestration_state,
        agent_name="文档合著专家",
        skill="doc-coauthor",
        skill_result=skill_result,
        message=message,
    )

    assert changed is True
    assert orchestration_state["continuation"] == {
        "owner_agent_name": "文档合著专家",
        "skill_session": "keep",
        "skill": "doc-coauthor",
        "message": message,
    }
    assert "host_scheduler" not in orchestration_state


def test_release_skill_session_clears_existing_continuation():
    orchestration_state = {
        "host_scheduler": {"current_phase": "写作中", "message": {"content": "旧主持人指令"}},
        "continuation": {
            "owner_agent_name": "写作专家",
            "skill_session": "keep",
            "skill": "article-writer",
            "message": {"content": "旧动作"},
        },
    }
    skill_result = {
        "execution_status": "succeeded",
        "next_action": {"agent_turn": "respond", "skill_session": "release"},
    }

    changed = apply_skill_result_to_orchestration_state(
        orchestration_state,
        agent_name="写作专家",
        skill="article-writer",
        skill_result=skill_result,
    )

    assert changed is True
    assert "continuation" not in orchestration_state
    assert "host_scheduler" not in orchestration_state
