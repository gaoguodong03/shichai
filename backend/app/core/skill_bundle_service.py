"""Skill resource-bundle import/export service shared by API route modules."""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException

from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.api.settings_mcp import load_mcp_config, save_mcp_config
from app.api.settings_skill_frontmatter import (
    python_doc_from_allowed_tools as _python_doc_from_allowed_tools,
    sanitize_skill_frontmatter_for_write as _sanitize_skill_frontmatter_for_write,
)
from app.api.settings_skill_store import (
    _get_skills_dir,
    read_skill_file as _read_skill_file,
    write_skill_file as _write_skill_file,
)
from app.core.sandbox_requirements import merge_requirements_lines, requirement_key
from app.core.scenario_bundle import (
    MANIFEST_NAME,
    SKILLS_DIR,
    TOOLS_DIR,
    bundle_skills_root,
    extract_scenario_bundle_dir,
    list_skill_directories_in_bundle_skills_dir,
    read_bundle_tool_rows,
    _resource_dir_name,
)
from app.core.settings_bundle_import import (
    bundle_skill_display_name_map as _bundle_skill_display_name_map,
    copy_bundle_skills_to_user_by_directory as _copy_bundle_skills_to_user_by_directory,
    find_missing_references_for_expert_bundle as _find_missing_references_for_expert_bundle,
    find_missing_references_for_skill_bundle as _find_missing_references_for_skill_bundle,
    mcp_name_identity_import_plan as _mcp_name_identity_import_plan,
    mcp_name_map_for_import,
    mcp_refs_from_skill_frontmatter,
    mcp_rows_for_bundle_refs,
    remap_frontmatter_mcp_refs,
    skill_directory_identity_import_plan as _skill_directory_identity_import_plan,
    upsert_rows_by_name as _upsert_rows_by_name,
)
from app.core.user_context import get_current_user_context, get_current_username
from app.core.user_settings_paths import sandbox_requirements_path
from app.mcp.manager import dispose_mcp_runtime_for_user
from app.skills.loader import get_builtin_skills_dir, invalidate_skills_cache_for_user


def python_requirements_from_skill_dir(skill_dir: Path) -> List[str]:
    """Read the Skill frontmatter python requirements as de-duplicated requirement lines."""
    try:
        fm, _ = _read_skill_file(skill_dir)
    except Exception:
        return []
    raw = _python_doc_from_allowed_tools(fm)
    out: List[str] = []
    seen: Set[str] = set()
    for line in str(raw or "").splitlines():
        item = line.strip()
        key = requirement_key(item)
        if not item or item.startswith("#") or not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def merge_sandbox_requirements_lines(incoming: List[str]) -> Tuple[List[str], str]:
    """Merge imported Skill python requirements into the current user's sandbox requirements."""
    return merge_requirements_lines(sandbox_requirements_path(), incoming)


def mcp_rows_for_skill_dir(skill_dir: Path) -> List[Dict[str, Any]]:
    """Resolve MCP tool rows referenced by one Skill directory."""
    try:
        fm, _ = _read_skill_file(skill_dir)
    except Exception:
        return []
    mcp_refs = mcp_refs_from_skill_frontmatter(fm)
    if not mcp_refs:
        return []
    return mcp_rows_for_bundle_refs(mcp_refs, load_mcp_config())


async def invalidate_mcp_runtime_after_config_change() -> None:
    """Drop the current user's MCP runtime after imported tool configuration changes."""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        await dispose_mcp_runtime_for_user(user_ctx.user_id)


async def merge_imported_skill_requirements_and_prewarm(directory_names: List[str], skills_root: Path) -> Dict[str, Any]:
    """Merge imported Skill requirements and prewarm the user's sandbox when new lines were added."""
    incoming: List[str] = []
    for sid in directory_names:
        safe_id = str(sid or "").strip()
        if not safe_id or ".." in safe_id or "/" in safe_id or "\\" in safe_id:
            continue
        incoming.extend(python_requirements_from_skill_dir(skills_root / safe_id))
    added, _merged = merge_sandbox_requirements_lines(incoming)
    result: Dict[str, Any] = {"requirements_added": added, "requirements_validated": False}
    if not added:
        result["requirements_validated"] = True
        return result
    username = (get_current_username() or "").strip()
    if not username:
        return result
    try:
        timeout_ms = int(os.getenv("SANDBOX_REQUIREMENTS_VALIDATE_TIMEOUT_MS", "600000") or "600000")
    except Exception:
        timeout_ms = 600_000
    try:
        await get_shared_sandbox_service().prewarm_user_sandbox(
            username,
            reason="skill_requirements_imported",
            timeout_ms=max(120_000, timeout_ms),
        )
        result["requirements_validated"] = True
    except Exception as e:
        logging.getLogger(__name__).warning("sandbox_requirements_import_install_failed user=%s err=%s", username, e)
        result["requirements_error"] = str(e)
    return result


