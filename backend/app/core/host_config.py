"""场景虚拟主持人配置。"""
from __future__ import annotations

from typing import Any, Dict

from app.core.name_based_resources import _normalize_scenario_host_config


def normalize_host_config_dict(raw: Any) -> Dict[str, Any]:
    """Normalize scene host_config to the persisted minimal contract."""
    return _normalize_scenario_host_config(raw)
