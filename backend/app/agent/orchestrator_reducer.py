"""Reducer utilities for orchestration context transitions."""
from __future__ import annotations

import uuid
from typing import Optional

from app.agent.orchestrator_state import (
    DecisionSource,
    InterruptReason,
    OrchestrationContext,
    OrchestrationDecision,
    OrchestrationPhase,
)


def start_turn(
    ctx: OrchestrationContext,
    *,
    phase: Optional[OrchestrationPhase] = None,
    owner_agent_id: Optional[str] = None,
    source: DecisionSource = DecisionSource.LEGACY,
) -> OrchestrationContext:
    """Mutate context for a new turn, bumping token version."""
    ctx.token_version += 1
    ctx.turn_id = f"turn-{uuid.uuid4().hex[:10]}"
    if phase is not None:
        ctx.phase = phase
    if owner_agent_id is not None:
        ctx.owner_agent_id = owner_agent_id
    ctx.interrupt_reason = InterruptReason.NONE
    ctx.decision_source = source
    return ctx


def apply_decision(ctx: OrchestrationContext, decision: OrchestrationDecision) -> OrchestrationContext:
    """Apply a unified decision onto orchestration context."""
    ctx.phase = decision.phase
    ctx.owner_agent_id = decision.owner_agent_id or ctx.owner_agent_id
    ctx.interrupt_reason = decision.interrupt_reason
    ctx.decision_source = decision.decision_source
    return ctx


def move_to_interrupt(
    ctx: OrchestrationContext,
    reason: InterruptReason,
    *,
    phase: OrchestrationPhase = OrchestrationPhase.AWAITING_USER,
) -> OrchestrationContext:
    """Move context into an interrupt phase."""
    ctx.phase = phase
    ctx.interrupt_reason = reason
    return ctx
