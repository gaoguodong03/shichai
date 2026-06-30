"""专家导入依赖校验：技能。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Sequence


@dataclass
class AgentImportValidation:
    missing_skills: List[Dict[str, str]] = field(default_factory=list)
    missing_mcp_servers: List[Dict[str, str]] = field(default_factory=list)
    disabled_mcp_servers: List[Dict[str, str]] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.missing_skills and not self.missing_mcp_servers


def _mcp_name_maps(servers: Sequence[Mapping[str, Any]]) -> Dict[str, bool]:
    by_name: Dict[str, bool] = {}
    for s in servers or []:
        name = str(s.get("name") or "").strip()
        if not name:
            continue
        by_name[name] = True
    return by_name


def validate_agent_instance_row(
    row: Mapping[str, Any],
    *,
    skill_has_content: Callable[[str], bool],
    mcp_servers: Sequence[Mapping[str, Any]],
) -> AgentImportValidation:
    out = AgentImportValidation()
    _ = mcp_servers

    for skill in row.get("skills") or []:
        sk = str(skill.get("directory_name") if isinstance(skill, Mapping) else skill).strip()
        if not sk:
            continue
        if not skill_has_content(sk):
            out.missing_skills.append({"skill": sk})

    return out


def agent_validation_to_api_dict(v: AgentImportValidation) -> Dict[str, Any]:
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
