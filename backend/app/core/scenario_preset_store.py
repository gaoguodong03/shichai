"""场景预设资源文件存储。

本文件只负责 resources/scenarios/{name}/scenario.json 的读取、规范化、
合并和镜像写入；API 路由只调用这些函数，不直接维护资源文件事务。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from app.core.name_based_resources import normalize_scenario_row
from app.core.resource_store import mirror_rows_to_resource_dir
from app.core.settings_bundle_import import normalized_name_key
from app.core.user_context import get_current_user_context


def preset_names(rows: List[Dict[str, Any]]) -> List[str]:
    return [str(row.get("name") or "").strip() for row in rows if str(row.get("name") or "").strip()]


def scenario_resource_names() -> List[str]:
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return []
    root = user_ctx.scenarios_dir.resolve()
    if not root.is_dir():
        return []
    names: List[str] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if child.is_dir() and (child / "scenario.json").is_file():
            names.append(child.name)
    return names


def normalize_session_preset_row_for_api(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    try:
        return normalize_scenario_row(item)
    except ValueError:
        return None


def load_session_preset_rows_from_resource_files() -> List[Dict[str, Any]]:
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return []
    root = user_ctx.scenarios_dir.resolve()
    if not root.is_dir():
        return []
    rows: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or child.name.startswith("."):
            continue
        body = child / "scenario.json"
        if not body.is_file():
            continue
        try:
            raw = json.loads(body.read_text(encoding="utf-8"))
        except Exception:
            continue
        row = normalize_session_preset_row_for_api(raw if isinstance(raw, dict) else {})
        if row is not None:
            rows.append(row)
    return rows


def merge_session_presets_with_resource_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    _ = rows
    resource_rows = load_session_preset_rows_from_resource_files()
    if not resource_rows:
        return []
    by_name: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for row in resource_rows:
        resource_name = str(row.get("name") or "").strip()
        if not resource_name:
            continue
        order.append(resource_name)
        by_name[resource_name] = row
    return [by_name[resource_name] for resource_name in order if resource_name in by_name]


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def session_preset_item_to_disk_row(item: Any) -> Optional[Dict[str, Any]]:
    """把 API 或导入产生的场景预设对象转换为当前磁盘契约行。"""
    name = str(_item_value(item, "name") or "").strip()
    agent_names = [str(x).strip() for x in (_item_value(item, "agent_names") or []) if str(x).strip()]
    if not name or not agent_names:
        return None
    host_raw = _item_value(item, "host")
    host_norm: Optional[Dict[str, Any]] = None
    if host_raw is not None:
        host_norm = normalize_scenario_row({"name": name, "agent_names": agent_names, "host": host_raw}).get("host")
    row: Dict[str, Any] = {
        "name": name,
        "agent_names": agent_names,
        "description": str(_item_value(item, "description", "") or ""),
        "system_prompt": str(_item_value(item, "system_prompt", "") or ""),
        "allow_agent_recruitment": bool(_item_value(item, "allow_agent_recruitment", True)),
    }
    if host_norm is not None:
        row["host"] = host_norm
    return row


def mirror_session_presets_to_resources(rows: List[Dict[str, Any]]) -> None:
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        mirror_rows_to_resource_dir(
            rows,
            user_ctx.scenarios_dir.resolve(),
            "name",
            body_filename="scenario.json",
        )


def merge_session_presets_into_file(
    normalized_rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """将已规范化的场景行合并写入 resources/scenarios。"""
    existing_rows = load_session_preset_rows_from_resource_files()
    by_name: Dict[str, Dict[str, Any]] = {str(r["name"]): dict(r) for r in existing_rows if r.get("name")}
    original_names = [str(r["name"]) for r in existing_rows if r.get("name")]
    name_to_existing_names: Dict[str, List[str]] = {}
    for row in existing_rows:
        existing_name = str(row.get("name") or "").strip()
        if not existing_name:
            continue
        name_key = normalized_name_key(row.get("name"))
        if name_key:
            name_to_existing_names.setdefault(name_key, []).append(existing_name)

    imported_names: List[str] = []
    overwritten_existing_names: List[str] = []
    overwritten_name_keys: set[str] = set()
    for norm in normalized_rows:
        incoming_name = str((norm or {}).get("name") or "").strip()
        if not incoming_name:
            continue
        incoming_name_key = normalized_name_key(incoming_name)
        same_names = [name for name in name_to_existing_names.get(incoming_name_key, []) if name in by_name]
        if same_names:
            for name in same_names:
                by_name.pop(name, None)
            overwritten_existing_names.extend(same_names)
            overwritten_name_keys.add(incoming_name_key)
        row = session_preset_item_to_disk_row(norm)
        if row is None:
            continue
        by_name[row["name"]] = row
        imported_names.append(row["name"])

    merged: List[Dict[str, Any]] = []
    for name in original_names:
        if normalized_name_key(name) in overwritten_name_keys:
            continue
        if name in by_name:
            merged.append(by_name[name])
    used = {name for name in original_names if normalized_name_key(name) not in overwritten_name_keys}
    for name, row in by_name.items():
        if name not in used:
            merged.append(row)
    mirror_session_presets_to_resources(merged)
    return merged, imported_names, overwritten_existing_names
