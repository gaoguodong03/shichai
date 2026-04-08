"""招募相关：从主持词中解析 agent_id、合并显式点名优先级。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set


def extract_valid_agent_ids_from_text(text: str, valid_ids: Set[str], max_n: int = 3) -> List[str]:
    """从自由文本里兜底提取合法 agent_id。"""
    if not text or not valid_ids:
        return []
    found = re.findall(r"agent-[a-zA-Z0-9\-]+", str(text), flags=re.I)
    cleaned = [x for x in dict.fromkeys(found) if x in valid_ids]
    return cleaned[: max(0, int(max_n))]


def extract_valid_agent_ids_from_text_or_names(
    text: str,
    valid_ids: Set[str],
    all_instances: List[Dict[str, Any]],
    max_n: int = 3,
) -> List[str]:
    """从主持人自由文本中兜底提取合法专家 ID（支持 agent_id 或专家名字）。"""
    if not text:
        return []
    ids = extract_valid_agent_ids_from_text(text, valid_ids, max_n=max_n)
    if ids:
        return ids[: max(0, int(max_n))]
    name_hits: List[str] = []
    low = str(text).lower()
    for d in all_instances or []:
        did = (d.get("agent_id") or "").strip()
        if not did or did not in valid_ids:
            continue
        name = str(d.get("name") or "").strip()
        if name and name.lower() in low and did not in name_hits:
            name_hits.append(did)
    return name_hits[: max(0, int(max_n))]


def prioritize_suggested_add_ids(
    suggested_ids: List[str],
    *,
    explicit_requested_agent_ids: List[str],
    recruitable_ids: Set[str],
    max_n: int = 3,
) -> List[str]:
    priority = [x for x in (explicit_requested_agent_ids or []) if x in recruitable_ids]
    merged: List[str] = []
    for sid in priority + list(suggested_ids or []):
        if sid in recruitable_ids and sid not in merged:
            merged.append(sid)
        if len(merged) >= max_n:
            break
    return merged
