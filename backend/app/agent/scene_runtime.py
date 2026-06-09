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


def pick_scene_host_skill_id(skill_ids: List[str]) -> str:
    """Pick the host Skill for a scene/host runtime in a predictable way."""
    ids = [str(x).strip() for x in (skill_ids or []) if str(x).strip()]
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
    agent_ids: List[str],
    orchestration_profile: str,
) -> Optional[Dict[str, Any]]:
    """Resolve the virtual or legacy real host profile for a group session."""
    base_profile = normalize_host_config_dict(dict(app_host_profile or {}))
    default_display_name = str((app_host_profile or {}).get("display_name") or "四九").strip() or "四九"
    leader = str((meta_item or {}).get("leader_agent_id") or "").strip()
    role_label = "群聊场景主持人" if orchestration_profile == ORCHESTRATION_SCENE else "群聊主持人"

    def _virtual(profile: Dict[str, Any], *, name: str) -> Dict[str, Any]:
        out = dict(profile)
        out["agent_id"] = VIRTUAL_SCENE_HOST_ID
        out["name"] = name
        out["role"] = role_label
        return out

    hc = (meta_item or {}).get("host_config")
    if isinstance(hc, dict):
        merged = dict(base_profile)
        merged.update(hc)
        display_name = str(merged.get("display_name") or "").strip() or default_display_name
        return _virtual(normalize_host_config_dict(merged), name=display_name)

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
    agent_ids: List[str]
    host_profile: Optional[Dict[str, Any]] = None
    available_to_add_for_scheduler: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_scene(self) -> bool:
        return self.orchestration_profile == ORCHESTRATION_SCENE

    def host_bubble_skill_id(self) -> str:
        if not self.host_profile:
            return ""
        return pick_scene_host_skill_id(list(self.host_profile.get("skill_ids") or []))

    @classmethod
    def from_group_session(
        cls,
        *,
        session_id: str,
        meta_item: Mapping[str, Any],
        agent_ids: List[str],
        agent_map: Mapping[str, Dict[str, Any]],
        app_host_profile: Mapping[str, Any],
        available_to_add: List[Dict[str, Any]],
    ) -> "SceneRuntime":
        ids = [str(x).strip() for x in (agent_ids or []) if str(x).strip()]
        profile = effective_orchestration_profile(dict(meta_item or {}), agent_ids=ids)
        host = resolve_scene_host_profile(
            meta_item,
            agent_map=agent_map,
            app_host_profile=app_host_profile,
            agent_ids=ids,
            orchestration_profile=profile,
        )
        available = available_to_add_for_prompt(
            list(available_to_add or []),
            orchestration_profile=profile,
            agent_ids=ids,
        )
        return cls(
            session_id=session_id,
            orchestration_profile=profile,
            agent_ids=ids,
            host_profile=host,
            available_to_add_for_scheduler=available,
        )
