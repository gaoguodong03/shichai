import json

from app.agent.group_chat_skill_session import (
    apply_skill_result_to_orchestration_state,
    skill_result_from_content,
)

DEFAULT_NEXT_ACTION = {
    "handoff": "host",
    "resume": "none",
    "reason": "stage_completed",
    "instruction": "本轮专家回复已完成，请主持人判断下一步。",
}


def v2_payload(
    *,
    execution_status="succeeded",
    handoff="host",
    resume="none",
    reason="stage_completed",
    instruction="本轮专家回复已完成，请主持人判断下一步。",
    artifacts=None,
):
    payload = {
        "schema_version": "expert_final_state.v2",
        "execution_status": execution_status,
        "artifacts": artifacts or [],
        "next_action": {
            "handoff": handoff,
            "resume": resume,
            "reason": reason,
            "instruction": instruction,
        },
    }
    return payload


def test_skill_result_uses_script_stdout_next_action_from_tool_results():
    stdout_payload = v2_payload(
        handoff="user",
        resume="same_skill",
        reason="missing_input",
        instruction="已生成初稿，请补充目标受众。",
    )
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
                    "stdout": json.dumps(stdout_payload, ensure_ascii=False),
                },
            }
        ],
    )

    assert result["next_action"] == stdout_payload["next_action"]


def test_skill_result_uses_v2_hidden_state_block_without_workflow_state():
    hidden_payload = v2_payload(
        handoff="user",
        resume="same_skill",
        reason="stage_gate",
        instruction="请用户确认资料范围，确认后继续生成大纲。",
        artifacts=[{"type": "markdown", "name": "资料", "path": "materials.md"}],
    )

    result = skill_result_from_content(
        status="succeeded",
        content="资料已保存，请确认是否进入大纲。\n\n[[SKILL_SESSION_STATE]]\n"
        + json.dumps(hidden_payload, ensure_ascii=False)
        + "\n[[/SKILL_SESSION_STATE]]",
        artifacts=[],
        tool_results=[],
    )

    assert result["execution_status"] == "succeeded"
    assert result["content"] == "资料已保存，请确认是否进入大纲。"
    assert result["artifacts"] == [{"type": "markdown", "name": "资料", "path": "materials.md"}]
    assert result["next_action"] == hidden_payload["next_action"]


def test_hidden_state_block_with_workflow_state_fails_protocol():
    hidden_payload = v2_payload(
        handoff="user",
        resume="same_skill",
        reason="stage_gate",
        instruction="请用户确认资料范围，确认后继续生成大纲。",
    )
    hidden_payload["workflow_state"] = {
        "stage": "material_collection",
        "stage_status": "waiting_confirmation",
    }

    result = skill_result_from_content(
        status="succeeded",
        content="资料已保存，请确认是否进入大纲。\n\n[[SKILL_SESSION_STATE]]\n"
        + json.dumps(hidden_payload, ensure_ascii=False)
        + "\n[[/SKILL_SESSION_STATE]]",
        artifacts=[],
        tool_results=[],
    )

    assert result["execution_status"] == "failed"
    assert "专家隐藏状态块不符合平台协议" in result["content"]
    assert result["next_action"]["reason"] == "protocol_error"


def test_resume_same_skill_writes_continuation_from_v2_next_action_instruction():
    orchestration_state = {"host_scheduler": {"current_phase": "资料搜集", "next_speaker": "文档合著专家", "next_action": "旧指令"}}
    skill_result = {
        "execution_status": "succeeded",
        "content": "资料已保存，请确认是否进入大纲。",
        "artifacts": [],
        "next_action": {
            "handoff": "user",
            "resume": "same_skill",
            "reason": "stage_gate",
            "instruction": "请用户确认资料范围，确认后继续生成大纲。",
        },
    }

    changed = apply_skill_result_to_orchestration_state(
        orchestration_state,
        agent_name="文档合著专家",
        skill="doc-coauthor",
        skill_result=skill_result,
    )

    assert changed is True
    assert orchestration_state["continuation"] == {
        "owner_agent_name": "文档合著专家",
        "skill_policy": "keep",
        "skill": "doc-coauthor",
        "next_action": "请用户确认资料范围，确认后继续生成大纲。",
    }
    assert "host_scheduler" not in orchestration_state


def test_script_stdout_instruction_is_display_fallback_when_expert_text_is_empty():
    stdout_payload = v2_payload(instruction="脚本 stdout 原文结果。")
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
                    "stdout": json.dumps(stdout_payload, ensure_ascii=False),
                },
            }
        ],
    )

    assert result["content"] == "脚本 stdout 原文结果。"


