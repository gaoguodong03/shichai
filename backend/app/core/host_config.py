"""Host snapshot normalization for scenarios and account defaults."""
from __future__ import annotations

from typing import Any, Dict

from app.core.name_based_resources import _normalize_scenario_host_config


def normalize_host_config_dict(raw: Any) -> Dict[str, Any]:
    """Normalize legacy host_config or current host input to the current host contract."""
    return _normalize_scenario_host_config(raw)
