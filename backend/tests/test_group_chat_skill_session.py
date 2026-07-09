import json

from app.agent.group_chat_skill_session import (
    apply_skill_result_to_orchestration_state,
    skill_result_from_content,
)


def test_skill_result_uses_script_stdout_next_action_from_tool_results():
    result = skill_result_from_content(
        status="succeeded",
        content="已生成初稿，请补充目标受众。",
        artifacts=[],
        tool_results=[
            {
                "tool_call": {"id": "call-1", "name": "run_skill_script", "kind": "script"},
                "execution_status": "succeeded",
                "message": "脚本完成",
                "output": {
                    "stdout": '{"execution_status":"succeeded","content":"已生成初稿，请补充目标受众。","artifacts":[],"next_action":{"agent_turn":"respond","skill_session":"keep"}}',
                },
            }
        ],
    )

    assert result["next_action"] == {"agent_turn": "respond", "skill_session": "keep"}


def test_skill_result_uses_hidden_state_block_and_strips_visible_content():
    hidden_payload = {
        "execution_status": "blocked",
        "content": "缺少继续处理所需的信息。",
        "artifacts": [],
        "next_action": {"agent_turn": "respond", "skill_session": "keep"},
    }

    result = skill_result_from_content(
        status="succeeded",
        content="请补充目标受众。\n\n[[SKILL_SESSION_STATE]]\n"
        + json.dumps(hidden_payload, ensure_ascii=False)
        + "\n[[/SKILL_SESSION_STATE]]",
        artifacts=[],
        tool_results=[],
    )

    assert result["execution_status"] == "blocked"
    assert result["content"] == "请补充目标受众。"
    assert result["next_action"] == {"agent_turn": "respond", "skill_session": "keep"}


def test_conflicting_script_stdout_and_hidden_state_block_fails_protocol():
    hidden_payload = {
        "execution_status": "succeeded",
        "content": "交回主持人。",
        "artifacts": [],
        "next_action": {"agent_turn": "respond", "skill_session": "release"},
    }

    result = skill_result_from_content(
        status="succeeded",
        content="脚本已完成。\n\n[[SKILL_SESSION_STATE]]\n"
        + json.dumps(hidden_payload, ensure_ascii=False)
        + "\n[[/SKILL_SESSION_STATE]]",
        artifacts=[],
        tool_results=[
            {
                "tool_call": {"id": "call-1", "name": "run_skill_script", "kind": "script"},
                "execution_status": "succeeded",
                "message": "脚本完成",
                "output": {
                    "stdout": '{"execution_status":"succeeded","content":"继续处理。","artifacts":[],"next_action":{"agent_turn":"continue","skill_session":"keep"}}',
                },
            }
        ],
    )

    assert result["execution_status"] == "failed"
    assert "互相冲突" in result["content"]
    assert result["next_action"] == {"agent_turn": "respond", "skill_session": "release"}


def test_invalid_script_stdout_becomes_failed_skill_result():
    result = skill_result_from_content(
        status="succeeded",
        content="模型没有返回可展示的文字内容。",
        artifacts=[],
        tool_results=[
            {
                "tool_call": {"id": "call-1", "name": "run_skill_script", "kind": "script"},
                "execution_status": "succeeded",
                "message": "脚本完成",
                "output": {
                    "stdout": '{"execution_status":"succeeded","content":"缺少 next_action","artifacts":[]}',
                },
            }
        ],
    )

    assert result["execution_status"] == "failed"
    assert "脚本 stdout 不符合平台协议" in result["content"]
    assert result["next_action"] == {"agent_turn": "respond", "skill_session": "release"}


def test_failed_tool_message_becomes_skill_result_content():
    result = skill_result_from_content(
        status="failed",
        content="模型没有返回可展示的文字内容。",
        artifacts=[],
        tool_results=[
            {
                "tool_call": {"id": "call-1", "name": "run_skill_script", "kind": "script"},
                "execution_status": "failed",
                "message": "脚本 stdout 不符合标准 JSON 协议: 缺少 next_action",
                "output": {
                    "stdout": '{"execution_status":"succeeded","content":"缺少 next_action","artifacts":[]}',
                },
                "error_log": {"message": "脚本 stdout 不符合标准 JSON 协议: 缺少 next_action"},
            }
        ],
    )

    assert result["execution_status"] == "failed"
    assert result["content"].startswith("当前步骤失败：run_skill_script")
    assert "缺少 next_action" in result["content"]
    assert result["next_action"] == {"agent_turn": "respond", "skill_session": "release"}


def test_keep_skill_session_writes_continuation_from_skill_result():
    orchestration_state = {}
    skill_result = {
        "execution_status": "succeeded",
        "content": "请补充目标受众。",
        "artifacts": [],
        "next_action": {"agent_turn": "respond", "skill_session": "keep"},
    }

    changed = apply_skill_result_to_orchestration_state(
        orchestration_state,
        agent_name="写作专家",
        skill="article-writer",
        skill_result=skill_result,
    )

    assert changed is True
    assert orchestration_state["continuation"] == {
        "owner_agent_name": "写作专家",
        "skill_policy": "keep",
        "skill": "article-writer",
        "next_action": "请补充目标受众。",
    }


def test_release_skill_session_clears_existing_continuation():
    orchestration_state = {
        "continuation": {
            "owner_agent_name": "写作专家",
            "skill_policy": "keep",
            "skill": "article-writer",
            "next_action": "旧动作",
        }
    }
    skill_result = {
        "execution_status": "succeeded",
        "content": "正文已完成。",
        "artifacts": [],
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
