"""设置导入 bundle 时的冲突检测、引用校验与引用更新。"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import yaml

from app.core.host_profile_contract import normalize_host_profile_dict
from app.core.name_based_resources import normalize_tool_row
from app.core.scenario_bundle import bundle_skills_root, list_skill_directories_in_bundle_skills_dir


def normalized_name_key(raw: Any) -> str:
    return str(raw or "").strip().casefold()


def _new_skill_directory_name(used_directory_names: Set[str]) -> str:
    candidate = f"skill-{uuid.uuid4().hex[:8]}"
    while candidate in used_directory_names:
        candidate = f"skill-{uuid.uuid4().hex[:8]}"
    used_directory_names.add(candidate)
    return candidate


def mcp_name_identity_import_plan(
    existing_servers: List[Dict[str, Any]],
    bundle_servers: List[Dict[str, Any]],
) -> Tuple[Dict[str, str], List[Dict[str, Any]], List[str]]:
    """Plan tool import by name only. Same name overwrites local content."""
    existing_names: Set[str] = set()
    for row in existing_servers:
        name_key = normalized_name_key(row.get("name"))
        if name_key:
            existing_names.add(name_key)

    name_map: Dict[str, str] = {}
    rows_to_import: List[Dict[str, Any]] = []
    overwritten_existing_names: List[str] = []
    for incoming in bundle_servers:
        incoming_name = str(incoming.get("name") or "").strip()
        name_key = normalized_name_key(incoming.get("name"))
        if not incoming_name or not name_key:
            continue
        copied = normalize_tool_row(dict(incoming))
        if name_key in existing_names:
            name_map[incoming_name] = incoming_name
            overwritten_existing_names.append(incoming_name)
        else:
            existing_names.add(name_key)
        name_map[incoming_name] = incoming_name
        rows_to_import.append(copied)
    return name_map, rows_to_import, list(dict.fromkeys(overwritten_existing_names))


def upsert_rows_by_name(
    existing_rows: List[Dict[str, Any]],
    incoming_rows: List[Dict[str, Any]],
    name_key: str,
) -> List[Dict[str, Any]]:
    by_name: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for row in existing_rows:
        name = str(row.get(name_key) or "").strip()
        if not name:
            continue
        if name not in by_name:
            order.append(name)
        by_name[name] = dict(row)
    for row in incoming_rows:
        name = str(row.get(name_key) or "").strip()
        if not name:
            continue
        if name not in by_name:
            order.append(name)
        by_name[name] = dict(row)
    return [by_name[name] for name in order if name in by_name]


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


def _reference_items(raw: Any, *, name_keys: Tuple[str, ...] = ("name",)) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    values = raw if isinstance(raw, list) else []
    for item in values:
        name = ""
        if isinstance(item, dict):
            for key in name_keys:
                name = str(item.get(key) or "").strip()
                if name:
                    break
        else:
            name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"name": name})
    return out


def mcp_refs_from_skill_frontmatter(fm: Dict[str, Any]) -> List[Dict[str, str]]:
    allowed = fm.get("allowed-tools")
    if not isinstance(allowed, dict):
        return []
    refs: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for key in ("mcp", "http_api"):
        for row in _reference_items(allowed.get(key)):
            name = row.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            refs.append(row)
    return refs


def tool_names_from_skill_frontmatter(fm: Dict[str, Any]) -> List[str]:
    return [item["name"] for item in mcp_refs_from_skill_frontmatter(fm)]


def collect_tool_names_from_skill_dirs(skills_root: Path, skill_directories: Iterable[str]) -> List[str]:
    return [ref["name"] for ref in collect_mcp_refs_from_skill_dirs(skills_root, skill_directories)]


def collect_mcp_refs_from_skill_dirs(skills_root: Path, skill_directories: Iterable[str]) -> List[Dict[str, str]]:
    refs: List[Dict[str, str]] = []
    seen: Set[str] = set()
    root = skills_root.resolve()
    for sid in _dedupe_nonempty(skill_directories):
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
            tool_name = ref["name"]
            if tool_name not in seen:
                seen.add(tool_name)
                refs.append(ref)
    return refs


def mcp_rows_for_bundle_refs(
    mcp_refs: Iterable[Dict[str, str]],
    all_servers: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
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
        name = str((ref or {}).get("name") or "").strip()
        if not name:
            continue
        row = by_name.get(normalized_name_key(name))
        if row is None:
            continue
        copied = normalize_tool_row(dict(row))
        out_name = str(copied.get("name") or "").strip()
        if out_name and out_name not in seen:
            seen.add(out_name)
            out.append(copied)
    return out


def _skill_directories_under(root: Path) -> Set[str]:
    if not root.is_dir():
        return set()
    return {
        child.name
        for child in root.iterdir()
        if child.is_dir() and (child / "SKILL.md").is_file()
    }


def _skill_dir_for_directory_name(
    directory_name: str,
    *,
    bundle_dir: Optional[Path],
    user_skills_dir: Path,
    extra_skill_roots: Iterable[Path] = (),
) -> Optional[Path]:
    if not directory_name or ".." in directory_name or "/" in directory_name or "\\" in directory_name:
        return None
    roots: List[Path] = []
    if bundle_dir is not None:
        roots.append(bundle_skills_root(bundle_dir))
    roots.append(user_skills_dir)
    roots.extend(extra_skill_roots)
    for root in roots:
        if not root:
            continue
        base = root.resolve()
        cand = (root / directory_name).resolve()
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
    ref_name: str,
    *,
    name: str = "",
    required_by: str,
    source: str,
) -> None:
    ref_name = str(ref_name or "").strip()
    if not ref_name:
        return
    type_label = _missing_type_label(kind)
    display_name = str(name or "").strip() or f"{type_label} {ref_name}"
    bucket = missing.setdefault(kind, [])
    for item in bucket:
        if item.get("name") == ref_name and item.get("source") == source:
            reqs = item.setdefault("required_by", [])
            if required_by and required_by not in reqs:
                reqs.append(required_by)
            if name and not item.get("name"):
                item["name"] = name
                item["display_name"] = display_name
            return
    bucket.append(
        {
            "name": str(name or ref_name),
            "display_name": display_name,
            "type_label": type_label,
            "required_by": [required_by] if required_by else [],
            "source": source,
        }
    )


def _available_skill_directories(
    bundle_dir: Optional[Path],
    user_skills_dir: Path,
    extra_skill_roots: Iterable[Path],
) -> Set[str]:
    out = set(list_skill_directories_in_bundle_skills_dir(bundle_dir)) if bundle_dir is not None else set()
    out.update(_skill_directories_under(user_skills_dir))
    for root in extra_skill_roots:
        out.update(_skill_directories_under(root))
    return out


def _available_tool_names(existing_mcp_servers: Iterable[Dict[str, Any]], bundle_mcp_servers: Iterable[Dict[str, Any]]) -> Set[str]:
    out: Set[str] = set()
    out.update(
        str(row.get("name") or "").strip()
        for row in existing_mcp_servers
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    )
    out.update(
        str(row.get("name") or "").strip()
        for row in bundle_mcp_servers
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    )
    return out


def _skill_mcp_refs_for_missing_check(
    sid: str,
    *,
    bundle_dir: Optional[Path],
    user_skills_dir: Path,
    extra_skill_roots: Iterable[Path],
) -> Tuple[List[Dict[str, str]], str]:
    skill_dir = _skill_dir_for_directory_name(
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
    preset_name = str(preset.get("name") or "场景").strip()
    scene_label = f"场景 {preset_name}"
    host_label = "场景主持人"

    bundle_expert_by_name = {
        str(row.get("name") or "").strip(): row
        for row in bundle_experts
        if str(row.get("name") or "").strip()
    }
    existing_expert_names = {
        str(row.get("name") or "").strip()
        for row in existing_experts
        if str(row.get("name") or "").strip()
    }
    available_skills = _available_skill_directories(bundle_dir, user_skills_dir, extra_skill_roots)
    available_mcp = _available_tool_names(existing_mcp_servers, bundle_mcp_servers)

    preset_agents = _dedupe_nonempty(preset.get("agent_names") or [])
    for agent_name in preset_agents:
        if agent_name not in bundle_expert_by_name and agent_name not in existing_expert_names:
            _add_missing_reference(missing, "experts", agent_name, required_by=scene_label, source="scene")

    host_profile = normalize_host_profile_dict(preset.get("host"))
    skill_refs: Dict[str, List[str]] = {}
    host_skill_directory = str(host_profile.get("skill_directory") or "").strip()
    if host_skill_directory:
        skill_refs.setdefault(host_skill_directory, []).append(host_label)

    for expert in bundle_experts:
        expert_name = str(expert.get("name") or "未命名专家").strip()
        expert_label = f"专家 {expert_name}"
        for sid in _dedupe_nonempty(
            [
                x.get("directory_name") if isinstance(x, dict) else x
                for x in (expert.get("skills") or [])
            ]
        ):
            skill_refs.setdefault(sid, []).append(expert_label)
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
            mid = ref["name"]
            name = str(ref.get("name") or "").strip()
            if mid not in available_mcp and (not name or name not in available_mcp):
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
    expert_name = str(expert.get("name") or "未命名专家").strip()
    expert_label = f"专家 {expert_name}"
    available_skills = _available_skill_directories(bundle_dir, user_skills_dir, extra_skill_roots)
    available_mcp = _available_tool_names(existing_mcp_servers, bundle_mcp_servers)

    for sid in _dedupe_nonempty(
        [
            x.get("directory_name") if isinstance(x, dict) else x
            for x in (expert.get("skills") or [])
        ]
    ):
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
            mid = ref["name"]
            name = str(ref.get("name") or "").strip()
            if mid not in available_mcp and (not name or name not in available_mcp):
                _add_missing_reference(missing, "tools", mid, name=ref.get("name", ""), required_by=skill_label, source="skill")
    return missing


def find_missing_references_for_skill_bundle(
    skill_directory: str,
    bundle_mcp_servers: List[Dict[str, Any]],
    bundle_dir: Optional[Path],
    user_skills_dir: Path,
    existing_mcp_servers: Iterable[Dict[str, Any]],
    *,
    extra_skill_roots: Iterable[Path] = (),
) -> Dict[str, List[Dict[str, Any]]]:
    missing = _empty_missing_references()
    available_mcp = _available_tool_names(existing_mcp_servers, bundle_mcp_servers)
    mcp_refs, skill_name = _skill_mcp_refs_for_missing_check(
        skill_directory,
        bundle_dir=bundle_dir,
        user_skills_dir=user_skills_dir,
        extra_skill_roots=extra_skill_roots,
    )
    skill_label = f"技能 {skill_name}"
    for ref in mcp_refs:
        mid = ref["name"]
        if mid not in available_mcp:
            _add_missing_reference(missing, "tools", mid, name=ref.get("name", ""), required_by=skill_label, source="skill")
    return missing


def skill_name_identity_import_plan(
    bundle_dir: Path,
    user_skills_dir: Path,
    skill_directories: List[str] | None = None,
) -> Tuple[Dict[str, str], List[Tuple[str, str]], List[str]]:
    """Plan Skill import by name only without copying files."""
    skill_directories = list(skill_directories) if skill_directories is not None else list_skill_directories_in_bundle_skills_dir(bundle_dir)
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    existing_name_to_directory: Dict[str, str] = {}
    used_directory_names: Set[str] = set()
    for child in sorted(user_skills_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        directory_name = child.name
        used_directory_names.add(directory_name)
        fm = _read_skill_frontmatter(child)
        name_key = normalized_name_key(fm.get("name") or directory_name)
        if name_key and name_key not in existing_name_to_directory:
            existing_name_to_directory[name_key] = directory_name

    directory_map: Dict[str, str] = {}
    copy_pairs: List[Tuple[str, str]] = []
    overwritten: List[str] = []
    skills_root = bundle_skills_root(bundle_dir)
    for incoming_directory in skill_directories:
        src = skills_root / incoming_directory
        if not src.is_dir() or not (src / "SKILL.md").is_file():
            continue
        fm = _read_skill_frontmatter(src)
        name_key = normalized_name_key(fm.get("name") or incoming_directory)
        existing_directory = existing_name_to_directory.get(name_key) if name_key else ""
        if existing_directory:
            target_directory = existing_directory
            overwritten.append(existing_directory)
        else:
            target_directory = _new_skill_directory_name(used_directory_names)
            if name_key:
                existing_name_to_directory[name_key] = target_directory
        directory_map[incoming_directory] = target_directory
        copy_pairs.append((incoming_directory, target_directory))
    return directory_map, copy_pairs, list(dict.fromkeys(overwritten))


def bundle_skill_display_name_map(bundle_dir: Path, skill_directories: List[str] | None = None) -> Dict[str, str]:
    skill_directories = list(skill_directories) if skill_directories is not None else list_skill_directories_in_bundle_skills_dir(bundle_dir)
    skills_root = bundle_skills_root(bundle_dir)
    out: Dict[str, str] = {}
    for sid in skill_directories:
        skill_directory = str(sid or "").strip()
        if not skill_directory:
            continue
        fm = _read_skill_frontmatter(skills_root / skill_directory)
        out[skill_directory] = str(fm.get("name") or skill_directory).strip()
    return out


def copy_bundle_skills_to_user_by_name(bundle_dir: Path, user_skills_dir: Path) -> Tuple[List[str], List[str], Dict[str, str]]:
    """Copy bundle skills using name as the import identity.

    Returns (imported_skill_directories, overwritten_skill_directories, bundle_directory_to_local_directory_map).
    """
    directory_map, copy_pairs, overwritten = skill_name_identity_import_plan(bundle_dir, user_skills_dir)
    skills_root = bundle_skills_root(bundle_dir)
    imported: List[str] = []
    for incoming_directory, target_directory in copy_pairs:
        src = skills_root / incoming_directory
        dest = user_skills_dir / target_directory
        if src.is_dir() and (src / "SKILL.md").is_file():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
            imported.append(target_directory)
    return imported, overwritten, directory_map
