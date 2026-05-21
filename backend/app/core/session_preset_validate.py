"""场景预设（session preset）依赖校验：专家、技能、MCP。无 I/O，便于单测。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.host_config import normalize_host_config_dict
from app.core.scene_host import VIRTUAL_SCENE_HOST_ID


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
    pid = str(data.get("id") or "").strip()
    name = str(data.get("name") or "").strip()
    aids = data.get("agent_ids")
    if not isinstance(aids, list) or not aids:
        aids = data.get("expert_ids")
    if pid and name and isinstance(aids, list) and aids:
        return [dict(data)]
    return []


def normalize_preset_dict_for_validation(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """与 get_session_presets 类似的行规范化；无效则 None。"""
    if not isinstance(item, dict):
        return None
    pid = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    agent_ids = item.get("agent_ids")
    if not isinstance(agent_ids, list) or not agent_ids:
        agent_ids = item.get("expert_ids")
    if not isinstance(agent_ids, list):
        agent_ids = []
    normalized_ids = [str(x).strip() for x in agent_ids if str(x).strip()]
    if not pid or not name or not normalized_ids:
        return None
    hc_raw = item.get("host_config")
    lid = str(item.get("leader_agent_id") or "").strip()
    if isinstance(hc_raw, dict):
        lid = VIRTUAL_SCENE_HOST_ID
    elif not lid:
        lid = normalized_ids[0]
    row: Dict[str, Any] = {
        "id": pid,
        "name": name,
        "agent_ids": normalized_ids,
        "leader_agent_id": lid,
        "description": str(item.get("description") or ""),
        "discussion_goal_example": str(item.get("discussion_goal_example") or ""),
    }
    if isinstance(hc_raw, dict):
        row["host_config"] = dict(hc_raw)
    return row


def _mcp_id_maps(servers: Sequence[Mapping[str, Any]]) -> Dict[str, bool]:
    """id -> enabled"""
    by_id: Dict[str, bool] = {}
    for s in servers or []:
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        by_id[sid] = bool(s.get("enabled", True))
    return by_id


@dataclass
class SessionPresetValidation:
    missing_agent_ids: List[str] = field(default_factory=list)
    missing_skills: List[Dict[str, str]] = field(default_factory=list)
    missing_mcp_servers: List[Dict[str, str]] = field(default_factory=list)
    disabled_mcp_servers: List[Dict[str, str]] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return (
            not self.missing_agent_ids
            and not self.missing_skills
            and not self.missing_mcp_servers
        )


def validate_session_preset(
    preset: Mapping[str, Any],
    *,
    dha_by_id: Mapping[str, Mapping[str, Any]],
    skill_has_content: Callable[[str], bool],
    mcp_servers: Sequence[Mapping[str, Any]],
) -> SessionPresetValidation:
    """
    dha_by_id: agent_id -> 专家配置（需含 skill_ids / mcp_server_ids 列表）
    skill_has_content: 与群聊一致，能加载 SKILL 正文则 True
    mcp_servers: load_mcp_config() 的列表
    """
    out = SessionPresetValidation()
    mcp_map = _mcp_id_maps(mcp_servers)

    agent_ids = [str(x).strip() for x in (preset.get("agent_ids") or []) if str(x).strip()]
    for aid in agent_ids:
        if aid not in dha_by_id:
            out.missing_agent_ids.append(aid)

    def check_skills(skill_ids: Sequence[str], *, context: str, agent_id: str = "") -> None:
        for sid in skill_ids:
            sk = str(sid).strip()
            if not sk:
                continue
            if not skill_has_content(sk):
                row: Dict[str, str] = {"context": context, "skill_id": sk}
                if agent_id:
                    row["agent_id"] = agent_id
                out.missing_skills.append(row)

    def check_mcps(mcp_ids: Sequence[str], *, context: str, agent_id: str = "") -> None:
        for mid in mcp_ids:
            m = str(mid).strip()
            if not m:
                continue
            if m not in mcp_map:
                row = {"context": context, "mcp_server_id": m}
                if agent_id:
                    row["agent_id"] = agent_id
                out.missing_mcp_servers.append(row)
            elif not mcp_map[m]:
                row = {"context": context, "mcp_server_id": m}
                if agent_id:
                    row["agent_id"] = agent_id
                out.disabled_mcp_servers.append(row)

    hc_raw = preset.get("host_config")
    if isinstance(hc_raw, dict):
        hc = normalize_host_config_dict(hc_raw)
        check_skills(hc.get("skill_ids") or [], context="host")
        check_mcps(hc.get("mcp_server_ids") or [], context="host")

    for aid in agent_ids:
        dha = dha_by_id.get(aid)
        if not isinstance(dha, Mapping):
            continue
        sids = dha.get("skill_ids") if isinstance(dha.get("skill_ids"), list) else []
        check_skills([str(x) for x in sids], context="agent", agent_id=aid)
        mids = dha.get("mcp_server_ids") if isinstance(dha.get("mcp_server_ids"), list) else []
        check_mcps([str(x) for x in mids], context="agent", agent_id=aid)

    return out


def validation_to_api_dict(v: SessionPresetValidation) -> Dict[str, Any]:
    return {
        "valid": v.valid,
        "missing_agent_ids": list(v.missing_agent_ids),
        "missing_skills": list(v.missing_skills),
        "missing_mcp_servers": list(v.missing_mcp_servers),
        "disabled_mcp_servers": list(v.disabled_mcp_servers),
    }
