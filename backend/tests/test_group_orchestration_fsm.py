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
from app.api import group_chat as group_chat_module


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
        override_next_speaker=None,
        ignore_auto_expert_id="",
    )
    assert r.skip_host_dispatch is True
    assert r.direct_expert_id == "agent-a"


def test_resolve_no_skip_on_host_takeover():
    meta = {"skill_session_owner_id": "agent-a"}
    r = resolve_group_entry_route(
        meta_item=meta,
        agent_ids=["agent-a"],
        host_takeover_requested=True,
        override_next_speaker=None,
        ignore_auto_expert_id="",
    )
    assert r.skip_host_dispatch is False


def test_resolve_no_skip_on_ignore_auto_same_expert():
    meta = {"skill_session_owner_id": "agent-a"}
    r = resolve_group_entry_route(
        meta_item=meta,
        agent_ids=["agent-a"],
        host_takeover_requested=False,
        override_next_speaker=None,
        ignore_auto_expert_id="agent-a",
    )
    assert r.skip_host_dispatch is False


def test_locked_skill_id_for_expert_match():
    meta = {"skill_session_owner_id": "agent-a", "skill_session_skill_id": "sk1"}
    assert locked_skill_id_for_expert(meta, expert_agent_id="agent-a", expert_skill_ids=["sk1", "sk2"]) == "sk1"


def test_locked_skill_id_for_expert_wrong_owner():
    meta = {"skill_session_owner_id": "agent-a", "skill_session_skill_id": "sk1"}
    assert locked_skill_id_for_expert(meta, expert_agent_id="agent-b", expert_skill_ids=["sk1"]) is None


def test_skill_session_ended_by_marker():
    assert group_chat_module.skill_session_ended_by_expert_output("完成 [[SKILL_SESSION_END]]")
    assert group_chat_module.skill_session_ended_by_expert_output("【技能会话结束】")
    assert not group_chat_module.skill_session_ended_by_expert_output("仍在处理中")


def test_user_requests_exit_skill_session_phrases():
    assert user_requests_exit_skill_session("你的任务完成了")
    assert user_requests_exit_skill_session("任务已经完成了，请下一位")
    assert user_requests_exit_skill_session("交给主持人安排")
    assert not user_requests_exit_skill_session("根据内容生成文章 张雪峰")
    assert not user_requests_exit_skill_session("好")
