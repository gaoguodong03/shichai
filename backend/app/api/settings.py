"""设置 API - MCP / Skills / 主持人提示词"""
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
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Set, Tuple

from app.core.user_context import get_current_user_context, get_current_username
from app.core.user_settings_paths import require_user_context, sandbox_requirements_path, skills_dir_path
from app.core.session_preset_validate import (
    normalize_preset_dict_for_validation,
)
from app.core.settings_references import (
    merge_reference_rows_for_ids as _merge_reference_rows_for_ids,
    normalize_reference_rows as _normalize_reference_rows,
    remap_bundle_references as _remap_bundle_references,
    remove_skill_id_from_user_configs as _remove_skill_id_from_user_configs,
    replace_mcp_server_id_in_user_configs as _replace_mcp_server_id_in_user_configs,
    replace_skill_id_in_user_configs as _replace_skill_id_in_user_configs,
)
from app.core.settings_bundle_import import (
    collect_mcp_ids_from_skill_dirs,
    copy_bundle_skills_to_user_by_name as _copy_bundle_skills_to_user_by_name,
    find_missing_references_for_expert_bundle as _find_missing_references_for_expert_bundle,
    find_missing_references_for_scene_bundle as _find_missing_references_for_scene_bundle,
    find_missing_references_for_skill_bundle as _find_missing_references_for_skill_bundle,
    mcp_conflict_id_map as _mcp_conflict_id_map,
    skill_conflict_id_map as _skill_conflict_id_map,
)
from app.core.scenario_bundle import (
    build_scenario_bundle_zip_bytes,
    collect_skill_and_mcp_ids_for_preset,
    copy_bundle_skills_to_user,
    extract_scenario_bundle_dir,
    list_skill_ids_in_bundle_skills_dir,
    merge_dha_instances_for_bundle,
    merge_mcp_servers_for_bundle,
    read_bundle_manifest_and_lists,
    strip_dha_row_for_disk,
)
from app.skills.loader import get_builtin_skills_dir, invalidate_skills_cache_for_user
from app.core.security import user_context_dependency
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.api.settings_app import (
    load_app_settings,
    normalize_host_profile,
    save_app_settings,
)
from app.api.settings_secrets import (
    load_api_secret_values,
    load_api_secret_values_for_user,
    load_api_secrets_raw,
    save_api_secrets_raw,
)
from app.api.settings_mcp import load_mcp_config, save_mcp_config
from app.mcp.manager import dispose_mcp_runtime_for_user
from app.core.sandbox_requirements import merge_requirements_lines, requirement_key

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])


async def _invalidate_mcp_runtime_after_config_change():
    """磁盘上的 mcp_servers.json 变更后丢弃内存中的连接，下次再懒加载。"""
    un = get_current_username()
    if un:
        await dispose_mcp_runtime_for_user(un)

def _require_user_ctx():
    return require_user_context()


def _get_skills_dir() -> Path:
    """根据当前用户返回 skills 目录。"""
    return skills_dir_path()


def _get_sandbox_requirements_path() -> Path:
    """当前用户沙箱依赖清单 requirements.txt 路径。"""
    return sandbox_requirements_path()


def _normalized_name_key(raw: Any) -> str:
    return str(raw or "").strip().lower()




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
    try:
        fm, _ = _read_skill_file(skill_dir)
    except Exception:
        return []
    mcp_ids = _mcp_ids_from_frontmatter(fm)
    if not mcp_ids:
        return []
    by_id = {str(row.get("id") or "").strip(): row for row in load_mcp_config() if str(row.get("id") or "").strip()}
    return [dict(by_id[mid]) for mid in mcp_ids if mid in by_id]


def _parse_mcp_bundle_rows(raw: bytes) -> List[Dict[str, Any]]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [row for row in parsed if isinstance(row, dict) and str(row.get("id") or "").strip()]


def _read_mcp_bundle_rows(bundle_dir: Path) -> List[Dict[str, Any]]:
    path = bundle_dir / "mcp_servers.json"
    if not path.is_file():
        return []
    try:
        return _parse_mcp_bundle_rows(path.read_bytes())
    except Exception:
        return []


