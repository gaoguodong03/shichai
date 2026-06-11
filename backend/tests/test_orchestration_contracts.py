"""Orchestration contract hardening and scheduler normalization tests."""

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
        {"next_speaker": "agent-b", "task_done": False, "reason": "x"},
        agent_ids=["agent-a", "agent-b"],
        current_owner_agent_id="agent-a",
    )
    assert out["next_speaker"] == "agent-b"


def test_orchestration_decision_migrates_legacy_next_prompt_to_speaker_task():
    payload = OrchestrationDecision(
        next_speaker="agent-a",
        next_prompt="请继续写大纲",
    ).to_dict()

    assert payload["speaker_task"] == "请继续写大纲"
    assert payload["next_prompt"] is None


def test_normalize_scheduler_decision_filters_suggested_add_by_recruitable_ids():
    out = normalize_scheduler_decision(
        {
            "next_speaker": "writer",
            "task_done": True,
            "suggested_add_agent_ids": ["writer", "illustrator", "newcomer", "illustrator"],
        },
        agent_ids=["host", "writer", "illustrator"],
        recruitable_ids=["newcomer", "contact"],
        current_owner_agent_id="writer",
    )
    assert out["suggested_add_agent_ids"] == ["newcomer"]
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
        resume_target_agent_id="Writer",
    )
    assert payload["discussion_ended"] is True
    assert payload["waiting_for_user"] is False
    assert payload["phase"] == OrchestrationPhase.COMPLETED.value
    assert payload["interrupt_reason"] == InterruptReason.NONE.value
    assert payload["suggested_next_speaker"] is None
    assert payload["required_user_fields"] == []
    assert payload["resume_target_agent_id"] == "writer"


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
