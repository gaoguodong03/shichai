"""场景虚拟主持人配置（与 Agent 字段对齐，存于会话 meta / 场景预设）。"""
from __future__ import annotations

from typing import Any, Dict

from app.api.agents import merge_file_capabilities
from app.core.settings_references import merge_reference_rows_for_ids, normalize_reference_rows


LEGACY_DEFAULT_HOST_SKILL_ID = "group-host"


def normalize_host_config_dict(raw: Any) -> Dict[str, Any]:
    """与群聊 build_tools / LLM 使用的 Agent 形状对齐。"""
    if not isinstance(raw, dict):
        raw = {}
    skill_ids = [str(x).strip() for x in (raw.get("skill_ids") or []) if str(x).strip()]
    skill_ids = [
        sid
        for sid in skill_ids
        if sid != LEGACY_DEFAULT_HOST_SKILL_ID
    ][:1]
    sp = raw.get("system_prompt")
    system_prompt = str(sp).strip() if sp is not None else ""
    llm = str(raw.get("llm_provider_id") or "").strip()
    mcp = [str(x).strip() for x in (raw.get("mcp_server_ids") or []) if str(x).strip()]
    fc = merge_file_capabilities(raw.get("file_capabilities") if isinstance(raw.get("file_capabilities"), dict) else {})
    url_cap = raw.get("url_capability")
    if url_cap is None:
        url_cap = True
    display_name = str(raw.get("display_name") or "").strip()
    out: Dict[str, Any] = {
        "skill_ids": skill_ids,
        "system_prompt": system_prompt or None,
        "llm_provider_id": llm,
        "mcp_server_ids": mcp,
        "file_capabilities": fc,
        "url_capability": bool(url_cap),
    }
    if display_name:
        out["display_name"] = display_name
    skill_refs = merge_reference_rows_for_ids(skill_ids, raw.get("skill_refs"))
    if skill_refs:
        out["skill_refs"] = skill_refs
    return out
