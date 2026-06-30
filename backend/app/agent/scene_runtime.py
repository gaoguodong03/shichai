"""Scene runtime entrypoint.

This module keeps the "scene" concept as a callable-ish runtime context instead
of scattering session meta interpretation across group_chat.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from app.agent.group_orchestration_fsm import (
    ORCHESTRATION_SCENE,
    available_to_add_for_prompt,
    effective_orchestration_profile,
)
from app.core.host_config import normalize_host_config_dict
from app.core.scene_host import VIRTUAL_SCENE_HOST_ID


def build_context_system_prompt(*, app_settings: Mapping[str, Any], meta_item: Mapping[str, Any]) -> str:
    """Combine platform-wide and scene-level context rules for host/expert turns."""
    sections = [
        str((app_settings or {}).get("system_prompt") or "").strip(),
        str((meta_item or {}).get("system_prompt") or "").strip(),
    ]
    return "\n\n".join(section for section in sections if section)


def pick_scene_host_skill(skill_directories: List[str]) -> str:
    """Pick the host Skill for a scene/host runtime in a predictable way."""
    ids = [str(x).strip() for x in (skill_directories or []) if str(x).strip()]
    if not ids:
        return ""
    for sid in ids:
        if sid.startswith("group-host-") and sid != "group-host":
            return sid
    return ids[0]


def resolve_scene_host_profile(
    meta_item: Mapping[str, Any],
    *,
    agent_map: Mapping[str, Dict[str, Any]],
    app_host_profile: Mapping[str, Any],
    orchestration_profile: str,
) -> Optional[Dict[str, Any]]:
    """Resolve the virtual or legacy real host profile for a group session."""
    base_profile = normalize_host_config_dict(dict(app_host_profile or {}))
    default_display_name = str((app_host_profile or {}).get("leader_agent_name") or "四九").strip() or "四九"
    leader = str((meta_item or {}).get("leader_agent_name") or "").strip()
    role_label = "群聊场景主持人" if orchestration_profile == ORCHESTRATION_SCENE else "群聊主持人"

    def _virtual(profile: Dict[str, Any], *, name: str) -> Dict[str, Any]:
        skill_name = str(profile.get("skill_name") or "").strip()
        skill_directory = str(profile.get("skill_directory") or "").strip()
        out = {
            "name": name,
            "agent_name": name,
            "role": role_label,
            "llm_name": str(profile.get("llm_name") or "").strip(),
            "system_prompt": profile.get("system_prompt"),
            "skills": (
                [{"name": skill_name, "directory_name": skill_directory}]
                if skill_name and skill_directory
                else []
            ),
        }
        out["name"] = name
        return out

    hc = (meta_item or {}).get("host_config")
    if isinstance(hc, dict):
        merged = dict(base_profile)
        merged.update(hc)
        normalized = normalize_host_config_dict(merged)
        display_name = str(normalized.get("leader_agent_name") or "").strip() or default_display_name
        return _virtual(normalized, name=display_name)

    if leader == VIRTUAL_SCENE_HOST_ID:
        return _virtual(base_profile, name=default_display_name)

    if leader and leader in agent_map:
        return dict(agent_map[leader])

    return None


@dataclass(frozen=True)
class SceneRuntime:
    """Resolved scene execution context for one group session turn."""

    session_id: str
    orchestration_profile: str
    agent_names: List[str]
    host_profile: Optional[Dict[str, Any]] = None
    available_to_add_for_scheduler: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_scene(self) -> bool:
        return self.orchestration_profile == ORCHESTRATION_SCENE

    def host_bubble_skill(self) -> str:
        if not self.host_profile:
            return ""
        skills = self.host_profile.get("skills")
        if isinstance(skills, list):
            return pick_scene_host_skill([str(x.get("directory_name") or "").strip() for x in skills if isinstance(x, dict)])
        return ""

    @classmethod
    def from_group_session(
        cls,
        *,
        session_id: str,
        meta_item: Mapping[str, Any],
        agent_names: List[str],
        agent_map: Mapping[str, Dict[str, Any]],
        app_host_profile: Mapping[str, Any],
        available_to_add: List[Dict[str, Any]],
    ) -> "SceneRuntime":
        names = [str(x).strip() for x in (agent_names or []) if str(x).strip()]
        profile = effective_orchestration_profile(dict(meta_item or {}), agent_names=names)
        host = resolve_scene_host_profile(
            meta_item,
            agent_map=agent_map,
            app_host_profile=app_host_profile,
            orchestration_profile=profile,
        )
        available = available_to_add_for_prompt(
            list(available_to_add or []),
            orchestration_profile=profile,
            agent_names=names,
        )
        return cls(
            session_id=session_id,
            orchestration_profile=profile,
            agent_names=names,
            host_profile=host,
            available_to_add_for_scheduler=available,
        )
