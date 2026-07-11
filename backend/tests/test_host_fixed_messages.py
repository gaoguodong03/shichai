from app.agent.group_chat_host_messages import (
    HOST_END_MESSAGE,
    HOST_USER_PAUSE_MESSAGE,
    HOST_ZERO_EXPERT_RECOMMENDATION,
    _build_host_next_speaker_message,
    _build_host_pause_message,
    _build_host_recommendation_message,
)
from app.agent.message_contracts import ChatMessageRecord


def _content(msg):
    return msg["message"]["content"]


def test_host_next_speaker_uses_nested_message_contract():
    msg = _build_host_next_speaker_message(
        skill="group-host-webnovel",
        next_speaker="文字创作专家",
        agent_map={"文字创作专家": {"name": "文字创作专家"}},
        current_phase="阶段2：撰写",
        next_action="请撰写正文。",
        host_agent_name="四九",
    )

    assert _content(msg) == "下面由 文字创作专家 发言。"
    assert msg["speaker"]["skill"] == "group-host-webnovel"
    assert "content" not in msg
    assert "routing" not in msg
    ChatMessageRecord.model_validate(msg)


def test_host_recommendation_uses_current_contract_copy():
    msg = _build_host_recommendation_message(
        skill="group-host-webnovel",
        content="",
        picked=["文字创作专家", "信息检索专家"],
    )

    assert _content(msg) == HOST_ZERO_EXPERT_RECOMMENDATION
    assert msg["speaker"]["skill"] == "group-host-webnovel"
    ChatMessageRecord.model_validate(msg)


def test_host_next_speaker_end_phase_uses_end_copy():
    msg = _build_host_next_speaker_message(
        skill="group-host-webnovel",
        next_speaker="文字创作专家",
        agent_map={"文字创作专家": {"name": "文字创作专家"}},
        current_phase="end",
        next_action="",
        host_agent_name="四九",
    )

    assert _content(msg) == HOST_END_MESSAGE
    ChatMessageRecord.model_validate(msg)


def test_host_pause_user_shows_next_action_or_default():
    msg = _build_host_pause_message(
        skill="group-host-webnovel",
        next_speaker="user",
        current_phase="阶段1：入口分流",
        next_action="请用户明确报告目标受众和篇幅。",
        host_agent_name="四九",
    )

    assert msg is not None
    assert _content(msg) == "请用户明确报告目标受众和篇幅。"
    ChatMessageRecord.model_validate(msg)


def test_host_pause_user_without_action_uses_default_copy():
    msg = _build_host_pause_message(
        skill="group-host-webnovel",
        next_speaker="user",
        host_agent_name="四九",
    )

    assert msg is not None
    assert _content(msg) == HOST_USER_PAUSE_MESSAGE
    ChatMessageRecord.model_validate(msg)
