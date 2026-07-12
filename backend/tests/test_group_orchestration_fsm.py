from app.agent.group_orchestration_fsm import resolve_group_entry_route
from app.agent.session_contracts import GroupChatRequest


def _request(message: str = "继续", target_agent_name: str | None = None) -> GroupChatRequest:
    return GroupChatRequest.model_validate(
        {"message_id": "msg-user-1", "message": message, "target_agent_name": target_agent_name}
    )


def test_target_agent_wins_and_clears_continuation():
    orchestration_state = {
        "continuation": {
            "owner_agent_name": "旧专家",
            "skill_session": "keep",
            "skill": "old-skill",
            "message": {"content": "旧动作"},
        }
    }

    decision, changed = resolve_group_entry_route(
        request=_request(target_agent_name="写作专家"),
        orchestration_state=orchestration_state,
        agent_names=["写作专家", "旧专家"],
        host_name="四九",
        default_next_action="默认动作",
    )

    assert decision == {
        "next_speaker": "写作专家",
        "next_action": "继续",
        "route_source": "target_agent",
        "skill_session": "none",
        "skill": None,
    }
    assert changed is True
    assert "continuation" not in orchestration_state


def test_host_scheduler_message_wins_over_conflicting_continuation():
    orchestration_state = {
        "host_scheduler": {
            "current_phase": "阶段2",
            "message": {"content": "请写大纲", "target_agent_name": "写作专家"},
        },
        "continuation": {
            "owner_agent_name": "检索专家",
            "skill_session": "keep",
            "skill": "search",
            "message": {"content": "继续检索"},
        },
    }

    decision, changed = resolve_group_entry_route(
        request=_request(),
        orchestration_state=orchestration_state,
        agent_names=["写作专家", "检索专家"],
        host_name="四九",
        default_next_action="默认动作",
    )

    assert decision == {
        "next_speaker": "写作专家",
        "next_action": "请写大纲",
        "route_source": "host_scheduler_state",
        "skill_session": "none",
        "skill": None,
    }
    assert changed is True
    assert "continuation" not in orchestration_state


def test_valid_continuation_routes_to_owner_with_kept_skill():
    orchestration_state = {
        "continuation": {
            "owner_agent_name": "检索专家",
            "skill_session": "keep",
            "skill": "search",
            "message": {"content": "继续整理结果"},
        }
    }

    decision, changed = resolve_group_entry_route(
        request=_request(),
        orchestration_state=orchestration_state,
        agent_names=["写作专家", "检索专家"],
        host_name="四九",
        default_next_action="默认动作",
    )

    assert decision == {
        "next_speaker": "检索专家",
        "next_action": "继续整理结果",
        "route_source": "continuation",
        "skill_session": "keep",
        "skill": "search",
    }
    assert changed is False


def test_invalid_continuation_is_cleared():
    orchestration_state = {
        "continuation": {
            "owner_agent_name": "已删除专家",
            "skill_session": "keep",
            "skill": "old-skill",
            "message": {"content": "旧动作"},
        }
    }

    decision, changed = resolve_group_entry_route(
        request=_request(),
        orchestration_state=orchestration_state,
        agent_names=["写作专家"],
        host_name="四九",
        default_next_action="默认动作",
    )

    assert decision is None
    assert changed is True
    assert "continuation" not in orchestration_state
