"""Skill settings API implementation."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
import yaml
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from typing import List, Optional, Dict, Any, Set, Tuple

from app.core.user_context import get_current_user_context, get_current_username
from app.core.user_settings_paths import require_user_context, sandbox_requirements_path, skills_dir_path
from app.core.session_preset_validate import (
    normalize_preset_dict_for_validation,
)
from app.core.settings_references import (
    remove_skill_path_from_user_configs as _remove_skill_path_from_user_configs,
    replace_skill_path_in_user_configs as _replace_skill_path_in_user_configs,
)
from app.core.settings_bundle_import import (
    bundle_skill_display_name_map as _bundle_skill_display_name_map,
    collect_tool_names_from_skill_dirs,
    copy_bundle_skills_to_user_by_name as _copy_bundle_skills_to_user_by_name,
    find_missing_references_for_expert_bundle as _find_missing_references_for_expert_bundle,
    find_missing_references_for_scene_bundle as _find_missing_references_for_scene_bundle,
    find_missing_references_for_skill_bundle as _find_missing_references_for_skill_bundle,
    mcp_name_identity_import_plan as _mcp_name_identity_import_plan,
    skill_name_identity_import_plan as _skill_name_identity_import_plan,
    upsert_rows_by_name as _upsert_rows_by_name,
)
from app.core.scenario_bundle import (
    bundle_skills_root,
    extract_scenario_bundle_dir,
    list_skill_directories_in_bundle_skills_dir,
    read_bundle_tool_rows,
)
from app.skills.loader import get_builtin_skills_dir, invalidate_skills_cache_for_user
from app.core.security import user_context_dependency
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.api.settings_mcp import load_mcp_config, save_mcp_config
from app.mcp.manager import dispose_mcp_runtime_for_user
from app.core.sandbox_requirements import merge_requirements_lines, requirement_key
from app.api.settings_skill_frontmatter import (
    ALLOWED_TOOLS_FM_KEY,
    SkillCreate,
    SkillUpdate,
    normalize_allowed_tools_payload as _normalize_allowed_tools_payload,
    normalized_allowed_tools_dict as _normalized_allowed_tools_dict,
    python_doc_from_allowed_tools as _python_doc_from_allowed_tools,
    runtime_tools_only as _runtime_tools_only,
    sanitize_skill_frontmatter_for_write as _sanitize_skill_frontmatter_for_write,
)
from app.api.settings_skill_store import (
    _get_skills_dir,
    get_mcp_servers_for_skill,
    load_skills_config,
    read_skill_file as _read_skill_file,
    skill_dir_for_directory_name as _skill_dir_for_directory_name,
    skill_display_name_from_dir as _skill_display_name_from_dir,
    write_skill_file as _write_skill_file,
)
from app.api.settings_skill_parts import (
    PartDirCreate,
    PartFileCreate,
    PartFileUpdate,
    register_skill_part_routes,
)

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])


async def _invalidate_mcp_runtime_after_config_change():
    """工具资源变更后丢弃内存中的 MCP 连接，下次再懒加载。"""
    un = get_current_username()
    if un:
        await dispose_mcp_runtime_for_user(un)

def _require_user_ctx():
    return require_user_context()


def _get_sandbox_requirements_path() -> Path:
    """当前用户沙箱依赖清单 requirements.txt 路径。"""
    return sandbox_requirements_path()


def _normalized_name_key(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _mcp_name_map_for_import(rows_to_import: List[Dict[str, Any]]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for row in load_mcp_config():
        rid = str(row.get("name") or "").strip()
        name = str(row.get("name") or "").strip()
        if rid and name:
            names[rid] = name
    for row in rows_to_import or []:
        rid = str(row.get("name") or "").strip()
        name = str(row.get("name") or "").strip()
        if rid and name:
            names[rid] = name
    return names


def _remap_frontmatter_mcp_refs(
    fm: Dict[str, Any],
    tool_name_map: Dict[str, str],
    mcp_name_map: Dict[str, str] | None = None,
) -> Dict[str, Any]:
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

    section = fm.get(ALLOWED_TOOLS_FM_KEY)
    if isinstance(section, dict):
        copied_section = dict(section)
        for key in ("mcp", "http_api", "http-api"):
            if key in copied_section:
                copied_section["http_api" if key == "http-api" else key] = remap_list(copied_section.get(key))
                if key == "http-api":
                    copied_section.pop("http-api", None)
        fm[ALLOWED_TOOLS_FM_KEY] = copied_section
    return fm




def _python_requirements_from_skill_dir(skill_dir: Path) -> List[str]:
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


def _merge_sandbox_requirements_lines(incoming: List[str]) -> Tuple[List[str], str]:
    return merge_requirements_lines(_get_sandbox_requirements_path(), incoming)


def _mcp_rows_for_skill_dir(skill_dir: Path) -> List[Dict[str, Any]]:
    from app.core.settings_bundle_import import mcp_refs_from_skill_frontmatter, mcp_rows_for_bundle_refs

    try:
        fm, _ = _read_skill_file(skill_dir)
    except Exception:
        return []
    mcp_refs = mcp_refs_from_skill_frontmatter(fm)
    if not mcp_refs:
        return []
    return mcp_rows_for_bundle_refs(mcp_refs, load_mcp_config())


def _parse_mcp_bundle_rows(raw: bytes) -> List[Dict[str, Any]]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [row for row in parsed if isinstance(row, dict) and str(row.get("name") or "").strip()]


def _read_mcp_bundle_rows(bundle_dir: Path) -> List[Dict[str, Any]]:
    path = bundle_dir / "mcp_servers.json"
    if not path.is_file():
        return []
    try:
        return _parse_mcp_bundle_rows(path.read_bytes())
    except Exception:
        return []


async def _merge_imported_skill_requirements_and_prewarm(directory_names: List[str], skills_root: Path) -> Dict[str, Any]:
    incoming: List[str] = []
    for sid in directory_names:
        safe_id = str(sid or "").strip()
        if not safe_id or ".." in safe_id or "/" in safe_id or "\\" in safe_id:
            continue
        incoming.extend(_python_requirements_from_skill_dir(skills_root / safe_id))
    added, _merged = _merge_sandbox_requirements_lines(incoming)
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
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("sandbox_requirements_import_install_failed user=%s err=%s", username, e)
        result["requirements_error"] = str(e)
    return result


async def _import_skill_from_bundle_bytes(raw: bytes, *, dry_run: bool) -> Dict[str, Any]:
    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        mcp_bundle = _read_mcp_bundle_rows(tmp)
        directory_names = list_skill_directories_in_bundle_skills_dir(tmp)
        if not directory_names:
            root_skill = tmp / "SKILL.md"
            if not root_skill.is_file():
                raise HTTPException(status_code=400, detail="分享包中缺少技能目录")
            root_fm, _root_body = _read_skill_file(tmp)
            root_name = str(root_fm.get("name") or "skill").strip() or "skill"
            sid0 = _slugify(root_name)
            normalized = tmp / "__normalized_skill_bundle"
            src = normalized / "resources" / "skills" / sid0
            src.mkdir(parents=True, exist_ok=True)
            for child in tmp.iterdir():
                if child.name in {"__normalized_skill_bundle", "mcp_servers.json"}:
                    continue
                dest_child = src / child.name
                if child.is_dir():
                    shutil.copytree(child, dest_child)
                else:
                    shutil.copy2(child, dest_child)
            bundle_dir_for_refs = normalized
        else:
            sid0 = directory_names[0]
            src = bundle_skills_root(tmp) / sid0
            bundle_dir_for_refs = tmp
        fm, body = _read_skill_file(src)
        incoming_name = str(fm.get("name") or sid0).strip() or sid0
        incoming_name_key = _normalized_name_key(incoming_name)
        base = _get_skills_dir()
        base.mkdir(parents=True, exist_ok=True)
        existing_same_name_directories: List[str] = []
        for child in sorted(base.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            try:
                efm, _ = _read_skill_file(child)
            except Exception:
                continue
            ename = str(efm.get("name") or child.name).strip()
            if _normalized_name_key(ename) == incoming_name_key:
                existing_same_name_directories.append(child.name)
        if dry_run:
            req_preview = _python_requirements_from_skill_dir(src)
            missing_references = _find_missing_references_for_skill_bundle(
                sid0,
                mcp_bundle,
                bundle_dir_for_refs,
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
                    "overwrite_directory_names": existing_same_name_directories,
                    "skip_existing_directory_names": [],
                    "python_requirements": req_preview,
                    "mcps": [{"name": str(x.get("name") or "")} for x in mcp_bundle],
                    "missing_references": missing_references,
                },
            }
        tool_name_map, mcp_rows_to_import, kept_tool_names = _mcp_name_identity_import_plan(load_mcp_config(), mcp_bundle)
        target_directory = existing_same_name_directories[0] if existing_same_name_directories else _next_available_directory_name(base, _slugify(incoming_name))
        dest = base / target_directory
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        fm2, body2 = _read_skill_file(dest)
        mcp_name_map = _mcp_name_map_for_import(mcp_rows_to_import)
        fm2 = _remap_frontmatter_mcp_refs(fm2, tool_name_map, mcp_name_map)
        fm2["name"] = str(fm2.get("name") or incoming_name)
        fm2["description"] = str(fm2.get("description") or "")
        _sanitize_skill_frontmatter_for_write(fm2)
        _write_skill_file(dest, fm2, body2)
        _refresh_skills_loader()
        existing_tool_names = {str(row.get("name") or "").strip() for row in load_mcp_config()}
        imported_tool_names = {str(row.get("name") or "").strip() for row in mcp_rows_to_import}
        mcp_added = len([mid for mid in imported_tool_names if mid and mid not in existing_tool_names])
        mcp_skipped = len(kept_tool_names)
        mcp_updated = len([mid for mid in imported_tool_names if mid and mid in existing_tool_names])
        if mcp_rows_to_import:
            merged_mcp = _upsert_rows_by_name(load_mcp_config(), mcp_rows_to_import, "name")
            save_mcp_config(merged_mcp)
            await _invalidate_mcp_runtime_after_config_change()
        requirements_result = await _merge_imported_skill_requirements_and_prewarm([target_directory], base)
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
                "overwritten_directory_names": existing_same_name_directories,
                "kept_directory_names": [],
                "missing_references": missing_references,
                "tool_name_map": tool_name_map,
                "mcp_added": mcp_added,
                "mcp_skipped": mcp_skipped,
                "mcp_updated": mcp_updated,
                "tool_kept_names": kept_tool_names,
            },
            **requirements_result,
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


async def _import_mcp_from_bundle_bytes(raw: bytes, *, dry_run: bool) -> Dict[str, Any]:
    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        mcp_path = tmp / "mcp_servers.json"
        if not mcp_path.is_file():
            raise HTTPException(status_code=400, detail="分享包中缺少 mcp_servers.json")
        rows = json.loads(mcp_path.read_text(encoding="utf-8"))
        mcp_bundle = [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []
        if not mcp_bundle:
            raise HTTPException(status_code=400, detail="分享包中没有可导入的 MCP 配置")
        preview = [{"name": str(x.get("name") or "")} for x in mcp_bundle]
        if dry_run:
            return {"object_type": "mcp", "preview": {"mcps": preview}}
        mcp_before = load_mcp_config()
        tool_name_map, mcp_rows_to_import, kept_tool_names = _mcp_name_identity_import_plan(mcp_before, mcp_bundle)
        existing_names = {str(row.get("name") or "").strip() for row in mcp_before}
        imported_names = {str(row.get("name") or "").strip() for row in mcp_rows_to_import}
        merged_mcp = _upsert_rows_by_name(mcp_before, mcp_rows_to_import, "name")
        mcp_added = len([mid for mid in imported_names if mid and mid not in existing_names])
        mcp_skipped = len(kept_tool_names)
        mcp_updated = len([mid for mid in imported_names if mid and mid in existing_names])
        save_mcp_config(merged_mcp)
        await _invalidate_mcp_runtime_after_config_change()
        return {
            "object_type": "mcp",
            "summary": {
                "mcp_added": mcp_added,
                "mcp_skipped": mcp_skipped,
                "mcp_updated": mcp_updated,
                "tool_name_map": tool_name_map,
                "tool_kept_names": kept_tool_names,
            },
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


async def _import_expert_from_bundle_bytes(raw: bytes, *, dry_run: bool) -> Dict[str, Any]:
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
        directory_name_map, _skill_copy_pairs, overwritten_directory_names = _skill_name_identity_import_plan(
            tmp,
            user_skills,
            directory_names_in_zip,
        )
        tool_name_map, _mcp_rows_to_import, kept_tool_names = _mcp_name_identity_import_plan(load_mcp_config(), mcp_bundle)
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
                    "would_skip_skills": [],
                    "would_remap_skills": directory_name_map,
                    "would_remap_tools": tool_name_map,
                    "would_overwrite_tools": [],
                    "would_keep_tools": kept_tool_names,
                    "would_skip_tools": [],
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
        imported_skills, overwritten_skills, directory_name_map = _copy_bundle_skills_to_user_by_name(tmp, user_skills)
        invalidate_skills_cache_for_user(get_current_username() or "")
        tool_name_map, mcp_rows_to_import, kept_tool_names = _mcp_name_identity_import_plan(load_mcp_config(), mcp_bundle)
        for sid in imported_skills:
            skill_dir = user_skills / sid
            if not (skill_dir / "SKILL.md").is_file():
                continue
            fm, body = _read_skill_file(skill_dir)
            fm = _remap_frontmatter_mcp_refs(fm, tool_name_map, _mcp_name_map_for_import(mcp_rows_to_import))
            _sanitize_skill_frontmatter_for_write(fm)
            _write_skill_file(skill_dir, fm, body)
        existing_mcp_names = {str(row.get("name") or "").strip() for row in load_mcp_config()}
        imported_mcp_names = {str(row.get("name") or "").strip() for row in mcp_rows_to_import}
        if mcp_rows_to_import:
            merged_mcp = _upsert_rows_by_name(load_mcp_config(), mcp_rows_to_import, "name")
            save_mcp_config(merged_mcp)
            await _invalidate_mcp_runtime_after_config_change()
        requirements_result = await _merge_imported_skill_requirements_and_prewarm(imported_skills, user_skills)
        instances = load_agent_instances()
        same_name_agent_names = [
            str(x.get("name") or "")
            for x in instances
            if str(x.get("name") or "").strip().lower() == str(norm.get("name") or "").strip().lower()
        ]
        skipped_by_name = False
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
                "skipped_by_name": skipped_by_name,
                "overwritten_agent_names": same_name_agent_names,
                "kept_agent_names": [],
                "skills_imported": imported_skills,
                "skills_overwritten": overwritten_skills,
                "skills_kept": [],
                "skills_skipped": [],
                "skill_map": directory_name_map,
                "tool_map": tool_name_map,
                "mcp_added": len([name for name in imported_mcp_names if name and name not in existing_mcp_names]),
                "mcp_updated": len([name for name in imported_mcp_names if name and name in existing_mcp_names]),
                "mcp_skipped": len(kept_tool_names),
                "mcp_kept_names": kept_tool_names,
                "missing_references": missing_references,
                **requirements_result,
            },
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


# ========== MCP 配置 API ==========


# ========== Skills 配置 API ==========


def _refresh_skills_loader():
    """使当前用户的技能缓存失效，下次请求重新从磁盘加载。"""
    from app.core.user_context import get_current_username
    from app.skills.loader import invalidate_skills_cache_for_user

    uname = get_current_username()
    if uname:
        invalidate_skills_cache_for_user(uname)


@router.get("/settings/skills")
async def get_skills():
    """获取 Skills 列表"""
    skills = load_skills_config()
    
    return {
        "status": "ok",
        "data": {
            "skills": skills
        }
    }

def _slugify(name: str) -> str:
    """生成可作目录名的 slug：仅允许 ASCII 字母数字与连字符，避免中文/特殊字符目录名导致脚本路径、沙箱、工具名异常。

    展示名仍可在 SKILL.md frontmatter.name 中使用中文；目录名（directory_name）与之一一对应但为稳定 ASCII。
    """
    raw = (name or "").strip()
    # 仅保留 ASCII 的「词」字符与空白、连字符（显式 ASCII，避免 \\w 匹配到中文）
    s = re.sub(r"[^A-Za-z0-9_\s-]", "", raw, flags=re.ASCII)
    s = re.sub(r"[-\s]+", "-", s).strip("-").lower()
    if s:
        return s
    # 纯中文/无可用拉丁字符：用哈希保证唯一、路径纯 ASCII
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"skill-{h}"



def _next_available_directory_name(base: Path, seed: str) -> str:
    """基于 seed 生成不冲突的 skill 目录名。"""
    directory_name = seed
    idx = 0
    while (base / directory_name).exists():
        idx += 1
        directory_name = f"{seed}-{idx}"
    return directory_name


@router.post("/settings/skills")
async def create_skill(skill: SkillCreate):
    """新建 Skill：在 skills 目录下新建 <directory_name>/SKILL.md"""
    base = _get_skills_dir()
    base.mkdir(parents=True, exist_ok=True)
    if not (skill.name or "").strip():
        raise HTTPException(status_code=400, detail="name is required")
    seed = _slugify((skill.name or "skill").strip())
    directory_name = _next_available_directory_name(base, seed)
    skill_dir = base / directory_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    body = "\n## 说明\n\n（待补充）\n"
    frontmatter = {
        "name": (skill.name or "").strip(),
        "description": skill.description or "",
        ALLOWED_TOOLS_FM_KEY: {"mcp": [], "http_api": [], "python": []},
    }
    content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n" + body
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    _refresh_skills_loader()
    ret_name = (skill.name or directory_name).strip()
    ret_desc = skill.description or ""
    new_skill = {
        "directory_name": directory_name,
        "name": ret_name,
        "description": ret_desc,
        "path": str(skill_dir),
        "allowed_tools": {"mcp": [], "http_api": [], "python": []},
    }
    return {"status": "ok", "data": new_skill}


@router.post("/settings/skills/import-zip")
async def import_skill_zip(
    file: UploadFile = File(...),
    name_conflict: str = Form("overwrite"),
):
    """通过 ZIP 导入 Skill。要求 ZIP 根目录包含 SKILL.md。"""
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 ZIP 文件")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="无效的 ZIP 文件")

    entries: List[tuple[str, List[str]]] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        raw_name = (info.filename or "").replace("\\", "/").strip("/")
        if not raw_name:
            continue
        parts = [p for p in raw_name.split("/") if p and p != "."]
        if not parts or any(p == ".." for p in parts):
            raise HTTPException(status_code=400, detail="ZIP 包含非法路径")
        entries.append((raw_name, parts))
    if not entries:
        raise HTTPException(status_code=400, detail="ZIP 中没有可导入文件")

    # 兼容“整个目录打包”场景：若所有文件都在同一顶层目录下，则自动剥离该层。
    first_heads = {parts[0] for _, parts in entries}
    strip_first = len(first_heads) == 1 and all(len(parts) >= 2 for _, parts in entries)

    normalized: List[tuple[str, List[str]]] = []
    for raw_name, parts in entries:
        rel_parts = parts[1:] if strip_first else parts
        if not rel_parts:
            continue
        normalized.append((raw_name, rel_parts))

    if not any(len(parts) == 1 and parts[0].lower() == "skill.md" for _, parts in normalized):
        raise HTTPException(status_code=400, detail="ZIP 根目录必须包含 SKILL.md")

    conflict_mode = str(name_conflict or "overwrite").strip().lower()
    if conflict_mode not in {"overwrite", "skip"}:
        logging.getLogger(__name__).warning("unknown skill name_conflict=%s, fallback to overwrite", conflict_mode)
        conflict_mode = "overwrite"

    base = _get_skills_dir()
    base.mkdir(parents=True, exist_ok=True)
    fallback_seed = _slugify(Path(filename).stem or "skill")
    directory_name = _next_available_directory_name(base, fallback_seed)
    skill_dir = base / directory_name
    created_skill_dir = False
    mcp_bundle: List[Dict[str, Any]] = []

    try:
        with tempfile.TemporaryDirectory(prefix="skill-zip-import-") as tmp:
            src_dir = Path(tmp) / "skill"
            src_dir.mkdir(parents=True, exist_ok=True)
            for raw_name, rel_parts in normalized:
                if len(rel_parts) == 1 and rel_parts[0].lower() == "mcp_servers.json":
                    with zf.open(raw_name, "r") as rf:
                        mcp_bundle = _parse_mcp_bundle_rows(rf.read())
                    continue
                if len(rel_parts) == 1 and rel_parts[0].lower() == "skill.md":
                    dst = src_dir / "SKILL.md"
                else:
                    dst = src_dir / Path(*rel_parts)
                dst.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(raw_name, "r") as rf:
                    dst.write_bytes(rf.read())

            if not (src_dir / "SKILL.md").is_file():
                raise HTTPException(status_code=400, detail="ZIP 根目录必须包含 SKILL.md")

            src_fm, _src_body = _read_skill_file(src_dir)
            incoming_name = str(src_fm.get("name") or "").strip() or fallback_seed
            incoming_name_key = _normalized_name_key(incoming_name)
            existing_same_name_directories: List[str] = []
            for child in sorted(base.iterdir(), key=lambda p: p.name):
                if not child.is_dir():
                    continue
                try:
                    fm_existing, _body_existing = _read_skill_file(child)
                except Exception:
                    continue
                existing_name = str(fm_existing.get("name") or "").strip() or child.name
                if _normalized_name_key(existing_name) != incoming_name_key:
                    continue
                existing_same_name_directories.append(child.name)

            if existing_same_name_directories:
                directory_name = existing_same_name_directories[0]
                skill_dir = base / directory_name
                if skill_dir.exists():
                    shutil.rmtree(skill_dir)
                shutil.copytree(src_dir, skill_dir)
                fm, body = _read_skill_file(skill_dir)
                final_name = (str(fm.get("name") or "").strip() or incoming_name or directory_name)
                final_desc = str(fm.get("description") or "")
                tool_name_map, mcp_rows_to_import, kept_tool_names = _mcp_name_identity_import_plan(load_mcp_config(), mcp_bundle)
                fm = _remap_frontmatter_mcp_refs(fm, tool_name_map, _mcp_name_map_for_import(mcp_rows_to_import))
                fm["name"] = final_name
                fm["description"] = final_desc
                _sanitize_skill_frontmatter_for_write(fm)
                _write_skill_file(skill_dir, fm, body)
                _refresh_skills_loader()
                existing_tool_names = {str(row.get("name") or "").strip() for row in load_mcp_config()}
                imported_tool_names = {str(row.get("name") or "").strip() for row in mcp_rows_to_import}
                mcp_added = len([mid for mid in imported_tool_names if mid and mid not in existing_tool_names])
                mcp_skipped = len(kept_tool_names)
                mcp_updated = len([mid for mid in imported_tool_names if mid and mid in existing_tool_names])
                if mcp_rows_to_import:
                    merged_mcp = _upsert_rows_by_name(load_mcp_config(), mcp_rows_to_import, "name")
                    save_mcp_config(merged_mcp)
                    await _invalidate_mcp_runtime_after_config_change()
                requirements_result = await _merge_imported_skill_requirements_and_prewarm([directory_name], base)
                return {
                    "status": "ok",
                    "data": {
                        "directory_name": directory_name,
                        "name": final_name,
                        "description": final_desc,
                        "path": str(skill_dir),
                        "allowed_tools": _normalized_allowed_tools_dict(fm),
                        "skipped_by_name": False,
                        "kept_by_name": False,
                        "overwritten_by_name": True,
                        "overwritten_directory_names": existing_same_name_directories,
                        "kept_directory_names": [],
                        "mcp_added": mcp_added,
                        "mcp_skipped": mcp_skipped,
                        "mcp_updated": mcp_updated,
                        "tool_name_map": tool_name_map,
                        "tool_kept_names": kept_tool_names,
                        **requirements_result,
                    },
                }

            shutil.copytree(src_dir, skill_dir)
            created_skill_dir = True

        fm, body = _read_skill_file(skill_dir)
        # 目录名优先使用 SKILL.md frontmatter.name（若可用）
        preferred_seed = _slugify(str(fm.get("name") or "").strip()) or fallback_seed
        preferred_directory = directory_name if existing_same_name_directories else _next_available_directory_name(base, preferred_seed)
        if preferred_directory != directory_name:
            target_dir = base / preferred_directory
            shutil.move(str(skill_dir), str(target_dir))
            directory_name = preferred_directory
            skill_dir = target_dir
            fm, body = _read_skill_file(skill_dir)
        final_name = (str(fm.get("name") or "").strip() or directory_name)
        final_desc = str(fm.get("description") or "")
        tool_name_map, mcp_rows_to_import, kept_tool_names = _mcp_name_identity_import_plan(load_mcp_config(), mcp_bundle)
        fm = _remap_frontmatter_mcp_refs(fm, tool_name_map, _mcp_name_map_for_import(mcp_rows_to_import))
        fm["name"] = final_name
        fm["description"] = final_desc
        _sanitize_skill_frontmatter_for_write(fm)
        _write_skill_file(skill_dir, fm, body)
        _refresh_skills_loader()
        existing_tool_names = {str(row.get("name") or "").strip() for row in load_mcp_config()}
        imported_tool_names = {str(row.get("name") or "").strip() for row in mcp_rows_to_import}
        mcp_added = len([mid for mid in imported_tool_names if mid and mid not in existing_tool_names])
        mcp_skipped = len(kept_tool_names)
        mcp_updated = len([mid for mid in imported_tool_names if mid and mid in existing_tool_names])
        if mcp_rows_to_import:
            merged_mcp = _upsert_rows_by_name(load_mcp_config(), mcp_rows_to_import, "name")
            save_mcp_config(merged_mcp)
            await _invalidate_mcp_runtime_after_config_change()
        requirements_result = await _merge_imported_skill_requirements_and_prewarm([directory_name], base)

        return {
            "status": "ok",
            "data": {
                "directory_name": directory_name,
                "name": final_name,
                "description": final_desc,
                "path": str(skill_dir),
                "allowed_tools": _normalized_allowed_tools_dict(fm),
                "skipped_by_name": False,
                "overwritten_directory_names": existing_same_name_directories,
                "kept_directory_names": [],
                "mcp_added": mcp_added,
                "mcp_skipped": mcp_skipped,
                "mcp_updated": mcp_updated,
                "tool_name_map": tool_name_map,
                "tool_kept_names": kept_tool_names,
                **requirements_result,
            },
        }
    except HTTPException:
        if created_skill_dir and skill_dir.exists():
            shutil.rmtree(skill_dir, ignore_errors=True)
        raise
    except Exception as e:
        if created_skill_dir and skill_dir.exists():
            shutil.rmtree(skill_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"ZIP 导入失败：{e}")

def _content_disposition_attachment(filename: str) -> str:
    """下载文件名：HTTP 头须为 latin-1；含中文等非 ASCII 时用 RFC 5987 的 filename*。"""
    try:
        filename.encode("latin-1")
        safe = filename.replace("\\", "\\\\").replace('"', '\\"')
        return f'attachment; filename="{safe}"'
    except UnicodeEncodeError:
        return (
            'attachment; filename="skill-export.zip"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )


def _build_skill_zip_bytes(skill_dir: Path, mcp_rows: Optional[List[Dict[str, Any]]] = None) -> bytes:
    """将技能目录打包为 ZIP；根目录含 SKILL.md，可选携带 mcp_servers.json。"""
    from app.core.scenario_bundle import sanitize_mcp_servers_for_bundle

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
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
            if arcname == "mcp_servers.json":
                continue
            zf.write(fp, arcname)
        safe_mcp_rows = sanitize_mcp_servers_for_bundle(mcp_rows or [])
        if safe_mcp_rows:
            zf.writestr("mcp_servers.json", json.dumps(safe_mcp_rows, ensure_ascii=False, indent=2) + "\n")
    return buf.getvalue()


@router.get("/settings/skills/{directory_name}/export-zip")
async def export_skill_zip(directory_name: str):
    """导出当前技能目录为 ZIP，可用于备份或再次 import-zip 导入。"""
    base = _get_skills_dir().resolve()
    skill_dir = (base / directory_name).resolve()
    if not skill_dir.is_dir() or skill_dir.parent != base:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not (skill_dir / "SKILL.md").is_file():
        raise HTTPException(status_code=404, detail="Skill not found")
    raw = _build_skill_zip_bytes(skill_dir, _mcp_rows_for_skill_dir(skill_dir))
    filename = f"{directory_name}.zip"
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_attachment(filename)},
    )


@router.put("/settings/skills/{directory_name}")
async def update_skill(directory_name: str, skill_update: SkillUpdate):
    """更新 Skill：修改 SKILL.md 的 frontmatter 与/或正文 body"""
    base = _get_skills_dir()
    skill_dir = base / directory_name
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    fm, body = _read_skill_file(skill_dir)
    if skill_update.name is not None:
        fm["name"] = skill_update.name
    if skill_update.description is not None:
        fm["description"] = skill_update.description
    if skill_update.allowed_tools is not None:
        if not isinstance(skill_update.allowed_tools, dict):
            raise HTTPException(status_code=400, detail="allowed_tools must be an object")
        normalized_tools = _normalize_allowed_tools_payload(skill_update.allowed_tools)
        fm[ALLOWED_TOOLS_FM_KEY] = _runtime_tools_only(normalized_tools)
    if skill_update.body is not None:
        body = skill_update.body
    _sanitize_skill_frontmatter_for_write(fm)
    _write_skill_file(skill_dir, fm, body)
    new_directory_name = directory_name
    # 若名字变更，自动将目录名对齐到 frontmatter.name（并做冲突避让）
    current_name = str(fm.get("name") or "").strip()
    if current_name:
        desired_seed = _slugify(current_name)
        if desired_seed and desired_seed != directory_name:
            if (base / desired_seed).exists():
                desired_seed = _next_available_directory_name(base, desired_seed)
            target_dir = base / desired_seed
            if target_dir != skill_dir:
                shutil.move(str(skill_dir), str(target_dir))
                skill_dir = target_dir
                new_directory_name = desired_seed
                _replace_skill_path_in_user_configs(directory_name, new_directory_name)
    _refresh_skills_loader()
    return {
        "status": "ok",
        "data": {
            "directory_name": new_directory_name,
            "updated": True,
            "renamed": new_directory_name != directory_name,
            "old_directory_name": directory_name,
        },
    }

@router.delete("/settings/skills/{directory_name}")
async def delete_skill(directory_name: str):
    """删除 Skill：删除对应目录"""
    base = _get_skills_dir()
    skill_dir = base / directory_name
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    skill_name = _skill_display_name_from_dir(skill_dir, directory_name)
    shutil.rmtree(skill_dir)
    _remove_skill_path_from_user_configs(directory_name, skill_name)
    _refresh_skills_loader()
    return {"status": "ok", "data": {"directory_name": directory_name, "deleted": True}}

@router.get("/settings/skills/{directory_name}/content")
async def get_skill_content(directory_name: str):
    """获取技能 SKILL.md 的完整内容（raw 全文）及 frontmatter 解析结果，用于详情页展示。"""
    base = _get_skills_dir()
    skill_dir = base / directory_name
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    path = skill_dir / "SKILL.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Skill not found")
    raw = path.read_text(encoding="utf-8")
    fm, body = _read_skill_file(skill_dir)
    allowed = _normalized_allowed_tools_dict(fm)
    return {
        "status": "ok",
        "data": {
            "raw": raw,
            "name": fm.get("name", directory_name),
            "description": fm.get("description", ""),
            "body": body,
            "allowed_tools": allowed,
        },
    }



register_skill_part_routes(router)
