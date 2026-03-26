"""Shared orchestration contracts for group chat scheduling.

This module is intentionally lightweight and backward compatible so old
group-chat flow can progressively adopt new fields without a hard cutover.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OrchestrationPhase(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    AWAITING_USER = "awaiting_user"
    RECRUITING = "recruiting"
    REVIEWING = "reviewing"
    COMPLETED = "completed"


class InterruptReason(str, Enum):
    NONE = "none"
    NEED_USER_INPUT = "need_user_input"
    NEED_MORE_CONTEXT = "need_more_context"
    NEED_RECRUIT_EXPERT = "need_recruit_expert"
    POLICY_OR_SECURITY = "policy_or_security"
    TOOL_UNAVAILABLE = "tool_unavailable"
    TIMEOUT_OR_BUDGET_EXCEEDED = "timeout_or_budget_exceeded"
    CONFLICT_DETECTED = "conflict_detected"


class DecisionSource(str, Enum):
    HOST = "host"
    EXPERT = "expert"
    HOOK = "hook"
    SYSTEM_GUARD = "system_guard"
    LEGACY = "legacy"


@dataclass
class OrchestrationContext:
    """In-memory runtime context for one orchestration stream."""

    session_id: str
    phase: OrchestrationPhase = OrchestrationPhase.PLANNING
    active_task_id: Optional[str] = None
    owner_dha_id: Optional[str] = None
    interrupt_reason: InterruptReason = InterruptReason.NONE
    turn_id: str = ""
    token_version: int = 0
    resume_nonce: Optional[str] = None
    decision_source: DecisionSource = DecisionSource.LEGACY
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "phase": self.phase.value,
            "active_task_id": self.active_task_id,
            "owner_dha_id": self.owner_dha_id,
            "interrupt_reason": self.interrupt_reason.value,
            "turn_id": self.turn_id,
            "token_version": self.token_version,
            "resume_nonce": self.resume_nonce,
            "decision_source": self.decision_source.value,
            "extra": self.extra or {},
        }


@dataclass
class OrchestrationDecision:
    """Unified scheduler output shared by host/leader/hook layers."""

    task_done: bool = True
    next_speaker: str = "user"
    reason: str = ""
    announcement: str = ""
    next_prompt: Optional[str] = None
    suggested_add_dha_ids: List[str] = field(default_factory=list)
    phase: OrchestrationPhase = OrchestrationPhase.PLANNING
    owner_dha_id: Optional[str] = None
    interrupt_reason: InterruptReason = InterruptReason.NONE
    decision_source: DecisionSource = DecisionSource.LEGACY
    handoff_reason: Optional[str] = None
    required_user_fields: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "task_done": bool(self.task_done),
            "next_speaker": (self.next_speaker or "user").strip().lower(),
            "reason": self.reason or "",
            "announcement": self.announcement or self.reason or "",
            "next_prompt": self.next_prompt,
            "suggested_add_dha_ids": list(self.suggested_add_dha_ids or []),
            "suggested_add_expert_ids": list(self.suggested_add_dha_ids or []),
            "phase": self.phase.value,
            "owner_dha_id": self.owner_dha_id,
            "interrupt_reason": self.interrupt_reason.value,
            "decision_source": self.decision_source.value,
            "handoff_reason": self.handoff_reason,
            "required_user_fields": list(self.required_user_fields or []),
        }
        if payload["next_speaker"] in ("user", "end"):
            payload["next_prompt"] = None
        return payload


def build_end_payload(
    *,
    waiting_for_user: bool = True,
    discussion_ended: bool = False,
    suggested_next_speaker: Optional[str] = None,
    phase: OrchestrationPhase = OrchestrationPhase.AWAITING_USER,
    interrupt_reason: InterruptReason = InterruptReason.NONE,
    resume_target_dha_id: Optional[str] = None,
    required_user_fields: Optional[List[Dict[str, Any]]] = None,
    turn_id: str = "",
    token_version: int = 0,
    handoff_reason: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build SSE end payload with v2 orchestration-compatible fields."""
    normalized_phase = phase
    normalized_interrupt = interrupt_reason
    normalized_waiting = bool(waiting_for_user)
    normalized_discussion_ended = bool(discussion_ended)
    normalized_required = list(required_user_fields or [])
    normalized_suggested_next = (suggested_next_speaker or "").strip().lower() or None
    normalized_resume_target = (resume_target_dha_id or "").strip().lower() or None

    # Contract hardening: terminal end must be completed/non-waiting/no-interrupt.
    if normalized_discussion_ended:
        normalized_waiting = False
        normalized_phase = OrchestrationPhase.COMPLETED
        normalized_interrupt = InterruptReason.NONE
        normalized_suggested_next = None
        normalized_required = []
    else:
        if normalized_waiting:
            if normalized_interrupt == InterruptReason.NEED_RECRUIT_EXPERT:
                normalized_phase = OrchestrationPhase.RECRUITING
                normalized_suggested_next = "user"
            elif normalized_phase == OrchestrationPhase.COMPLETED:
                normalized_phase = OrchestrationPhase.AWAITING_USER
            if normalized_required and normalized_interrupt == InterruptReason.NONE:
                normalized_interrupt = InterruptReason.NEED_USER_INPUT
        else:
            normalized_suggested_next = None
            normalized_required = []
            if normalized_phase in (OrchestrationPhase.AWAITING_USER, OrchestrationPhase.RECRUITING):
                normalized_phase = OrchestrationPhase.EXECUTING

    payload: Dict[str, Any] = {
        "type": "end",
        "waiting_for_user": normalized_waiting,
        "discussion_ended": normalized_discussion_ended,
        "phase": normalized_phase.value,
        "interrupt_reason": normalized_interrupt.value,
        "resume_target_dha_id": normalized_resume_target,
        "required_user_fields": normalized_required,
        "turn_id": turn_id or "",
        "token_version": int(token_version),
        "handoff_reason": handoff_reason,
        "suggested_next_speaker": normalized_suggested_next,
    }
    if extra:
        for k, v in (extra or {}).items():
            if k in payload:
                continue
            payload[k] = v
    return payload
