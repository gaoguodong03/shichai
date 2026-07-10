"""设置导入 bundle 时的冲突检测、引用校验与引用更新。"""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import yaml

from app.core.host_profile_contract import normalize_host_profile_dict
from app.core.name_based_resources import normalize_tool_row
from app.core.scenario_bundle import (
    MANIFEST_NAME,
    TOOLS_DIR,
    bundle_skills_root,
    extract_scenario_bundle_dir,
    list_skill_directories_in_bundle_skills_dir,
    sanitize_mcp_servers_for_bundle,
    strip_agent_row_for_disk,
    _read_resource_rows,
    _resource_dir_name,
)


def normalized_name_key(raw: Any) -> str:
    return str(raw or "").strip().casefold()


def build_single_mcp_bundle_zip_bytes(server: Dict[str, Any]) -> bytes:
    """Build the ZIP payload for exporting one MCP tool resource."""
    safe_rows = sanitize_mcp_servers_for_bundle([server])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        root_name = str((safe_rows[0] if safe_rows else {}).get("name") or "").strip()
        manifest = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "bundle_type": "tool",
            "root_resources": [{"type": "tool", "name": root_name}],
            "resource_counts": {
                "scenarios": 0,
                "agents": 0,
                "skills": 0,
                "tools": len(safe_rows),
                "models": 0,
            },
        }
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for row in safe_rows:
            tool_dir = _resource_dir_name(row.get("name"), "tool")
            zf.writestr(f"{TOOLS_DIR}/{tool_dir}/tool.json", json.dumps(row, ensure_ascii=False, indent=2) + "\n")
    return buf.getvalue()


