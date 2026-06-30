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


def _clean_names(values: Any, valid: List[str]) -> List[str]:
    if not isinstance(values, list):
        return []
    valid_map = {str(x or "").strip().casefold(): str(x or "").strip() for x in valid or [] if str(x or "").strip()}
    out: List[str] = []
    for v in values:
        key = str(v or "").strip().casefold()
        name = valid_map.get(key)
        if name and name not in out:
            out.append(name)
    return out


def normalize_scheduler_decision(
    raw: Optional[Dict[str, Any]],
    *,
    agent_names: List[str],
    recruitable_names: Optional[List[str]] = None,
    current_owner_agent_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize host/leader decision to a stable orchestration payload.

    Rules:
    - 不再根据 task_done 强行把 next_speaker 改回「上一位专家」；由主持人/leader 的 JSON 与 Skill 会话锁表达流程。
    - Invalid next_speaker falls back to user with conflict interrupt.
    """
    data = dict(raw or {})
    valid_name_map = {str(x or "").strip().casefold(): str(x or "").strip() for x in agent_names or [] if str(x or "").strip()}
    next_raw = str(data.get("next_speaker") or "user").strip()
    next_key = next_raw.casefold()
    next_speaker = valid_name_map.get(next_key, next_raw)
    reason = str(data.get("reason") or "")
    announcement = str(data.get("announcement") or reason)
    task_done = bool(data.get("task_done", True))
    current_phase = str(data.get("current_phase") or "").strip()
    speaker_task = str(data.get("speaker_task") or data.get("next_prompt") or "").strip()

    suggested = _clean_names(
        data.get("suggested_add_agent_names") or [],
        recruitable_names or [],
    )
    if suggested:
        next_speaker = "user"

    interrupt_reason = _INTERRUPT_MAP.get(
        str(data.get("interrupt_reason") or "").strip().lower(),
        InterruptReason.NONE,
    )
    if suggested:
        interrupt_reason = InterruptReason.NEED_RECRUIT_EXPERT

    if next_speaker not in agent_names and next_speaker not in ("user", "end", "invite"):
        next_speaker = "user"
        if interrupt_reason == InterruptReason.NONE:
            interrupt_reason = InterruptReason.CONFLICT_DETECTED
        reason = (reason + " | invalid next_speaker fallback to user").strip(" |")

    phase_raw = str(data.get("phase") or "").strip().lower()
    phase = _PHASE_MAP.get(phase_raw)
    if phase is None:
        if next_speaker == "end":
            phase = OrchestrationPhase.COMPLETED
        elif next_speaker == "invite":
            phase = OrchestrationPhase.RECRUITING
            if interrupt_reason == InterruptReason.NONE:
                interrupt_reason = InterruptReason.NEED_RECRUIT_EXPERT
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

    owner_agent_name = str(data.get("owner_agent_name") or "").strip() or None
    if not owner_agent_name:
        if next_speaker in agent_names:
            owner_agent_name = next_speaker
        elif not task_done and current_owner_agent_name:
            owner_agent_name = current_owner_agent_name

    decision = OrchestrationDecision(
        task_done=task_done,
        next_speaker=next_speaker,
        reason=reason,
        announcement=announcement,
        next_prompt=None,
        current_phase=current_phase,
        speaker_task=speaker_task,
        suggested_add_agent_names=suggested,
        phase=phase,
        owner_agent_name=owner_agent_name,
        interrupt_reason=interrupt_reason,
        decision_source=source,
        handoff_reason=(data.get("handoff_reason") or reason or None),
        required_user_fields=required_user_fields,
    )

    out = decision.to_dict()
    if data.get("suggested_order"):
        out["suggested_order"] = data.get("suggested_order")
    return out
