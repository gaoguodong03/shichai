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
