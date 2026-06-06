"""Structured sandbox audit helpers."""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def append_sandbox_event(
    *,
    session_id: str,
    event_type: str,
    payload: Dict[str, Any],
    turn_id: str = "",
) -> None:
    """Keep sandbox audit events in logs without writing workspace memory files."""
    logger.debug(
        "sandbox_event session=%s turn=%s event=%s payload=%s",
        session_id,
        turn_id,
        event_type,
        payload,
    )
