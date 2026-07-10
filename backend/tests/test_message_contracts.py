import pytest
from pydantic import ValidationError

from app.agent.message_contracts import ChatMessageRecord, MessageSpeaker, SkillResult


def test_user_message_record_uses_nested_message_object():
    message = ChatMessageRecord(
        message_id="msg-user",
        speaker={"type": "user"},
        message={
            "content": "请处理附件",
            "attachments": [{"type": "workspace_file", "path": "input.pdf", "name": "input.pdf"}],
            "target_agent_name": "写作专家",
        },
        created_at="2026062908104800",
        client_message_id="client-1",
    )

    assert message.model_dump(exclude_none=True) == {
        "message_id": "msg-user",
        "speaker": {"type": "user"},
        "message": {
            "content": "请处理附件",
            "attachments": [{"type": "workspace_file", "path": "input.pdf", "name": "input.pdf"}],
            "target_agent_name": "写作专家",
        },
        "created_at": "2026062908104800",
        "client_message_id": "client-1",
    }


def test_expert_message_record_uses_current_skill_result_shape():
    message = ChatMessageRecord(
        message_id="msg-expert",
        speaker={"type": "expert", "agent_name": "写作专家", "skill": "article-writer"},
        message={"content": "大纲已完成"},
        created_at="2026062908104900",
        skill_result={
            "execution_status": "succeeded",
            "content": "大纲已完成",
            "artifacts": [{"type": "markdown", "name": "大纲", "path": "outline.md"}],
            "next_action": {"agent_turn": "respond", "skill_session": "release"},
        },
    )

    dumped = message.model_dump(exclude_none=True)
    assert dumped["message"]["content"] == "大纲已完成"
    assert "attachments" not in dumped["message"]
    assert "target_agent_name" not in dumped["message"]
    assert dumped["skill_result"]["artifacts"][0]["path"] == "outline.md"


@pytest.mark.parametrize(
    "old_key, value",
    [
        ("role", "assistant"),
        ("content", "旧顶层正文"),
        ("timestamp", "2026062908104900"),
        ("agent_name", "专家A"),
        ("skill", "skill-a"),
        ("tool_results", []),
        ("tool_raw_results", []),
        ("tool_debug", {}),
        ("required_user_fields", []),
        ("debug", {}),
        ("turn_id", "turn-1"),
    ],
)
def test_chat_message_record_rejects_old_top_level_fields(old_key, value):
    payload = {
        "message_id": "msg-1",
        "speaker": {"type": "expert", "agent_name": "专家A"},
        "message": {"content": "回答"},
        "created_at": "2026062908104900",
        old_key: value,
    }

    with pytest.raises(ValidationError):
        ChatMessageRecord.model_validate(payload)


@pytest.mark.parametrize(
    "speaker",
    [
        {"type": "expert"},
        {"type": "host"},
        {"type": "user", "agent_name": "用户"},
        {"type": "user", "skill": "skill-a"},
    ],
)
def test_message_speaker_rejects_invalid_identity_shapes(speaker):
    with pytest.raises(ValidationError):
        MessageSpeaker.model_validate(speaker)


@pytest.mark.parametrize(
    "old_key, value",
    [
        ("result_code", "ok"),
        ("message", "完成"),
        ("tool_results", []),
        ("data", {}),
    ],
)
def test_skill_result_rejects_old_fields(old_key, value):
    payload = {
        "execution_status": "succeeded",
        "content": "完成",
        "artifacts": [],
        "next_action": {"agent_turn": "respond", "skill_session": "release"},
        old_key: value,
    }

    with pytest.raises(ValidationError):
        SkillResult.model_validate(payload)
