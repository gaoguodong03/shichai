"""Structured sandbox audit helpers."""
from __future__ import annotations

from typing import Any, Dict

from app.agent.orchestrator_audit import append_audit_event


def append_sandbox_event(
    *,
    session_id: str,
    event_type: str,
    payload: Dict[str, Any],
    turn_id: str = "",
) -> None:
    append_audit_event(
        session_id=session_id,
        event_type=event_type,
        payload=payload,
        turn_id=turn_id or None,
    )