async def _merge_imported_skill_requirements_and_prewarm(skill_ids: List[str], skills_root: Path) -> Dict[str, Any]:
    incoming: List[str] = []
    for sid in skill_ids:
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
        skill_ids = list_skill_ids_in_bundle_skills_dir(tmp)
        if not skill_ids:
            root_skill = tmp / "SKILL.md"
            if not root_skill.is_file():
                raise HTTPException(status_code=400, detail="分享包中缺少技能目录")
            root_fm, _root_body = _read_skill_file(tmp)
            root_name = str(root_fm.get("name") or "skill").strip() or "skill"
            sid0 = _slugify(root_name)
            normalized = tmp / "__normalized_skill_bundle"
            src = normalized / "skills" / sid0
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
            sid0 = skill_ids[0]
            src = tmp / "skills" / sid0
            bundle_dir_for_refs = tmp
        fm, body = _read_skill_file(src)
        incoming_name = str(fm.get("name") or sid0).strip() or sid0
        incoming_name_key = _normalized_name_key(incoming_name)
        base = _get_skills_dir()
        base.mkdir(parents=True, exist_ok=True)
        overwrite_skill_ids: List[str] = []
        for child in sorted(base.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            try:
                efm, _ = _read_skill_file(child)
            except Exception:
                continue
            ename = str(efm.get("name") or child.name).strip()
            if _normalized_name_key(ename) == incoming_name_key:
                overwrite_skill_ids.append(child.name)
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
                    "skill_id": sid0,
                    "name": incoming_name,
                    "overwrite_skill_ids": overwrite_skill_ids,
                    "python_requirements": req_preview,
                    "mcps": [{"id": str(x.get("id") or ""), "name": str(x.get("name") or "")} for x in mcp_bundle],
                    "missing_references": missing_references,
                },
            }
        for old_id in overwrite_skill_ids:
            old_dir = base / old_id
            if old_dir.is_dir():
                old_name = _skill_display_name_from_dir(old_dir, old_id)
                shutil.rmtree(old_dir, ignore_errors=True)
                _remove_skill_id_from_user_configs(old_id, old_name)
        target_id = _next_available_skill_id(base, _slugify(incoming_name))
        dest = base / target_id
        shutil.copytree(src, dest)
        fm2, body2 = _read_skill_file(dest)
        fm2["name"] = str(fm2.get("name") or incoming_name)
        fm2["description"] = str(fm2.get("description") or "")
        _sanitize_skill_frontmatter_for_write(fm2)
        _write_skill_file(dest, fm2, body2)
        _refresh_skills_loader()
        mcp_added = 0
        mcp_skipped = 0
        mcp_updated = 0
        if mcp_bundle:
            merged_mcp, mcp_added, mcp_skipped, mcp_updated = merge_mcp_servers_for_bundle(
                load_mcp_config(), mcp_bundle, skip_existing=False
            )
            save_mcp_config(merged_mcp)
            await _invalidate_mcp_runtime_after_config_change()
        requirements_result = await _merge_imported_skill_requirements_and_prewarm([target_id], base)
        missing_references = _find_missing_references_for_skill_bundle(
            target_id,
            mcp_bundle,
            None,
            base,
            load_mcp_config(),
            extra_skill_roots=(get_builtin_skills_dir(),),
        )
        return {
            "object_type": "skill",
            "imported_skill_id": target_id,
            "name": str(fm2.get("name") or target_id),
            "summary": {
                "missing_references": missing_references,
                "mcp_added": mcp_added,
                "mcp_skipped": mcp_skipped,
                "mcp_updated": mcp_updated,
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
        preview = [{"id": str(x.get("id") or ""), "name": str(x.get("name") or "")} for x in mcp_bundle]
        if dry_run:
            return {"object_type": "mcp", "preview": {"mcps": preview}}
        merged_mcp, mcp_added, mcp_skipped, mcp_updated = merge_mcp_servers_for_bundle(
            load_mcp_config(), mcp_bundle, skip_existing=False
        )
        save_mcp_config(merged_mcp)
        await _invalidate_mcp_runtime_after_config_change()
        return {
            "object_type": "mcp",
            "summary": {"mcp_added": mcp_added, "mcp_skipped": mcp_skipped, "mcp_updated": mcp_updated},
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


async def _import_expert_from_bundle_bytes(raw: bytes, *, dry_run: bool) -> Dict[str, Any]:
    from app.api.dha import load_dha_instances, normalize_expert_row_for_import, save_dha_instances, _dha_skills_dir
    from app.core.expert_bundle import merge_single_expert_into_instances, read_expert_bundle_manifest

    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        _man, expert_raw = read_expert_bundle_manifest(tmp)
        norm = normalize_expert_row_for_import(expert_raw)
        if norm is None:
            raise HTTPException(status_code=400, detail="专家分享包无效")
        skill_ids_in_zip = list_skill_ids_in_bundle_skills_dir(tmp)
        mcp_path = tmp / "mcp_servers.json"
        mcp_bundle: List[Dict[str, Any]] = []
        if mcp_path.is_file():
            raw_m = json.loads(mcp_path.read_text(encoding="utf-8"))
            if isinstance(raw_m, list):
                mcp_bundle = [x for x in raw_m if isinstance(x, dict)]
        user_skills = _dha_skills_dir()
        skill_id_map = _skill_conflict_id_map(tmp, user_skills, skill_ids_in_zip)
        mcp_id_map = _mcp_conflict_id_map(load_mcp_config(), mcp_bundle)
        _unused_preset, remapped_experts = _remap_bundle_references(
            {},
            [norm],
            skill_id_map=skill_id_map,
            mcp_id_map=mcp_id_map,
        )
        norm = remapped_experts[0] if remapped_experts else norm
        same_name_agent_ids = [
            str(x.get("agent_id") or "")
            for x in load_dha_instances()
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
                    "agent_id": str(norm.get("agent_id") or ""),
                    "skills": skill_ids_in_zip,
                    "mcps": [{"id": str(x.get("id") or ""), "name": str(x.get("name") or "")} for x in mcp_bundle],
                    "name_conflict_existing_ids": same_name_agent_ids,
                    "would_overwrite_skills": sorted(skill_id_map.keys()),
                    "would_remap_skill_ids": skill_id_map,
                    "would_remap_mcp_server_ids": mcp_id_map,
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
        imported_skills, overwritten_skills, skill_id_map = _copy_bundle_skills_to_user_by_name(tmp, user_skills)
        invalidate_skills_cache_for_user(get_current_username() or "")
        for old_id, new_id in mcp_id_map.items():
            _replace_mcp_server_id_in_user_configs(old_id, new_id)
        if mcp_bundle:
            merged_mcp, _a, _s, _u = merge_mcp_servers_for_bundle(load_mcp_config(), mcp_bundle, skip_existing=False)
            save_mcp_config(merged_mcp)
            await _invalidate_mcp_runtime_after_config_change()
        requirements_result = await _merge_imported_skill_requirements_and_prewarm(imported_skills, user_skills)
        instances, final_id, skipped_by_name, overwritten_agent_ids = merge_single_expert_into_instances(
            load_dha_instances(), norm, id_conflict="overwrite"
        )
        save_dha_instances(instances)
        return {
            "object_type": "expert",
            "summary": {
                "imported_agent_id": final_id,
                "skipped_by_name": skipped_by_name,
                "overwritten_agent_ids": overwritten_agent_ids,
                "skills_imported": imported_skills,
                "skills_overwritten": overwritten_skills,
                "skill_id_map": skill_id_map,
                "mcp_id_map": mcp_id_map,
                "missing_references": missing_references,
                **requirements_result,
            },
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


# ========== MCP 配置 API ==========


# ========== Skills 配置 API ==========

class SkillCreate(BaseModel):
    """创建 Skill 请求"""
    name: Optional[str] = None
    description: Optional[str] = None

class SkillUpdate(BaseModel):
    """更新 Skill 请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    body: Optional[str] = None  # SKILL.md frontmatter 之后的正文
    allowed_tools: Optional[Dict[str, Any]] = None  # allowed-tools：mcp 为运行时声明；python 会同步到沙箱 requirements


# SKILL.md frontmatter 标准键：与 YAML 中 `allowed-tools` 一致
ALLOWED_TOOLS_FM_KEY = "allowed-tools"
AUTO_TOOLS_FM_KEY = "auto-tools"
REFERENCE_LABELS_FM_KEY = "reference-labels"


def _refresh_skills_loader():
    """使当前用户的技能缓存失效，下次请求重新从磁盘加载。"""
    from app.core.user_context import get_current_username
    from app.skills.loader import invalidate_skills_cache_for_user

    uname = get_current_username()
    if uname:
        invalidate_skills_cache_for_user(uname)


def _parse_frontmatter_lenient(frontmatter_text: str) -> Dict[str, Any]:
    """解析 frontmatter：优先 YAML，失败时回退到宽容 key:value 解析。"""
    try:
        parsed = yaml.safe_load(frontmatter_text) or {}
        if isinstance(parsed, dict):
            return parsed
        return {}
    except Exception:
        result: Dict[str, Any] = {}
        for raw in (frontmatter_text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            key = (k or "").strip()
            if not key:
                continue
            val = (v or "").strip()
            # 兼容最常见 frontmatter 值类型
            if val.lower() == "true":
                result[key] = True
            elif val.lower() == "false":
                result[key] = False
            else:
                result[key] = val.strip("'\"")
        return result


def _mcp_ids_from_frontmatter(fm: Dict[str, Any]) -> List[str]:
    auto = fm.get(AUTO_TOOLS_FM_KEY)
    if isinstance(auto, dict) and "mcp" in auto:
        m = auto.get("mcp")
        if isinstance(m, list):
            return list(dict.fromkeys(str(x).strip() for x in m if str(x).strip()))
        return []
    at = fm.get(ALLOWED_TOOLS_FM_KEY)
    if isinstance(at, dict) and "mcp" in at:
        m = at.get("mcp")
        if isinstance(m, list):
            return list(dict.fromkeys(str(x).strip() for x in m if str(x).strip()))
        return []
    legacy = fm.get("mcp_server_ids")
    if isinstance(legacy, list):
        return list(dict.fromkeys(str(x).strip() for x in legacy if str(x).strip()))
    return []


def _python_doc_from_allowed_tools(fm: Dict[str, Any]) -> str:
    at = fm.get(ALLOWED_TOOLS_FM_KEY)
    auto = fm.get(AUTO_TOOLS_FM_KEY)
    py: Any = ""
    if isinstance(auto, dict):
        py = auto.get("python")
    if (py is None or py == "") and isinstance(at, dict):
        py = at.get("python")
    if isinstance(py, str):
        return py
    if py is None:
        return ""
    if isinstance(py, list):
        return "\n".join(str(x).strip() for x in py if str(x).strip())
    return str(py)


def _mcp_reference_rows_from_frontmatter(fm: Dict[str, Any]) -> List[Dict[str, str]]:
    labels = fm.get(REFERENCE_LABELS_FM_KEY)
    if isinstance(labels, dict):
        rows = _normalize_reference_rows(labels.get("mcp"))
        if rows:
            return rows
    for source in (fm.get(AUTO_TOOLS_FM_KEY), fm.get(ALLOWED_TOOLS_FM_KEY)):
        if isinstance(source, dict):
            rows = _normalize_reference_rows(source.get("mcp_refs"))
            if rows:
                return rows
    return []


def _mcp_name_lookup() -> Dict[str, str]:
    try:
        return {
            str(row.get("id") or "").strip(): str(row.get("name") or "").strip()
            for row in load_mcp_config()
            if str(row.get("id") or "").strip()
        }
    except Exception:
        return {}


def _runtime_tools_only(normalized: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mcp": list(normalized.get("mcp") or []),
        "python": str(normalized.get("python") or ""),
    }


def _normalized_allowed_tools_dict(fm: Dict[str, Any]) -> Dict[str, Any]:
    """从当前 frontmatter 归一化 allowed-tools（合并旧 mcp_server_ids）。"""
    mcp_ids = list(_mcp_ids_from_frontmatter(fm))
    return {
        "mcp": mcp_ids,
        "python": _python_doc_from_allowed_tools(fm),
        "mcp_refs": _merge_reference_rows_for_ids(
            mcp_ids,
            _mcp_reference_rows_from_frontmatter(fm),
            _mcp_name_lookup(),
        ),
    }


def _normalize_allowed_tools_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """校验并归一化 API 传入的 allowed_tools 体。"""
    mcp_raw = raw.get("mcp")
    mcp_list = list(dict.fromkeys(str(x).strip() for x in (mcp_raw if isinstance(mcp_raw, list) else []) if str(x).strip()))
    py = raw.get("python", "")
    py_str = py if isinstance(py, str) else ("" if py is None else str(py))
    return {
        "mcp": mcp_list,
        "python": py_str,
        "mcp_refs": _merge_reference_rows_for_ids(
            mcp_list,
            raw.get("mcp_refs"),
            _mcp_name_lookup(),
        ),
    }


def _sanitize_skill_frontmatter_for_write(fm: Dict[str, Any]) -> None:
    """写入前：保证 auto-tools/allowed-tools 存在并剥离已废弃键。"""
    normalized = _normalized_allowed_tools_dict(fm)
    runtime_tools = _runtime_tools_only(normalized)
    fm[AUTO_TOOLS_FM_KEY] = runtime_tools
    fm[ALLOWED_TOOLS_FM_KEY] = runtime_tools
    ref_labels = fm.get(REFERENCE_LABELS_FM_KEY) if isinstance(fm.get(REFERENCE_LABELS_FM_KEY), dict) else {}
    ref_labels = dict(ref_labels)
    ref_labels["mcp"] = normalized.get("mcp_refs") or []
    fm[REFERENCE_LABELS_FM_KEY] = ref_labels
    for k in ("enabled", "write_mode", "mcp_server_ids", "source", "url"):
        fm.pop(k, None)


def _skill_dir_for_id(skill_id: str) -> Optional[Path]:
    sid = (skill_id or "").strip()
    if not sid or ".." in sid or "/" in sid or "\\" in sid:
        return None
    base = _get_skills_dir().resolve()
    d = (base / sid).resolve()
    if d.is_dir() and str(d).startswith(str(base)) and (d / "SKILL.md").is_file():
        return d
    br = get_builtin_skills_dir()
    if not br.exists():
        return None
    br = br.resolve()
    d2 = (br / sid).resolve()
    if d2.is_dir() and str(d2).startswith(str(br)) and (d2 / "SKILL.md").is_file():
        return d2
    return None


def _skill_item_from_skill_dir(skill_dir: Path) -> Optional[Dict[str, Any]]:
    """从单个 skill 目录解析一条技能清单项（与 load_skills_config 原逻辑一致）。"""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return None
    content = skill_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        frontmatter = _parse_frontmatter_lenient(parts[1])
        skill_id = skill_dir.name
        item: Dict[str, Any] = {
            "id": skill_id,
            "name": frontmatter.get("name", skill_id),
            "description": frontmatter.get("description", ""),
            "path": str(skill_dir),
            "allowed_tools": _normalized_allowed_tools_dict(frontmatter),
        }
        return item
    except Exception:
        return None


def load_skills_config() -> List[Dict[str, Any]]:
    """加载 Skills 配置（用户 skills 目录优先；内置 builtin_skills 补全未覆盖的 id）。"""
    skills_dir = _get_skills_dir()
    seen: Set[str] = set()
    skills: List[Dict[str, Any]] = []
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            item = _skill_item_from_skill_dir(skill_dir)
            if item:
                skills.append(item)
                seen.add(str(item.get("id") or ""))
    builtin_root = get_builtin_skills_dir()
    if builtin_root.exists():
        for skill_dir in builtin_root.iterdir():
            if not skill_dir.is_dir():
                continue
            item = _skill_item_from_skill_dir(skill_dir)
            if not item:
                continue
            sid = str(item.get("id") or "")
            if sid and sid not in seen:
                skills.append(item)
                seen.add(sid)
    skills.sort(key=lambda x: (x.get("name") or x.get("id") or "").strip())
    return skills

def _validate_skill_mcp_server_ids(mcp_ids: Optional[List[str]]) -> List[str]:
    """校验 skill 声明的 MCP id 均存在。"""
    raw = [str(x).strip() for x in (mcp_ids or []) if str(x).strip()]
    cfg = load_mcp_config()
    allowed = {
        str(s.get("id")).strip()
        for s in cfg
        if str(s.get("id") or "").strip()
    }
    unknown = [x for x in raw if x not in allowed]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail="Unknown MCP server id: " + ", ".join(unknown),
        )
    return list(dict.fromkeys(raw))


def get_mcp_servers_for_skill(skill_id: str) -> List[str]:
    """根据 skill_id 从 SKILL.md 的 allowed-tools.mcp（或兼容旧 mcp_server_ids）解析 MCP server_id 列表。"""
    skill_dir = _skill_dir_for_id(skill_id)
    if skill_dir is None:
        return []
    fm, _ = _read_skill_file(skill_dir)
    ids = _mcp_ids_from_frontmatter(fm)
    existing_ids = {s.get("id") for s in load_mcp_config()}
    return [x for x in ids if x in existing_ids]


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

    展示名仍可在 SKILL.md frontmatter.name 中使用中文；目录名（skill_id）与之一一对应但为稳定 ASCII。
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



def _next_available_skill_id(base: Path, seed: str) -> str:
    """基于 seed 生成不冲突的 skill 目录名。"""
    skill_id = seed
    idx = 0
    while (base / skill_id).exists():
        idx += 1
        skill_id = f"{seed}-{idx}"
    return skill_id


@router.post("/settings/skills")
async def create_skill(skill: SkillCreate):
    """创建 Skill：在 skills 目录下创建 <id>/SKILL.md"""
    base = _get_skills_dir()
    base.mkdir(parents=True, exist_ok=True)
    if not (skill.name or "").strip():
        raise HTTPException(status_code=400, detail="name is required")
    raw_id = _slugify((skill.name or "skill").strip())
    skill_id = _next_available_skill_id(base, raw_id)
    skill_dir = base / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    body = "\n## 说明\n\n（待补充）\n"
    frontmatter = {
        "name": (skill.name or "").strip(),
        "description": skill.description or "",
        AUTO_TOOLS_FM_KEY: {"mcp": [], "python": ""},
        ALLOWED_TOOLS_FM_KEY: {"mcp": [], "python": ""},
    }
    content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n" + body
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    _refresh_skills_loader()
    ret_name = (skill.name or skill_id).strip()
    ret_desc = skill.description or ""
    new_skill = {
        "id": skill_id,
        "name": ret_name,
        "description": ret_desc,
        "path": str(skill_dir),
        "allowed_tools": {"mcp": [], "python": ""},
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
    skill_id = _next_available_skill_id(base, fallback_seed)
    skill_dir = base / skill_id
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
            overwrite_skill_ids: List[str] = []
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
                overwrite_skill_ids.append(child.name)

            if overwrite_skill_ids and conflict_mode == "skip":
                return {
                    "status": "ok",
                    "data": {
                        "id": None,
                        "name": incoming_name,
                        "skipped_by_name": True,
                        "overwritten_skill_ids": overwrite_skill_ids,
                    },
                }

            for sid in overwrite_skill_ids:
                old_dir = base / sid
                if old_dir.is_dir():
                    old_name = _skill_display_name_from_dir(old_dir, sid)
                    shutil.rmtree(old_dir, ignore_errors=True)
                    _remove_skill_id_from_user_configs(sid, old_name)

            shutil.copytree(src_dir, skill_dir)

        fm, body = _read_skill_file(skill_dir)
        # 目录名优先使用 SKILL.md frontmatter.name（若可用）
        preferred_seed = _slugify(str(fm.get("name") or "").strip()) or fallback_seed
        preferred_id = _next_available_skill_id(base, preferred_seed)
        if preferred_id != skill_id:
            target_dir = base / preferred_id
            shutil.move(str(skill_dir), str(target_dir))
            skill_id = preferred_id
            skill_dir = target_dir
            fm, body = _read_skill_file(skill_dir)
        final_name = (str(fm.get("name") or "").strip() or skill_id)
        final_desc = str(fm.get("description") or "")
        fm["name"] = final_name
        fm["description"] = final_desc
        _sanitize_skill_frontmatter_for_write(fm)
        _write_skill_file(skill_dir, fm, body)
        _refresh_skills_loader()
        mcp_added = 0
        mcp_skipped = 0
        mcp_updated = 0
        if mcp_bundle:
            merged_mcp, mcp_added, mcp_skipped, mcp_updated = merge_mcp_servers_for_bundle(
                load_mcp_config(), mcp_bundle, skip_existing=False
            )
            save_mcp_config(merged_mcp)
            await _invalidate_mcp_runtime_after_config_change()
        requirements_result = await _merge_imported_skill_requirements_and_prewarm([skill_id], base)

        return {
            "status": "ok",
            "data": {
                "id": skill_id,
                "name": final_name,
                "description": final_desc,
                "path": str(skill_dir),
                "allowed_tools": _normalized_allowed_tools_dict(fm),
                "skipped_by_name": False,
                "mcp_added": mcp_added,
                "mcp_skipped": mcp_skipped,
                "mcp_updated": mcp_updated,
                **requirements_result,
            },
        }
    except HTTPException:
        if skill_dir.exists():
            shutil.rmtree(skill_dir, ignore_errors=True)
        raise
    except Exception as e:
        if skill_dir.exists():
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
        if mcp_rows:
            zf.writestr("mcp_servers.json", json.dumps(mcp_rows, ensure_ascii=False, indent=2) + "\n")
    return buf.getvalue()


@router.get("/settings/skills/{skill_id}/export-zip")
async def export_skill_zip(skill_id: str):
    """导出当前技能目录为 ZIP，可用于备份或再次 import-zip 导入。"""
    base = _get_skills_dir().resolve()
    skill_dir = (base / skill_id).resolve()
    if not skill_dir.is_dir() or skill_dir.parent != base:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not (skill_dir / "SKILL.md").is_file():
        raise HTTPException(status_code=404, detail="Skill not found")
    raw = _build_skill_zip_bytes(skill_dir, _mcp_rows_for_skill_dir(skill_dir))
    filename = f"{skill_id}.zip"
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_attachment(filename)},
    )


@router.get("/settings/skills/{skill_id}/share-link")
async def get_skill_share_link(skill_id: str):
    from app.core.scenario_share_store import find_share_id_for_object

    sid = str(skill_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="skill_id required")
    base = _get_skills_dir().resolve()
    sdir = (base / sid).resolve()
    if not sdir.is_dir() or sdir.parent != base or not (sdir / "SKILL.md").is_file():
        raise HTTPException(status_code=404, detail="Skill not found")
    share_id = find_share_id_for_object(get_current_username() or "", "skill", sid)
    if not share_id:
        return {"status": "ok", "data": {"share_id": None, "open_path": None}}
    return {"status": "ok", "data": {"share_id": share_id, "open_path": f"/share/run?id={share_id}"}}


@router.post("/settings/skills/{skill_id}/publish-share")
async def publish_skill_share(skill_id: str):
    from app.core.scenario_share_store import upsert_public_share

    sid = str(skill_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="skill_id required")
    base = _get_skills_dir().resolve()
    sdir = (base / sid).resolve()
    if not sdir.is_dir() or sdir.parent != base or not (sdir / "SKILL.md").is_file():
        raise HTTPException(status_code=404, detail="Skill not found")
    mcp_rows = _mcp_rows_for_skill_dir(sdir)
    zip_bytes = _build_skill_zip_bytes(sdir, mcp_rows)
    fm, _body = _read_skill_file(sdir)
    title = str(fm.get("name") or sid)
    share_id = upsert_public_share(
        zip_bytes,
        {
            "object_type": "skill",
            "source_ref": sid,
            "title": title,
            "skill_name": title,
            "created_by": get_current_username() or "",
            "summary": {"skill_count": 1, "mcp_count": len(mcp_rows)},
        },
    )
    return {
        "status": "ok",
        "data": {"share_id": share_id, "open_path": f"/share/run?id={share_id}", "skill_id": sid, "skill_name": title},
    }


def _read_skill_file(skill_dir: Path) -> tuple[Dict, str]:
    """读取 SKILL.md，返回 (frontmatter_dict, body)"""
    path = skill_dir / "SKILL.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Skill not found")
    text = path.read_text(encoding="utf-8")
    if not text.strip().startswith("---"):
        return ({}, text)
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ({}, text)
    fm = _parse_frontmatter_lenient(parts[1])
    return (fm, parts[2].lstrip("\n"))


def _write_skill_file(skill_dir: Path, frontmatter: Dict, body: str):
    """写入 SKILL.md"""
    content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n" + body
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


def _skill_display_name_from_dir(skill_dir: Path, fallback_id: str) -> str:
    try:
        fm, _body = _read_skill_file(skill_dir)
        return str(fm.get("name") or fallback_id).strip() or fallback_id
    except Exception:
        return fallback_id


@router.put("/settings/skills/{skill_id}")
async def update_skill(skill_id: str, skill_update: SkillUpdate):
    """更新 Skill：修改 SKILL.md 的 frontmatter 与/或正文 body"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
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
        runtime_tools = _runtime_tools_only(normalized_tools)
        fm[AUTO_TOOLS_FM_KEY] = runtime_tools
        fm[ALLOWED_TOOLS_FM_KEY] = runtime_tools
        ref_labels = fm.get(REFERENCE_LABELS_FM_KEY) if isinstance(fm.get(REFERENCE_LABELS_FM_KEY), dict) else {}
        ref_labels = dict(ref_labels)
        ref_labels["mcp"] = normalized_tools.get("mcp_refs") or []
        fm[REFERENCE_LABELS_FM_KEY] = ref_labels
    if skill_update.body is not None:
        body = skill_update.body
    _sanitize_skill_frontmatter_for_write(fm)
    _write_skill_file(skill_dir, fm, body)
    new_id = skill_id
    # 若名字变更，自动将目录名对齐到 frontmatter.name（并做冲突避让）
    current_name = str(fm.get("name") or "").strip()
    if current_name:
        desired_seed = _slugify(current_name)
        if desired_seed and desired_seed != skill_id:
            if (base / desired_seed).exists():
                desired_seed = _next_available_skill_id(base, desired_seed)
            target_dir = base / desired_seed
            if target_dir != skill_dir:
                shutil.move(str(skill_dir), str(target_dir))
                skill_dir = target_dir
                new_id = desired_seed
                _replace_skill_id_in_user_configs(skill_id, new_id)
    _refresh_skills_loader()
    return {"status": "ok", "data": {"id": new_id, "updated": True, "renamed": new_id != skill_id, "old_id": skill_id}}

@router.delete("/settings/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """删除 Skill：删除对应目录"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    skill_name = _skill_display_name_from_dir(skill_dir, skill_id)
    shutil.rmtree(skill_dir)
    _remove_skill_id_from_user_configs(skill_id, skill_name)
    _refresh_skills_loader()
    return {"status": "ok", "data": {"id": skill_id, "deleted": True}}

@router.get("/settings/skills/{skill_id}/content")
async def get_skill_content(skill_id: str):
    """获取技能 SKILL.md 的完整内容（raw 全文）及 frontmatter 解析结果，用于详情页展示。"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
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
            "name": fm.get("name", skill_id),
            "description": fm.get("description", ""),
            "body": body,
            "allowed_tools": allowed,
        },
    }


# ========== Skill 辅助目录（references / assets / scripts / other）==========

ALLOWED_PART_TYPES = ("references", "assets", "scripts", "other")


def _list_skill_part_dir(skill_dir: Path, part_type: str) -> List[Dict[str, str]]:
    """列出 skill 下某子目录中的文件，返回 [{name, path}]，path 为相对该子目录的路径。"""
    if part_type not in ALLOWED_PART_TYPES:
        return []
    # other: 列出 skill 根目录下除标准目录与 SKILL.md 外的文件（含子目录）
    if part_type == "other":
        items: List[Dict[str, str]] = []
        exclude = {"references", "assets", "scripts", ".git"}
        for fp in sorted(skill_dir.rglob("*")):
            if fp.is_dir():
                continue
            try:
                rel = fp.relative_to(skill_dir)
            except ValueError:
                continue
            if rel.parts and rel.parts[0] in exclude:
                continue
            if str(rel).replace("\\", "/") == "SKILL.md":
                continue
            items.append({"name": str(rel).replace("\\", "/"), "path": str(rel).replace("\\", "/")})
        return items
    dir_path = skill_dir / part_type
    if not dir_path.is_dir():
        return []
    items = []
    for p in sorted(dir_path.iterdir()):
        if p.is_file():
            items.append({"name": p.name, "path": p.name})
        elif p.is_dir():
            for fp in sorted(p.rglob("*")):
                if fp.is_file():
                    rel = fp.relative_to(dir_path)
                    items.append({"name": str(rel), "path": str(rel).replace("\\", "/")})
    return items


@router.get("/settings/skills/{skill_id}/parts")
async def get_skill_parts(skill_id: str):
    """获取某 skill 目录下 references、assets、scripts 的文件列表。"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    return {
        "status": "ok",
        "data": {
            "references": _list_skill_part_dir(skill_dir, "references"),
            "assets": _list_skill_part_dir(skill_dir, "assets"),
            "scripts": _list_skill_part_dir(skill_dir, "scripts"),
            "other": _list_skill_part_dir(skill_dir, "other"),
        },
    }


@router.get("/settings/skills/{skill_id}/parts/{part_type}/{file_path:path}")
async def get_skill_part_file(skill_id: str, part_type: str, file_path: str):
    """获取某 skill 下 references/assets/scripts 中指定文件的内容。file_path 为相对该子目录的路径，禁止 ..。"""
    if part_type not in ALLOWED_PART_TYPES:
        raise HTTPException(status_code=400, detail="Invalid part type")
    if ".." in file_path or file_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    if part_type == "other":
        full_path = (skill_dir / file_path).resolve()
        base_dir = skill_dir.resolve()
        if not str(full_path).startswith(str(base_dir)):
            raise HTTPException(status_code=400, detail="Invalid file path")
        if full_path.name == "SKILL.md" or full_path.parts and "skills" in full_path.parts and full_path.name == ".git":
            raise HTTPException(status_code=400, detail="Invalid file path")
    else:
        full_path = skill_dir / part_type / file_path
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        content = full_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {e}")
    return {"status": "ok", "data": {"path": file_path, "content": content}}


class PartFileCreate(BaseModel):
    """在 references/assets/scripts 下新建文件"""
    path: str  # 相对该子目录的路径，如 new-doc.md 或 subdir/file.txt
    content: str = ""


class PartFileUpdate(BaseModel):
    """更新 references/assets/scripts 下某文件内容"""
    content: str


class PartDirCreate(BaseModel):
    """在 references/assets/scripts/other 下创建目录"""
    path: str  # 相对该子目录（或 skill 根）的目录路径，如 a 或 subdir/a


@router.post("/settings/skills/{skill_id}/parts/{part_type}")
async def create_skill_part_file(skill_id: str, part_type: str, body: PartFileCreate):
    """在 skill 的 references/assets/scripts 下新建文件。path 为相对该子目录的路径，禁止 ..。"""
    if part_type not in ALLOWED_PART_TYPES:
        raise HTTPException(status_code=400, detail="Invalid part type")
    path = (body.path or "").strip().lstrip("/")
    if ".." in path or not path:
        raise HTTPException(status_code=400, detail="Invalid path")
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    if part_type == "other":
        full_path = (skill_dir / path).resolve()
        base_dir = skill_dir.resolve()
        if not str(full_path).startswith(str(base_dir)):
            raise HTTPException(status_code=400, detail="Path outside skill dir")
        if str(full_path.relative_to(base_dir)).replace("\\", "/") == "SKILL.md":
            raise HTTPException(status_code=400, detail="Cannot create SKILL.md in other")
    else:
        full_path = (skill_dir / part_type / path).resolve()
        part_dir = (skill_dir / part_type).resolve()
        if not str(full_path).startswith(str(part_dir)):
            raise HTTPException(status_code=400, detail="Path outside part dir")
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(body.content or "", encoding="utf-8")
    return {"status": "ok", "data": {"path": path.replace("\\", "/")}}


@router.post("/settings/skills/{skill_id}/parts/{part_type}/mkdir")
async def create_skill_part_dir(skill_id: str, part_type: str, body: PartDirCreate):
    """在 skill 的 references/assets/scripts/other 下新建目录。"""
    if part_type not in ALLOWED_PART_TYPES:
        raise HTTPException(status_code=400, detail="Invalid part type")
    path = (body.path or "").strip().lstrip("/").rstrip("/")
    if ".." in path or not path:
        raise HTTPException(status_code=400, detail="Invalid path")
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    if part_type == "other":
        full_dir = (skill_dir / path).resolve()
        base_dir = skill_dir.resolve()
        if not str(full_dir).startswith(str(base_dir)):
            raise HTTPException(status_code=400, detail="Path outside skill dir")
        if str(full_dir.relative_to(base_dir)).replace("\\", "/") == "SKILL.md":
            raise HTTPException(status_code=400, detail="Cannot create SKILL.md in other")
    else:
        full_dir = (skill_dir / part_type / path).resolve()
        part_dir = (skill_dir / part_type).resolve()
        if not str(full_dir).startswith(str(part_dir)):
            raise HTTPException(status_code=400, detail="Path outside part dir")
    full_dir.mkdir(parents=True, exist_ok=True)
    # 便于前端目录树立即可见：当前列表接口按文件汇总目录，放一个占位文件。
    keep = full_dir / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
    return {"status": "ok", "data": {"path": path.replace("\\", "/"), "created": True}}


@router.put("/settings/skills/{skill_id}/parts/{part_type}/{file_path:path}")
async def update_skill_part_file(skill_id: str, part_type: str, file_path: str, body: PartFileUpdate):
    """更新 skill 下 references/assets/scripts 中指定文件的内容。"""
    if part_type not in ALLOWED_PART_TYPES:
        raise HTTPException(status_code=400, detail="Invalid part type")
    if ".." in file_path or file_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    if part_type == "other":
        full_path = (skill_dir / file_path).resolve()
        base_dir = skill_dir.resolve()
        if not str(full_path).startswith(str(base_dir)):
            raise HTTPException(status_code=400, detail="Invalid file path")
        if str(full_path.relative_to(base_dir)).replace("\\", "/") == "SKILL.md":
            raise HTTPException(status_code=400, detail="Cannot edit SKILL.md via other")
    else:
        full_path = skill_dir / part_type / file_path
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    full_path.write_text(body.content, encoding="utf-8")
    return {"status": "ok", "data": {"path": file_path}}


@router.delete("/settings/skills/{skill_id}/parts/{part_type}/{file_path:path}")
async def delete_skill_part_file(skill_id: str, part_type: str, file_path: str):
    """删除 skill 下 references/assets/scripts 中的指定文件。"""
    if part_type not in ALLOWED_PART_TYPES:
        raise HTTPException(status_code=400, detail="Invalid part type")
    if ".." in file_path or file_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    if part_type == "other":
        full_path = (skill_dir / file_path).resolve()
        base_dir = skill_dir.resolve()
        if not str(full_path).startswith(str(base_dir)):
            raise HTTPException(status_code=400, detail="Invalid file path")
        if str(full_path.relative_to(base_dir)).replace("\\", "/") == "SKILL.md":
            raise HTTPException(status_code=400, detail="Cannot delete SKILL.md via other")
    else:
        full_path = skill_dir / part_type / file_path
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    full_path.unlink()
    return {"status": "ok", "data": {"path": file_path, "deleted": True}}
