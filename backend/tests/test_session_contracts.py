import pytest
from pydantic import ValidationError

from app.agent.session_contracts import GroupChatRequest, SessionCreateRequest, SessionUpdateRequest


@pytest.mark.parametrize(
    "legacy_field",
    ["system_prompt", "scenario_name", "orchestration_profile", "leader_agent_name", "host_config"],
)
def test_session_create_rejects_legacy_fields(legacy_field):
    with pytest.raises(ValidationError):
        SessionCreateRequest.model_validate({"title": "新对话", legacy_field: "旧值"})


def test_session_create_accepts_host_snapshot_and_agent_names():
    parsed = SessionCreateRequest.model_validate(
        {
            "title": "创作会话",
            "agent_names": ["写作专家", "写作专家", "检索专家"],
            "host": {"name": "四九", "llm_name": "qwen3-max", "skill_directory": "group-host"},
        }
    )

    assert parsed.agent_names == ["写作专家", "检索专家"]
    assert parsed.host and parsed.host.name == "四九"


@pytest.mark.parametrize(
    "legacy_field",
    ["action", "host_takeover_requested", "ignore_auto_agent_name", "ignore_auto_skill", "agent_name", "next_speaker"],
)
def test_group_chat_request_rejects_legacy_control_fields(legacy_field):
    with pytest.raises(ValidationError):
        GroupChatRequest.model_validate(
            {
                "message": "请处理",
                "client_message_id": "client-1",
                legacy_field: "旧控制",
            }
        )


def test_group_chat_request_requires_payload_source():
    with pytest.raises(ValidationError):
        GroupChatRequest.model_validate({"message": "", "client_message_id": "client-1"})


def test_group_chat_request_accepts_attachments_and_target_agent():
    parsed = GroupChatRequest.model_validate(
        {
            "message": "",
            "client_message_id": "client-1",
            "attachments": [{"type": "workspace_file", "path": "input.md", "name": "input.md"}],
            "target_agent_name": "写作专家",
        }
    )

    assert parsed.attachments[0].path == "input.md"
    assert parsed.target_agent_name == "写作专家"


def test_session_update_rejects_legacy_fields():
    with pytest.raises(ValidationError):
        SessionUpdateRequest.model_validate({"host_config": {"name": "旧主持人"}})
