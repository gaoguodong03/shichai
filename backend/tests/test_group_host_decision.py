import pytest
from pydantic import ValidationError

from app.agent import group_host_decision as hd
from app.agent.runtime_status import InterruptReason
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
        "phase": None,
        "interrupt_reason": None,
        "decision_source": "host_scheduler_state",
    }


def test_strict_host_scheduler_rejects_wrapped_json_text():
    text = """安排如下：
```json
{"current_phase":"资料收集","next_speaker":"写作专家","next_action":"请整理大纲。"}
```"""

    out = hd.parse_strict_host_scheduler_output(text, agent_profiles=[{"name": "写作专家"}])

    assert out["next_speaker"] == "user"
    assert out["next_action"] == hd.HOST_PROTOCOL_ERROR_MESSAGE
    assert out["interrupt_reason"] == InterruptReason.PROTOCOL_ERROR.value
    assert out["decision_source"] == "system_guard"


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
