"""设置导入 bundle 时的冲突检测、引用校验与引用更新。"""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

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
from app.core.settings_bundle_missing_references import (
    collect_mcp_refs_from_skill_dirs,
    collect_tool_names_from_skill_dirs,
    find_missing_references_for_expert_bundle,
    find_missing_references_for_scene_bundle,
    find_missing_references_for_skill_bundle,
    mcp_refs_from_skill_frontmatter,
    mcp_rows_for_bundle_refs,
    tool_names_from_skill_frontmatter,
    _read_skill_frontmatter,
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
