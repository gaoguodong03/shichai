import pytest
from pydantic import ValidationError

from app.agent.message_contracts import (
    ChatMessageRecord,
    MessageSpeaker,
    SkillTurnResult,
    ToolCallRecord,
    ToolResultRecord,
)


def test_user_message_record_serializes_only_canonical_fields():
    message = ChatMessageRecord(
        message_id="msg-user",
        speaker={"type": "user"},
        content="你好",
        created_at="2026062908104800",
        client_message_id="client-1",
    )

    assert message.model_dump(exclude_none=True) == {
        "message_id": "msg-user",
        "speaker": {"type": "user"},
        "content": "你好",
        "created_at": "2026062908104800",
        "client_message_id": "client-1",
        "tool_results": [],
        "required_user_fields": [],
    }


def test_expert_message_record_accepts_skill_result_and_tool_results():
    message = ChatMessageRecord(
        message_id="msg-expert",
        speaker={"type": "expert", "agent_name": "信息检索专家", "skill": "skill-web"},
        content="检索完成",
        created_at="2026062908104900",
        skill_result={
            "execution_status": "succeeded",
            "result_code": "ok",
            "next_action": {"agent_turn": "respond", "skill_session": "release"},
        },
        tool_results=[
            {
                "tool_call": {
                    "id": "call-1",
                    "name": "web_search",
                    "kind": "mcp",
                    "provider": "linkup",
                    "provider_tool": "linkup-fetch",
                    "arguments": {"query": "智能软件工程"},
                },
                "execution_status": "succeeded",
                "result_code": "ok",
                "message": "检索成功",
                "output": {"text": "Title: Intelligent software engineering"},
            }
        ],
    )

    dumped = message.model_dump(exclude_none=True)
    assert dumped["speaker"] == {"type": "expert", "agent_name": "信息检索专家", "skill": "skill-web"}
    assert dumped["skill_result"]["execution_status"] == "succeeded"
    assert dumped["tool_results"][0]["tool_call"]["provider"] == "linkup"
    assert dumped["tool_results"][0]["tool_call"]["provider_tool"] == "linkup-fetch"


@pytest.mark.parametrize(
    "speaker",
    [
        {"type": "expert"},
        {"type": "user", "agent_name": "用户"},
        {"type": "user", "skill": "skill-a"},
        {"type": "host", "skill": "skill-a"},
    ],
)
def test_message_speaker_rejects_invalid_identity_shapes(speaker):
    with pytest.raises(ValidationError):
        MessageSpeaker.model_validate(speaker)


def test_status_rejects_partial():
    with pytest.raises(ValidationError):
        SkillTurnResult.model_validate(
            {
                "execution_status": "partial",
                "result_code": "partial",
            }
        )

    with pytest.raises(ValidationError):
        ToolResultRecord.model_validate(
            {
                "tool_call": {"id": "call-1", "name": "web_search", "kind": "mcp"},
                "execution_status": "partial",
                "result_code": "partial",
                "message": "部分成功",
            }
        )


@pytest.mark.parametrize(
    "old_key, value",
    [
        ("role", "assistant"),
        ("timestamp", "2026062908104900"),
        ("agent_name", "专家A"),
        ("skill", "skill-a"),
        ("tool_raw_results", []),
        ("tool_debug", {}),
        ("presentation_content", "展示内容"),
        ("meta", {}),
        ("schema_version", "chat.message.v1"),
        ("diagnostics", {}),
        ("raw", {}),
    ],
)
def test_chat_message_record_rejects_old_top_level_fields(old_key, value):
    payload = {
        "message_id": "msg-1",
        "speaker": {"type": "expert", "agent_name": "专家A"},
        "content": "回答",
        "created_at": "2026062908104900",
        old_key: value,
    }

    with pytest.raises(ValidationError):
        ChatMessageRecord.model_validate(payload)


def test_tool_call_keeps_stable_name_and_provider_fields():
    tool_call = ToolCallRecord.model_validate(
        {
            "id": "call-1",
            "name": "web_search",
            "kind": "mcp",
            "provider": "linkup",
            "provider_tool": "linkup-fetch",
            "arguments": {"url": "https://example.com"},
        }
    )

    assert tool_call.name == "web_search"
    assert tool_call.provider == "linkup"
    assert tool_call.provider_tool == "linkup-fetch"


def test_required_user_fields_accept_required_flag():
    payload = {
        "message_id": "msg-1",
        "speaker": {"type": "expert", "agent_name": "专家A"},
        "content": "请确认是否继续。",
        "created_at": "2026062908104900",
        "required_user_fields": [
            {
                "key": "workflow_user_confirmation",
                "label": "请确认是否继续",
                "required": True,
            }
        ],
    }

    parsed = ChatMessageRecord.model_validate(payload)

    assert parsed.required_user_fields[0].required is True
