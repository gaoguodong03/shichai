"""Runtime helpers to normalize scheduler decisions for orchestration v2."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.orchestrator_state import (
    DecisionSource,
    InterruptReason,
    OrchestrationDecision,
    OrchestrationPhase,
)


_PHASE_MAP = {p.value: p for p in OrchestrationPhase}
_INTERRUPT_MAP = {r.value: r for r in InterruptReason}
_SOURCE_MAP = {s.value: s for s in DecisionSource}


def _clean_ids(values: Any, valid: List[str]) -> List[str]:
    if not isinstance(values, list):
        return []
    valid_set = set(valid or [])
    out: List[str] = []
    for v in values:
        sid = str(v or "").strip().lower()
        if sid and sid in valid_set and sid not in out:
            out.append(sid)
    return out


def normalize_scheduler_decision(
    raw: Optional[Dict[str, Any]],
    *,
    agent_ids: List[str],
    recruitable_ids: Optional[List[str]] = None,
    last_speaker_agent_id: Optional[str],
    current_owner_agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize host/leader decision to a stable orchestration payload.

    Rules:
    - Preserve same owner when task is not done.
    - Never apply round-robin fallback.
    - Invalid next_speaker falls back to user with conflict interrupt.
    """
    data = dict(raw or {})
    next_speaker = str(data.get("next_speaker") or "user").strip().lower()
    reason = str(data.get("reason") or "")
    announcement = str(data.get("announcement") or reason)
    task_done = bool(data.get("task_done", True))
    next_prompt = (data.get("next_prompt") or None)

    suggested = _clean_ids(
        data.get("suggested_add_agent_ids") or data.get("suggested_add_expert_ids") or [],
        recruitable_ids or [],
    )
    if suggested:
        next_speaker = "user"

    interrupt_reason = _INTERRUPT_MAP.get(
        str(data.get("interrupt_reason") or "").strip().lower(),
        InterruptReason.NONE,
    )
    if suggested:
        interrupt_reason = InterruptReason.NEED_RECRUIT_EXPERT

    if not task_done and last_speaker_agent_id and last_speaker_agent_id in agent_ids:
        next_speaker = last_speaker_agent_id

    if next_speaker not in agent_ids and next_speaker not in ("user", "end"):
        next_speaker = "user"
        if interrupt_reason == InterruptReason.NONE:
            interrupt_reason = InterruptReason.CONFLICT_DETECTED
        reason = (reason + " | invalid next_speaker fallback to user").strip(" |")

    phase_raw = str(data.get("phase") or "").strip().lower()
    phase = _PHASE_MAP.get(phase_raw)
    if phase is None:
        if next_speaker == "end":
            phase = OrchestrationPhase.COMPLETED
        elif next_speaker == "user":
            phase = OrchestrationPhase.RECRUITING if suggested else OrchestrationPhase.AWAITING_USER
        else:
            phase = OrchestrationPhase.EXECUTING

    source = _SOURCE_MAP.get(
        str(data.get("decision_source") or "").strip().lower(),
        DecisionSource.LEGACY,
    )
    required_user_fields = data.get("required_user_fields")
    if not isinstance(required_user_fields, list):
        required_user_fields = []

    owner_agent_id = str(data.get("owner_agent_id") or "").strip() or None
    if not owner_agent_id:
        if next_speaker in agent_ids:
            owner_agent_id = next_speaker
        elif not task_done and current_owner_agent_id:
            owner_agent_id = current_owner_agent_id

    decision = OrchestrationDecision(
        task_done=task_done,
        next_speaker=next_speaker,
        reason=reason,
        announcement=announcement,
        next_prompt=next_prompt,
        suggested_add_agent_ids=suggested,
        phase=phase,
        owner_agent_id=owner_agent_id,
        interrupt_reason=interrupt_reason,
        decision_source=source,
        handoff_reason=(data.get("handoff_reason") or reason or None),
        required_user_fields=required_user_fields,
    )

    out = decision.to_dict()
    if data.get("suggested_order"):
        out["suggested_order"] = data.get("suggested_order")
    return out
