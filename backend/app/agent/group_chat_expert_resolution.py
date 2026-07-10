"""Agent skill selection and LLM resolution helpers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.llm_client import (
    build_llm_credential_notice,
    get_llm_from_config,
    resolve_llm_api_key,
    resolve_llm_provider_entry,
)
from app.api.settings_env_vars import load_env_var_values


def _resolve_llm_config_for_agent(
    agent_profile: Optional[Dict[str, Any]],
    app_settings: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    """Resolve the model-name config used by an Agent or the app default."""
    llm_name = (agent_profile.get("llm_name") or "").strip() if agent_profile else ""
    if not llm_name:
        llm_name = str(app_settings.get("default_llm") or "qwen3-max").strip() or "qwen3-max"
    return resolve_llm_provider_entry(llm_name, app_settings.get("llm_providers"))


def _llm_credential_notice_for_agent(
    agent_profile: Optional[Dict[str, Any]],
    app_settings: Dict[str, Any],
) -> Optional[str]:
    """Return a host-facing notice when the resolved provider has no API key."""
    llm_name, cfg = _resolve_llm_config_for_agent(agent_profile, app_settings)
    env_vars = load_env_var_values()
    if resolve_llm_api_key(cfg, env_vars):
        return None
    return build_llm_credential_notice(llm_name, cfg)


def _get_llm_for_agent(agent_profile: Optional[Dict[str, Any]], app_settings: Dict[str, Any]) -> Any:
    """Create the LLM configured for an Agent, falling back to the app default provider."""
    llm_name, _cfg = _resolve_llm_config_for_agent(agent_profile, app_settings)
    env_vars = load_env_var_values()
    return get_llm_from_config(llm_name, app_settings.get("llm_providers"), env_vars)


def _last_user_message_text(messages: List[Dict[str, Any]]) -> str:
    """Return the latest user message body."""
    for message in reversed(messages or []):
        speaker = message.get("speaker") if isinstance(message, dict) and isinstance(message.get("speaker"), dict) else {}
        if isinstance(message, dict) and speaker.get("type") == "user":
            body = message.get("message")
            if isinstance(body, dict):
                return str(body.get("content") or "").strip()
            return ""
    return ""
