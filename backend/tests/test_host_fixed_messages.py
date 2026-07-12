from app.agent.group_chat_host_messages import (
    HOST_ZERO_EXPERT_RECOMMENDATION,
    _build_host_recommendation_message,
    _build_host_scheduler_message,
)
from app.agent.message_contracts import ChatMessageRecord


def test_host_scheduler_message_preserves_standard_message_body():
    msg = _build_host_scheduler_message(
        skill="group-host-webnovel",
        message={
            "content": "请撰写正文。",
            "target_agent_name": "文字创作专家",
            "attachments": [{"type": "workspace_file", "path": "materials/outline.md"}],
        },
        host_agent_name="四九",
    )

    assert msg["message"] == {
        "content": "请撰写正文。",
        "target_agent_name": "文字创作专家",
        "attachments": [{"type": "workspace_file", "path": "materials/outline.md"}],
    }
    assert msg["speaker"]["skill"] == "group-host-webnovel"
    assert "routing" not in msg
    ChatMessageRecord.model_validate(msg)


def test_host_wait_message_has_no_synthetic_default_copy():
    msg = _build_host_scheduler_message(
        skill="group-host-webnovel",
        message={"content": "请用户明确报告目标受众和篇幅。"},
        host_agent_name="四九",
    )

    assert msg["message"] == {"content": "请用户明确报告目标受众和篇幅。"}
    ChatMessageRecord.model_validate(msg)


def test_host_recommendation_uses_current_contract_copy():
    msg = _build_host_recommendation_message(
        skill="group-host-webnovel",
        content="",
        picked=["文字创作专家", "信息检索专家"],
    )

    assert msg["message"]["content"] == HOST_ZERO_EXPERT_RECOMMENDATION
    assert msg["speaker"]["skill"] == "group-host-webnovel"
    ChatMessageRecord.model_validate(msg)
