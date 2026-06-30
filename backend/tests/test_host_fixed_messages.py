from app.agent.group_chat_host_messages import (
    HOST_END_MESSAGE,
    HOST_USER_PAUSE_MESSAGE,
    HOST_ZERO_EXPERT_RECOMMENDATION,
    _build_host_next_speaker_message,
    _build_host_pause_message,
    _build_host_recommendation_message,
)


def test_host_next_speaker_ignores_custom_announcement():
    msg = _build_host_next_speaker_message(
        skill="group-host-webnovel",
        next_speaker="agent-writer",
        agent_map={"agent-writer": {"name": "文字创作专家"}},
        announcement="好的，我理解了你的需求。",
        current_phase="阶段2：撰写",
        speaker_task="请撰写正文。",
    )

    assert msg["content"] == "下面由 文字创作专家 发言。"
    assert "理解了" not in msg["content"]


def test_host_recommendation_uses_fixed_copy():
    msg = _build_host_recommendation_message(
        skill="group-host-webnovel",
        content="好的，我来为你协调这次的文章写作任务。",
        picked=["agent-writer", "agent-search"],
    )

    assert msg["content"] == HOST_ZERO_EXPERT_RECOMMENDATION
    assert msg["suggested_add_agent_names"] == ["agent-writer", "agent-search"]


def test_host_next_speaker_end_phase_uses_fixed_copy():
    msg = _build_host_next_speaker_message(
        skill="group-host-webnovel",
        next_speaker="agent-writer",
        agent_map={"agent-writer": {"name": "文字创作专家"}},
        current_phase="end",
        speaker_task="",
    )

    assert msg["content"] == HOST_END_MESSAGE


def test_host_pause_user_shows_speaker_task_or_default():
    msg = _build_host_pause_message(
        skill="group-host-webnovel",
        next_speaker="user",
        current_phase="阶段1：入口分流",
        speaker_task="请用户明确报告目标受众和篇幅。",
    )

    assert msg is not None
    assert msg["content"] == "请用户明确报告目标受众和篇幅。"


def test_host_pause_user_without_task_uses_default_copy():
    msg = _build_host_pause_message(
        skill="group-host-webnovel",
        next_speaker="user",
    )

    assert msg is not None
    assert msg["content"] == HOST_USER_PAUSE_MESSAGE
