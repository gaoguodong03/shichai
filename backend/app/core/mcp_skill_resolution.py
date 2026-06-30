"""Resolve skill MCP declarations to local server names."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


def normalized_name_key(raw: Any) -> str:
    return str(raw or "").strip().casefold()


def build_mcp_server_index(
    servers: Iterable[Mapping[str, Any]],
) -> Dict[str, Mapping[str, Any]]:
    by_name: Dict[str, Mapping[str, Any]] = {}
    for row in servers:
        name_key = normalized_name_key(row.get("name"))
        if name_key and name_key not in by_name:
            by_name[name_key] = row
    return by_name


def _unique_name_contains_match(candidate: str, by_name: Mapping[str, Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    key = normalized_name_key(candidate)
    if not key:
        return None
    matches = [row for name_key, row in by_name.items() if key in name_key]
    if len(matches) == 1:
        return matches[0]
    return None


def resolve_skill_mcp_declaration(
    declared: str,
    *,
    by_name: Mapping[str, Mapping[str, Any]],
) -> Optional[str]:
    decl = str(declared or "").strip()
    if not decl:
        return None
    key = normalized_name_key(decl)
    row = by_name.get(key)
    if row is not None:
        return str(row.get("name") or "").strip() or decl
    row = _unique_name_contains_match(decl, by_name)
    if row is not None:
        return str(row.get("name") or "").strip() or decl
    return None


def resolve_skill_mcp_declarations(
    declared_ids: Iterable[str],
    servers: Iterable[Mapping[str, Any]],
) -> Tuple[List[str], List[str]]:
    """Return (resolved local server names, unresolved declarations)."""
    by_name = build_mcp_server_index(servers)
    resolved: List[str] = []
    missing: List[str] = []
    seen: set[str] = set()
    for raw in declared_ids:
        decl = str(raw or "").strip()
        if not decl:
            continue
        local_id = resolve_skill_mcp_declaration(
            decl,
            by_name=by_name,
        )
        if local_id is None:
            missing.append(decl)
            continue
        if local_id not in seen:
            seen.add(local_id)
            resolved.append(local_id)
    return resolved, missing
