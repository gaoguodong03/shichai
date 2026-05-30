"""设置导入 bundle 时的冲突检测、引用校验与引用更新。"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import yaml

from app.core.scenario_bundle import copy_bundle_skills_to_user, list_skill_ids_in_bundle_skills_dir
from app.core.settings_references import replace_skill_id_in_user_configs


def normalized_name_key(raw: Any) -> str:
    return str(raw or "").strip().casefold()


def mcp_conflict_id_map(existing_servers: List[Dict[str, Any]], bundle_servers: List[Dict[str, Any]]) -> Dict[str, str]:
    by_id = {str(s.get("id") or "").strip(): s for s in existing_servers if str(s.get("id") or "").strip()}
    id_map: Dict[str, str] = {}
    for incoming in bundle_servers:
        incoming_id = str(incoming.get("id") or "").strip()
        incoming_name = normalized_name_key(incoming.get("name"))
        if not incoming_id:
            continue
        for old_id, old in by_id.items():
            if old_id == incoming_id:
                continue
            if incoming_name and normalized_name_key(old.get("name")) == incoming_name:
                id_map[old_id] = incoming_id
    return id_map


def _read_skill_frontmatter(skill_dir: Path) -> Dict[str, Any]:
    path = skill_dir / "SKILL.md"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip().startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _dedupe_nonempty(values: Iterable[Any]) -> List[str]:
    return list(dict.fromkeys(str(x).strip() for x in values if str(x).strip()))


def _reference_items(raw: Any, *, id_keys: Tuple[str, ...] = ("id",), name_keys: Tuple[str, ...] = ("name",)) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    values = raw if isinstance(raw, list) else []
    for item in values:
        ref_id = ""
        name = ""
        if isinstance(item, dict):
            for key in id_keys:
                ref_id = str(item.get(key) or "").strip()
                if ref_id:
                    break
            for key in name_keys:
                name = str(item.get(key) or "").strip()
                if name:
                    break
        else:
            ref_id = str(item or "").strip()
        if not ref_id or ref_id in seen:
            continue
        seen.add(ref_id)
        out.append({"id": ref_id, "name": name})
    return out


def mcp_refs_from_skill_frontmatter(fm: Dict[str, Any]) -> List[Dict[str, str]]:
    labels = fm.get("reference-labels") if isinstance(fm.get("reference-labels"), dict) else {}
    label_rows = _reference_items(labels.get("mcp") if isinstance(labels, dict) else None)
    label_by_id = {row["id"]: row.get("name", "") for row in label_rows if row.get("id")}
    auto = fm.get("auto-tools")
    if isinstance(auto, dict) and "mcp" in auto:
        refs = _reference_items(auto.get("mcp"), id_keys=("id", "server_id", "mcp_server_id"), name_keys=("name", "label"))
        return [{**ref, "name": ref.get("name") or label_by_id.get(ref["id"], "")} for ref in refs]
    allowed = fm.get("allowed-tools")
    if isinstance(allowed, dict) and "mcp" in allowed:
        refs = _reference_items(allowed.get("mcp"), id_keys=("id", "server_id", "mcp_server_id"), name_keys=("name", "label"))
        return [{**ref, "name": ref.get("name") or label_by_id.get(ref["id"], "")} for ref in refs]
    refs = _reference_items(fm.get("mcp_server_ids"), id_keys=("id", "server_id", "mcp_server_id"), name_keys=("name", "label"))
    return [{**ref, "name": ref.get("name") or label_by_id.get(ref["id"], "")} for ref in refs]


def mcp_ids_from_skill_frontmatter(fm: Dict[str, Any]) -> List[str]:
    return [item["id"] for item in mcp_refs_from_skill_frontmatter(fm)]


def collect_mcp_ids_from_skill_dirs(skills_root: Path, skill_ids: Iterable[str]) -> List[str]:
    return [ref["id"] for ref in collect_mcp_refs_from_skill_dirs(skills_root, skill_ids)]


def collect_mcp_refs_from_skill_dirs(skills_root: Path, skill_ids: Iterable[str]) -> List[Dict[str, str]]:
    refs: List[Dict[str, str]] = []
    seen: Set[str] = set()
    root = skills_root.resolve()
    for sid in _dedupe_nonempty(skill_ids):
        if ".." in sid or "/" in sid or "\\" in sid:
            continue
        skill_dir = (skills_root / sid).resolve()
        try:
            skill_dir.relative_to(root)
        except ValueError:
            continue
        if not (skill_dir / "SKILL.md").is_file():
            continue
        for ref in mcp_refs_from_skill_frontmatter(_read_skill_frontmatter(skill_dir)):
            mid = ref["id"]
            if mid not in seen:
                seen.add(mid)
                refs.append(ref)
    return refs


def mcp_rows_for_bundle_refs(
    mcp_refs: Iterable[Dict[str, str]],
    all_servers: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_id = {
        str(row.get("id") or "").strip(): row
        for row in all_servers
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    by_name: Dict[str, Dict[str, Any]] = {}
    for row in all_servers:
        if not isinstance(row, dict):
            continue
        name_key = normalized_name_key(row.get("name"))
        if name_key and name_key not in by_name:
            by_name[name_key] = row

    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for ref in mcp_refs:
        rid = str((ref or {}).get("id") or "").strip()
        if not rid:
            continue
        name = str((ref or {}).get("name") or "").strip()
        row = by_id.get(rid)
        if row is None and name:
            row = by_name.get(normalized_name_key(name))
        if row is None:
            continue
        copied = dict(row)
        if str(copied.get("id") or "").strip() != rid:
            copied["id"] = rid
        if name and not str(copied.get("name") or "").strip():
            copied["name"] = name
        out_id = str(copied.get("id") or "").strip()
        if out_id and out_id not in seen:
            seen.add(out_id)
            out.append(copied)
    return out


def _skill_ids_under(root: Path) -> Set[str]:
    if not root.is_dir():
        return set()
    return {
        child.name
        for child in root.iterdir()
        if child.is_dir() and (child / "SKILL.md").is_file()
    }


def _skill_dir_for_id(
    sid: str,
    *,
    bundle_dir: Optional[Path],
    user_skills_dir: Path,
    extra_skill_roots: Iterable[Path] = (),
) -> Optional[Path]:
    if not sid or ".." in sid or "/" in sid or "\\" in sid:
        return None
    roots: List[Path] = []
    if bundle_dir is not None:
        roots.append(bundle_dir / "skills")
    roots.append(user_skills_dir)
    roots.extend(extra_skill_roots)
    for root in roots:
        if not root:
            continue
        base = root.resolve()
        cand = (root / sid).resolve()
        try:
            cand.relative_to(base)
        except ValueError:
            continue
        if (cand / "SKILL.md").is_file():
            return cand
    return None


def _empty_missing_references() -> Dict[str, List[Dict[str, Any]]]:
    return {"experts": [], "skills": [], "tools": []}


def _missing_type_label(kind: str) -> str:
    return {"experts": "专家", "skills": "技能", "tools": "MCP 工具"}.get(kind, "资源")


def _add_missing_reference(
    missing: Dict[str, List[Dict[str, Any]]],
    kind: str,
    ref_id: str,
    *,
    name: str = "",
    required_by: str,
    source: str,
) -> None:
    rid = str(ref_id or "").strip()
    if not rid:
        return
    type_label = _missing_type_label(kind)
    display_name = str(name or "").strip() or f"{type_label} {rid}"
    bucket = missing.setdefault(kind, [])
    for item in bucket:
        if item.get("id") == rid and item.get("source") == source:
            reqs = item.setdefault("required_by", [])
            if required_by and required_by not in reqs:
                reqs.append(required_by)
            if name and not item.get("name"):
                item["name"] = name
                item["display_name"] = display_name
            return
    bucket.append(
        {
            "id": rid,
            "name": str(name or ""),
            "display_name": display_name,
            "type_label": type_label,
            "required_by": [required_by] if required_by else [],
            "source": source,
        }
    )


def _available_skill_ids(
    bundle_dir: Optional[Path],
    user_skills_dir: Path,
    extra_skill_roots: Iterable[Path],
) -> Set[str]:
    out = set(list_skill_ids_in_bundle_skills_dir(bundle_dir)) if bundle_dir is not None else set()
    out.update(_skill_ids_under(user_skills_dir))
    for root in extra_skill_roots:
        out.update(_skill_ids_under(root))
    return out


def _available_mcp_ids(existing_mcp_servers: Iterable[Dict[str, Any]], bundle_mcp_servers: Iterable[Dict[str, Any]]) -> Set[str]:
    out = {
        str(row.get("id") or "").strip()
        for row in existing_mcp_servers
        if str(row.get("id") or "").strip()
    }
    out.update(
        str(row.get("id") or "").strip()
        for row in bundle_mcp_servers
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    )
    return out


def _skill_mcp_refs_for_missing_check(
    sid: str,
    *,
    bundle_dir: Optional[Path],
    user_skills_dir: Path,
    extra_skill_roots: Iterable[Path],
) -> Tuple[List[Dict[str, str]], str]:
    skill_dir = _skill_dir_for_id(
        sid,
        bundle_dir=bundle_dir,
        user_skills_dir=user_skills_dir,
        extra_skill_roots=extra_skill_roots,
    )
    if skill_dir is None:
        return [], sid
    fm = _read_skill_frontmatter(skill_dir)
    return mcp_refs_from_skill_frontmatter(fm), str(fm.get("name") or sid).strip() or sid


def find_missing_references_for_scene_bundle(
    preset: Dict[str, Any],
    bundle_experts: List[Dict[str, Any]],
    bundle_mcp_servers: List[Dict[str, Any]],
    bundle_dir: Path,
    user_skills_dir: Path,
    existing_experts: Iterable[Dict[str, Any]],
    existing_mcp_servers: Iterable[Dict[str, Any]],
    *,
    extra_skill_roots: Iterable[Path] = (),
) -> Dict[str, List[Dict[str, Any]]]:
    missing = _empty_missing_references()
    preset_name = str(preset.get("name") or preset.get("id") or "场景").strip()
    scene_label = f"场景 {preset_name}"
    host_label = "场景主持人"

    bundle_expert_by_id = {
        str(row.get("agent_id") or "").strip(): row
        for row in bundle_experts
        if str(row.get("agent_id") or "").strip()
    }
    existing_expert_ids = {
        str(row.get("agent_id") or "").strip()
        for row in existing_experts
        if str(row.get("agent_id") or "").strip()
    }
    available_skills = _available_skill_ids(bundle_dir, user_skills_dir, extra_skill_roots)
    available_mcp = _available_mcp_ids(existing_mcp_servers, bundle_mcp_servers)

    preset_agent_ids = _dedupe_nonempty(preset.get("agent_ids") or preset.get("expert_ids") or [])
    for aid in preset_agent_ids:
        if aid not in bundle_expert_by_id and aid not in existing_expert_ids:
            _add_missing_reference(missing, "experts", aid, required_by=scene_label, source="scene")

    host_config = preset.get("host_config") if isinstance(preset.get("host_config"), dict) else {}
    skill_refs: Dict[str, List[str]] = {}
    for sid in _dedupe_nonempty(host_config.get("skill_ids") or []):
        skill_refs.setdefault(sid, []).append(host_label)
    for mid in _dedupe_nonempty(host_config.get("mcp_server_ids") or []):
        if mid not in available_mcp:
            _add_missing_reference(missing, "tools", mid, required_by=host_label, source="scene")

    for expert in bundle_experts:
        aid = str(expert.get("agent_id") or "").strip()
        expert_name = str(expert.get("name") or aid or "未命名专家").strip()
        expert_label = f"专家 {expert_name}"
        for sid in _dedupe_nonempty(expert.get("skill_ids") or []):
            skill_refs.setdefault(sid, []).append(expert_label)
        for mid in _dedupe_nonempty(expert.get("mcp_server_ids") or []):
            if mid not in available_mcp:
                _add_missing_reference(missing, "tools", mid, required_by=expert_label, source="expert")

    for sid, required_by_list in skill_refs.items():
        if sid not in available_skills:
            for required_by in required_by_list:
                _add_missing_reference(missing, "skills", sid, required_by=required_by, source="skill")
            continue
        mcp_refs, skill_name = _skill_mcp_refs_for_missing_check(
            sid,
            bundle_dir=bundle_dir,
            user_skills_dir=user_skills_dir,
            extra_skill_roots=extra_skill_roots,
        )
        skill_label = f"技能 {skill_name}"
        for ref in mcp_refs:
            mid = ref["id"]
            if mid not in available_mcp:
                _add_missing_reference(missing, "tools", mid, name=ref.get("name", ""), required_by=skill_label, source="skill")
    return missing


def find_missing_references_for_expert_bundle(
    expert: Dict[str, Any],
    bundle_mcp_servers: List[Dict[str, Any]],
    bundle_dir: Path,
    user_skills_dir: Path,
    existing_mcp_servers: Iterable[Dict[str, Any]],
    *,
    extra_skill_roots: Iterable[Path] = (),
) -> Dict[str, List[Dict[str, Any]]]:
    missing = _empty_missing_references()
    expert_name = str(expert.get("name") or expert.get("agent_id") or "未命名专家").strip()
    expert_label = f"专家 {expert_name}"
    available_skills = _available_skill_ids(bundle_dir, user_skills_dir, extra_skill_roots)
    available_mcp = _available_mcp_ids(existing_mcp_servers, bundle_mcp_servers)

    for mid in _dedupe_nonempty(expert.get("mcp_server_ids") or []):
        if mid not in available_mcp:
            _add_missing_reference(missing, "tools", mid, required_by=expert_label, source="expert")
    for sid in _dedupe_nonempty(expert.get("skill_ids") or []):
        if sid not in available_skills:
            _add_missing_reference(missing, "skills", sid, required_by=expert_label, source="skill")
            continue
        mcp_refs, skill_name = _skill_mcp_refs_for_missing_check(
            sid,
            bundle_dir=bundle_dir,
            user_skills_dir=user_skills_dir,
            extra_skill_roots=extra_skill_roots,
        )
        skill_label = f"技能 {skill_name}"
        for ref in mcp_refs:
            mid = ref["id"]
            if mid not in available_mcp:
                _add_missing_reference(missing, "tools", mid, name=ref.get("name", ""), required_by=skill_label, source="skill")
    return missing


def find_missing_references_for_skill_bundle(
    skill_id: str,
    bundle_mcp_servers: List[Dict[str, Any]],
    bundle_dir: Optional[Path],
    user_skills_dir: Path,
    existing_mcp_servers: Iterable[Dict[str, Any]],
    *,
    extra_skill_roots: Iterable[Path] = (),
) -> Dict[str, List[Dict[str, Any]]]:
    missing = _empty_missing_references()
    available_mcp = _available_mcp_ids(existing_mcp_servers, bundle_mcp_servers)
    mcp_refs, skill_name = _skill_mcp_refs_for_missing_check(
        skill_id,
        bundle_dir=bundle_dir,
        user_skills_dir=user_skills_dir,
        extra_skill_roots=extra_skill_roots,
    )
    skill_label = f"技能 {skill_name}"
    for ref in mcp_refs:
        mid = ref["id"]
        if mid not in available_mcp:
            _add_missing_reference(missing, "tools", mid, name=ref.get("name", ""), required_by=skill_label, source="skill")
    return missing


def skill_conflict_id_map(bundle_dir: Path, user_skills_dir: Path, skill_ids: List[str]) -> Dict[str, str]:
    id_map: Dict[str, str] = {}
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    existing_by_id: Dict[str, str] = {}
    existing_name_to_ids: Dict[str, List[str]] = {}
    for child in sorted(user_skills_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        fm = _read_skill_frontmatter(child)
        sid = child.name
        existing_by_id[sid] = normalized_name_key(fm.get("name") or sid)
        if existing_by_id[sid]:
            existing_name_to_ids.setdefault(existing_by_id[sid], []).append(sid)

    for incoming_id in skill_ids:
        src = bundle_dir / "skills" / incoming_id
        if not src.is_dir() or not (src / "SKILL.md").is_file():
            continue
        fm = _read_skill_frontmatter(src)
        incoming_name_key = normalized_name_key(fm.get("name") or incoming_id)
        conflict_ids: List[str] = []
        if incoming_id in existing_by_id:
            conflict_ids.append(incoming_id)
        if incoming_name_key:
            conflict_ids.extend(old_id for old_id in existing_name_to_ids.get(incoming_name_key, []) if old_id != incoming_id)
        for old_id in dict.fromkeys(conflict_ids):
            id_map[old_id] = incoming_id
    return id_map


def copy_bundle_skills_to_user_by_name(bundle_dir: Path, user_skills_dir: Path) -> Tuple[List[str], List[str], Dict[str, str]]:
    skill_ids = list_skill_ids_in_bundle_skills_dir(bundle_dir)
    id_map = skill_conflict_id_map(bundle_dir, user_skills_dir, skill_ids)
    overwritten = sorted(id_map.keys())
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    for old_id in overwritten:
        old_dir = user_skills_dir / old_id
        if old_dir.is_dir():
            shutil.rmtree(old_dir, ignore_errors=True)
    imported, _skipped = copy_bundle_skills_to_user(bundle_dir, user_skills_dir, overwrite=True)
    for old_id, new_id in id_map.items():
        replace_skill_id_in_user_configs(old_id, new_id)
    return imported, overwritten, id_map
