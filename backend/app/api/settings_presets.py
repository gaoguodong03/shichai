"""设置 API - 场景预设与场景导入导出。"""
from __future__ import annotations

import io
import json
import logging
import shutil
import uuid
from pathlib import Path
from urllib.parse import quote
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.settings_mcp import load_mcp_config, save_mcp_config
from app.core.host_config import normalize_host_config_dict
from app.core.resource_store import mirror_rows_to_resource_dir
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
from app.core.scene_host import VIRTUAL_SCENE_HOST_ID
from app.core.security import user_context_dependency
from app.core.session_preset_validate import (
    normalize_preset_dict_for_validation,
    validate_session_preset,
    validation_to_api_dict,
)
from app.core.settings_bundle_import import (
    collect_mcp_refs_from_skill_dirs,
    copy_bundle_skills_to_user_by_name as _copy_bundle_skills_to_user_by_name,
    find_missing_references_for_scene_bundle as _find_missing_references_for_scene_bundle,
    mcp_rows_for_bundle_refs,
    mcp_conflict_id_map as _mcp_conflict_id_map,
    skill_conflict_id_map as _skill_conflict_id_map,
)
from app.core.settings_references import (
    merge_reference_rows_for_ids as _merge_reference_rows_for_ids,
    normalize_reference_rows as _normalize_reference_rows,
    remap_bundle_references as _remap_bundle_references,
    replace_mcp_server_id_in_user_configs as _replace_mcp_server_id_in_user_configs,
)
from app.core.user_context import get_current_user_context, get_current_username
from app.core.user_settings_paths import session_presets_path, skills_dir_path
from app.mcp.manager import dispose_mcp_runtime_for_user
from app.skills.loader import get_builtin_skills_dir, get_skills_loader_for_user, invalidate_skills_cache_for_user

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])
logger = logging.getLogger(__name__)


def _get_session_presets_path() -> Path:
    """根据当前用户返回 session_presets.json 路径。"""
    return session_presets_path()


def _request_log_meta(request: Optional[Request]) -> Dict[str, str]:
    if request is None:
        return {"client": "", "referer": "", "user_agent": ""}
    client = getattr(request, "client", None)
    return {
        "client": getattr(client, "host", "") or "",
        "referer": str(request.headers.get("referer") or ""),
        "user_agent": str(request.headers.get("user-agent") or ""),
    }


def _preset_ids(rows: List[Dict[str, Any]]) -> List[str]:
    return [str(row.get("id") or "").strip() for row in rows if str(row.get("id") or "").strip()]


def _scenario_resource_ids() -> List[str]:
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return []
    root = user_ctx.scenarios_dir.resolve()
    if not root.is_dir():
        return []
    ids: List[str] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if child.is_dir() and (child / "scenario.json").is_file():
            ids.append(child.name)
    return ids


