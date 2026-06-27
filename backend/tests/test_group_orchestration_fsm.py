"""双轨编排 FSM：profile 与入口路由。"""
from app.agent.group_orchestration_fsm import (
    ORCHESTRATION_RECRUITMENT,
    ORCHESTRATION_SCENE,
    available_to_add_for_prompt,
    default_orchestration_profile_for_new_session,
    effective_orchestration_profile,
    locked_skill_id_for_expert,
    resolve_group_entry_route,
    user_requests_exit_skill_session,
)
from app.agent import skill_session_contract


def test_effective_profile_explicit():
    assert (
        effective_orchestration_profile({"orchestration_profile": "scene"}, agent_ids=["a"])
        == ORCHESTRATION_SCENE
    )
    assert (
        effective_orchestration_profile({"orchestration_profile": "recruitment"}, agent_ids=[])
        == ORCHESTRATION_RECRUITMENT
    )


def test_effective_profile_migration_empty_agents():
    assert effective_orchestration_profile({}, agent_ids=[]) == ORCHESTRATION_RECRUITMENT


def test_effective_profile_migration_nonempty_agents():
    assert effective_orchestration_profile({}, agent_ids=["x"]) == ORCHESTRATION_SCENE


def test_default_for_new_session():
    assert default_orchestration_profile_for_new_session(agent_ids=[]) == ORCHESTRATION_RECRUITMENT
    assert default_orchestration_profile_for_new_session(agent_ids=["a"]) == ORCHESTRATION_SCENE


def test_available_to_add_scene_empty():
    full = [{"agent_id": "ext-1", "name": "外"}]
    assert available_to_add_for_prompt(full, orchestration_profile=ORCHESTRATION_SCENE) == []
    assert len(available_to_add_for_prompt(full, orchestration_profile=ORCHESTRATION_RECRUITMENT)) == 1


def test_resolve_skip_host_when_skill_lock():
    meta = {"skill_session_owner_id": "agent-a"}
    r = resolve_group_entry_route(
        meta_item=meta,
        agent_ids=["agent-a"],
        host_takeover_requested=False,
        ignore_auto_agent_id="",
    )
    assert r.skip_host_dispatch is True
    assert r.direct_agent_id == "agent-a"


def test_resolve_no_skip_on_host_takeover():
    meta = {"skill_session_owner_id": "agent-a"}
    r = resolve_group_entry_route(
        meta_item=meta,
        agent_ids=["agent-a"],
        host_takeover_requested=True,
        ignore_auto_agent_id="",
    )
    assert r.skip_host_dispatch is False


def test_resolve_no_skip_on_ignore_auto_same_expert():
    meta = {"skill_session_owner_id": "agent-a"}
    r = resolve_group_entry_route(
        meta_item=meta,
        agent_ids=["agent-a"],
        host_takeover_requested=False,
        ignore_auto_agent_id="agent-a",
    )
    assert r.skip_host_dispatch is False


def test_locked_skill_id_for_expert_match():
    meta = {"skill_session_owner_id": "agent-a", "skill_session_skill_id": "sk1"}
    assert locked_skill_id_for_expert(meta, expert_agent_id="agent-a", expert_skill_ids=["sk1", "sk2"]) == "sk1"


def test_locked_skill_id_for_expert_wrong_owner():
    meta = {"skill_session_owner_id": "agent-a", "skill_session_skill_id": "sk1"}
    assert locked_skill_id_for_expert(meta, expert_agent_id="agent-b", expert_skill_ids=["sk1"]) is None


def test_skill_session_ended_by_marker():
    assert skill_session_contract.skill_session_ended_by_expert_output("完成 [[SKILL_SESSION_END]]")
    assert skill_session_contract.skill_session_ended_by_expert_output("【技能会话结束】")
    assert not skill_session_contract.skill_session_ended_by_expert_output("仍在处理中")


def test_strip_skill_session_state_blocks_over_true():
    raw = '说明文字\n\n[[SKILL_SESSION_STATE]]\n{"over": true}\n[[/SKILL_SESSION_STATE]]'
    over, stripped = skill_session_contract.strip_skill_session_state_blocks_and_get_over(raw)
    assert over is True
    assert "SKILL_SESSION_STATE" not in stripped
    assert "说明文字" in stripped


def test_strip_skill_session_state_blocks_over_false():
    raw = '还要再问\n[[SKILL_SESSION_STATE]]{"over": false}[[/SKILL_SESSION_STATE]]'
    over, stripped = skill_session_contract.strip_skill_session_state_blocks_and_get_over(raw)
    assert over is False
    assert stripped.strip() == "还要再问"


def test_strip_skill_session_state_blocks_alias_skill_session_over():
    raw = 'x\n[[SKILL_SESSION_STATE]]\n{"skill_session_over": true}\n[[/SKILL_SESSION_STATE]]'
    over, stripped = skill_session_contract.strip_skill_session_state_blocks_and_get_over(raw)
    assert over is True
    assert stripped.strip() == "x"


def test_strip_end_markers_for_display():
    t = "好了 [[SKILL_SESSION_END]]"
    assert "SESSION_END" not in skill_session_contract.strip_skill_session_end_markers_for_display(t)


def test_resolve_skill_session_state_reads_script_stdout_over():
    raw_tool_outputs = [
        '{"ok": true, "stdout": "{\\"ok\\": true, \\"skill_session_over\\": true}"}'
    ]
    resolved = skill_session_contract.resolve_skill_session_state(
        "已转写完成",
        raw_tool_outputs,
        tool_names=["run_skill_script_audio_transcription"],
    )
    assert resolved.over is True
    assert resolved.source == "script_stdout"
    assert resolved.display_content == "已转写完成"


