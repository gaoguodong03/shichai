"""设置 API - 场景预设与场景导入导出。"""
from __future__ import annotations

import io
import json
import logging
import shutil
from pathlib import Path
from urllib.parse import quote
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.import_contract import reject_legacy_import_strategy_fields
from app.api.request_models import StrictRequestModel
from app.api.settings_mcp import load_mcp_config, save_mcp_config
from app.core.resource_store import mirror_rows_to_resource_dir
from app.core.scenario_bundle import (
    build_scenario_bundle_zip_bytes,
    collect_skill_directories_and_tool_names_for_preset,
    extract_scenario_bundle_dir,
    list_skill_directories_in_bundle_skills_dir,
    read_bundle_manifest_and_lists,
    strip_agent_row_for_disk,
)
from app.core.scene_host import VIRTUAL_SCENE_HOST_ID
from app.core.security import user_context_dependency
from app.core.session_preset_validate import (
    normalize_preset_dict_for_validation,
    validate_session_preset,
    validation_to_api_dict,
)
from app.core.settings_bundle_import import (
    agent_name_conflicts,
    bundle_skill_display_name_map as _bundle_skill_display_name_map,
    collect_mcp_refs_from_skill_dirs,
    find_missing_references_for_scene_bundle as _find_missing_references_for_scene_bundle,
    mcp_rows_for_bundle_refs,
    mcp_name_identity_import_plan as _mcp_name_identity_import_plan,
    mcp_name_map_for_import,
    normalized_name_key,
    prepare_scene_import_by_name_identity,
    remap_frontmatter_mcp_refs,
    skill_directory_identity_import_plan as _skill_directory_identity_import_plan,
    upsert_rows_by_name as _upsert_rows_by_name,
)
from app.core.name_based_resources import normalize_scenario_row
from app.core.user_context import get_current_user_context, get_current_username
from app.core.user_settings_paths import skills_dir_path
from app.mcp.manager import dispose_mcp_runtime_for_user
from app.skills.loader import get_builtin_skills_dir, get_skills_loader_for_user, invalidate_skills_cache_for_user

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])
logger = logging.getLogger(__name__)


def _request_log_meta(request: Optional[Request]) -> Dict[str, str]:
    if request is None:
        return {"client": "", "referer": "", "user_agent": ""}
    client = getattr(request, "client", None)
    return {
        "client": getattr(client, "host", "") or "",
        "referer": str(request.headers.get("referer") or ""),
        "user_agent": str(request.headers.get("user-agent") or ""),
    }


def _preset_names(rows: List[Dict[str, Any]]) -> List[str]:
    return [str(row.get("name") or "").strip() for row in rows if str(row.get("name") or "").strip()]


def _scenario_resource_names() -> List[str]:
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