def _normalize_session_preset_row_for_api(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    pid = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    agent_ids = item.get("agent_ids")
    if not isinstance(agent_ids, list) or not agent_ids:
        agent_ids = item.get("expert_ids")
    if not isinstance(agent_ids, list):
        agent_ids = []
    normalized_ids = [str(x).strip() for x in agent_ids if str(x).strip()]
    if not pid or not name or not normalized_ids:
        return None
    hc_raw = item.get("host_config")
    lid = str(item.get("leader_agent_id") or "").strip()
    if isinstance(hc_raw, dict):
        lid = VIRTUAL_SCENE_HOST_ID
    elif not lid:
        lid = normalized_ids[0]
    row_out: Dict[str, Any] = {
        "id": pid,
        "name": name,
        "agent_ids": normalized_ids,
        "leader_agent_id": lid,
        "description": str(item.get("description") or ""),
        "discussion_goal_example": str(item.get("discussion_goal_example") or ""),
    }
    agent_refs = _normalize_reference_rows(item.get("agent_refs"))
    if agent_refs:
        row_out["agent_refs"] = _merge_reference_rows_for_ids(normalized_ids, agent_refs)
    if isinstance(hc_raw, dict):
        row_out["host_config"] = normalize_host_config_dict(hc_raw)
    return row_out


def _load_session_preset_rows_from_file(path: Path) -> List[Dict[str, Any]]:
    """解析磁盘 session_presets.json 为与 GET session-presets 一致的行列表。"""
    presets: List[Dict[str, Any]] = []
    if not path.exists():
        return presets
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            for item in raw:
                row_out = _normalize_session_preset_row_for_api(item)
                if row_out is not None:
                    presets.append(row_out)
    except Exception:
        return []
    return presets


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
        return rows
    by_id: Dict[str, Dict[str, Any]] = {str(row.get("id") or ""): dict(row) for row in rows if row.get("id")}
    order = [str(row.get("id") or "") for row in rows if row.get("id")]
    changed = False
    for row in resource_rows:
        rid = str(row.get("id") or "").strip()
        if not rid:
            continue
        if rid not in by_id:
            order.append(rid)
            changed = True
        elif by_id[rid] != row:
            changed = True
        by_id[rid] = row
    merged = [by_id[rid] for rid in order if rid in by_id]
    if changed:
        path = _get_session_presets_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        _mirror_session_presets_to_resources(merged)
    return merged


@router.get("/settings/session-presets")
async def get_session_presets(request: Request = None):
    """读取会话快捷预设（用于前端快捷按钮），兼容历史字段 expert_ids。"""
    path = _get_session_presets_path()
    presets = _load_session_preset_rows_from_file(path)
    before_ids = _preset_ids(presets)
    resource_ids = _scenario_resource_ids()
    presets = _merge_session_presets_with_resource_rows(presets)
    after_ids = _preset_ids(presets)
    meta = _request_log_meta(request)
    user_ctx = get_current_user_context(default_fallback=False)
    logger.info(
        "scenario_presets_get user=%s username=%s client=%s aggregate_ids=%s resource_ids=%s returned_ids=%s recovered=%s referer=%s",
        user_ctx.user_id if user_ctx else "",
        user_ctx.username if user_ctx else get_current_username() or "",
        meta["client"],
        before_ids,
        resource_ids,
        after_ids,
        [rid for rid in after_ids if rid not in before_ids],
        meta["referer"],
    )
    return {"status": "ok", "data": {"presets": presets}}


class SessionPresetItem(BaseModel):
    id: str
    name: str
    agent_ids: List[str]
    agent_refs: Optional[List[Dict[str, Any]]] = None
    description: Optional[str] = ""
    discussion_goal_example: Optional[str] = ""
    leader_agent_id: Optional[str] = ""
    host_config: Optional[Dict[str, Any]] = None


class SessionPresetsBody(BaseModel):
    presets: List[SessionPresetItem]


def _session_preset_item_to_disk_row(item: SessionPresetItem) -> Optional[Dict[str, Any]]:
    """与 update_session_presets 落盘格式一致；无效项返回 None。"""
    from app.api.dha import load_dha_instances

    pid = str(item.id or "").strip()
    name = str(item.name or "").strip()
    agent_ids = [str(x).strip() for x in (item.agent_ids or []) if str(x).strip()]
    if not pid or not name or not agent_ids:
        return None
    hc_norm: Optional[Dict[str, Any]] = None
    try:
        dha_name_by_id = {
            str(d.get("agent_id")).strip(): str(d.get("name") or "").strip()
            for d in load_dha_instances()
            if d.get("agent_id")
        }
        valid_dha_ids = set(dha_name_by_id)
    except RuntimeError:
        dha_name_by_id = {}
        valid_dha_ids = set()
    if item.host_config is not None:
        hc_norm = normalize_host_config_dict(item.host_config)
        lid = VIRTUAL_SCENE_HOST_ID
    else:
        lid = str(item.leader_agent_id or "").strip() if item.leader_agent_id is not None else ""
        if not lid:
            lid = agent_ids[0]
        elif lid not in valid_dha_ids and lid != VIRTUAL_SCENE_HOST_ID:
            lid = agent_ids[0]
    row: Dict[str, Any] = {
        "id": pid,
        "name": name,
        "agent_ids": agent_ids,
        "expert_ids": agent_ids,
        "leader_agent_id": lid,
        "description": str(item.description or ""),
        "discussion_goal_example": str(item.discussion_goal_example or ""),
    }
    row["agent_refs"] = _merge_reference_rows_for_ids(agent_ids, item.agent_refs, dha_name_by_id)
    if hc_norm is not None:
        row["host_config"] = hc_norm
    return row


def _session_preset_validation_payload(preset: Dict[str, Any]) -> Dict[str, Any]:
    """当前登录用户下校验场景预设依赖。"""
    from app.api.dha import load_dha_instances
    from app.core.user_settings_paths import skills_dir_path

    un = get_current_username() or ""
    sl = get_skills_loader_for_user(un, skills_dir_path())

    def skill_ok(sid: str) -> bool:
        return bool(sl.get_skill_full_content(sid))

    dha_by_id: Dict[str, Any] = {
        str(d.get("agent_id")): d for d in load_dha_instances() if d.get("agent_id")
    }
    v = validate_session_preset(
        preset,
        dha_by_id=dha_by_id,
        skill_has_content=skill_ok,
        mcp_servers=load_mcp_config(),
    )
    return validation_to_api_dict(v)


def _dict_to_session_preset_item(row: Dict[str, Any]) -> Optional[SessionPresetItem]:
    try:
        hc = row.get("host_config")
        return SessionPresetItem(
            id=str(row["id"]),
            name=str(row["name"]),
            agent_ids=list(row["agent_ids"]),
            agent_refs=list(row.get("agent_refs") or []),
            description=str(row.get("description") or ""),
            discussion_goal_example=str(row.get("discussion_goal_example") or ""),
            leader_agent_id=str(row.get("leader_agent_id") or ""),
            host_config=hc if isinstance(hc, dict) else None,
        )
    except Exception:
        return None


def _normalized_name_key(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _merge_session_presets_into_file(
    normalized_rows: List[Dict[str, Any]], id_conflict: str
) -> Tuple[List[Dict[str, Any]], List[str], List[str], List[str]]:
    """将已规范化的场景行合并写入 session_presets.json。

    返回 (合并后列表, 本次写入的 preset id 列表, 因同名跳过的名称, 被覆盖的旧 preset id 列表)。
    """
    path = _get_session_presets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_rows = _load_session_preset_rows_from_file(path)
    by_id: Dict[str, Dict[str, Any]] = {str(r["id"]): dict(r) for r in existing_rows if r.get("id")}
    original_ids = [str(r["id"]) for r in existing_rows if r.get("id")]
    name_to_existing_ids: Dict[str, List[str]] = {}
    for r in existing_rows:
        rid = str(r.get("id") or "").strip()
        if not rid:
            continue
        nk = _normalized_name_key(r.get("name"))
        if not nk:
            continue
        name_to_existing_ids.setdefault(nk, []).append(rid)

    imported_ids: List[str] = []
    skipped_by_name: List[str] = []
    overwritten_existing_ids: List[str] = []
    for norm in normalized_rows:
        work = dict(norm)
        incoming_name = str(work.get("name") or "").strip()
        same_name_ids = [rid for rid in name_to_existing_ids.get(_normalized_name_key(incoming_name), []) if rid in by_id]
        if same_name_ids:
            if id_conflict == "skip":
                skipped_by_name.append(incoming_name or str(work.get("id") or ""))
                continue
            for rid in same_name_ids:
                by_id.pop(rid, None)
            overwritten_existing_ids.extend(same_name_ids)
        item = _dict_to_session_preset_item(work)
        if item is None:
            continue
        row = _session_preset_item_to_disk_row(item)
        if row is None:
            continue
        if row["id"] in by_id:
            row["id"] = f"scenario-{uuid.uuid4().hex[:10]}"
            while row["id"] in by_id:
                row["id"] = f"scenario-{uuid.uuid4().hex[:10]}"
        by_id[row["id"]] = row
        imported_ids.append(row["id"])

    merged: List[Dict[str, Any]] = []
    for rid in original_ids:
        if rid in by_id:
            merged.append(by_id[rid])
    used = set(original_ids)
    for rid, row in by_id.items():
        if rid not in used:
            merged.append(row)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    _mirror_session_presets_to_resources(merged)
    return merged, imported_ids, skipped_by_name, overwritten_existing_ids


def _mirror_session_presets_to_resources(rows: List[Dict[str, Any]]) -> None:
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        mirror_rows_to_resource_dir(
            rows,
            user_ctx.scenarios_dir.resolve(),
            "id",
            body_filename="scenario.json",
        )


@router.put("/settings/session-presets")
async def update_session_presets(body: SessionPresetsBody, request: Request = None):
    """保存会话快捷预设（用于前端快捷按钮）。"""
    path = _get_session_presets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    before_rows = _load_session_preset_rows_from_file(path)
    before_ids = _preset_ids(before_rows)
    resource_ids_before = _scenario_resource_ids()
    normalized: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for item in body.presets:
        row = _session_preset_item_to_disk_row(item)
        if row is None or row["id"] in seen:
            continue
        seen.add(row["id"])
        normalized.append(row)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    _mirror_session_presets_to_resources(normalized)
    incoming_ids = [str(item.id or "").strip() for item in body.presets if str(item.id or "").strip()]
    after_ids = _preset_ids(normalized)
    meta = _request_log_meta(request)
    user_ctx = get_current_user_context(default_fallback=False)
    logger.info(
        "scenario_presets_put user=%s username=%s client=%s incoming_ids=%s before_ids=%s after_ids=%s removed_ids=%s resource_ids_before=%s resource_ids_after=%s referer=%s user_agent=%s",
        user_ctx.user_id if user_ctx else "",
        user_ctx.username if user_ctx else get_current_username() or "",
        meta["client"],
        incoming_ids,
        before_ids,
        after_ids,
        [rid for rid in before_ids if rid not in after_ids],
        resource_ids_before,
        _scenario_resource_ids(),
        meta["referer"],
        meta["user_agent"],
    )
    return {"status": "ok", "data": {"presets": normalized}}


def _get_skills_dir() -> Path:
    """根据当前用户返回 skills 目录。"""
    return skills_dir_path()


async def _invalidate_mcp_runtime_after_config_change():
    """磁盘上的 mcp_servers.json 变更后丢弃内存中的连接，下次再懒加载。"""
    un = get_current_username()
    if un:
        await dispose_mcp_runtime_for_user(un)


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


def _session_preset_bundle_zip_for_preset(preset_id: str) -> Tuple[bytes, Dict[str, Any], str]:
    """构建场景包 ZIP；返回 (zip_bytes, preset_row, safe_name)。"""
    from app.api.dha import load_dha_instances

    key = str(preset_id or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="preset_id required")
    path = _get_session_presets_path()
    rows = _load_session_preset_rows_from_file(path)
    match = next((r for r in rows if r.get("id") == key), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Session preset not found")

    dha_all = load_dha_instances()
    dha_by_id = {str(d.get("agent_id")): d for d in dha_all if d.get("agent_id")}
    expert_rows: List[Dict[str, Any]] = []
    for aid in match.get("agent_ids") or []:
        a = str(aid).strip()
        if a in dha_by_id:
            expert_rows.append(strip_dha_row_for_disk(dict(dha_by_id[a])))

    skill_ids, mcp_ids = collect_skill_and_mcp_ids_for_preset(match, dha_by_id)
    mcp_refs = [{"id": mid, "name": ""} for mid in sorted(mcp_ids)]
    mcp_refs.extend(collect_mcp_refs_from_skill_dirs(_get_skills_dir(), skill_ids))
    mcp_refs.extend(collect_mcp_refs_from_skill_dirs(get_builtin_skills_dir(), skill_ids))
    mcp_all = load_mcp_config()
    mcp_rows = mcp_rows_for_bundle_refs(mcp_refs, mcp_all)

    zip_bytes = build_scenario_bundle_zip_bytes(
        match,
        expert_rows,
        mcp_rows,
        _get_skills_dir(),
        sorted(skill_ids),
    )
    safe_name = key.replace("..", "").replace("/", "").replace("\\", "") or "scenario"
    return zip_bytes, match, safe_name


@router.get("/settings/session-presets/{preset_id}/export-bundle")
async def export_session_preset_bundle(preset_id: str):
    """导出场景包 ZIP：含 scenario_bundle.json、dha_instances.json、skills/、可选 mcp_servers.json。"""
    zip_bytes, _match, safe_name = _session_preset_bundle_zip_for_preset(preset_id)
    filename = f"scenario-bundle-{safe_name}.zip"
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_attachment(filename)},
    )


@router.get("/settings/session-presets/{preset_id}/share-link")
async def get_session_preset_share_link(preset_id: str):
    """若当前用户已发布过该场景，返回固定 share_id 与路径（未发布则 share_id 为 null）。"""
    from app.core.scenario_share_store import find_share_id_for_object

    key = str(preset_id or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="preset_id required")
    path = _get_session_presets_path()
    rows = _load_session_preset_rows_from_file(path)
    if not next((r for r in rows if r.get("id") == key), None):
        raise HTTPException(status_code=404, detail="Session preset not found")
    uid = get_current_username() or ""
    sid = find_share_id_for_object(uid, "scene", key)
    if not sid:
        return {"status": "ok", "data": {"share_id": None, "open_path": None}}
    return {
        "status": "ok",
        "data": {
            "share_id": sid,
            "open_path": f"/share/run?id={sid}",
        },
    }


@router.post("/settings/session-presets/{preset_id}/publish-share")
async def publish_session_preset_share(preset_id: str):
    """将场景包发布到服务器公开目录；同一账号下同一场景 id 复用同一分享编号（链接固定）。"""
    from app.core.scenario_share_store import upsert_public_share

    zip_bytes, match, _safe = _session_preset_bundle_zip_for_preset(preset_id)
    share_id = upsert_public_share(
        zip_bytes,
        {
            "object_type": "scene",
            "source_ref": str(match.get("id") or ""),
            "title": str(match.get("name") or ""),
            "summary": {
                "agent_count": len(match.get("agent_ids") or []),
            },
            "preset_name": str(match.get("name") or ""),
            "source_preset_id": str(match.get("id") or ""),
            "created_by": get_current_username() or "",
        },
    )
    return {
        "status": "ok",
        "data": {
            "share_id": share_id,
            "open_path": f"/share/run?id={share_id}",
            "preset_name": str(match.get("name") or ""),
        },
    }


@router.post("/settings/session-presets/import-bundle")
async def import_session_preset_bundle(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    overwrite_experts: bool = Form(True),
    overwrite_skills: bool = Form(True),
    # False=用包内覆盖本地同名 MCP（与前端「同名工具覆盖本地工具配置」勾选一致）；True=保留本地同名，仅追加缺失 id
    mcp_skip_existing: bool = Form(False),
    preset_id_conflict: str = Form("overwrite"),
):
    """导入场景包：合并专家、技能、MCP 与场景预设。dry_run=true 时仅返回包内清单与将覆盖的技能提示。"""
    from app.api.dha import load_dha_instances, save_dha_instances
    from app.api.settings import _merge_imported_skill_requirements_and_prewarm

    fn = (file.filename or "").strip().lower()
    if not fn.endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 ZIP 场景包")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")

    conflict = str(preset_id_conflict or "overwrite").strip().lower()
    if conflict not in ("overwrite", "skip"):
        logging.getLogger(__name__).warning("unknown preset_id_conflict=%s, fallback to overwrite", conflict)
        conflict = "overwrite"

    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        _manifest, preset, dha_bundle, mcp_bundle = read_bundle_manifest_and_lists(tmp)
        norm = normalize_preset_dict_for_validation(preset)
        if norm is None:
            raise HTTPException(status_code=400, detail="场景包内 preset 无效（需 id、name、agent_ids）")

        skill_ids_in_zip = list_skill_ids_in_bundle_skills_dir(tmp)
        experts_preview = [
            {"agent_id": str(x.get("agent_id") or ""), "name": str(x.get("name") or "")}
            for x in dha_bundle
            if str(x.get("agent_id") or "").strip()
        ]
        mcps_preview = [
            {"id": str(x.get("id") or ""), "name": str(x.get("name") or "")}
            for x in mcp_bundle
            if str(x.get("id") or "").strip()
        ]

        user_skills = _get_skills_dir()
        would_overwrite_skills: List[str] = []
        would_skip_skills: List[str] = []
        for sid in skill_ids_in_zip:
            dest = user_skills / sid
            if dest.is_dir():
                if overwrite_skills:
                    would_overwrite_skills.append(sid)
                else:
                    would_skip_skills.append(sid)

        existing_presets = _load_session_preset_rows_from_file(_get_session_presets_path())
        preset_name_conflicts = [
            str(r.get("id") or "")
            for r in existing_presets
            if _normalized_name_key(r.get("name")) == _normalized_name_key(norm.get("name"))
            and str(r.get("id") or "").strip()
        ]
        existing_dha = load_dha_instances()
        existing_mcp = load_mcp_config()
        missing_references = _find_missing_references_for_scene_bundle(
            norm,
            dha_bundle,
            mcp_bundle,
            tmp,
            user_skills,
            existing_dha,
            existing_mcp,
            extra_skill_roots=(get_builtin_skills_dir(),),
        )

        if dry_run:
            meta = _request_log_meta(request)
            user_ctx = get_current_user_context(default_fallback=False)
            logger.info(
                "scenario_bundle_import_preview user=%s username=%s client=%s preset_id=%s preset_name=%s existing_ids=%s resource_ids=%s name_conflict_ids=%s skill_ids=%s expert_ids=%s mcp_ids=%s referer=%s",
                user_ctx.user_id if user_ctx else "",
                user_ctx.username if user_ctx else get_current_username() or "",
                meta["client"],
                norm["id"],
                norm["name"],
                _preset_ids(existing_presets),
                _scenario_resource_ids(),
                preset_name_conflicts,
                skill_ids_in_zip,
                [row["agent_id"] for row in experts_preview if row.get("agent_id")],
                [row["id"] for row in mcps_preview if row.get("id")],
                meta["referer"],
            )
            return {
                "status": "ok",
                "data": {
                    "dry_run": True,
                    "bundle_preview": {
                        "preset_id": norm["id"],
                        "preset_name": norm["name"],
                        "experts": experts_preview,
                        "skills": skill_ids_in_zip,
                        "mcps": mcps_preview,
                        "would_overwrite_skills": would_overwrite_skills,
                        "would_skip_skills": would_skip_skills,
                        "name_conflict_existing_ids": preset_name_conflicts,
                        "name_conflict_mode": conflict,
                        "missing_references": missing_references,
                    },
                    "note": "确认导入后，数据写入服务器上该账号目录下的配置文件与技能文件夹。界面无法修改专家 agent_id；若需改 id，请在服务端编辑 dha_instances.json。",
                },
            }

        imported_skills, skipped_skills = copy_bundle_skills_to_user(
            tmp, user_skills, overwrite=overwrite_skills
        )
        invalidate_skills_cache_for_user(get_current_username() or "")
        requirements_result = await _merge_imported_skill_requirements_and_prewarm(imported_skills, user_skills)

        merged_dha = merge_dha_instances_for_bundle(
            existing_dha, dha_bundle, overwrite=overwrite_experts
        )
        save_dha_instances(merged_dha)

        merged_mcp, mcp_added, mcp_skipped, mcp_updated = merge_mcp_servers_for_bundle(
            existing_mcp, mcp_bundle, skip_existing=mcp_skip_existing
        )
        save_mcp_config(merged_mcp)
        await _invalidate_mcp_runtime_after_config_change()

        before_import_ids = _preset_ids(_load_session_preset_rows_from_file(_get_session_presets_path()))
        before_import_resource_ids = _scenario_resource_ids()
        merged_presets, imported_ids, skipped_by_name, overwritten_existing_ids = _merge_session_presets_into_file([norm], conflict)
        val_after = _session_preset_validation_payload(norm)
        meta = _request_log_meta(request)
        user_ctx = get_current_user_context(default_fallback=False)
        logger.info(
            "scenario_bundle_import_commit user=%s username=%s client=%s preset_id=%s preset_name=%s before_ids=%s after_ids=%s imported_ids=%s overwritten_ids=%s skipped_by_name=%s resource_ids_before=%s resource_ids_after=%s skills_imported=%s skills_skipped=%s mcp_added=%s mcp_updated=%s mcp_skipped=%s referer=%s",
            user_ctx.user_id if user_ctx else "",
            user_ctx.username if user_ctx else get_current_username() or "",
            meta["client"],
            norm["id"],
            norm["name"],
            before_import_ids,
            _preset_ids(merged_presets),
            imported_ids,
            overwritten_existing_ids,
            skipped_by_name,
            before_import_resource_ids,
            _scenario_resource_ids(),
            imported_skills,
            skipped_skills,
            mcp_added,
            mcp_updated,
            mcp_skipped,
            meta["referer"],
        )

        return {
            "status": "ok",
            "data": {
                "dry_run": False,
                "summary": {
                    "preset_imported_ids": imported_ids,
                    "skipped_by_name": skipped_by_name,
                    "overwritten_existing_ids": overwritten_existing_ids,
                    "skills_imported": imported_skills,
                    "skills_skipped": skipped_skills,
                    "missing_references": missing_references,
                    **requirements_result,
                    "experts_total_after": len(merged_dha),
                    "mcp_added": mcp_added,
                    "mcp_skipped": mcp_skipped,
                    "mcp_updated": mcp_updated,
                },
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
    from app.api.dha import load_dha_instances, save_dha_instances
    from app.api.settings import _merge_imported_skill_requirements_and_prewarm

    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        _manifest, preset, dha_bundle, mcp_bundle = read_bundle_manifest_and_lists(tmp)
        norm = normalize_preset_dict_for_validation(preset)
        if norm is None:
            raise HTTPException(status_code=400, detail="场景分享包无效")
        skill_ids_in_zip = list_skill_ids_in_bundle_skills_dir(tmp)
        user_skills = _get_skills_dir()
        skill_id_map = _skill_conflict_id_map(tmp, user_skills, skill_ids_in_zip)
        mcp_id_map = _mcp_conflict_id_map(load_mcp_config(), mcp_bundle)
        remapped_preset, remapped_dha_bundle = _remap_bundle_references(
            norm,
            dha_bundle,
            skill_id_map=skill_id_map,
            mcp_id_map=mcp_id_map,
        )
        norm = normalize_preset_dict_for_validation(remapped_preset)
        if norm is None:
            raise HTTPException(status_code=400, detail="场景分享包无效")
        dha_bundle = remapped_dha_bundle
        existing_presets = _load_session_preset_rows_from_file(_get_session_presets_path())
        preset_name_conflicts = [
            str(r.get("id") or "")
            for r in existing_presets
            if _normalized_name_key(r.get("name")) == _normalized_name_key(norm.get("name"))
            and str(r.get("id") or "").strip()
        ]
        existing_experts = load_dha_instances()
        expert_conflicts: Dict[str, List[str]] = {}
        for incoming in dha_bundle:
            incoming_id = str(incoming.get("agent_id") or "").strip()
            incoming_name_key = _normalized_name_key(incoming.get("name"))
            conflicts = [
                str(old.get("agent_id") or "")
                for old in existing_experts
                if str(old.get("agent_id") or "").strip()
                and (
                    str(old.get("agent_id") or "").strip() == incoming_id
                    or (incoming_name_key and _normalized_name_key(old.get("name")) == incoming_name_key)
                )
            ]
            if conflicts:
                expert_conflicts[incoming_id or str(incoming.get("name") or "")] = list(dict.fromkeys(conflicts))
        missing_references = _find_missing_references_for_scene_bundle(
            norm,
            dha_bundle,
            mcp_bundle,
            tmp,
            user_skills,
            load_dha_instances(),
            load_mcp_config(),
            extra_skill_roots=(get_builtin_skills_dir(),),
        )
        if dry_run:
            return {
                "object_type": "scene",
                "preview": {
                    "preset_id": norm["id"],
                    "preset_name": norm["name"],
                    "experts": [
                        {"agent_id": str(x.get("agent_id") or ""), "name": str(x.get("name") or "")}
                        for x in dha_bundle
                        if str(x.get("agent_id") or "").strip()
                    ],
                    "skills": skill_ids_in_zip,
                    "mcps": [{"id": str(x.get("id") or ""), "name": str(x.get("name") or "")} for x in mcp_bundle],
                    "name_conflict_existing_ids": preset_name_conflicts,
                    "would_overwrite_skills": sorted(skill_id_map.keys()),
                    "would_remap_skill_ids": skill_id_map,
                    "would_remap_mcp_server_ids": mcp_id_map,
                    "would_overwrite_experts": expert_conflicts,
                    "missing_references": missing_references,
                },
            }
        imported_skills, overwritten_skills, skill_id_map = _copy_bundle_skills_to_user_by_name(tmp, user_skills)
        invalidate_skills_cache_for_user(get_current_username() or "")
        for old_id, new_id in mcp_id_map.items():
            _replace_mcp_server_id_in_user_configs(old_id, new_id)
        merged_dha = merge_dha_instances_for_bundle(load_dha_instances(), dha_bundle, overwrite=True)
        save_dha_instances(merged_dha)
        merged_mcp, mcp_added, mcp_skipped, mcp_updated = merge_mcp_servers_for_bundle(
            load_mcp_config(), mcp_bundle, skip_existing=False
        )
        save_mcp_config(merged_mcp)
        await _invalidate_mcp_runtime_after_config_change()
        requirements_result = await _merge_imported_skill_requirements_and_prewarm(imported_skills, user_skills)
        _merged_presets, imported_ids, skipped_by_name, overwritten_existing_ids = _merge_session_presets_into_file(
            [norm], "overwrite"
        )
        return {
            "object_type": "scene",
            "summary": {
                "preset_imported_ids": imported_ids,
                "skipped_by_name": skipped_by_name,
                "overwritten_existing_ids": overwritten_existing_ids,
                "skills_imported": imported_skills,
                "skills_overwritten": overwritten_skills,
                "skill_id_map": skill_id_map,
                "mcp_id_map": mcp_id_map,
                "missing_references": missing_references,
                **requirements_result,
                "mcp_added": mcp_added,
                "mcp_skipped": mcp_skipped,
                "mcp_updated": mcp_updated,
            },
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


@router.post("/settings/shares/{share_id}/import")
async def import_public_share_bundle(share_id: str, dry_run: bool = Form(True)):
    from app.api.settings import (
        _import_expert_from_bundle_bytes,
        _import_mcp_from_bundle_bytes,
        _import_skill_from_bundle_bytes,
    )
    from app.core.scenario_share_store import bundle_path_for_share, get_share_entry, validate_share_id

    sid = str(share_id or "").strip()
    if not validate_share_id(sid):
        raise HTTPException(status_code=404, detail="分享不存在")
    entry = get_share_entry(sid)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="分享不存在")
    p = bundle_path_for_share(sid)
    if not p:
        raise HTTPException(status_code=404, detail="分享包不存在")
    raw = p.read_bytes()
    obj_type = str(entry.get("object_type") or "scene").strip().lower()
    if obj_type == "scene":
        data = await _import_scene_from_bundle_bytes(raw, dry_run=dry_run)
    elif obj_type == "expert":
        data = await _import_expert_from_bundle_bytes(raw, dry_run=dry_run)
    elif obj_type == "skill":
        data = await _import_skill_from_bundle_bytes(raw, dry_run=dry_run)
    elif obj_type == "mcp":
        data = await _import_mcp_from_bundle_bytes(raw, dry_run=dry_run)
    else:
        raise HTTPException(status_code=400, detail="不支持的分享对象类型")
    return {"status": "ok", "data": {"share_id": sid, "dry_run": dry_run, **data}}
