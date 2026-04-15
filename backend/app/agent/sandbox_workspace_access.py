"""Process-wide shared SandboxService for workspace + tool gateway consistency."""
from __future__ import annotations

import threading
from typing import Optional

from app.agent.sandbox_service import SandboxService

_lock = threading.Lock()
_shared: Optional[SandboxService] = None


def get_shared_sandbox_service() -> SandboxService:
    global _shared
    with _lock:
        if _shared is None:
            _shared = SandboxService()
        return _shared
