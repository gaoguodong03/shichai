"""Host profile normalization for account defaults and scenario presets."""
from __future__ import annotations

from typing import Any, Dict

from app.core.name_based_resources import _normalize_scenario_host_snapshot


def normalize_host_profile_dict(raw: Any) -> Dict[str, Any]:
    """Normalize current host input to the scenario host contract."""
    return _normalize_scenario_host_snapshot(raw)
