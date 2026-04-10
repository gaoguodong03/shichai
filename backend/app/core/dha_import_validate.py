"""专家（DHA）导入依赖校验：技能、MCP。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Sequence


@dataclass
class DhaImportValidation:
    missing_skills: List[Dict[str, str]] = field(default_factory=list)
    missing_mcp_servers: List[Dict[str, str]] = field(default_factory=list)
    disabled_mcp_servers: List[Dict[str, str]] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.missing_skills and not self.missing_mcp_servers


def _mcp_id_maps(servers: Sequence[Mapping[str, Any]]) -> Dict[str, bool]:
    by_id: Dict[str, bool] = {}
    for s in servers or []:
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        by_id[sid] = bool(s.get("enabled", True))
    return by_id


def validate_dha_instance_row(
    row: Mapping[str, Any],
    *,
    skill_has_content: Callable[[str], bool],
    mcp_servers: Sequence[Mapping[str, Any]],
) -> DhaImportValidation:
    out = DhaImportValidation()
    mcp_map = _mcp_id_maps(mcp_servers)

    for sid in row.get("skill_ids") or []:
        sk = str(sid).strip()
        if not sk:
            continue
        if not skill_has_content(sk):
            out.missing_skills.append({"skill_id": sk})

    for mid in row.get("mcp_server_ids") or []:
        m = str(mid).strip()
        if not m:
            continue
        if m not in mcp_map:
            out.missing_mcp_servers.append({"mcp_server_id": m})
        elif not mcp_map[m]:
            out.disabled_mcp_servers.append({"mcp_server_id": m})

    return out


def dha_validation_to_api_dict(v: DhaImportValidation) -> Dict[str, Any]:
    return {
        "valid": v.valid,
        "missing_skills": list(v.missing_skills),
        "missing_mcp_servers": list(v.missing_mcp_servers),
        "disabled_mcp_servers": list(v.disabled_mcp_servers),
    }


def extract_expert_from_import_body(data: Any) -> List[Dict[str, Any]]:
    """从 JSON 解析专家对象列表：expert / experts / 裸对象（需含 name）。"""
    if not isinstance(data, dict):
        return []
    one = data.get("expert")
    if isinstance(one, dict):
        return [one]
    many = data.get("experts")
    if isinstance(many, list):
        return [x for x in many if isinstance(x, dict)]
    name = str(data.get("name") or "").strip()
    if not name:
        return []
    return [dict(data)]
