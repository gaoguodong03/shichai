"""Feature flags used for gradual rollout."""
from __future__ import annotations

import os


def is_feature_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    value = str(raw).strip().lower()
    return value in {"1", "true", "yes", "on", "enabled"}

