"""Name-based resource contract helpers.

These helpers are intentionally strict: resource bundle payloads must not carry
database-style ids, and import identity is the human-readable resource name.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List


_ID_KEYS = {
    "id",
    *(f"{prefix}_id" for prefix in ("agent", "expert", "skill", "mcp_server", "llm_provider", "provider", "server", "model", "scenario")),
    *(f"{prefix}_ids" for prefix in ("agent", "expert", "skill", "mcp_server")),
}


def _normalize_skill_directory_ref(raw: Any) -> str:
    """Normalize a Skill reference without changing the directory identity."""
    text = str(raw or "").strip().replace("\\", "/").strip("/")
    if not text or "/" in text or text in {".", ".."}:
        return ""
    if ".." in text.split("/"):
        return ""
    return text


def strip_resource_ids(value: Any) -> Any:
    """Remove every known resource id key from nested dict/list payloads."""
    if isinstance(value, list):
        return [strip_resource_ids(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): strip_resource_ids(item)
            for key, item in value.items()
            if str(key) not in _ID_KEYS
        }
    return value


def removed_resource_identity_fields(value: Any) -> List[str]:
    """Return removed resource identity fields found in a nested payload."""
    found: List[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                walk(child)
            return
        if not isinstance(item, dict):
            return
        for key, child in item.items():
            key_text = str(key)
            if key_text in _ID_KEYS and key_text not in found:
                found.append(key_text)
            walk(child)

    walk(value)
    return found


def normalize_tool_type(raw: Any) -> str:
    value = str(raw or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if value == "mcp":
        return "mcp"
    if value in {"http_api", "httpapi", "http"}:
        return "http_api"
    return value


def _normalize_http_api_config(raw: Any) -> Dict[str, Any]:
    cfg = dict(raw) if isinstance(raw, dict) else {}
    method = str(cfg.get("type") or cfg.get("method") or "GET").strip().upper() or "GET"
    normalized = {
        "type": method,
        "base_url": str(cfg.get("base_url") or "").strip(),
        "path": str(cfg.get("path") or "").strip(),
        "header": dict(cfg.get("header") or cfg.get("headers") or {}),
        "query": dict(cfg.get("query") or {}),
        "body": cfg.get("body") if cfg.get("body") is not None else "",
        "timeout_seconds": int(cfg.get("timeout_seconds") or 60),
    }
    raw_file_upload = cfg.get("file_upload")
    raw_workspace_text = cfg.get("workspace_text")
    if isinstance(raw_file_upload, dict) and isinstance(raw_workspace_text, dict):
        raise ValueError("file_upload 和 workspace_text 不能同时配置。")
    if isinstance(raw_file_upload, dict):
        max_bytes = int(raw_file_upload.get("max_bytes") or 0)
        normalized["file_upload"] = {
            "content_base64_field": str(raw_file_upload.get("content_base64_field") or "contentBase64").strip(),
            "filename_field": str(raw_file_upload.get("filename_field") or "filename").strip(),
            "mime_type_field": str(raw_file_upload.get("mime_type_field") or "mimeType").strip(),
            "max_bytes": max_bytes,
        }
    if isinstance(raw_workspace_text, dict):
        raw_extensions = raw_workspace_text.get("allowed_extensions")
        allowed_extensions = [
            str(item).strip().lower()
            for item in raw_extensions if str(item).strip()
        ] if isinstance(raw_extensions, list) else []
        normalized["workspace_text"] = {
            "content_field": str(raw_workspace_text.get("content_field") or "body").strip(),
            "title_field": str(raw_workspace_text.get("title_field") or "title").strip(),
            "allowed_extensions": allowed_extensions,
            "max_bytes": int(raw_workspace_text.get("max_bytes") or 0),
            "encoding": str(raw_workspace_text.get("encoding") or "utf-8").strip() or "utf-8",
        }
    return normalized


def normalize_tool_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one tool row for the name-based resource contract."""
    name = str((raw or {}).get("name") or "").strip()
    if not name:
        raise ValueError("tool name required")
    tool_type = normalize_tool_type((raw or {}).get("type") or "mcp")
    row: Dict[str, Any] = {
        "name": name,
        "type": tool_type,
        "description": str((raw or {}).get("description") or ""),
    }
    if tool_type == "mcp":
        server_config = (raw or {}).get("server_config")
        if isinstance(server_config, dict):
            server_config = json.dumps(server_config, ensure_ascii=False, indent=2)
        server_config = str(server_config or "").strip()
        if not server_config:
            transport = (raw or {}).get("transport")
            if isinstance(transport, dict):
                server_config = json.dumps({"mcpServers": {name: transport}}, ensure_ascii=False, indent=2)
        if server_config:
            json.loads(server_config)
        row["server_config"] = server_config
    elif tool_type == "http_api":
        row["config"] = _normalize_http_api_config((raw or {}).get("config"))
    else:
        raise ValueError(f"unsupported tool type: {tool_type}")
    return row


def normalize_skill_refs(raw: Any) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        directory_name = _normalize_skill_directory_ref(item.get("directory_name"))
        if not directory_name:
            continue
        key = directory_name
        if key in seen:
            continue
        seen.add(key)
        rows.append({"name": name, "directory_name": directory_name})
    return rows


def normalize_agent_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one Agent row to the minimal name-based resource contract."""
    row = raw if isinstance(raw, dict) else {}
    name = str(row.get("name") or "").strip()
    if not name:
        raise ValueError("agent name required")
    return {
        "name": name,
        "llm_name": str(row.get("llm_name") or "").strip(),
        "description": str(row.get("description") or ""),
        "system_prompt": str(row.get("system_prompt") or "") if row.get("system_prompt") is not None else "",
        "skills": normalize_skill_refs(row.get("skills") or []),
    }


def _agent_names_from_row(row: Dict[str, Any]) -> List[str]:
    raw = row.get("agent_names")
    out: List[str] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        name = str(item.get("name") if isinstance(item, dict) else item).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _normalize_scenario_host_snapshot(raw: Any) -> Dict[str, Any]:
    """Normalize host snapshots to the current `host` contract."""
    cfg = raw if isinstance(raw, dict) else {}
    skill_name = str(cfg.get("skill_name") or "").strip()
    skill_directory = _normalize_skill_directory_ref(cfg.get("skill_directory"))
    return {
        "name": str(cfg.get("name") or "").strip(),
        "llm_name": str(cfg.get("llm_name") or "").strip(),
        "system_prompt": str(cfg.get("system_prompt") or "").strip(),
        "skill_name": skill_name,
        "skill_directory": skill_directory,
    }


def normalize_scenario_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one Scenario row to the minimal name-based resource contract."""
    row = raw if isinstance(raw, dict) else {}
    name = str(row.get("name") or "").strip()
    if not name:
        raise ValueError("scenario name required")
    agent_names = _agent_names_from_row(row)
    if not agent_names:
        raise ValueError("scenario agent_names required")
    allow_agent_recruitment = row.get("allow_agent_recruitment")
    return {
        "name": name,
        "description": str(row.get("description") or ""),
        "system_prompt": str(row.get("system_prompt") or "") if row.get("system_prompt") is not None else "",
        "host": _normalize_scenario_host_snapshot(row.get("host")),
        "agent_names": agent_names,
        "allow_agent_recruitment": allow_agent_recruitment if isinstance(allow_agent_recruitment, bool) else True,
    }
