"""用户设置中 Skill/MCP 引用关系的更新服务。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from app.core.user_context import get_current_user_context


def normalize_reference_rows(raw: Any) -> List[Dict[str, str]]:
    """Normalize lightweight reference snapshots such as [{"id": "...", "name": "..."}]."""
    rows: List[Dict[str, str]] = []
    seen: set[str] = set()
    source = raw if isinstance(raw, list) else []
    for item in source:
        if isinstance(item, dict):
            rid = str(item.get("id") or item.get("agent_id") or item.get("skill_id") or item.get("mcp_server_id") or "").strip()
            name = str(item.get("name") or item.get("display_name") or item.get("label") or "").strip()
        else:
            rid = str(item or "").strip()
            name = ""
        if not rid or rid in seen:
            continue
        row = {"id": rid}
        if name:
            row["name"] = name
        rows.append(row)
        seen.add(rid)
    return rows


def merge_reference_rows_for_ids(
    ids: Any,
    existing_refs: Any = None,
    lookup_names: Mapping[str, str] | None = None,
) -> List[Dict[str, str]]:
    """Build reference snapshots for ids, preferring current names then existing snapshots."""
    normalized_ids: List[str] = []
    seen: set[str] = set()
    for raw in ids or []:
        rid = str(raw).strip()
        if not rid or rid in seen:
            continue
        normalized_ids.append(rid)
        seen.add(rid)

    old_names = {
        row["id"]: str(row.get("name") or "").strip()
        for row in normalize_reference_rows(existing_refs)
        if row.get("id")
    }
    current_names = {str(k): str(v).strip() for k, v in (lookup_names or {}).items() if str(k).strip()}
    rows: List[Dict[str, str]] = []
    for rid in normalized_ids:
        name = current_names.get(rid) or old_names.get(rid) or ""
        row = {"id": rid}
        if name:
            row["name"] = name
        rows.append(row)
    return rows


def remap_id_list(values: Any, id_map: Dict[str, str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in values or []:
        item = str(raw).strip()
        if not item:
            continue
        item = id_map.get(item, item)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def remap_bundle_references(
    preset: Dict[str, Any],
    experts: List[Dict[str, Any]],
    *,
    skill_id_map: Dict[str, str],
    mcp_id_map: Dict[str, str],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    preset_out = dict(preset)
    hc_raw = preset_out.get("host_config")
    if isinstance(hc_raw, dict):
        hc = dict(hc_raw)
        hc["skill_ids"] = remap_id_list(hc.get("skill_ids"), skill_id_map)
        hc["mcp_server_ids"] = remap_id_list(hc.get("mcp_server_ids"), mcp_id_map)
        preset_out["host_config"] = hc
    experts_out: List[Dict[str, Any]] = []
    for row in experts:
        work = dict(row)
        work["skill_ids"] = remap_id_list(work.get("skill_ids"), skill_id_map)
        work["mcp_server_ids"] = remap_id_list(work.get("mcp_server_ids"), mcp_id_map)
        experts_out.append(work)
    return preset_out, experts_out


def _read_json_list(path: Path) -> List[Dict[str, Any]] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, list) else None


def _write_json_list(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_agent_id_missing_in_session_presets(agent_id: str, agent_name: str = "") -> None:
    """删除专家前，为仍引用它的场景保存名称快照，便于 UI 显示缺失项。"""
    aid = (agent_id or "").strip()
    if not aid:
        return
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    path = (user_ctx.config_dir / "session_presets.json").resolve()
    raw = _read_json_list(path)
    if raw is None:
        return
    changed = False
    for preset in raw:
        if not isinstance(preset, dict):
            continue
        agent_ids = preset.get("agent_ids")
        if not isinstance(agent_ids, list) or not agent_ids:
            agent_ids = preset.get("expert_ids")
        if not isinstance(agent_ids, list):
            continue
        normalized = [str(x).strip() for x in agent_ids if str(x).strip()]
        if aid not in normalized:
            continue
        refs = merge_reference_rows_for_ids(
            normalized,
            preset.get("agent_refs"),
            {aid: agent_name} if agent_name else {},
        )
        if refs != normalize_reference_rows(preset.get("agent_refs")):
            preset["agent_refs"] = refs
            changed = True
    if changed:
        try:
            _write_json_list(path, raw)
        except Exception:
            pass


def replace_skill_id_in_user_configs(old_id: str, new_id: str) -> None:
    """技能 id 变化后，同步当前用户专家与场景主持人配置里的 skill_ids。"""
    if not old_id or not new_id or old_id == new_id:
        return
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    path = (user_ctx.config_dir / "dha_instances.json").resolve()
    raw = _read_json_list(path)
    if raw is None:
        return
    changed = False
    for inst in raw:
        if not isinstance(inst, dict):
            continue
        sids = inst.get("skill_ids")
        if not isinstance(sids, list):
            continue
        orig = [str(x).strip() for x in sids if str(x).strip()]
        out = remap_id_list(orig, {old_id: new_id})
        if out != orig:
            inst["skill_ids"] = out
            changed = True
    if changed:
        try:
            _write_json_list(path, raw)
        except Exception:
            pass
    preset_path = (user_ctx.config_dir / "session_presets.json").resolve()
    presets = _read_json_list(preset_path)
    if presets is None:
        return
    changed = False
    for preset in presets:
        if not isinstance(preset, dict) or not isinstance(preset.get("host_config"), dict):
            continue
        hc = preset["host_config"]
        sids = hc.get("skill_ids")
        if not isinstance(sids, list):
            continue
        orig = [str(x).strip() for x in sids if str(x).strip()]
        out = remap_id_list(orig, {old_id: new_id})
        if out != orig:
            hc["skill_ids"] = out
            changed = True
    if changed:
        try:
            _write_json_list(preset_path, presets)
        except Exception:
            pass


def replace_mcp_server_id_in_user_configs(old_id: str, new_id: str) -> None:
    if not old_id or not new_id or old_id == new_id:
        return
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    paths = [
        (user_ctx.config_dir / "dha_instances.json").resolve(),
        (user_ctx.config_dir / "session_presets.json").resolve(),
    ]
    for path in paths:
        raw = _read_json_list(path)
        if raw is None:
            continue
        changed = False
        for row in raw:
            if not isinstance(row, dict):
                continue
            targets = [row]
            if isinstance(row.get("host_config"), dict):
                targets.append(row["host_config"])
            for target in targets:
                mids = target.get("mcp_server_ids")
                if not isinstance(mids, list):
                    continue
                orig = [str(x).strip() for x in mids if str(x).strip()]
                out = remap_id_list(orig, {old_id: new_id})
                if out != orig:
                    target["mcp_server_ids"] = out
                    changed = True
        if changed:
            try:
                _write_json_list(path, raw)
            except Exception:
                pass


def remove_skill_id_from_user_configs(skill_id: str, skill_name: str = "") -> None:
    """删除技能后保留父级引用，并写入名称快照以便 UI 显示缺失项。"""
    sid = (skill_id or "").strip()
    if not sid:
        return
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    lookup = {sid: skill_name} if skill_name else {}
    paths = [
        (user_ctx.config_dir / "dha_instances.json").resolve(),
        (user_ctx.config_dir / "session_presets.json").resolve(),
    ]
    for path in paths:
        raw = _read_json_list(path)
        if raw is None:
            continue
        changed = False
        for row in raw:
            if not isinstance(row, dict):
                continue
            targets = [row]
            if isinstance(row.get("host_config"), dict):
                targets.append(row["host_config"])
            for target in targets:
                sids = target.get("skill_ids")
                if not isinstance(sids, list):
                    continue
                normalized = [str(x).strip() for x in sids if str(x).strip()]
                if sid not in normalized:
                    continue
                refs = merge_reference_rows_for_ids(normalized, target.get("skill_refs"), lookup)
                if refs != normalize_reference_rows(target.get("skill_refs")):
                    target["skill_refs"] = refs
                    changed = True
        if changed:
            try:
                _write_json_list(path, raw)
            except Exception:
                pass