async def import_skill_from_bundle_bytes(raw: bytes, *, dry_run: bool) -> Dict[str, Any]:
    """Import one Skill resource bundle by directory-name identity."""
    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        manifest_path = tmp / MANIFEST_NAME
        if not manifest_path.is_file():
            raise HTTPException(status_code=400, detail="分享包中缺少 bundle.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("bundle_type") != "skill":
            raise HTTPException(status_code=400, detail="技能资源包类型无效")
        mcp_bundle = read_bundle_tool_rows(tmp)
        directory_names = list_skill_directories_in_bundle_skills_dir(tmp)
        if not directory_names:
            raise HTTPException(status_code=400, detail="分享包中缺少技能目录")
        sid0 = directory_names[0]
        src = bundle_skills_root(tmp) / sid0
        fm, _body = _read_skill_file(src)
        incoming_name = str(fm.get("name") or sid0).strip() or sid0
        base = _get_skills_dir()
        base.mkdir(parents=True, exist_ok=True)
        existing_same_directory = (base / sid0).is_dir()
        if dry_run:
            req_preview = python_requirements_from_skill_dir(src)
            missing_references = _find_missing_references_for_skill_bundle(
                sid0,
                mcp_bundle,
                tmp,
                base,
                load_mcp_config(),
                extra_skill_roots=(get_builtin_skills_dir(),),
            )
            return {
                "object_type": "skill",
                "title": incoming_name,
                "preview": {
                    "directory_name": sid0,
                    "name": incoming_name,
                    "overwrite_directory_names": [sid0] if existing_same_directory else [],
                    "python_requirements": req_preview,
                    "mcps": [{"name": str(x.get("name") or "")} for x in mcp_bundle],
                    "missing_references": missing_references,
                },
            }
        tool_name_map, mcp_rows_to_import, overwritten_tool_names = _mcp_name_identity_import_plan(load_mcp_config(), mcp_bundle)
        target_directory = sid0
        dest = base / target_directory
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        fm2, body2 = _read_skill_file(dest)
        mcp_name_map = mcp_name_map_for_import(load_mcp_config(), mcp_rows_to_import)
        fm2 = remap_frontmatter_mcp_refs(fm2, tool_name_map, mcp_name_map)
        fm2["name"] = str(fm2.get("name") or incoming_name)
        fm2["description"] = str(fm2.get("description") or "")
        _sanitize_skill_frontmatter_for_write(fm2)
        _write_skill_file(dest, fm2, body2)
        user_ctx = get_current_user_context(default_fallback=False)
        if user_ctx is not None:
            invalidate_skills_cache_for_user(user_ctx.user_id)
        existing_tool_names = {str(row.get("name") or "").strip() for row in load_mcp_config()}
        imported_tool_names = {str(row.get("name") or "").strip() for row in mcp_rows_to_import}
        mcp_added = len([mid for mid in imported_tool_names if mid and mid not in existing_tool_names])
        mcp_updated = len([mid for mid in imported_tool_names if mid and mid in existing_tool_names])
        if mcp_rows_to_import:
            merged_mcp = _upsert_rows_by_name(load_mcp_config(), mcp_rows_to_import, "name")
            save_mcp_config(merged_mcp)
            await invalidate_mcp_runtime_after_config_change()
        requirements_result = await merge_imported_skill_requirements_and_prewarm([target_directory], base)
        missing_references = _find_missing_references_for_skill_bundle(
            target_directory,
            mcp_bundle,
            None,
            base,
            load_mcp_config(),
            extra_skill_roots=(get_builtin_skills_dir(),),
        )
        return {
            "object_type": "skill",
            "imported_directory_name": target_directory,
            "name": str(fm2.get("name") or target_directory),
            "summary": {
                "overwritten_directory_names": [target_directory] if existing_same_directory else [],
                "missing_references": missing_references,
                "tool_name_map": tool_name_map,
                "mcp_added": mcp_added,
                "mcp_updated": mcp_updated,
                "overwritten_tool_names": overwritten_tool_names,
            },
            **requirements_result,
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


async def import_mcp_from_bundle_bytes(raw: bytes, *, dry_run: bool) -> Dict[str, Any]:
    """Import a tool-only resource bundle using the current name-identity contract."""
    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        manifest_path = tmp / MANIFEST_NAME
        if not manifest_path.is_file():
            raise HTTPException(status_code=400, detail="分享包中缺少 bundle.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("bundle_type") != "tool":
            raise HTTPException(status_code=400, detail="工具资源包类型无效")
        mcp_bundle = read_bundle_tool_rows(tmp)
        if not mcp_bundle:
            raise HTTPException(status_code=400, detail="分享包中没有可导入的工具配置")
        preview = [{"name": str(x.get("name") or "")} for x in mcp_bundle]
        if dry_run:
            return {"object_type": "mcp", "preview": {"mcps": preview}}
        mcp_before = load_mcp_config()
        tool_name_map, mcp_rows_to_import, overwritten_tool_names = _mcp_name_identity_import_plan(mcp_before, mcp_bundle)
        existing_names = {str(row.get("name") or "").strip() for row in mcp_before}
        imported_names = {str(row.get("name") or "").strip() for row in mcp_rows_to_import}
        merged_mcp = _upsert_rows_by_name(mcp_before, mcp_rows_to_import, "name")
        mcp_added = len([mid for mid in imported_names if mid and mid not in existing_names])
        mcp_updated = len([mid for mid in imported_names if mid and mid in existing_names])
        save_mcp_config(merged_mcp)
        await invalidate_mcp_runtime_after_config_change()
        return {
            "object_type": "mcp",
            "summary": {
                "mcp_added": mcp_added,
                "mcp_updated": mcp_updated,
                "tool_name_map": tool_name_map,
                "overwritten_tool_names": overwritten_tool_names,
            },
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


async def import_expert_from_bundle_bytes(raw: bytes, *, dry_run: bool) -> Dict[str, Any]:
    """Import an expert bundle and remap Skill/tool references by current resource identity."""
    from app.api.agents import load_agent_instances, normalize_expert_row_for_import, save_agent_instances, _agent_skills_dir
    from app.core.expert_bundle import read_expert_bundle_manifest

    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        _man, expert_raw = read_expert_bundle_manifest(tmp)
        norm = normalize_expert_row_for_import(expert_raw)
        if norm is None:
            raise HTTPException(status_code=400, detail="专家分享包无效")
        directory_names_in_zip = list_skill_directories_in_bundle_skills_dir(tmp)
        skill_display_names = _bundle_skill_display_name_map(tmp, directory_names_in_zip)
        mcp_bundle = read_bundle_tool_rows(tmp)
        user_skills = _agent_skills_dir()
        directory_name_map, _skill_copy_pairs, overwritten_directory_names = _skill_directory_identity_import_plan(
            tmp,
            user_skills,
            directory_names_in_zip,
        )
        tool_name_map, _mcp_rows_to_import, overwritten_tool_names = _mcp_name_identity_import_plan(load_mcp_config(), mcp_bundle)
        same_name_agent_names = [
            str(x.get("name") or "")
            for x in load_agent_instances()
            if str(x.get("name") or "").strip().lower() == str(norm.get("name") or "").strip().lower()
        ]
        if dry_run:
            missing_references = _find_missing_references_for_expert_bundle(
                norm,
                mcp_bundle,
                tmp,
                user_skills,
                load_mcp_config(),
                extra_skill_roots=(get_builtin_skills_dir(),),
            )
            return {
                "object_type": "expert",
                "preview": {
                    "name": norm.get("name"),
                    "skills": directory_names_in_zip,
                    "skill_display_names": skill_display_names,
                    "mcps": [{"name": str(x.get("name") or "")} for x in mcp_bundle],
                    "name_conflict_existing_names": same_name_agent_names,
                    "would_overwrite_skills": overwritten_directory_names,
                    "would_remap_skills": directory_name_map,
                    "would_remap_tools": tool_name_map,
                    "would_overwrite_tools": overwritten_tool_names,
                    "missing_references": missing_references,
                },
            }
        missing_references = _find_missing_references_for_expert_bundle(
            norm,
            mcp_bundle,
            tmp,
            user_skills,
            load_mcp_config(),
            extra_skill_roots=(get_builtin_skills_dir(),),
        )
        imported_skills, overwritten_skills, directory_name_map = _copy_bundle_skills_to_user_by_directory(tmp, user_skills)
        user_ctx = get_current_user_context(default_fallback=False)
        if user_ctx is not None:
            invalidate_skills_cache_for_user(user_ctx.user_id)
        tool_name_map, mcp_rows_to_import, overwritten_tool_names = _mcp_name_identity_import_plan(load_mcp_config(), mcp_bundle)
        for sid in imported_skills:
            skill_dir = user_skills / sid
            if not (skill_dir / "SKILL.md").is_file():
                continue
            fm, body = _read_skill_file(skill_dir)
            fm = remap_frontmatter_mcp_refs(
                fm,
                tool_name_map,
                mcp_name_map_for_import(load_mcp_config(), mcp_rows_to_import),
            )
            _sanitize_skill_frontmatter_for_write(fm)
            _write_skill_file(skill_dir, fm, body)
        existing_mcp_names = {str(row.get("name") or "").strip() for row in load_mcp_config()}
        imported_mcp_names = {str(row.get("name") or "").strip() for row in mcp_rows_to_import}
        if mcp_rows_to_import:
            merged_mcp = _upsert_rows_by_name(load_mcp_config(), mcp_rows_to_import, "name")
            save_mcp_config(merged_mcp)
            await invalidate_mcp_runtime_after_config_change()
        requirements_result = await merge_imported_skill_requirements_and_prewarm(imported_skills, user_skills)
        instances = load_agent_instances()
        same_name_agent_names = [
            str(x.get("name") or "")
            for x in instances
            if str(x.get("name") or "").strip().lower() == str(norm.get("name") or "").strip().lower()
        ]
        final_name = str(norm.get("name") or "").strip()
        remapped_norm = dict(norm)
        remapped_skills: List[Any] = []
        for item in remapped_norm.get("skills") or []:
            if isinstance(item, dict):
                row = dict(item)
                directory_name = str(row.get("directory_name") or "").strip()
                if directory_name and directory_name in directory_name_map:
                    row["directory_name"] = directory_name_map[directory_name]
                remapped_skills.append(row)
            elif isinstance(item, str) and item.strip():
                remapped_skills.append(directory_name_map.get(item.strip(), item.strip()))
        remapped_norm["skills"] = remapped_skills
        instances = _upsert_rows_by_name(instances, [remapped_norm], "name")
        save_agent_instances(instances)
        return {
            "object_type": "expert",
            "summary": {
                "imported_agent_name": final_name,
                "overwritten_agent_names": same_name_agent_names,
                "skills_imported": imported_skills,
                "skills_overwritten": overwritten_skills,
                "skill_map": directory_name_map,
                "tool_map": tool_name_map,
                "mcp_added": len([name for name in imported_mcp_names if name and name not in existing_mcp_names]),
                "mcp_updated": len([name for name in imported_mcp_names if name and name in existing_mcp_names]),
                "overwritten_tool_names": overwritten_tool_names,
                "missing_references": missing_references,
                **requirements_result,
            },
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def build_skill_zip_bytes(skill_dir: Path, mcp_rows: Optional[List[Dict[str, Any]]] = None) -> bytes:
    """Package a Skill directory and its referenced MCP rows into the current resource bundle ZIP."""
    from app.core.scenario_bundle import sanitize_mcp_servers_for_bundle

    directory_name = skill_dir.name
    safe_mcp_rows = sanitize_mcp_servers_for_bundle(mcp_rows or [])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "bundle_type": "skill",
            "root_resources": [{"type": "skill", "name": directory_name}],
            "resource_counts": {
                "scenarios": 0,
                "agents": 0,
                "skills": 1,
                "tools": len(safe_mcp_rows),
                "models": 0,
            },
        }
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for fp in sorted(skill_dir.rglob("*")):
            if fp.is_dir():
                continue
            try:
                rel = fp.relative_to(skill_dir)
            except ValueError:
                continue
            if ".git" in rel.parts:
                continue
            arcname = "/".join(rel.parts)
            zf.write(fp, f"{SKILLS_DIR}/{directory_name}/{arcname}")
        for row in safe_mcp_rows:
            tool_dir = _resource_dir_name(row.get("name"), "tool")
            zf.writestr(f"{TOOLS_DIR}/{tool_dir}/tool.json", json.dumps(row, ensure_ascii=False, indent=2) + "\n")
    return buf.getvalue()
