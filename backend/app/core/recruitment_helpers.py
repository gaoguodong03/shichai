"""招募相关：从主持词中解析 Agent 名称、合并显式点名优先级。"""
from __future__ import annotations

from typing import Any, Dict, List, Set


def extract_valid_agent_names_from_text(
    text: str,
    valid_names: Set[str],
    all_instances: List[Dict[str, Any]],
    max_n: int = 3,
) -> List[str]:
    """从主持人自由文本中兜底提取合法专家名称。"""
    if not text:
        return []
    name_hits: List[str] = []
    low = str(text).lower()
    for d in all_instances or []:
        name = str(d.get("name") or "").strip()
        if name and name in valid_names and name.lower() in low and name not in name_hits:
            name_hits.append(name)
    return name_hits[: max(0, int(max_n))]


def prioritize_suggested_add_names(
    suggested_names: List[str],
    *,
    explicit_requested_agent_names: List[str],
    recruitable_names: Set[str],
    max_n: int = 3,
) -> List[str]:
    priority = [x for x in (explicit_requested_agent_names or []) if x in recruitable_names]
    merged: List[str] = []
    for name in priority + list(suggested_names or []):
        if name in recruitable_names and name not in merged:
            merged.append(name)
        if len(merged) >= max_n:
            break
    return merged