def test_resolve_skill_session_state_reads_next_action_skill_session():
    raw_tool_outputs = [
        (
            '{"execution_status": "blocked", "result_code": "input.missing", '
            '"message": "缺少目标文件路径。", '
            '"next_action": {"agent_turn": "respond", "skill_session": "keep"}}'
        )
    ]
    resolved = skill_session_contract.resolve_skill_session_state(
        "缺少目标文件路径。",
        raw_tool_outputs,
        tool_names=["run_skill_script_demo"],
    )
    assert resolved.over is False
    assert resolved.source == "script_stdout"


def test_resolve_skill_session_state_next_action_beats_legacy_over():
    raw_tool_outputs = [
        (
            '{"ok": true, "skill_session_over": true, '
            '"next_action": {"agent_turn": "respond", "skill_session": "keep"}}'
        )
    ]
    resolved = skill_session_contract.resolve_skill_session_state(
        "还需要继续",
        raw_tool_outputs,
        tool_names=["run_skill_script_demo"],
    )
    assert resolved.over is False
    assert resolved.source == "script_stdout"


def test_resolve_skill_session_state_reads_travel_script_stdout_over():
    raw_tool_outputs = [
        (
            '{"ok": true, "stdout": "{\\"ok\\": true, '
            '\\"skill_session_over\\": true, '
            '\\"matched_records\\": 1, '
            '\\"description\\": \\"西安市住宿费标准：其他人员350元/人·天。\\"}"}'
        )
    ]
    resolved = skill_session_contract.resolve_skill_session_state(
        "西安市住宿费标准：其他人员350元/人·天。",
        raw_tool_outputs,
        tool_names=["run_skill_script_travel-expense-calculator"],
    )
    assert resolved.over is True
    assert resolved.source == "script_stdout"


def test_resolve_skill_session_state_ignores_done_final_for_session_lock():
    raw_tool_outputs = ['{"ok": true, "stdout": "{\\"ok\\": true, \\"done\\": true, \\"final\\": true}"}']
    resolved = skill_session_contract.resolve_skill_session_state("脚本完成", raw_tool_outputs)
    assert resolved.over is None
    assert resolved.source == "none"


def test_resolve_skill_session_state_ignores_non_script_tool_over_when_named():
    raw_tool_outputs = [
        '{"ok": true, "stdout": "{\\"ok\\": true, \\"skill_session_over\\": true}"}'
    ]
    resolved = skill_session_contract.resolve_skill_session_state(
        "API 返回完成",
        raw_tool_outputs,
        tool_names=["call_api"],
    )
    assert resolved.over is None
    assert resolved.source == "none"


def test_resolve_skill_session_state_false_assistant_block_beats_script_stdout_true():
    raw_tool_outputs = [
        '{"ok": true, "stdout": "{\\"ok\\": true, \\"skill_session_over\\": true}"}'
    ]
    raw = '还需要你确认\n[[SKILL_SESSION_STATE]]{"over": false}[[/SKILL_SESSION_STATE]]'
    resolved = skill_session_contract.resolve_skill_session_state(raw, raw_tool_outputs)
    assert resolved.over is False
    assert resolved.source == "assistant_state_block"
    assert resolved.display_content == "还需要你确认"


def test_resolve_skill_session_state_script_false_beats_assistant_block_true():
    raw_tool_outputs = [
        '{"ok": true, "stdout": "{\\"ok\\": true, \\"skill_session_over\\": false}"}'
    ]
    raw = '已完成\n[[SKILL_SESSION_STATE]]{"over": true}[[/SKILL_SESSION_STATE]]'
    resolved = skill_session_contract.resolve_skill_session_state(raw, raw_tool_outputs)
    assert resolved.over is False
    assert resolved.source == "script_stdout"
    assert resolved.display_content == "已完成"
    assert resolved.signals is not None
    assert resolved.signals.assistant_state_block is True
    assert resolved.signals.script_stdout is False


def test_resolve_skill_session_state_script_false_beats_legacy_marker():
    raw_tool_outputs = [
        '{"ok": true, "stdout": "{\\"ok\\": true, \\"skill_session_over\\": false}"}'
    ]
    resolved = skill_session_contract.resolve_skill_session_state("完成 [[SKILL_SESSION_END]]", raw_tool_outputs)
    assert resolved.over is False
    assert resolved.source == "script_stdout"
    assert resolved.signals is not None
    assert resolved.signals.legacy_end_marker is True
    assert "SKILL_SESSION_END" not in resolved.display_content


def test_resolve_skill_session_state_legacy_marker_releases_without_explicit_signal():
    resolved = skill_session_contract.resolve_skill_session_state("完成 [[SKILL_SESSION_END]]")
    assert resolved.over is True
    assert resolved.source == "legacy_end_marker"
    assert "SKILL_SESSION_END" not in resolved.display_content


def test_resolve_skill_session_state_explicit_script_false_keeps_lock():
    raw_tool_outputs = [
        (
            '{"ok": true, "stdout": "{\\"ok\\": true, '
            '\\"code\\": \\"transcribed\\", '
            '\\"skill_session_over\\": false, '
            '\\"text\\": \\"转写文本\\"}"}'
        )
    ]
    resolved = skill_session_contract.resolve_skill_session_state(
        "转写文本",
        raw_tool_outputs,
        tool_names=["run_skill_script_audio-transcription"],
    )
    assert resolved.over is False
    assert resolved.source == "script_stdout"


def test_user_requests_exit_skill_session_phrases():
    assert user_requests_exit_skill_session("你的任务完成了")
    assert user_requests_exit_skill_session("任务已经完成了，请下一位")
    assert user_requests_exit_skill_session("交给主持人安排")
    assert not user_requests_exit_skill_session("根据内容生成文章 张雪峰")
    assert not user_requests_exit_skill_session("好")
