"""Resolve skill MCP declarations to local server ids by id or normalized name."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


def normalized_name_key(raw: Any) -> str:
    return str(raw or "").strip().casefold()


def _mcp_ref_name_by_id(mcp_refs: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not isinstance(mcp_refs, list):
        return out
    for item in mcp_refs:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("id") or item.get("mcp_server_id") or item.get("server_id") or "").strip()
        name = str(item.get("name") or item.get("display_name") or item.get("label") or "").strip()
        if rid and name and rid not in out:
            out[rid] = name
    return out


def build_mcp_server_index(
    servers: Iterable[Mapping[str, Any]],
) -> Tuple[Dict[str, Mapping[str, Any]], Dict[str, Mapping[str, Any]]]:
    by_id: Dict[str, Mapping[str, Any]] = {}
    by_name: Dict[str, Mapping[str, Any]] = {}
    for row in servers:
        rid = str(row.get("id") or "").strip()
        if rid:
            by_id[rid] = row
        name_key = normalized_name_key(row.get("name"))
        if name_key and name_key not in by_name:
            by_name[name_key] = row
    return by_id, by_name


def resolve_skill_mcp_declaration(
    declared: str,
    *,
    by_id: Mapping[str, Mapping[str, Any]],
    by_name: Mapping[str, Mapping[str, Any]],
    ref_names: Mapping[str, str],
) -> Optional[str]:
    decl = str(declared or "").strip()
    if not decl:
        return None
    if decl in by_id:
        return decl
    for candidate in (decl, ref_names.get(decl, "")):
        key = normalized_name_key(candidate)
        if not key:
            continue
        row = by_name.get(key)
        if row is not None:
            resolved = str(row.get("id") or "").strip()
            if resolved:
                return resolved
    return None


def resolve_skill_mcp_declarations(
    declared_ids: Iterable[str],
    mcp_refs: Any,
    servers: Iterable[Mapping[str, Any]],
) -> Tuple[List[str], List[str]]:
    """Return (resolved local server ids, unresolved declarations)."""
    by_id, by_name = build_mcp_server_index(servers)
    ref_names = _mcp_ref_name_by_id(mcp_refs)
    resolved: List[str] = []
    missing: List[str] = []
    seen: set[str] = set()
    for raw in declared_ids:
        decl = str(raw or "").strip()
        if not decl:
            continue
        local_id = resolve_skill_mcp_declaration(
            decl,
            by_id=by_id,
            by_name=by_name,
            ref_names=ref_names,
        )
        if local_id is None:
            missing.append(decl)
            continue
        if local_id not in seen:
            seen.add(local_id)
            resolved.append(local_id)
    return resolved, missing
