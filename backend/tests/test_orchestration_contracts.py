"""Orchestration contract hardening and scheduler normalization tests."""

import pytest

from app.agent.orchestrator_runtime import normalize_scheduler_decision
from app.agent.orchestrator_state import (
    InterruptReason,
    OrchestrationDecision,
    OrchestrationPhase,
    build_end_payload,
)


def test_normalize_respects_next_speaker_without_binding_last_expert():
    """不再根据 task_done 把 next_speaker 绑回 last_speaker；以主持人 JSON 为准。"""
    out = normalize_scheduler_decision(
        {"next_speaker": "检索专家", "task_done": False, "reason": "x"},
        agent_names=["写作专家", "检索专家"],
        current_owner_agent_name="写作专家",
    )
    assert out["next_speaker"] == "检索专家"


def test_orchestration_decision_rejects_legacy_next_prompt_constructor_arg():
    with pytest.raises(TypeError):
        OrchestrationDecision(
            next_speaker="写作专家",
            next_prompt="请继续写大纲",
        )


def test_normalize_scheduler_decision_rejects_legacy_next_prompt():
    out = normalize_scheduler_decision(
        {
            "current_phase": "阶段1",
            "next_speaker": "写作专家",
            "next_prompt": "请继续写大纲",
        },
        agent_names=["写作专家"],
    )

    assert out["next_speaker"] == "user"
    assert out["speaker_task"] == "主持人输出格式错误，请重试或联系管理员。"
    assert out["interrupt_reason"] == InterruptReason.PROTOCOL_ERROR.value
    assert out["decision_source"] == "system_guard"


def test_normalize_scheduler_decision_rejects_legacy_next_prompt_even_when_null():
    out = normalize_scheduler_decision(
        {
            "current_phase": "阶段1",
            "next_speaker": "写作专家",
            "speaker_task": "请继续写大纲",
            "next_prompt": None,
        },
        agent_names=["写作专家"],
    )

    assert out["next_speaker"] == "user"
    assert out["interrupt_reason"] == InterruptReason.PROTOCOL_ERROR.value


def test_normalize_scheduler_decision_filters_suggested_add_by_recruitable_ids():
    out = normalize_scheduler_decision(
        {
            "next_speaker": "写作专家",
            "task_done": True,
            "suggested_add_agent_names": ["写作专家", "插画专家", "新专家", "插画专家"],
        },
        agent_names=["主持人", "写作专家", "插画专家"],
        recruitable_names=["新专家", "联系人"],
        current_owner_agent_name="写作专家",
    )
    assert out["suggested_add_agent_names"] == ["新专家"]
    assert out["next_speaker"] == "user"
    assert out["phase"] == OrchestrationPhase.RECRUITING.value
    assert out["interrupt_reason"] == InterruptReason.NEED_RECRUIT_EXPERT.value


def test_end_payload_hardens_terminal_semantics():
    payload = build_end_payload(
        waiting_for_user=True,
        discussion_ended=True,
        suggested_next_speaker="writer",
        phase=OrchestrationPhase.AWAITING_USER,
        interrupt_reason=InterruptReason.NEED_USER_INPUT,
        required_user_fields=[{"name": "topic", "required": True}],
        resume_target_agent_name="写作专家",
    )
    assert payload["discussion_ended"] is True
    assert payload["waiting_for_user"] is False
    assert payload["phase"] == OrchestrationPhase.COMPLETED.value
    assert payload["interrupt_reason"] == InterruptReason.NONE.value
    assert payload["suggested_next_speaker"] is None
    assert payload["required_user_fields"] == []
    assert payload["resume_target_agent_name"] == "写作专家"


def test_end_payload_sets_need_user_input_when_required_fields_present():
    payload = build_end_payload(
        waiting_for_user=True,
        suggested_next_speaker="user",
        phase=OrchestrationPhase.AWAITING_USER,
        interrupt_reason=InterruptReason.NONE,
        required_user_fields=[{"name": "budget", "required": True}],
    )
    assert payload["interrupt_reason"] == InterruptReason.NEED_USER_INPUT.value
    assert payload["required_user_fields"] == [{"name": "budget", "required": True}]


def test_end_payload_recruit_interrupt_forces_recruiting_and_user_next():
    payload = build_end_payload(
        waiting_for_user=True,
        suggested_next_speaker="writer",
        phase=OrchestrationPhase.AWAITING_USER,
        interrupt_reason=InterruptReason.NEED_RECRUIT_EXPERT,
    )
    assert payload["phase"] == OrchestrationPhase.RECRUITING.value
    assert payload["suggested_next_speaker"] == "user"


def test_end_payload_extra_cannot_override_contract_fields():
    payload = build_end_payload(
        waiting_for_user=True,
        suggested_next_speaker="user",
        phase=OrchestrationPhase.AWAITING_USER,
        interrupt_reason=InterruptReason.NONE,
        extra={"phase": "completed", "custom_flag": True},
    )
    assert payload["phase"] == OrchestrationPhase.AWAITING_USER.value
    assert payload["custom_flag"] is True


def test_end_payload_defaults_suggested_to_user_when_waiting_and_omitted():
    payload = build_end_payload(
        waiting_for_user=True,
        suggested_next_speaker=None,
        phase=OrchestrationPhase.AWAITING_USER,
        interrupt_reason=InterruptReason.NONE,
    )
    assert payload["suggested_next_speaker"] == "user"


def test_normalize_scheduler_accepts_invite_next_speaker():
    out = normalize_scheduler_decision(
        {"next_speaker": "invite", "speaker_task": "请邀请文字创作专家"},
        agent_names=["写作专家"],
    )
    assert out["next_speaker"] == "invite"
    assert out["phase"] == OrchestrationPhase.RECRUITING.value
    assert out["interrupt_reason"] == InterruptReason.NEED_RECRUIT_EXPERT.value
