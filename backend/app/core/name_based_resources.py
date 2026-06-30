"""Name-based resource contract helpers.

These helpers are intentionally strict: resource bundle payloads must not carry
database-style ids, and import identity is the human-readable resource name.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

import yaml


_ID_KEYS = {
    "id",
    *(f"{prefix}_id" for prefix in ("agent", "expert", "skill", "mcp_server", "llm_provider", "provider", "server", "model", "scenario")),
    *(f"{prefix}_ids" for prefix in ("agent", "expert", "skill", "mcp_server")),
}


def _normalize_skill_folder(raw: Any) -> str:
    folder = str(raw or "").strip().replace("\\", "/").strip("/")
    folder = re.sub(r"[^A-Za-z0-9_-]+", "-", folder).strip("-_").lower()
    if not folder:
        return ""
    return folder


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
    return {
        "type": method,
        "base_url": str(cfg.get("base_url") or "").strip(),
        "path": str(cfg.get("path") or "").strip(),
        "header": dict(cfg.get("header") or cfg.get("headers") or {}),
        "query": dict(cfg.get("query") or {}),
        "body": cfg.get("body") if cfg.get("body") is not None else "",
        "timeout_seconds": int(cfg.get("timeout_seconds") or 60),
    }


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


def _read_skill_name(skill_dir: Path) -> str:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return ""
    text = skill_file.read_text(encoding="utf-8")
    if not text.strip().startswith("---"):
        return ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ""
    try:
        data = yaml.safe_load(parts[1]) or {}
    except Exception:
        return ""
    return str(data.get("name") or "").strip() if isinstance(data, dict) else ""


def next_available_skill_folder(*, desired_folder: str, skill_name: str, user_skills_dir: Path) -> str:
    """Return a skill folder name for importing a differently named Skill."""
    folder = _normalize_skill_folder(desired_folder)
    if not folder:
        folder = f"skill-{uuid.uuid4().hex[:8]}"
    target = user_skills_dir / folder
    if not target.exists():
        return folder
    existing_name = _read_skill_name(target)
    if existing_name and existing_name.strip().casefold() == str(skill_name or "").strip().casefold():
        return folder
    candidate = f"skill-{uuid.uuid4().hex[:8]}"
    while (user_skills_dir / candidate).exists():
        candidate = f"skill-{uuid.uuid4().hex[:8]}"
    return candidate


def normalize_skill_refs(raw: Any) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        directory_name = _normalize_skill_folder(item.get("directory_name") or item.get("folder_name"))
        if not name or not directory_name:
            continue
        key = name.casefold()
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
        "skills": normalize_skill_refs(row.get("skills") or row.get("skill_names") or []),
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


def _normalize_scenario_host_config(raw: Any) -> Dict[str, Any]:
    cfg = raw if isinstance(raw, dict) else {}
    skill_name = str(cfg.get("skill_name") or "").strip()
    skill_directory = _normalize_skill_folder(cfg.get("skill_directory"))
    return {
        "leader_agent_name": str(cfg.get("leader_agent_name") or "").strip(),
        "llm_name": str(cfg.get("llm_name") or "").strip(),
        "system_prompt": str(cfg.get("system_prompt") or "").strip() if cfg.get("system_prompt") is not None else None,
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
    return {
        "name": name,
        "description": str(row.get("description") or ""),
        "system_prompt": str(row.get("system_prompt") or "") if row.get("system_prompt") is not None else "",
        "host_config": _normalize_scenario_host_config(row.get("host_config")),
        "agent_names": agent_names,
    }