def test_script_stdout_artifacts_are_skill_result_source_of_truth():
    stdout_payload = v2_payload(artifacts=[{"type": "file", "name": "报告", "path": "reports/report.md"}])
    result = skill_result_from_content(
        status="succeeded",
        content="模型综合后的产物说明。",
        artifacts=[],
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

    assert result["artifacts"] == [{"type": "file", "name": "报告", "path": "reports/report.md"}]


def test_skill_result_uses_hidden_state_block_and_strips_visible_content():
    hidden_payload = v2_payload(
        execution_status="blocked",
        handoff="user",
        resume="same_skill",
        reason="missing_input",
        instruction="缺少继续处理所需的信息。",
    )

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
    assert result["next_action"] == hidden_payload["next_action"]


def test_conflicting_script_stdout_and_hidden_state_block_fails_protocol():
    hidden_payload = v2_payload(instruction="交回主持人。")
    stdout_payload = v2_payload(
        handoff="user",
        resume="same_skill",
        reason="stage_gate",
        instruction="继续处理。",
    )

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
                    "stdout": json.dumps(stdout_payload, ensure_ascii=False),
                },
            }
        ],
    )

    assert result["execution_status"] == "failed"
    assert "互相冲突" in result["content"]
    assert result["next_action"]["reason"] == "protocol_error"


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
                    "stdout": '{"schema_version":"expert_final_state.v2","execution_status":"succeeded","artifacts":[]}',
                },
            }
        ],
    )

    assert result["execution_status"] == "failed"
    assert "脚本 stdout 不符合平台协议" in result["content"]
    assert result["next_action"]["reason"] == "protocol_error"


def test_invalid_hidden_state_block_becomes_failed_protocol_result():
    result = skill_result_from_content(
        status="succeeded",
        content='大纲已保存到工作区。\n\n[[SKILL_SESSION_STATE]]\n{"execution_status":"succeeded","content":"完成"}\n[[/SKILL_SESSION_STATE]]',
        artifacts=[],
        tool_results=[],
    )

    assert result["execution_status"] == "failed"
    assert "专家隐藏状态块不符合平台协议" in result["content"]
    assert result["next_action"]["reason"] == "protocol_error"


def test_plain_expert_content_does_not_require_next_action_block():
    result = skill_result_from_content(
        status="succeeded",
        content="文章已完成并保存到工作区。",
        artifacts=[],
        tool_results=[],
    )

    assert result["execution_status"] == "succeeded"
    assert result["content"] == "文章已完成并保存到工作区。"
    assert result["next_action"] == DEFAULT_NEXT_ACTION


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
                    "stdout": '{"schema_version":"expert_final_state.v2","execution_status":"succeeded","artifacts":[]}',
                },
                "error_log": {"message": "脚本 stdout 不符合标准 JSON 协议: 缺少 next_action"},
            }
        ],
    )

    assert result["execution_status"] == "failed"
    assert result["content"].startswith("当前步骤失败：run_skill_script")
    assert "缺少 next_action" in result["content"]
    assert result["next_action"] == DEFAULT_NEXT_ACTION


def test_failed_tool_result_content_excludes_execution_log_fields():
    result = skill_result_from_content(
        status="failed",
        content="模型没有返回可展示的文字内容。",
        artifacts=[],
        tool_results=[
            {
                "tool_call": {"id": "call-1", "name": "run_skill_script", "kind": "script"},
                "execution_status": "failed",
                "message": "脚本执行失败，请检查 Skill 输出协议。",
                "error_log": {
                    "message": "脚本执行失败，请检查 Skill 输出协议。",
                    "detail": "ValueError",
                    "stdout": "private stdout should stay in runtime logs",
                    "stderr": "private stderr should stay in runtime logs",
                    "raw_output": "private raw output should stay in runtime logs",
                },
            }
        ],
    )

    assert result["execution_status"] == "failed"
    assert result["content"] == "当前步骤失败：run_skill_script\n\n脚本执行失败，请检查 Skill 输出协议。"
    assert "stdout" not in result["content"]
    assert "stderr" not in result["content"]
    assert "raw_output" not in result["content"]


def test_resume_same_skill_writes_continuation_from_skill_result():
    orchestration_state = {
        "host_scheduler": {
            "current_phase": "写作中",
            "next_speaker": "写作专家",
            "next_action": "旧主持人指令",
        }
    }
    skill_result = {
        "execution_status": "succeeded",
        "content": "请补充目标受众。",
        "artifacts": [],
        "next_action": {
            "handoff": "user",
            "resume": "same_skill",
            "reason": "missing_input",
            "instruction": "请补充目标受众。",
        },
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
    assert "host_scheduler" not in orchestration_state


def test_resume_none_clears_existing_continuation():
    orchestration_state = {
        "host_scheduler": {
            "current_phase": "写作中",
            "next_speaker": "写作专家",
            "next_action": "旧主持人指令",
        },
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
        "next_action": {
            "handoff": "end",
            "resume": "none",
            "reason": "final_delivery",
            "instruction": "正文已完成。",
        },
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
