from app.agent.group_entry_router import resolve_group_entry_route
from app.agent.session_contracts import GroupChatRequest


def _request(message: str = "任意自然语言", target_agent_name: str | None = None) -> GroupChatRequest:
    return GroupChatRequest.model_validate(
        {"message_id": "msg-user-1", "message": message, "target_agent_name": target_agent_name}
    )


def test_explicit_target_routes_without_touching_skill_sessions():
    state = {"skill_sessions": {"检索专家": {"skill": "research"}}}

    decision = resolve_group_entry_route(
        request=_request(target_agent_name="写作专家"),
        orchestration_state=state,
        agent_names=["检索专家", "写作专家"],
        default_next_action="默认动作",
    )

    assert decision == {
        "next_speaker": "写作专家",
        "next_action": "任意自然语言",
        "route_source": "target_agent",
    }
    assert state == {"skill_sessions": {"检索专家": {"skill": "research"}}}


def test_persisted_host_target_routes_without_clearing_other_skill_sessions():
    state = {
        "skill_sessions": {"检索专家": {"skill": "research"}},
        "host_scheduler": {
            "current_phase": "写作",
            "message": {"content": "请写大纲", "target_agent_name": "写作专家"},
        },
    }

    decision = resolve_group_entry_route(
        request=_request(),
        orchestration_state=state,
        agent_names=["检索专家", "写作专家"],
        default_next_action="默认动作",
    )

    assert decision == {
        "next_speaker": "写作专家",
        "next_action": "请写大纲",
        "route_source": "host_scheduler_state",
    }
    assert state["skill_sessions"] == {"检索专家": {"skill": "research"}}


def test_no_structured_target_returns_none_even_with_skill_binding():
    state = {"skill_sessions": {"检索专家": {"skill": "research"}}}

    decision = resolve_group_entry_route(
        request=_request("用户可以用任何方式表达"),
        orchestration_state=state,
        agent_names=["检索专家", "写作专家"],
        default_next_action="默认动作",
    )

    assert decision is None
    assert state == {"skill_sessions": {"检索专家": {"skill": "research"}}}


def test_succeeded_release_turn_does_not_restore_stale_expert_target():
    state = {
        "host_scheduler": {
            "current_phase": "写作",
            "message": {"content": "请写大纲", "target_agent_name": "写作专家"},
        },
        "last_expert_turn": {
            "agent_name": "写作专家",
            "skill": "writer",
            "execution_status": "succeeded",
            "agent_turn": "respond",
            "skill_session": "release",
            "message_id": "msg-expert-1",
            "user_message_id": "msg-user-1",
        },
    }

    decision = resolve_group_entry_route(
        request=GroupChatRequest.model_validate(
            {"message_id": "msg-user-2", "message": "继续下一步"}
        ),
        orchestration_state=state,
        agent_names=["写作专家"],
        default_next_action="默认动作",
    )

    assert decision is None


def test_waiting_keep_turn_can_restore_same_expert_for_new_user_message():
    state = {
        "host_scheduler": {
            "current_phase": "等待信息",
            "message": {"content": "请补充目标篇幅", "target_agent_name": "写作专家"},
        },
        "last_expert_turn": {
            "agent_name": "写作专家",
            "skill": "writer",
            "execution_status": "blocked",
            "agent_turn": "respond",
            "skill_session": "keep",
            "message_id": "msg-expert-1",
            "user_message_id": "msg-user-1",
        },
    }

    decision = resolve_group_entry_route(
        request=GroupChatRequest.model_validate(
            {"message_id": "msg-user-2", "message": "目标篇幅 1000 字"}
        ),
        orchestration_state=state,
        agent_names=["写作专家"],
        default_next_action="默认动作",
    )

    assert decision == {
        "next_speaker": "写作专家",
        "next_action": "请补充目标篇幅",
        "route_source": "host_scheduler_state",
    }


def test_same_user_message_does_not_restore_stale_expert_target():
    state = {
        "host_scheduler": {
            "current_phase": "写作",
            "message": {"content": "请写大纲", "target_agent_name": "写作专家"},
        },
        "last_expert_turn": {
            "agent_name": "写作专家",
            "skill": "writer",
            "execution_status": "succeeded",
            "agent_turn": "respond",
            "skill_session": "keep",
            "message_id": "msg-expert-1",
            "user_message_id": "msg-user-1",
        },
    }

    decision = resolve_group_entry_route(
        request=GroupChatRequest.model_validate(
            {"message_id": "msg-user-1", "message": "请写大纲"}
        ),
        orchestration_state=state,
        agent_names=["写作专家"],
        default_next_action="默认动作",
    )

    assert decision is None
