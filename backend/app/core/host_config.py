"""场景虚拟主持人配置（与 DHA 字段对齐，存于会话 meta / 场景预设）。"""
from __future__ import annotations

from typing import Any, Dict

from app.api.dha import merge_file_capabilities


def normalize_host_config_dict(raw: Any) -> Dict[str, Any]:
    """与群聊 build_tools / LLM 使用的 DHA 形状对齐。"""
    if not isinstance(raw, dict):
        raw = {}
    skill_ids = [str(x).strip() for x in (raw.get("skill_ids") or []) if str(x).strip()]
    if not skill_ids:
        skill_ids = ["group-host"]
    sp = raw.get("system_prompt")
    system_prompt = str(sp).strip() if sp is not None else ""
    llm = str(raw.get("llm_provider_id") or "").strip()
    mcp = [str(x).strip() for x in (raw.get("mcp_server_ids") or []) if str(x).strip()]
    fc = merge_file_capabilities(raw.get("file_capabilities") if isinstance(raw.get("file_capabilities"), dict) else {})
    url_cap = raw.get("url_capability")
    if url_cap is None:
        url_cap = True
    return {
        "skill_ids": skill_ids,
        "system_prompt": system_prompt or None,
        "llm_provider_id": llm,
        "mcp_server_ids": mcp,
        "file_capabilities": fc,
        "url_capability": bool(url_cap),
    }
