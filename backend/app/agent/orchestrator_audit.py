"""Minimal audit logging helpers for orchestration flow."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.api.files import get_workspace_root_path


def _audit_file(session_id: str) -> Path:
    root = get_workspace_root_path(session_id)
    p = root / "memory" / "orchestrator_audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def append_audit_event(session_id: str, event_type: str, payload: Dict[str, Any], turn_id: Optional[str] = None) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "turn_id": turn_id or "",
        "payload": payload or {},
    }
    p = _audit_file(session_id)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
