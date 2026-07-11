import pytest
from pydantic import ValidationError

from app.agent.message_contracts import ChatMessageRecord, MessageSpeaker, SkillResult, WorkspaceAttachment
from app.agent.structured_output_contracts import ArtifactRef


def v2_next_action(instruction="本轮专家回复已完成，请主持人判断下一步。"):
    return {
        "handoff": "host",
        "resume": "none",
        "reason": "stage_completed",
        "instruction": instruction,
    }


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
            "next_action": v2_next_action("大纲已完成"),
        },
    )

    dumped = message.model_dump(exclude_none=True)
    assert dumped["message"]["content"] == "大纲已完成"
    assert "attachments" not in dumped["message"]
    assert "target_agent_name" not in dumped["message"]
    assert dumped["skill_result"]["artifacts"][0]["path"] == "outline.md"


def test_skill_result_rejects_workflow_state_field():
    payload = {
        "execution_status": "blocked",
        "content": "请先补充这篇文章的想法。",
        "artifacts": [],
        "next_action": {
            "handoff": "user",
            "resume": "same_skill",
            "reason": "missing_input",
            "instruction": "等待用户补充文章想法后，由文档合著专家继续上下文收集。",
        },
        "workflow_state": {
            "stage": "context_collection",
            "stage_status": "waiting_confirmation",
        },
    }

    with pytest.raises(ValidationError):
        SkillResult.model_validate(payload)


def test_skill_message_content_must_match_skill_result_content():
    payload = {
        "message_id": "msg-expert",
        "speaker": {"type": "expert", "agent_name": "写作专家", "skill": "article-writer"},
        "message": {"content": "平台改写后的总结"},
        "created_at": "2026062908104900",
        "skill_result": {
            "execution_status": "succeeded",
            "content": "脚本原始正文",
            "artifacts": [],
            "next_action": v2_next_action("脚本原始正文"),
        },
    }

    with pytest.raises(ValidationError):
        ChatMessageRecord.model_validate(payload)


def test_skill_result_requires_speaker_skill_directory():
    payload = {
        "message_id": "msg-host",
        "speaker": {"type": "host", "agent_name": "四九"},
        "message": {"content": "请继续"},
        "created_at": "2026062908104900",
        "skill_result": {
            "execution_status": "succeeded",
            "content": "请继续",
            "artifacts": [],
            "next_action": v2_next_action("请继续"),
        },
    }

    with pytest.raises(ValidationError):
        ChatMessageRecord.model_validate(payload)


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "C:/Users/admin/secret.txt",
        "../outside.txt",
        "docs/../../outside.txt",
        "memory/facts.md",
        "execution_logs/tool-execution.jsonl",
    ],
)
def test_workspace_attachment_rejects_non_public_workspace_relative_paths(path):
    with pytest.raises(ValidationError):
        WorkspaceAttachment.model_validate({"type": "workspace_file", "path": path, "name": "bad"})


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/report.md",
        "D:/outputs/report.md",
        "../report.md",
        "reports/../../report.md",
        "memory/index.md",
        "traces/run.json",
    ],
)
def test_artifact_ref_rejects_non_public_workspace_relative_paths(path):
    with pytest.raises(ValidationError):
        ArtifactRef.model_validate({"type": "file", "name": "报告", "path": path})


@pytest.mark.parametrize(
    "created_at",
    [
        "2026-06-29T08:10:49Z",
        "20260629081049",
        "2026132908104800",
        "2026023008104800",
        "2026062924104800",
        "t",
        "",
    ],
)
def test_chat_message_record_requires_storage_timestamp_format(created_at):
    payload = {
        "message_id": "msg-1",
        "speaker": {"type": "host", "agent_name": "四九"},
        "message": {"content": "请继续"},
        "created_at": created_at,
    }

    with pytest.raises(ValidationError):
        ChatMessageRecord.model_validate(payload)


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
        "next_action": v2_next_action("完成"),
        old_key: value,
    }

    with pytest.raises(ValidationError):
        SkillResult.model_validate(payload)
