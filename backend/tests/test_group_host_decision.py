import pytest
from pydantic import ValidationError

from app.agent import group_host_decision as hd
from app.agent.structured_output_contracts import HostSchedulerDecisionPayload


def test_host_payload_accepts_current_next_action_contract():
    payload = HostSchedulerDecisionPayload.model_validate(
        {
            "current_phase": "资料收集",
            "next_speaker": "写作专家",
            "next_action": "请基于用户目标整理一版大纲。",
        }
    )

    assert payload.next_action == "请基于用户目标整理一版大纲。"


@pytest.mark.parametrize(
    "extra_field",
    ["unexpected_instruction", "extra_reason", "extra_payload", "announcement_text", "invite_target", "agent_ref"],
)
def test_host_payload_rejects_extra_fields(extra_field):
    data = {
        "current_phase": "资料收集",
        "next_speaker": "写作专家",
        "next_action": "请整理大纲。",
        extra_field: "额外字段",
    }

    with pytest.raises(ValidationError):
        HostSchedulerDecisionPayload.model_validate(data)


def test_strict_host_scheduler_accepts_valid_agent_decision():
    text = '{"current_phase":"资料收集","next_speaker":"写作专家","next_action":"请整理大纲。"}'

    out = hd.parse_strict_host_scheduler_output(text, agent_profiles=[{"name": "写作专家"}])

    assert out == {
        "next_speaker": "写作专家",
        "current_phase": "资料收集",
        "next_action": "请整理大纲。",
        "suggested_add_agent_names": None,
    }


def test_strict_host_scheduler_rejects_wrapped_json_text():
    text = """安排如下：
```json
{"current_phase":"资料收集","next_speaker":"写作专家","next_action":"请整理大纲。"}
```"""

    out = hd.parse_strict_host_scheduler_output(text, agent_profiles=[{"name": "写作专家"}])

    assert out["next_speaker"] == "user"
    assert out["next_action"] == hd.HOST_PROTOCOL_ERROR_MESSAGE
    assert "interrupt_reason" not in out
    assert "decision_source" not in out
    assert "protocol_error" not in out
    assert "phase" not in out


def test_strict_host_scheduler_rejects_agent_id_next_speaker():
    text = '{"current_phase":"资料收集","next_speaker":"agent-writer","next_action":"请整理大纲。"}'

    out = hd.parse_strict_host_scheduler_output(
        text,
        agent_profiles=[{"name": "写作专家", "agent_id": "agent-writer"}],
    )

    assert out["next_speaker"] == "user"
    assert out["next_action"] == hd.HOST_PROTOCOL_ERROR_MESSAGE


def test_host_suggestions_require_user_next_speaker():
    with pytest.raises(ValidationError):
        HostSchedulerDecisionPayload.model_validate(
            {
                "current_phase": "招募",
                "next_speaker": "写作专家",
                "next_action": "建议补充专家。",
                "suggested_add_agent_names": ["检索专家"],
            }
        )


def test_finalize_host_decision_suppresses_unsolicited_recruitment_with_existing_members():
    decision = {
        "current_phase": "执行中",
        "next_speaker": "user",
        "next_action": "请补充材料。",
        "suggested_add_agent_names": ["检索专家"],
    }

    out = hd.finalize_host_scheduler_decision(
        decision,
        agent_names=["文书专员"],
        available_to_add=[{"name": "检索专家"}],
        user_text="继续写正文",
    )

    assert out["next_speaker"] == "user"
    assert out["suggested_add_agent_names"] == []


def test_finalize_host_decision_keeps_recruitment_for_zero_member_session():
    decision = {
        "current_phase": "招募",
        "next_speaker": "user",
        "next_action": "建议先邀请检索专家。",
        "suggested_add_agent_names": ["检索专家"],
    }

    out = hd.finalize_host_scheduler_decision(
        decision,
        agent_names=[],
        available_to_add=[{"name": "检索专家"}],
        user_text="帮我写文章",
    )

    assert out["next_speaker"] == "user"
    assert out["suggested_add_agent_names"] == ["检索专家"]


def test_finalize_host_decision_keeps_recruitment_when_user_explicitly_requests_it():
    decision = {
        "current_phase": "招募",
        "next_speaker": "user",
        "next_action": "建议邀请检索专家。",
        "suggested_add_agent_names": ["检索专家"],
    }

    out = hd.finalize_host_scheduler_decision(
        decision,
        agent_names=["文书专员"],
        available_to_add=[{"name": "检索专家"}],
        user_text="请加一个检索专家进来",
    )

    assert out["next_speaker"] == "user"
    assert out["suggested_add_agent_names"] == ["检索专家"]


def test_finalize_host_decision_filters_unavailable_and_duplicate_recruitment_names():
    decision = {
        "current_phase": "招募",
        "next_speaker": "user",
        "next_action": "建议邀请专家。",
        "suggested_add_agent_names": ["检索专家", "未知专家", "检索专家", ""],
    }

    out = hd.finalize_host_scheduler_decision(
        decision,
        agent_names=[],
        available_to_add=[{"name": "检索专家"}],
        user_text="帮我写文章",
    )

    assert out["next_speaker"] == "user"
    assert out["suggested_add_agent_names"] == ["检索专家"]


def test_apply_decision_to_ctx_returns_runtime_routing_fields_and_host_scheduler():
    decision = {
        "current_phase": "执行中",
        "next_speaker": "写作专家",
        "next_action": "请写第一版正文。",
        "suggested_add_agent_names": ["检索专家"],
    }

    out = hd._apply_decision_to_ctx(decision, default_next_action="默认下一步")

    assert out == {
        "next_speaker": "写作专家",
        "next_action": "请写第一版正文。",
        "suggested_add_agent_names": ["检索专家"],
        "host_scheduler": {
            "current_phase": "执行中",
            "next_speaker": "写作专家",
            "next_action": "请写第一版正文。",
        },
    }


def test_apply_decision_to_ctx_uses_default_next_action_when_decision_action_is_empty():
    decision = {
        "current_phase": "等待",
        "next_speaker": "user",
        "next_action": "",
        "suggested_add_agent_names": [],
    }

    out = hd._apply_decision_to_ctx(decision, default_next_action="请补充材料。")

    assert out["next_action"] == "请补充材料。"
    assert out["host_scheduler"]["next_action"] == "请补充材料。"
