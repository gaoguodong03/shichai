"""场景预设（session preset）依赖校验：专家、技能、MCP。无 I/O，便于单测。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.host_config import normalize_host_config_dict
from app.core.name_based_resources import normalize_scenario_row


def extract_presets_from_import_body(data: Any) -> List[Dict[str, Any]]:
    """从导入 JSON 中解析出预设对象列表（支持 export 包装或裸预设）。"""
    if not isinstance(data, dict):
        return []
    inner = data.get("preset")
    if isinstance(inner, dict):
        return [inner]
    many = data.get("presets")
    if isinstance(many, list):
        return [x for x in many if isinstance(x, dict)]
    name = str(data.get("name") or "").strip()
    agent_names = data.get("agent_names")
    if name and isinstance(agent_names, list) and agent_names:
        return [dict(data)]
    return []


def normalize_preset_dict_for_validation(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """与 get_session_presets 类似的行规范化；无效则 None。"""
    if not isinstance(item, dict):
        return None
    try:
        return normalize_scenario_row(item)
    except ValueError:
        return None


def _mcp_name_maps(servers: Sequence[Mapping[str, Any]]) -> Dict[str, bool]:
    """name -> present."""
    by_name: Dict[str, bool] = {}
    for s in servers or []:
        name = str(s.get("name") or "").strip()
        if not name:
            continue
        by_name[name] = True
    return by_name


@dataclass
class SessionPresetValidation:
    missing_agents: List[str] = field(default_factory=list)
    missing_skills: List[Dict[str, str]] = field(default_factory=list)
    missing_mcp_servers: List[Dict[str, str]] = field(default_factory=list)
    disabled_mcp_servers: List[Dict[str, str]] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return (
            not self.missing_agents
            and not self.missing_skills
            and not self.missing_mcp_servers
        )


def validate_session_preset(
    preset: Mapping[str, Any],
    *,
    agent_by_name: Mapping[str, Mapping[str, Any]],
    skill_has_content: Callable[[str], bool],
    mcp_servers: Sequence[Mapping[str, Any]],
) -> SessionPresetValidation:
    """
    agent_by_name: name -> 专家配置
    skill_has_content: 与群聊一致，能加载 SKILL 正文则 True
    mcp_servers: load_mcp_config() 的列表
    """
    out = SessionPresetValidation()
    _ = mcp_servers

    agent_names = [str(x.get("name") if isinstance(x, Mapping) else x).strip() for x in (preset.get("agent_names") or []) if str(x.get("name") if isinstance(x, Mapping) else x).strip()]
    for agent_name in agent_names:
        if agent_name not in agent_by_name:
            out.missing_agents.append(agent_name)

    def check_skills(skills: Sequence[Any], *, context: str, agent_name: str = "") -> None:
        for skill in skills:
            sk = str(skill.get("directory_name") if isinstance(skill, Mapping) else skill).strip()
            if not sk:
                continue
            if not skill_has_content(sk):
                row: Dict[str, str] = {"context": context, "skill": sk}
                if agent_name:
                    row["agent"] = agent_name
                out.missing_skills.append(row)

    hc_raw = preset.get("host") or preset.get("host_config")
    if isinstance(hc_raw, dict):
        hc = normalize_host_config_dict(hc_raw)
        skill_directory = str(hc.get("skill_directory") or "").strip()
        if skill_directory and not skill_has_content(skill_directory):
            out.missing_skills.append({"context": "host", "skill": skill_directory})

    for agent_name in agent_names:
        agent_profile = agent_by_name.get(agent_name)
        if not isinstance(agent_profile, Mapping):
            continue
        skills = agent_profile.get("skills") if isinstance(agent_profile.get("skills"), list) else []
        check_skills(skills, context="agent", agent_name=agent_name)

    return out


def validation_to_api_dict(v: SessionPresetValidation) -> Dict[str, Any]:
    return {
        "valid": v.valid,
        "missing_agents": list(v.missing_agents),
        "missing_skills": list(v.missing_skills),
        "missing_mcp_servers": list(v.missing_mcp_servers),
        "disabled_mcp_servers": list(v.disabled_mcp_servers),
    }
