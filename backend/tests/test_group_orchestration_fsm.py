from app.agent.group_orchestration_fsm import resolve_group_entry_route
from app.agent.session_contracts import GroupChatRequest


def _request(message: str = "继续", target_agent_name: str | None = None) -> GroupChatRequest:
    return GroupChatRequest.model_validate(
        {
            "message": message,
            "client_message_id": "client-1",
            "target_agent_name": target_agent_name,
        }
    )


def test_target_agent_wins_and_clears_continuation():
    orchestration_state = {
        "continuation": {
            "owner_agent_name": "旧专家",
            "skill_policy": "keep",
            "skill": "old-skill",
            "next_action": "旧动作",
        }
    }

    speaker, action, changed = resolve_group_entry_route(
        request=_request(target_agent_name="写作专家"),
        orchestration_state=orchestration_state,
        agent_names=["写作专家", "旧专家"],
        host_name="四九",
        default_next_action="默认动作",
    )

    assert (speaker, action, changed) == ("写作专家", "默认动作", True)
    assert "continuation" not in orchestration_state


def test_host_scheduler_wins_over_conflicting_continuation_and_clears_it():
    orchestration_state = {
        "host_scheduler": {
            "current_phase": "阶段2",
            "next_speaker": "写作专家",
            "next_action": "请写大纲",
        },
        "continuation": {
            "owner_agent_name": "检索专家",
            "skill_policy": "keep",
            "skill": "search",
            "next_action": "继续检索",
        },
    }

    speaker, action, changed = resolve_group_entry_route(
        request=_request(),
        orchestration_state=orchestration_state,
        agent_names=["写作专家", "检索专家"],
        host_name="四九",
        default_next_action="默认动作",
    )

    assert (speaker, action, changed) == ("写作专家", "请写大纲", True)
    assert "continuation" not in orchestration_state


def test_valid_continuation_routes_to_owner_when_no_scheduler_wins():
    orchestration_state = {
        "continuation": {
            "owner_agent_name": "检索专家",
            "skill_policy": "release",
            "next_action": "继续整理结果",
        }
    }

    speaker, action, changed = resolve_group_entry_route(
        request=_request(),
        orchestration_state=orchestration_state,
        agent_names=["写作专家", "检索专家"],
        host_name="四九",
        default_next_action="默认动作",
    )

    assert (speaker, action, changed) == ("检索专家", "继续整理结果", False)
    assert "continuation" in orchestration_state


def test_invalid_continuation_is_cleared_and_host_scheduler_can_run():
    orchestration_state = {
        "continuation": {
            "owner_agent_name": "已删除专家",
            "skill_policy": "keep",
            "skill": "old-skill",
            "next_action": "旧动作",
        }
    }

    speaker, action, changed = resolve_group_entry_route(
        request=_request(),
        orchestration_state=orchestration_state,
        agent_names=["写作专家"],
        host_name="四九",
        default_next_action="默认动作",
    )

    assert (speaker, action, changed) == ("", "默认动作", True)
    assert "continuation" not in orchestration_state


def test_message_text_host_mention_does_not_clear_continuation():
    orchestration_state = {
        "continuation": {
            "owner_agent_name": "写作专家",
            "skill_policy": "keep",
            "skill": "write",
            "next_action": "继续写",
        }
    }

    speaker, action, changed = resolve_group_entry_route(
        request=_request("@四九 请重新调度"),
        orchestration_state=orchestration_state,
        agent_names=["写作专家"],
        host_name="四九",
        default_next_action="默认动作",
    )

    assert (speaker, action, changed) == ("写作专家", "继续写", False)
    assert "continuation" in orchestration_state
