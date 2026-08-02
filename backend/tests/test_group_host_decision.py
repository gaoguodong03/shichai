import pytest
from pydantic import ValidationError

from app.agent import group_host_decision as hd
from app.agent.structured_output_contracts import HostSchedulerDecisionPayload, StructuredOutputProtocolError


def _decision(*, target: str | None = "写作专家", suggestions: list[str] | None = None):
    message = {"content": "请基于用户目标整理一版大纲。"}
    if target:
        message["target_agent_name"] = target
    return {
        "current_phase": "资料收集",
        "message": message,
        "suggested_add_agent_names": suggestions or [],
    }


def test_host_payload_accepts_message_routing_contract():
    payload = HostSchedulerDecisionPayload.model_validate(_decision())

    assert payload.message.content == "请基于用户目标整理一版大纲。"
    assert payload.message.target_agent_name == "写作专家"


@pytest.mark.parametrize("extra_field", ["next_speaker", "next_action", "reason", "invite", "announcement"])
def test_host_payload_rejects_legacy_control_fields(extra_field):
    data = _decision()
    data[extra_field] = "旧字段"

    with pytest.raises(ValidationError):
        HostSchedulerDecisionPayload.model_validate(data)


def test_host_payload_rejects_suggestions_with_target_agent():
    with pytest.raises(ValidationError):
        HostSchedulerDecisionPayload.model_validate(_decision(suggestions=["检索专家"]))


def test_strict_host_scheduler_accepts_valid_agent_decision():
    text = '{"current_phase":"资料收集","message":{"content":"请整理大纲。","target_agent_name":"写作专家"}}'

    out = hd.parse_strict_host_scheduler_output(text, agent_profiles=[{"name": "写作专家"}])

    assert out == {
        "current_phase": "资料收集",
        "message": {"content": "请整理大纲。", "target_agent_name": "写作专家"},
        "suggested_add_agent_names": None,
    }


def test_strict_host_scheduler_rejects_wrapped_json_text():
    text = """安排如下：
```json
{"current_phase":"资料收集","message":{"content":"请整理大纲。","target_agent_name":"写作专家"}}
```"""

    out = hd.parse_strict_host_scheduler_output(text, agent_profiles=[{"name": "写作专家"}])

    assert out["message"] == {"content": hd.HOST_PROTOCOL_ERROR_MESSAGE}
    assert "next_speaker" not in out
    assert "next_action" not in out


def test_strict_host_scheduler_rejects_agent_id_target():
    text = '{"current_phase":"资料收集","message":{"content":"请整理大纲。","target_agent_name":"agent-writer"}}'

    out = hd.parse_strict_host_scheduler_output(
        text,
        agent_profiles=[{"name": "写作专家", "agent_id": "agent-writer"}],
    )

    assert out["message"] == {"content": hd.HOST_PROTOCOL_ERROR_MESSAGE}


def test_scene_host_rejects_delegation_claim_without_target_agent():
    payload = HostSchedulerDecisionPayload.model_validate(
        {
            "current_phase": "等待用户下一步操作",
            "message": {"content": "用户请求查询资源详情，已转交资源管理专家处理。"},
        }
    )

    with pytest.raises(StructuredOutputProtocolError, match="delegation claim requires message.target_agent_name"):
        hd.host_scheduler_decision_from_payload(
            payload,
            agent_profiles=[{"name": "资源管理专家"}],
            host_mode="scene",
        )


def test_scene_host_allows_actual_user_wait_without_target_agent():
    payload = HostSchedulerDecisionPayload.model_validate(
        {
            "current_phase": "等待用户选择发布方式",
            "message": {"content": "请明确选择：保留为原文件上传，或渲染为网页正文。"},
        }
    )

    out = hd.host_scheduler_decision_from_payload(
        payload,
        agent_profiles=[{"name": "资源管理专家"}],
        host_mode="scene",
    )

    assert out["message"] == {"content": "请明确选择：保留为原文件上传，或渲染为网页正文。"}


def test_finalize_host_decision_suppresses_unsolicited_recruitment_with_existing_members():
    decision = _decision(target=None, suggestions=["检索专家"])

    out = hd.finalize_host_scheduler_decision(
        decision,
        agent_names=["文书专员"],
        available_to_add=[{"name": "检索专家"}],
        user_text="继续写正文",
    )

    assert out["message"].get("target_agent_name") is None
    assert out["suggested_add_agent_names"] == []


def test_finalize_host_decision_keeps_valid_recruitment_for_zero_member_session():
    decision = _decision(target=None, suggestions=["检索专家", "未知专家", "检索专家"])

    out = hd.finalize_host_scheduler_decision(
        decision,
        agent_names=[],
        available_to_add=[{"name": "检索专家"}],
        user_text="帮我写文章",
    )

    assert out["message"].get("target_agent_name") is None
    assert out["suggested_add_agent_names"] == ["检索专家"]


def test_apply_decision_to_ctx_derives_internal_route_and_persists_standard_message():
    decision = _decision()

    out = hd._apply_decision_to_ctx(decision, default_next_action="默认下一步")

    assert out == {
        "next_speaker": "写作专家",
        "next_action": "请基于用户目标整理一版大纲。",
        "suggested_add_agent_names": [],
        "host_scheduler": {
            "current_phase": "资料收集",
            "message": {
                "content": "请基于用户目标整理一版大纲。",
                "target_agent_name": "写作专家",
            },
        },
    }


def test_apply_decision_to_ctx_derives_user_wait_when_target_is_absent():
    decision = {"current_phase": "等待", "message": {"content": "请补充材料。"}}

    out = hd._apply_decision_to_ctx(decision, default_next_action="默认下一步")

    assert out["next_speaker"] == "user"
    assert out["next_action"] == "请补充材料。"
    assert out["host_scheduler"]["message"] == {"content": "请补充材料。"}
