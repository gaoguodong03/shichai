"""Agent id normalization, skill selection, and LLM resolution helpers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.llm_client import (
    build_llm_credential_notice,
    get_llm_from_config,
    resolve_llm_api_key,
    resolve_llm_provider_entry,
)
from app.api.settings_secrets import load_api_secret_values
from app.agent.scene_runtime import pick_scene_host_skill_id


def _normalize_agent_ids(
    agent_ids: Optional[List[str]] = None,
) -> List[str]:
    """Normalize current id fields."""
    return list(agent_ids or [])


def _name_key(name: Any) -> str:
    return str(name or "").strip().lower()


def _to_agent_style_id(raw_id: str) -> str:
    agent_id = str(raw_id or "").strip()
    if not agent_id:
        return agent_id
    if agent_id.startswith("agent-"):
        return agent_id
    return f"agent-{agent_id}"


def _build_preferred_agent_id_map(instances: List[Dict[str, Any]]) -> Dict[str, str]:
    """Build id->preferred-id mapping; prefer agent-* within the same expert name."""
    name_to_ids: Dict[str, List[str]] = {}
    for instance in instances or []:
        agent_id = str(instance.get("agent_id") or "").strip()
        if not agent_id:
            continue
        key = _name_key(instance.get("name") or agent_id)
        name_to_ids.setdefault(key, [])
        if agent_id not in name_to_ids[key]:
            name_to_ids[key].append(agent_id)

    name_to_preferred: Dict[str, str] = {}
    for key, ids in name_to_ids.items():
        name_to_preferred[key] = next((item for item in ids if item.startswith("agent-")), _to_agent_style_id(ids[0]))

    id_to_preferred: Dict[str, str] = {}
    for instance in instances or []:
        agent_id = str(instance.get("agent_id") or "").strip()
        if not agent_id:
            continue
        key = _name_key(instance.get("name") or agent_id)
        id_to_preferred[agent_id] = name_to_preferred.get(key, agent_id)
    return id_to_preferred


def _build_preferred_instances(
    instances: List[Dict[str, Any]],
    *,
    id_to_preferred: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Clone instances to canonical agent-* ids, keeping one row per canonical id."""
    preferred_to_row: Dict[str, Dict[str, Any]] = {}
    for instance in instances or []:
        agent_id = str(instance.get("agent_id") or "").strip()
        if not agent_id:
            continue
        preferred = id_to_preferred.get(agent_id, agent_id)
        row = dict(instance)
        row["agent_id"] = preferred
        if preferred not in preferred_to_row or agent_id == preferred:
            preferred_to_row[preferred] = row
    return list(preferred_to_row.values())


def _normalize_to_preferred_agent_ids(
    ids: List[str],
    *,
    id_to_preferred: Dict[str, str],
) -> List[str]:
    out: List[str] = []
    for raw in ids or []:
        agent_id = str(raw or "").strip()
        if not agent_id:
            continue
        preferred = id_to_preferred.get(agent_id, agent_id)
        if preferred not in out:
            out.append(preferred)
    return out


def _default_leader_agent_id(preferred_instances: List[Dict[str, Any]]) -> str:
    """Compatibility for old data: an is_leader expert used to be the host."""
    for instance in preferred_instances or []:
        if instance.get("is_leader") and instance.get("agent_id"):
            return str(instance.get("agent_id")).strip()
    return ""


def _pick_resolved_host_skill_id(skill_ids: List[str]) -> str:
    return pick_scene_host_skill_id(skill_ids)


def _resolve_llm_provider_for_agent(
    agent_profile: Optional[Dict[str, Any]],
    app_settings: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    """Resolve the provider id/config used by an Agent or the app default."""
    provider = (agent_profile.get("llm_provider_id") or "").strip() if agent_profile else ""
    if not provider:
        provider = str(app_settings.get("default_llm") or "qwen").strip() or "qwen"
    return resolve_llm_provider_entry(provider, app_settings.get("llm_providers"))


def _llm_credential_notice_for_agent(
    agent_profile: Optional[Dict[str, Any]],
    app_settings: Dict[str, Any],
) -> Optional[str]:
    """Return a host-facing notice when the resolved provider has no API key."""
    provider_id, cfg = _resolve_llm_provider_for_agent(agent_profile, app_settings)
    secrets = load_api_secret_values()
    if resolve_llm_api_key(cfg, secrets):
        return None
    return build_llm_credential_notice(provider_id, cfg)


def _get_llm_for_agent(agent_profile: Optional[Dict[str, Any]], app_settings: Dict[str, Any]) -> Any:
    """Create the LLM configured for an Agent, falling back to the app default provider."""
    provider_id, _cfg = _resolve_llm_provider_for_agent(agent_profile, app_settings)
    secrets = load_api_secret_values()
    return get_llm_from_config(provider_id, app_settings.get("llm_providers"), secrets)


def _last_user_message_text(messages: List[Dict[str, Any]]) -> str:
    """Return the latest user message body."""
    for message in reversed(messages or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""