def read_mcp_bundle_rows(raw: bytes) -> List[Dict[str, Any]]:
    """Read MCP tool rows from a tool ZIP bundle and raise ValueError for invalid input."""
    try:
        tmp = extract_scenario_bundle_dir(raw)
    except zipfile.BadZipFile as exc:
        raise ValueError("不是有效的 ZIP 文件") from exc
    except ValueError as exc:
        raise ValueError(str(exc) or "不是有效的 ZIP 文件") from exc
    try:
        manifest_path = tmp / MANIFEST_NAME
        if not manifest_path.is_file():
            raise ValueError("ZIP 中缺少 bundle.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("bundle_type") != "tool":
            raise ValueError("工具资源包类型无效")
        rows = _read_resource_rows(tmp / TOOLS_DIR, "tool.json")
        if not rows:
            raise ValueError("分享包中没有可导入的工具配置")
        return rows
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("工具资源包格式错误") from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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


def mcp_name_map_for_import(
    existing_servers: List[Dict[str, Any]],
    rows_to_import: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Build the post-import tool display-name map used by Skill frontmatter rewrites."""
    names: Dict[str, str] = {}
    for row in existing_servers:
        name = str(row.get("name") or "").strip()
        if name:
            names[name] = name
    for row in rows_to_import or []:
        name = str(row.get("name") or "").strip()
        if name:
            names[name] = name
    return names


def remap_frontmatter_mcp_refs(
    fm: Dict[str, Any],
    tool_name_map: Dict[str, str],
    mcp_name_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Rewrite imported Skill allowed-tools references to post-import tool names."""
    if not tool_name_map:
        return fm
    names = mcp_name_map or {}

    def remap_list(raw: Any) -> Any:
        if not isinstance(raw, list):
            return raw
        out: List[Any] = []
        seen: Set[str] = set()
        for item in raw:
            old = str(item.get("name") if isinstance(item, dict) else item or "").strip()
            if not old:
                continue
            new = tool_name_map.get(old, old)
            label = names.get(new, new)
            if label not in seen:
                seen.add(label)
                out.append(label)
        return out

    section = fm.get("allowed-tools")
    if isinstance(section, dict):
        copied_section = {key: section.get(key) for key in ("mcp", "http_api", "python") if key in section}
        for key in ("mcp", "http_api"):
            if key in copied_section:
                copied_section[key] = remap_list(copied_section.get(key))
        fm["allowed-tools"] = copied_section
    return fm


def agent_name_identity_import_plan(
    existing_agents: List[Dict[str, Any]],
    bundle_agents: List[Dict[str, Any]],
) -> Tuple[Dict[str, str], List[Dict[str, Any]], List[str]]:
    """Plan expert import by display name; same name overwrites local content."""
    existing_names: Set[str] = set()
    for row in existing_agents:
        name_key = normalized_name_key(row.get("name"))
        if name_key:
            existing_names.add(name_key)

    name_map: Dict[str, str] = {}
    rows_to_import: List[Dict[str, Any]] = []
    overwritten_existing_names: List[str] = []
    for incoming in bundle_agents:
        incoming_name = str(incoming.get("name") or "").strip()
        name_key = normalized_name_key(incoming.get("name"))
        if not incoming_name or not name_key:
            continue
        copied = strip_agent_row_for_disk(dict(incoming))
        name_map[incoming_name] = incoming_name
        if name_key in existing_names:
            overwritten_existing_names.append(incoming_name)
            rows_to_import.append(copied)
            continue
        rows_to_import.append(copied)
        existing_names.add(name_key)
    return name_map, rows_to_import, list(dict.fromkeys(overwritten_existing_names))


def agent_name_conflicts(
    existing_agents: List[Dict[str, Any]],
    bundle_agents: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Return incoming expert names that will overwrite existing expert names."""
    existing_name_to_names: Dict[str, List[str]] = {}
    for row in existing_agents:
        name = str(row.get("name") or "").strip()
        name_key = normalized_name_key(row.get("name"))
        if name and name_key:
            existing_name_to_names.setdefault(name_key, []).append(name)

    conflicts: Dict[str, List[str]] = {}
    for incoming in bundle_agents:
        incoming_name = str(incoming.get("name") or "").strip()
        incoming_name_key = normalized_name_key(incoming.get("name"))
        if not incoming_name or not incoming_name_key:
            continue
        names = existing_name_to_names.get(incoming_name_key) or []
        if names:
            conflicts[incoming_name] = list(dict.fromkeys(names))
    return conflicts


def remap_scene_references(
    preset: Dict[str, Any],
    agent_name_map: Dict[str, str],
    skill_directory_map: Dict[str, str],
) -> Dict[str, Any]:
    """Rewrite bundle-local scene references to current account resource names."""
    work = dict(preset)
    if isinstance(work.get("agent_names"), list):
        work["agent_names"] = [
            agent_name_map.get(str(name or "").strip(), str(name or "").strip())
            for name in work.get("agent_names") or []
            if str(name or "").strip()
        ]
    host = dict(work.get("host") or {}) if isinstance(work.get("host"), dict) else {}
    skill_directory = str(host.get("skill_directory") or "").strip()
    if skill_directory and skill_directory in skill_directory_map:
        host["skill_directory"] = skill_directory_map[skill_directory]
    if host:
        work["host"] = host
    return work


def remap_agent_skill_references(agent: Dict[str, Any], skill_directory_map: Dict[str, str]) -> Dict[str, Any]:
    """Rewrite expert Skill directory references after bundle Skill import planning."""
    work = strip_agent_row_for_disk(dict(agent))
    skills = []
    for item in work.get("skills") or []:
        if isinstance(item, dict):
            row = dict(item)
            directory_name = str(row.get("directory_name") or "").strip()
            if directory_name and directory_name in skill_directory_map:
                row["directory_name"] = skill_directory_map[directory_name]
            skills.append(row)
        elif isinstance(item, str) and item.strip():
            skills.append(skill_directory_map.get(item.strip(), item.strip()))
    work["skills"] = skills
    return work


def prepare_scene_import_by_name_identity(
    norm: Dict[str, Any],
    agent_bundle: List[Dict[str, Any]],
    mcp_bundle: List[Dict[str, Any]],
    bundle_dir: Path,
    user_skills_dir: Path,
    existing_agents: List[Dict[str, Any]],
    existing_mcp: List[Dict[str, Any]],
) -> Tuple[
    Dict[str, Any],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    Dict[str, str],
    Dict[str, str],
    Dict[str, str],
    List[str],
    List[str],
    List[str],
]:
    """Prepare scene, expert, Skill, and tool rows for name-based bundle import."""
    imported_skills, overwritten_skills, skill_directory_map = copy_bundle_skills_to_user_by_directory(bundle_dir, user_skills_dir)
    tool_name_map, mcp_rows_to_import, _overwritten_mcp = mcp_name_identity_import_plan(existing_mcp, mcp_bundle)
    remapped_agents = [
        remap_agent_skill_references(row, skill_directory_map)
        for row in agent_bundle
        if isinstance(row, dict)
    ]
    agent_name_map, agent_rows_to_import, overwritten_agent_names = agent_name_identity_import_plan(
        existing_agents,
        remapped_agents,
    )
    remapped_preset = remap_scene_references(norm, agent_name_map, skill_directory_map)

    return (
        remapped_preset,
        agent_rows_to_import,
        mcp_rows_to_import,
        skill_directory_map,
        tool_name_map,
        agent_name_map,
        imported_skills,
        overwritten_agent_names,
        overwritten_skills,
    )


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


def skill_directory_identity_import_plan(
    bundle_dir: Path,
    user_skills_dir: Path,
    skill_directories: List[str] | None = None,
) -> Tuple[Dict[str, str], List[Tuple[str, str]], List[str]]:
    """Plan Skill import by directory_name without copying files."""
    skill_directories = list(skill_directories) if skill_directories is not None else list_skill_directories_in_bundle_skills_dir(bundle_dir)
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    existing_directory_names: Set[str] = set()
    for child in sorted(user_skills_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        existing_directory_names.add(child.name)

    directory_map: Dict[str, str] = {}
    copy_pairs: List[Tuple[str, str]] = []
    overwritten: List[str] = []
    skills_root = bundle_skills_root(bundle_dir)
    for incoming_directory in skill_directories:
        src = skills_root / incoming_directory
        if not src.is_dir() or not (src / "SKILL.md").is_file():
            continue
        target_directory = incoming_directory
        if target_directory in existing_directory_names:
            overwritten.append(target_directory)
        else:
            existing_directory_names.add(target_directory)
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


def copy_bundle_skills_to_user_by_directory(bundle_dir: Path, user_skills_dir: Path) -> Tuple[List[str], List[str], Dict[str, str]]:
    """Copy bundle skills using directory_name as the import identity.

    Returns (imported_skill_directories, overwritten_skill_directories, bundle_directory_to_local_directory_map).
    """
    directory_map, copy_pairs, overwritten = skill_directory_identity_import_plan(bundle_dir, user_skills_dir)
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