def _normalize_session_preset_row_for_api(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    try:
        return normalize_scenario_row(item)
    except ValueError:
        return None


def _load_session_preset_rows_from_resource_files() -> List[Dict[str, Any]]:
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
        row = _normalize_session_preset_row_for_api(raw if isinstance(raw, dict) else {})
        if row is not None:
            rows.append(row)
    return rows


def _merge_session_presets_with_resource_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    resource_rows = _load_session_preset_rows_from_resource_files()
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
    merged = [by_name[resource_name] for resource_name in order if resource_name in by_name]
    return merged


@router.get("/settings/session-presets")
async def get_session_presets():
    """读取会话快捷预设（用于前端快捷按钮）。"""
    presets = _merge_session_presets_with_resource_rows([])
    return {"status": "ok", "data": {"presets": presets}}


class SessionPresetItem(StrictRequestModel):
    name: str
    agent_names: List[str]
    description: Optional[str] = ""
    system_prompt: Optional[str] = ""
    host: Optional[Dict[str, Any]] = None


class SessionPresetsBody(StrictRequestModel):
    presets: List[SessionPresetItem]


def _session_preset_item_to_disk_row(item: SessionPresetItem) -> Optional[Dict[str, Any]]:
    """与 update_session_presets 落盘格式一致；无效项返回 None。"""
    name = str(item.name or "").strip()
    agent_names = [str(x).strip() for x in (item.agent_names or []) if str(x).strip()]
    if not name or not agent_names:
        return None
    host_norm: Optional[Dict[str, Any]] = None
    if item.host is not None:
        host_norm = normalize_scenario_row({"name": name, "agent_names": agent_names, "host": item.host}).get("host")
    row: Dict[str, Any] = {
        "name": name,
        "agent_names": agent_names,
        "description": str(item.description or ""),
        "system_prompt": str(item.system_prompt or ""),
    }
    if host_norm is not None:
        row["host"] = host_norm
    return row


def _session_preset_validation_payload(preset: Dict[str, Any]) -> Dict[str, Any]:
    """当前登录用户下校验场景预设依赖。"""
    from app.api.agents import load_agent_instances
    from app.core.user_settings_paths import skills_dir_path

    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise HTTPException(status_code=401, detail="未登录")
    sl = get_skills_loader_for_user(user_ctx.user_id, skills_dir_path())

    def skill_ok(sid: str) -> bool:
        return bool(sl.get_skill_full_content(sid))

    agent_by_name: Dict[str, Any] = {
        str(d.get("name") or "").strip(): d for d in load_agent_instances() if str(d.get("name") or "").strip()
    }
    v = validate_session_preset(
        preset,
        agent_by_name=agent_by_name,
        skill_has_content=skill_ok,
        mcp_servers=load_mcp_config(),
    )
    return validation_to_api_dict(v)


def _dict_to_session_preset_item(row: Dict[str, Any]) -> Optional[SessionPresetItem]:
    try:
        host = row.get("host")
        return SessionPresetItem(
            name=str(row["name"]),
            agent_names=list(row["agent_names"]),
            description=str(row.get("description") or ""),
            system_prompt=str(row.get("system_prompt") or ""),
            host=host if isinstance(host, dict) else None,
        )
    except Exception:
        return None


def _merge_session_presets_into_file(
    normalized_rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """将已规范化的场景行合并写入 resources/scenarios。

    返回 (合并后列表, 本次写入的 preset name 列表, 被同名覆盖的旧 name 列表)。
    """
    existing_rows = _load_session_preset_rows_from_resource_files()
    by_name: Dict[str, Dict[str, Any]] = {str(r["name"]): dict(r) for r in existing_rows if r.get("name")}
    original_names = [str(r["name"]) for r in existing_rows if r.get("name")]
    name_to_existing_names: Dict[str, List[str]] = {}
    for r in existing_rows:
        existing_name = str(r.get("name") or "").strip()
        if not existing_name:
            continue
        nk = normalized_name_key(r.get("name"))
        if not nk:
            continue
        name_to_existing_names.setdefault(nk, []).append(existing_name)

    imported_names: List[str] = []
    overwritten_existing_names: List[str] = []
    overwritten_name_keys: set[str] = set()
    for norm in normalized_rows:
        work = dict(norm)
        incoming_name = str(work.get("name") or "").strip()
        if not incoming_name:
            continue
        same_names = [name for name in name_to_existing_names.get(normalized_name_key(incoming_name), []) if name in by_name]
        if same_names:
            for name in same_names:
                by_name.pop(name, None)
            overwritten_existing_names.extend(same_names)
            overwritten_name_keys.add(normalized_name_key(incoming_name))
        item = _dict_to_session_preset_item(work)
        if item is None:
            continue
        row = _session_preset_item_to_disk_row(item)
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
    _mirror_session_presets_to_resources(merged)
    return merged, imported_names, overwritten_existing_names


def _mirror_session_presets_to_resources(rows: List[Dict[str, Any]]) -> None:
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        mirror_rows_to_resource_dir(
            rows,
            user_ctx.scenarios_dir.resolve(),
            "name",
            body_filename="scenario.json",
        )


@router.put("/settings/session-presets")
async def update_session_presets(body: SessionPresetsBody, request: Request = None):
    """保存会话快捷预设（用于前端快捷按钮）。"""
    before_rows = _load_session_preset_rows_from_resource_files()
    before_names = _preset_names(before_rows)
    resource_names_before = _scenario_resource_names()
    normalized: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for item in body.presets:
        row = _session_preset_item_to_disk_row(item)
        if row is None or row["name"] in seen:
            continue
        seen.add(row["name"])
        normalized.append(row)
    _mirror_session_presets_to_resources(normalized)
    incoming_names = [str(item.name or "").strip() for item in body.presets if str(item.name or "").strip()]
    after_names = _preset_names(normalized)
    meta = _request_log_meta(request)
    user_ctx = get_current_user_context(default_fallback=False)
    logger.info(
        "scenario_presets_put user=%s username=%s client=%s incoming_names=%s before_names=%s after_names=%s removed_names=%s resource_names_before=%s resource_names_after=%s referer=%s user_agent=%s",
        user_ctx.user_id if user_ctx else "",
        user_ctx.username if user_ctx else get_current_username() or "",
        meta["client"],
        incoming_names,
        before_names,
        after_names,
        [name for name in before_names if name not in after_names],
        resource_names_before,
        _scenario_resource_names(),
        meta["referer"],
        meta["user_agent"],
    )
    return {"status": "ok", "data": {"presets": normalized}}


def _get_skills_dir() -> Path:
    """根据当前用户返回 skills 目录。"""
    return skills_dir_path()


async def _invalidate_mcp_runtime_after_config_change():
    """工具资源变更后丢弃内存中的 MCP 连接，下次再懒加载。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        await dispose_mcp_runtime_for_user(user_ctx.user_id)


def _content_disposition_attachment(filename: str) -> str:
    try:
        filename.encode("ascii")
        safe = filename.replace("\\", "\\\\").replace('"', '\\"')
        return f'attachment; filename="{safe}"'
    except Exception:
        fallback = "download.zip"
        return (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )


def _session_preset_bundle_zip_for_preset(preset_name: str) -> Tuple[bytes, Dict[str, Any], str]:
    """构建场景包 ZIP；返回 (zip_bytes, preset_row, safe_name)。"""
    from app.api.agents import load_agent_instances

    key = str(preset_name or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="preset_name required")
    rows = _load_session_preset_rows_from_resource_files()
    match = next((r for r in rows if str(r.get("name") or "").strip() == key), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Session preset not found")

    agent_rows_all = load_agent_instances()
    agent_by_name = {str(d.get("name") or "").strip(): d for d in agent_rows_all if str(d.get("name") or "").strip()}
    expert_rows: List[Dict[str, Any]] = []
    for agent_name in match.get("agent_names") or []:
        a = str(agent_name.get("name") if isinstance(agent_name, dict) else agent_name).strip()
        if a in agent_by_name:
            expert_rows.append(strip_agent_row_for_disk(dict(agent_by_name[a])))

    skill_directories, tool_names = collect_skill_directories_and_tool_names_for_preset(match, agent_by_name)
    mcp_refs = [{"name": mid} for mid in sorted(tool_names)]
    mcp_refs.extend(collect_mcp_refs_from_skill_dirs(_get_skills_dir(), skill_directories))
    mcp_refs.extend(collect_mcp_refs_from_skill_dirs(get_builtin_skills_dir(), skill_directories))
    mcp_all = load_mcp_config()
    mcp_rows = mcp_rows_for_bundle_refs(mcp_refs, mcp_all)

    zip_bytes = build_scenario_bundle_zip_bytes(
        match,
        expert_rows,
        mcp_rows,
        _get_skills_dir(),
        sorted(skill_directories),
    )
    safe_name = key.replace("..", "").replace("/", "").replace("\\", "") or "scenario"
    return zip_bytes, match, safe_name


@router.get("/settings/session-presets/{preset_name}/export-bundle")
async def export_session_preset_bundle(preset_name: str):
    """导出场景资源包 ZIP：bundle.json + resources/ 镜像树。"""
    zip_bytes, _match, safe_name = _session_preset_bundle_zip_for_preset(preset_name)
    filename = f"scenario-bundle-{safe_name}.zip"
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_attachment(filename)},
    )


@router.post("/settings/session-presets/import-bundle")
async def import_session_preset_bundle(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
):
    """导入场景包：合并 Agent、Skill、工具与场景预设。dry_run=true 时返回包内清单、同名覆盖与名称映射预览。"""
    from app.api.agents import load_agent_instances

    fn = (file.filename or "").strip().lower()
    if not fn.endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 ZIP 场景包")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    await reject_legacy_import_strategy_fields(request)

    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        _manifest, preset, agent_bundle, mcp_bundle = read_bundle_manifest_and_lists(tmp)
        norm = normalize_preset_dict_for_validation(preset)
        if norm is None:
            raise HTTPException(status_code=400, detail="场景包内 preset 无效（需 name、agent_names）")

        skill_directories_in_zip = list_skill_directories_in_bundle_skills_dir(tmp)
        skill_display_names = _bundle_skill_display_name_map(tmp, skill_directories_in_zip)
        experts_preview = [
            {"name": str(x.get("name") or "")}
            for x in agent_bundle
            if str(x.get("name") or "").strip()
        ]
        mcps_preview = [
            {"name": str(x.get("name") or "")}
            for x in mcp_bundle
            if str(x.get("name") or "").strip()
        ]

        user_skills = _get_skills_dir()
        skill_directory_map, _skill_copy_pairs, would_overwrite_skills = _skill_directory_identity_import_plan(
            tmp,
            user_skills,
            skill_directories_in_zip,
        )

        existing_presets = _load_session_preset_rows_from_resource_files()
        preset_name_conflicts = [
            str(r.get("name") or "")
            for r in existing_presets
            if normalized_name_key(r.get("name")) == normalized_name_key(norm.get("name"))
            and str(r.get("name") or "").strip()
        ]
        existing_agents = load_agent_instances()
        existing_mcp = load_mcp_config()
        tool_name_map, _mcp_rows_to_import, would_overwrite_mcp = _mcp_name_identity_import_plan(existing_mcp, mcp_bundle)
        expert_conflicts = agent_name_conflicts(existing_agents, agent_bundle)
        missing_references = _find_missing_references_for_scene_bundle(
            norm,
            agent_bundle,
            mcp_bundle,
            tmp,
            user_skills,
            existing_agents,
            existing_mcp,
            extra_skill_roots=(get_builtin_skills_dir(),),
        )

        if dry_run:
            meta = _request_log_meta(request)
            user_ctx = get_current_user_context(default_fallback=False)
            logger.info(
                "scenario_bundle_import_preview user=%s username=%s client=%s preset_name=%s existing_names=%s resource_names=%s name_conflicts=%s skills=%s experts=%s mcps=%s referer=%s",
                user_ctx.user_id if user_ctx else "",
                user_ctx.username if user_ctx else get_current_username() or "",
                meta["client"],
                norm["name"],
                _preset_names(existing_presets),
                _scenario_resource_names(),
                preset_name_conflicts,
                skill_directories_in_zip,
                [row["name"] for row in experts_preview if row.get("name")],
                [row["name"] for row in mcps_preview if row.get("name")],
                meta["referer"],
            )
            return {
                "status": "ok",
                "data": {
                    "dry_run": True,
                    "bundle_preview": {
                        "preset_name": norm["name"],
                        "experts": experts_preview,
                        "skills": skill_directories_in_zip,
                        "skill_display_names": skill_display_names,
                        "mcps": mcps_preview,
                        "would_overwrite_skills": would_overwrite_skills,
                        "would_remap_skills": skill_directory_map,
                        "would_remap_tools": tool_name_map,
                        "would_overwrite_tools": would_overwrite_mcp,
                        "would_overwrite_experts": expert_conflicts,
                        "name_conflict_existing_names": preset_name_conflicts,
                        "missing_references": missing_references,
                    },
                    "note": "确认导入后，数据写入服务器上该账号目录下的配置文件与技能文件夹；同名资源按当前契约覆盖。",
                },
            }

        before_import_names = _preset_names(_load_session_preset_rows_from_resource_files())
        before_import_resource_names = _scenario_resource_names()
        helper_result = await _import_scene_from_bundle_bytes(raw, dry_run=False)
        summary = dict(helper_result.get("summary") or {})
        merged_presets = _load_session_preset_rows_from_resource_files()
        imported_names = list(summary.get("preset_imported_names") or [])
        overwritten_existing_names = list(summary.get("overwritten_existing_names") or [])
        val_after = _session_preset_validation_payload(
            next((row for row in merged_presets if str(row.get("name") or "") in imported_names), norm)
        ) if imported_names else None
        meta = _request_log_meta(request)
        user_ctx = get_current_user_context(default_fallback=False)
        logger.info(
            "scenario_bundle_import_commit user=%s username=%s client=%s preset_name=%s before_names=%s after_names=%s imported_names=%s overwritten_names=%s resource_names_before=%s resource_names_after=%s skills_imported=%s mcp_added=%s mcp_updated=%s referer=%s",
            user_ctx.user_id if user_ctx else "",
            user_ctx.username if user_ctx else get_current_username() or "",
            meta["client"],
            norm["name"],
            before_import_names,
            _preset_names(merged_presets),
            imported_names,
            overwritten_existing_names,
            before_import_resource_names,
            _scenario_resource_names(),
            summary.get("skills_imported") or [],
            summary.get("mcp_added") or 0,
            summary.get("mcp_updated") or 0,
            meta["referer"],
        )

        return {
            "status": "ok",
            "data": {
                "dry_run": False,
                "summary": summary,
                "validation_after": val_after,
                "presets": merged_presets,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e) or "无效的场景包") from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"场景包导入失败：{e}") from e
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)

async def _import_scene_from_bundle_bytes(raw: bytes, *, dry_run: bool) -> Dict[str, Any]:
    from app.api.agents import load_agent_instances, save_agent_instances
    from app.api.settings_skills import (
        _merge_imported_skill_requirements_and_prewarm,
        _read_skill_file,
        _sanitize_skill_frontmatter_for_write,
        _write_skill_file,
    )

    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        _manifest, preset, agent_bundle, mcp_bundle = read_bundle_manifest_and_lists(tmp)
        norm = normalize_preset_dict_for_validation(preset)
        if norm is None:
            raise HTTPException(status_code=400, detail="场景分享包无效")
        skill_directories_in_zip = list_skill_directories_in_bundle_skills_dir(tmp)
        skill_display_names = _bundle_skill_display_name_map(tmp, skill_directories_in_zip)
        user_skills = _get_skills_dir()
        skill_directory_map, _skill_copy_pairs, overwritten_skill_directories = _skill_directory_identity_import_plan(
            tmp,
            user_skills,
            skill_directories_in_zip,
        )
        tool_name_map, _mcp_rows_to_import, overwritten_tool_names = _mcp_name_identity_import_plan(load_mcp_config(), mcp_bundle)
        existing_presets = _load_session_preset_rows_from_resource_files()
        preset_name_conflicts = [
            str(r.get("name") or "")
            for r in existing_presets
            if normalized_name_key(r.get("name")) == normalized_name_key(norm.get("name"))
            and str(r.get("name") or "").strip()
        ]
        existing_experts = load_agent_instances()
        expert_conflicts = agent_name_conflicts(existing_experts, agent_bundle)
        missing_references = _find_missing_references_for_scene_bundle(
            norm,
            agent_bundle,
            mcp_bundle,
            tmp,
            user_skills,
            load_agent_instances(),
            load_mcp_config(),
            extra_skill_roots=(get_builtin_skills_dir(),),
        )
        if dry_run:
            return {
                "object_type": "scene",
                "preview": {
                    "preset_name": norm["name"],
                    "experts": [
                        {"name": str(x.get("name") or "")}
                        for x in agent_bundle
                        if str(x.get("name") or "").strip()
                    ],
                    "skills": skill_directories_in_zip,
                    "skill_display_names": skill_display_names,
                    "mcps": [{"name": str(x.get("name") or "")} for x in mcp_bundle],
                    "name_conflict_existing_names": preset_name_conflicts,
                    "would_overwrite_skills": overwritten_skill_directories,
                    "would_remap_skills": skill_directory_map,
                    "would_remap_tools": tool_name_map,
                    "would_overwrite_tools": overwritten_tool_names,
                    "would_overwrite_experts": expert_conflicts,
                    "missing_references": missing_references,
                },
            }
        (
            norm,
            agent_rows_to_import,
            mcp_rows_to_import,
            skill_directory_map,
            tool_name_map,
            agent_name_map,
            imported_skills,
            overwritten_agent_names,
            overwritten_skills,
        ) = prepare_scene_import_by_name_identity(
            norm,
            agent_bundle,
            mcp_bundle,
            tmp,
            user_skills,
            load_agent_instances(),
            load_mcp_config(),
        )
        norm = normalize_preset_dict_for_validation(norm)
        if norm is None:
            raise HTTPException(status_code=400, detail="场景分享包无效")
        user_ctx = get_current_user_context(default_fallback=False)
        if user_ctx is not None:
            invalidate_skills_cache_for_user(user_ctx.user_id)
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
        merged_agents = _upsert_rows_by_name(load_agent_instances(), agent_rows_to_import, "name")
        save_agent_instances(merged_agents)
        mcp_before = load_mcp_config()
        existing_mcp_names = {str(row.get("name") or "").strip() for row in mcp_before}
        imported_mcp_names = {str(row.get("name") or "").strip() for row in mcp_rows_to_import}
        merged_mcp = _upsert_rows_by_name(mcp_before, mcp_rows_to_import, "name")
        mcp_added = len([name for name in imported_mcp_names if name and name not in existing_mcp_names])
        mcp_updated = len([name for name in imported_mcp_names if name and name in existing_mcp_names])
        save_mcp_config(merged_mcp)
        await _invalidate_mcp_runtime_after_config_change()
        requirements_result = await _merge_imported_skill_requirements_and_prewarm(imported_skills, user_skills)
        _merged_presets, imported_names, overwritten_existing_names = _merge_session_presets_into_file([norm])
        return {
            "object_type": "scene",
            "summary": {
                "preset_imported_names": imported_names,
                "overwritten_existing_names": overwritten_existing_names,
                "skills_imported": imported_skills,
                "skills_overwritten": overwritten_skills,
                "agent_imported_names": [
                    str(row.get("name") or "").strip()
                    for row in agent_rows_to_import
                    if str(row.get("name") or "").strip()
                ],
                "overwritten_agent_names": overwritten_agent_names,
                "skill_map": skill_directory_map,
                "tool_map": tool_name_map,
                "agent_map": agent_name_map,
                "missing_references": missing_references,
                **requirements_result,
                "mcp_added": mcp_added,
                "mcp_updated": mcp_updated,
            },
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
