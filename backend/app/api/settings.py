"""设置 API - MCP / Skills / 主持人提示词"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import yaml
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Set, Tuple

from app.core.user_context import get_current_user_context, get_current_username
from app.core.host_config import normalize_host_config_dict
from app.core.session_preset_validate import (
    extract_presets_from_import_body,
    normalize_preset_dict_for_validation,
    validate_session_preset,
    validation_to_api_dict,
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
from app.skills.loader import get_builtin_skills_dir, get_skills_loader_for_user, invalidate_skills_cache_for_user
from app.core.scene_host import VIRTUAL_SCENE_HOST_ID
from app.core.security import user_context_dependency
from app.mcp.manager import dispose_mcp_runtime_for_user, ensure_user_mcp_bootstrapped, execute_mcp_call

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])


async def _mcp_runtime_for_request():
    """当前登录用户的 MCP 运行时（已加载该用户 mcp_servers.json）。"""
    un = get_current_username()
    if not un:
        raise HTTPException(status_code=401, detail="未登录")
    return await ensure_user_mcp_bootstrapped(un)


async def _invalidate_mcp_runtime_after_config_change():
    """磁盘上的 mcp_servers.json 变更后丢弃内存中的连接，下次再懒加载。"""
    un = get_current_username()
    if un:
        await dispose_mcp_runtime_for_user(un)

def _require_user_ctx():
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise RuntimeError("缺少用户上下文，无法读取用户级设置目录。")
    return user_ctx


def _get_app_settings_path() -> Path:
    """根据当前用户返回 app_settings.json 路径，实现设置级隔离。"""
    user_ctx = _require_user_ctx()
    return (user_ctx.config_dir / "app_settings.json").resolve()


def _get_mcp_config_path() -> Path:
    """根据当前用户返回 mcp_servers.json 路径。"""
    user_ctx = _require_user_ctx()
    return (user_ctx.config_dir / "mcp_servers.json").resolve()


def _get_skills_dir() -> Path:
    """根据当前用户返回 skills 目录。"""
    user_ctx = _require_user_ctx()
    return user_ctx.skills_dir.resolve()


def _get_session_presets_path() -> Path:
    """根据当前用户返回 session_presets.json 路径。"""
    user_ctx = _require_user_ctx()
    return (user_ctx.config_dir / "session_presets.json").resolve()


def _load_session_preset_rows_from_file(path: Path) -> List[Dict[str, Any]]:
    """解析磁盘 session_presets.json 为与 GET session-presets 一致的行列表。"""
    presets: List[Dict[str, Any]] = []
    if not path.exists():
        return presets
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("id") or "").strip()
                name = str(item.get("name") or "").strip()
                agent_ids = item.get("agent_ids")
                if not isinstance(agent_ids, list) or not agent_ids:
                    agent_ids = item.get("expert_ids")
                if not isinstance(agent_ids, list):
                    agent_ids = []
                normalized_ids = [str(x).strip() for x in agent_ids if str(x).strip()]
                if not pid or not name or not normalized_ids:
                    continue
                hc_raw = item.get("host_config")
                lid = str(item.get("leader_agent_id") or "").strip()
                if isinstance(hc_raw, dict) and hc_raw:
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
                if isinstance(hc_raw, dict):
                    row_out["host_config"] = hc_raw
                presets.append(row_out)
    except Exception:
        return []
    return presets


def _get_api_secrets_path() -> Path:
    """当前用户 api_secrets.json（API Key 密钥库）。"""
    user_ctx = _require_user_ctx()
    return (user_ctx.config_dir / "api_secrets.json").resolve()


def load_api_secrets_raw() -> Dict[str, Any]:
    """加载密钥库原始 JSON（含 api_key 明文，仅服务端使用）。"""
    path = _get_api_secrets_path()
    default: Dict[str, Any] = {"items": {}}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("items"), dict):
                    return {"items": dict(data["items"])}
        except Exception:
            pass
    return default


def save_api_secrets_raw(data: Dict[str, Any]) -> None:
    path = _get_api_secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_api_secret_values_for_user(username: str) -> Dict[str, str]:
    """指定用户密钥 id -> api_key（无 HTTP 上下文时使用，如 MCP 连接）。"""
    from app.core.user_context import get_user_context_for

    un = (username or "").strip()
    if not un:
        return {}
    path = (get_user_context_for(un).config_dir / "api_secrets.json").resolve()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, dict):
            return {}
        out: Dict[str, str] = {}
        for sid, meta in items.items():
            if isinstance(meta, dict):
                v = (meta.get("api_key") or "").strip()
                if v:
                    out[str(sid)] = v
        return out
    except Exception:
        return {}


def load_api_secret_values() -> Dict[str, str]:
    """当前请求用户密钥 id -> api_key，供 LLM 解析 api_key_ref。"""
    from app.core.user_context import get_current_username

    un = get_current_username()
    if not un:
        return {}
    return load_api_secret_values_for_user(un)


def _normalize_api_secret_id(raw: str) -> str:
    """与常见环境变量名一致，允许大写字母，区分大小写。"""
    s = (raw or "").strip().replace(" ", "-")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$", s):
        raise HTTPException(
            status_code=400,
            detail="密钥标识仅能使用字母、数字、连字符与下划线，长度 1～63，区分大小写",
        )
    return s


# ========== 应用设置 API（LLM 选择、系统提示词） ==========

class AppSettingsBody(BaseModel):
    """应用设置请求体"""
    default_llm: Optional[str] = None  # 如 qwen、jeniya
    llm_providers: Optional[Dict[str, Dict[str, Any]]] = None  # provider_id -> {base_url, model, api_key_env}

# 默认 llm_providers（无配置文件时使用）；jeniya 系共用 JENIYA_API_KEY + base_url，模型见 https://jeniya.top/pricing
_JENIYA_BASE = "http://jeniya.top/v1"
_JENIYA_KEY = "JENIYA_API_KEY"
_DEFAULT_LLM_PROVIDERS = {
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3-max",
        "api_key_env": "QWEN_API_KEY",
    },
    "jeniya": {
        "base_url": _JENIYA_BASE,
        "model": "gpt-4o",
        "api_key_env": _JENIYA_KEY,
    },
    "gemini": {
        "base_url": _JENIYA_BASE,
        "model": "gemini-3-pro-preview",
        "api_key_env": _JENIYA_KEY,
    },
    "claude": {
        "base_url": _JENIYA_BASE,
        "model": "claude-sonnet-4-6",
        "api_key_env": _JENIYA_KEY,
    },
    "glm": {
        "base_url": _JENIYA_BASE,
        "model": "glm-4.7",
        "api_key_env": _JENIYA_KEY,
    },
    "deepseek": {
        "base_url": _JENIYA_BASE,
        "model": "deepseek-chat",
        "api_key_env": _JENIYA_KEY,
    },
    "kimi": {
        "base_url": _JENIYA_BASE,
        "model": "moonshot-v1-128k",
        "api_key_env": _JENIYA_KEY,
    },
}

_DEFAULT_HOST_PROFILE: Dict[str, Any] = {
    "display_name": "四九",
    "system_prompt": "",
    "skill_ids": ["group-host"],
    "llm_provider_id": "",
    "mcp_server_ids": [],
    "file_capabilities": normalize_host_config_dict({}).get("file_capabilities") or {},
    "url_capability": True,
}


def normalize_host_profile(raw: Any) -> Dict[str, Any]:
    """主持人独立配置：名称 + DHA 同构能力字段。"""
    if not isinstance(raw, dict):
        raw = {}
    base_cfg = normalize_host_config_dict(raw)
    display_name = str(raw.get("display_name") or "").strip() or str(_DEFAULT_HOST_PROFILE["display_name"])
    out = dict(_DEFAULT_HOST_PROFILE)
    out.update(base_cfg)
    out["display_name"] = display_name
    return out

def load_app_settings() -> Dict[str, Any]:
    """加载应用设置；合并默认 provider，保证新增的模型在未保存前也可用"""
    path = _get_app_settings_path()
    # 说明：历史上支持过 system_prompt（全局系统提示词），现已废弃
    data = {
        "default_llm": "qwen",
        "llm_providers": dict(_DEFAULT_LLM_PROVIDERS),
        "host_profile": dict(_DEFAULT_HOST_PROFILE),
    }
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict) and "system_prompt" in loaded:
                    loaded = dict(loaded)
                    loaded.pop("system_prompt", None)
                # 合并 host_profile，保证新增字段不会因为旧配置缺失而丢失
                if isinstance(loaded, dict):
                    hp = loaded.get("host_profile")
                    if isinstance(hp, dict):
                        loaded = dict(loaded)
                        loaded["host_profile"] = normalize_host_profile(hp)
                data.update(loaded)
                data.pop("router_tfidf", None)
                providers = data.get("llm_providers") or {}
                for k, v in _DEFAULT_LLM_PROVIDERS.items():
                    if k not in providers:
                        providers[k] = v
                data["llm_providers"] = providers
                return data
        except Exception:
            pass
    return data


def _sanitize_app_settings_for_client(data: Dict[str, Any]) -> Dict[str, Any]:
    """GET/PUT 响应：不返回 llm_providers 中的 api_key 明文，仅保留 api_key_set。"""
    safe = dict(data)
    providers = safe.get("llm_providers") or {}
    if isinstance(providers, dict):
        safe_providers: Dict[str, Dict[str, Any]] = {}
        for pid, meta in providers.items():
            m = dict(meta or {}) if isinstance(meta, dict) else {}
            api_key = (m.get("api_key") or "").strip()
            m["api_key_set"] = bool(api_key)
            m.pop("api_key", None)
            safe_providers[pid] = m
        safe["llm_providers"] = safe_providers
    return safe


class HostProfileBody(BaseModel):
    """主持人独立配置（账号级默认）。"""

    display_name: Optional[str] = None
    system_prompt: Optional[str] = None
    skill_ids: Optional[List[str]] = None
    llm_provider_id: Optional[str] = None
    mcp_server_ids: Optional[List[str]] = None
    file_capabilities: Optional[Dict[str, bool]] = None
    url_capability: Optional[bool] = None


def _host_profile_response_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    hp = data.get("host_profile") or {}
    return normalize_host_profile(hp if isinstance(hp, dict) else {})


@router.get("/settings/host-profile")
async def get_host_profile():
    data = load_app_settings()
    return {"status": "ok", "data": _host_profile_response_payload(data)}


@router.put("/settings/host-profile")
async def update_host_profile(body: HostProfileBody):
    incoming = body.model_dump(exclude_none=True)
    current = load_app_settings()
    hp = current.get("host_profile") if isinstance(current.get("host_profile"), dict) else {}
    merged = dict(hp if isinstance(hp, dict) else {})
    for k in (
        "display_name",
        "system_prompt",
        "skill_ids",
        "llm_provider_id",
        "mcp_server_ids",
        "file_capabilities",
        "url_capability",
    ):
        if k in incoming:
            merged[k] = incoming[k]
    merged = normalize_host_profile(merged)
    save_app_settings({"host_profile": merged})
    return {"status": "ok", "data": _host_profile_response_payload(load_app_settings())}


@router.get("/settings/host-profile/defaults")
async def get_host_profile_defaults():
    """返回内置默认主持人配置（不读配置文件）。"""
    return {"status": "ok", "data": {**dict(_DEFAULT_HOST_PROFILE)}}


@router.post("/settings/host-profile/reset")
async def reset_host_profile():
    """将主持人配置恢复为内置默认值。"""
    save_app_settings({"host_profile": dict(_DEFAULT_HOST_PROFILE)})
    return {"status": "ok", "data": _host_profile_response_payload(load_app_settings())}


@router.get("/settings/session-presets")
async def get_session_presets():
    """读取会话快捷预设（用于前端快捷按钮），兼容历史字段 expert_ids。"""
    path = _get_session_presets_path()
    presets = _load_session_preset_rows_from_file(path)
    return {"status": "ok", "data": {"presets": presets}}


class SessionPresetItem(BaseModel):
    id: str
    name: str
    agent_ids: List[str]
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
    valid_dha_ids = {str(d.get("agent_id")).strip() for d in load_dha_instances() if d.get("agent_id")}
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
    if hc_norm is not None:
        row["host_config"] = hc_norm
    return row


def _session_preset_validation_payload(preset: Dict[str, Any]) -> Dict[str, Any]:
    """当前登录用户下校验场景预设依赖。"""
    from app.api.dha import load_dha_instances

    un = get_current_username() or ""
    sl = get_skills_loader_for_user(un, _get_skills_dir())

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
            description=str(row.get("description") or ""),
            discussion_goal_example=str(row.get("discussion_goal_example") or ""),
            leader_agent_id=str(row.get("leader_agent_id") or ""),
            host_config=hc if isinstance(hc, dict) else None,
        )
    except Exception:
        return None


def _merge_session_presets_into_file(
    normalized_rows: List[Dict[str, Any]], id_conflict: str
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """将已规范化的场景行合并写入 session_presets.json；返回 (合并后列表, 本次写入的 preset id 列表)。"""
    path = _get_session_presets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_rows = _load_session_preset_rows_from_file(path)
    by_id: Dict[str, Dict[str, Any]] = {str(r["id"]): dict(r) for r in existing_rows if r.get("id")}
    original_ids = [str(r["id"]) for r in existing_rows if r.get("id")]

    imported_ids: List[str] = []
    for norm in normalized_rows:
        work = dict(norm)
        pid0 = str(work["id"])
        if pid0 in by_id and id_conflict == "new_id":
            work["id"] = f"scenario-{uuid.uuid4().hex[:10]}"
        item = _dict_to_session_preset_item(work)
        if item is None:
            continue
        row = _session_preset_item_to_disk_row(item)
        if row is None:
            continue
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
    return merged, imported_ids


@router.put("/settings/session-presets")
async def update_session_presets(body: SessionPresetsBody):
    """保存会话快捷预设（用于前端快捷按钮）。"""
    path = _get_session_presets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for item in body.presets:
        row = _session_preset_item_to_disk_row(item)
        if row is None or row["id"] in seen:
            continue
        seen.add(row["id"])
        normalized.append(row)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "data": {"presets": normalized}}


@router.get("/settings/session-presets/{preset_id}/export")
async def export_session_preset(preset_id: str):
    """导出单条场景为 JSON 文件（含 export_version，便于分享与再导入）。"""
    key = str(preset_id or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="preset_id required")
    path = _get_session_presets_path()
    rows = _load_session_preset_rows_from_file(path)
    match = next((r for r in rows if r.get("id") == key), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Session preset not found")
    payload = {
        "export_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "preset": match,
    }
    safe_name = key.replace("..", "").replace("/", "").replace("\\", "") or "scenario"
    filename = f"scenario-{safe_name}.json"
    return JSONResponse(
        content=payload,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
    mcp_all = load_mcp_config()
    mcp_by = {str(s.get("id")): s for s in mcp_all if s.get("id")}
    mcp_rows = [dict(mcp_by[mid]) for mid in sorted(mcp_ids) if mid in mcp_by]

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
    from app.core.scenario_share_store import find_share_id_for_source

    key = str(preset_id or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="preset_id required")
    path = _get_session_presets_path()
    rows = _load_session_preset_rows_from_file(path)
    if not next((r for r in rows if r.get("id") == key), None):
        raise HTTPException(status_code=404, detail="Session preset not found")
    uid = get_current_username() or ""
    sid = find_share_id_for_source(uid, key)
    if not sid:
        return {"status": "ok", "data": {"share_id": None, "open_path": None}}
    return {
        "status": "ok",
        "data": {
            "share_id": sid,
            "open_path": f"/scenario/run?id={sid}",
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
            "preset_name": str(match.get("name") or ""),
            "source_preset_id": str(match.get("id") or ""),
            "created_by": get_current_username() or "",
        },
    )
    return {
        "status": "ok",
        "data": {
            "share_id": share_id,
            "open_path": f"/scenario/run?id={share_id}",
            "preset_name": str(match.get("name") or ""),
        },
    }


@router.post("/settings/session-presets/import-bundle")
async def import_session_preset_bundle(
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    overwrite_experts: bool = Form(True),
    overwrite_skills: bool = Form(True),
    # False=用包内覆盖本地同名 MCP（与前端「同名工具覆盖本地工具配置」勾选一致）；True=保留本地同名，仅追加缺失 id
    mcp_skip_existing: bool = Form(False),
    preset_id_conflict: str = Form("new_id"),
):
    """导入场景包：合并专家、技能、MCP 与场景预设。dry_run=true 时仅返回包内清单与将覆盖的技能提示。"""
    from app.api.dha import load_dha_instances, save_dha_instances

    fn = (file.filename or "").strip().lower()
    if not fn.endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 ZIP 场景包")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")

    conflict = str(preset_id_conflict or "new_id").strip().lower()
    if conflict not in ("overwrite", "new_id"):
        conflict = "new_id"

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

        if dry_run:
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
                    },
                    "note": "确认导入后，数据写入服务器上该账号目录下的配置文件与技能文件夹。界面无法修改专家 agent_id；若需改 id，请在服务端编辑 dha_instances.json。",
                },
            }

        imported_skills, skipped_skills = copy_bundle_skills_to_user(
            tmp, user_skills, overwrite=overwrite_skills
        )
        invalidate_skills_cache_for_user(get_current_username() or "")

        merged_dha = merge_dha_instances_for_bundle(
            load_dha_instances(), dha_bundle, overwrite=overwrite_experts
        )
        save_dha_instances(merged_dha)

        merged_mcp, mcp_added, mcp_skipped, mcp_updated = merge_mcp_servers_for_bundle(
            load_mcp_config(), mcp_bundle, skip_existing=mcp_skip_existing
        )
        save_mcp_config(merged_mcp)
        await _invalidate_mcp_runtime_after_config_change()

        merged_presets, imported_ids = _merge_session_presets_into_file([norm], conflict)
        val_after = _session_preset_validation_payload(norm)

        return {
            "status": "ok",
            "data": {
                "dry_run": False,
                "summary": {
                    "preset_imported_ids": imported_ids,
                    "skills_imported": imported_skills,
                    "skills_skipped": skipped_skills,
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


@router.post("/settings/session-presets/import")
async def import_session_presets(request: Request):
    """导入场景预设。dry_run=true 时仅校验依赖，不写盘。"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    # 缺省 dry_run：避免误 POST 即写盘；显式 dry_run:false 才提交
    dry_run = True if "dry_run" not in data else bool(data.get("dry_run"))
    id_conflict = str(data.get("id_conflict") or "new_id").strip().lower()
    if id_conflict not in ("overwrite", "new_id"):
        id_conflict = "new_id"

    raw_presets = extract_presets_from_import_body(data)
    if not raw_presets:
        raise HTTPException(status_code=400, detail="未识别到场景数据（需要 preset 字段或完整场景对象）")

    results: List[Dict[str, Any]] = []
    normalized_rows: List[Dict[str, Any]] = []

    for raw in raw_presets:
        norm = normalize_preset_dict_for_validation(raw)
        if norm is None:
            results.append(
                {
                    "preset_id": str(raw.get("id") or ""),
                    "error": "invalid_preset",
                    "message": "场景需包含非空的 id、name 与 agent_ids",
                }
            )
            continue
        val = _session_preset_validation_payload(norm)
        results.append({"preset_id": norm["id"], "name": norm["name"], "validation": val})
        normalized_rows.append(norm)

    if dry_run:
        return {"status": "ok", "data": {"dry_run": True, "results": results}}

    merged, imported_ids = _merge_session_presets_into_file(normalized_rows, id_conflict)
    return {"status": "ok", "data": {"dry_run": False, "imported_ids": imported_ids, "presets": merged, "results": results}}

def save_app_settings(data: Dict[str, Any]):
    """保存应用设置"""
    path = _get_app_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_app_settings()
    patch = {k: v for k, v in data.items() if v is not None}

    # llm_providers 需要“保留密钥”的合并语义：
    # - GET 返回会隐藏 api_key，前端通常不会回传；若直接覆盖会导致已保存的 key 被清空。
    # - 支持通过传入 api_key 显式更新；传入空字符串表示删除。
    if "llm_providers" in patch and isinstance(patch["llm_providers"], dict):
        # 以现有配置为底，增量覆盖 incoming，避免只传部分 provider 时丢失其他项
        existing = (current.get("llm_providers") or {}) if isinstance(current.get("llm_providers"), dict) else {}
        merged: Dict[str, Dict[str, Any]] = {
            pid: (dict(meta) if isinstance(meta, dict) else {}) for pid, meta in (existing or {}).items()
        }
        incoming = patch["llm_providers"]
        for pid, meta in incoming.items():
            base: Dict[str, Any] = dict(existing.get(pid) or {})
            if isinstance(meta, dict):
                base.update(meta)
                if "api_key" not in meta and "api_key" in existing.get(pid, {}):
                    # 前端未传 api_key 时，保留旧值
                    base["api_key"] = existing[pid].get("api_key")
                if isinstance(meta.get("api_key"), str) and meta.get("api_key") == "":
                    # 显式清空
                    base.pop("api_key", None)
                if "api_key_ref" not in meta and "api_key_ref" in existing.get(pid, {}):
                    base["api_key_ref"] = existing[pid].get("api_key_ref")
                if isinstance(meta.get("api_key_ref"), str) and not (meta.get("api_key_ref") or "").strip():
                    base.pop("api_key_ref", None)
            merged[pid] = base
        patch["llm_providers"] = merged

    current.update(patch)
    current.pop("router_tfidf", None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

@router.get("/settings/app")
async def get_app_settings():
    """获取应用设置（LLM 选择、系统提示词）"""
    return {"status": "ok", "data": _sanitize_app_settings_for_client(load_app_settings())}

@router.put("/settings/app")
async def update_app_settings(body: AppSettingsBody):
    """更新应用设置"""
    save_app_settings(body.model_dump(exclude_none=True))
    return {"status": "ok", "data": _sanitize_app_settings_for_client(load_app_settings())}


# ========== API 密钥库（供 LLM 提供方 api_key_ref 引用） ==========


class ApiSecretCreate(BaseModel):
    id: str
    label: Optional[str] = None
    api_key: str = ""


class ApiSecretUpdate(BaseModel):
    label: Optional[str] = None
    api_key: Optional[str] = None  # 传入空字符串表示清除密钥内容


@router.get("/settings/api-secrets")
async def list_api_secrets():
    """列出密钥条目（不含 api_key 明文）。"""
    raw = load_api_secrets_raw()
    items = raw.get("items") or {}
    out: List[Dict[str, Any]] = []
    if isinstance(items, dict):
        for sid in sorted(items.keys()):
            meta = items.get(sid)
            if not isinstance(meta, dict):
                continue
            k = (meta.get("api_key") or "").strip()
            out.append(
                {
                    "id": str(sid),
                    "label": (meta.get("label") or "").strip() or str(sid),
                    "key_set": bool(k),
                }
            )
    return {"status": "ok", "data": {"items": out}}


@router.post("/settings/api-secrets")
async def create_api_secret(body: ApiSecretCreate):
    raw = load_api_secrets_raw()
    items = raw.setdefault("items", {})
    if not isinstance(items, dict):
        items = {}
        raw["items"] = items
    sid = _normalize_api_secret_id(body.id)
    if sid in items:
        raise HTTPException(status_code=409, detail="该密钥标识已存在")
    key = (body.api_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="请填写 API Key")
    label = (body.label or "").strip() or sid
    items[sid] = {"label": label, "api_key": key}
    save_api_secrets_raw(raw)
    return {"status": "ok", "data": {"id": sid, "label": label, "key_set": True}}


@router.put("/settings/api-secrets/{secret_id}")
async def update_api_secret(secret_id: str, body: ApiSecretUpdate):
    raw = load_api_secrets_raw()
    items = raw.setdefault("items", {})
    if not isinstance(items, dict):
        raise HTTPException(status_code=500, detail="密钥库格式错误")
    sid = _normalize_api_secret_id(secret_id)
    if sid not in items:
        raise HTTPException(status_code=404, detail="密钥不存在")
    meta = dict(items[sid]) if isinstance(items[sid], dict) else {}
    if body.label is not None:
        meta["label"] = (body.label or "").strip() or sid
    if body.api_key is not None:
        nk = body.api_key.strip()
        if nk:
            meta["api_key"] = nk
        else:
            meta.pop("api_key", None)
    items[sid] = meta
    save_api_secrets_raw(raw)
    k = (meta.get("api_key") or "").strip()
    return {
        "status": "ok",
        "data": {
            "id": sid,
            "label": (meta.get("label") or "").strip() or sid,
            "key_set": bool(k),
        },
    }


@router.delete("/settings/api-secrets/{secret_id}")
async def delete_api_secret(secret_id: str):
    raw = load_api_secrets_raw()
    items = raw.setdefault("items", {})
    if not isinstance(items, dict):
        raise HTTPException(status_code=404, detail="密钥不存在")
    sid = _normalize_api_secret_id(secret_id)
    if sid not in items:
        raise HTTPException(status_code=404, detail="密钥不存在")
    del items[sid]
    save_api_secrets_raw(raw)
    return {"status": "ok"}


# ========== MCP 配置 API ==========

class MCPTransport(BaseModel):
    """MCP 传输配置"""
    type: str  # stdio, sse, http
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    base_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    env: Optional[Dict[str, str]] = None

class MCPServerCreate(BaseModel):
    """创建 MCP Server 请求"""
    name: str
    enabled: bool = True
    transport: MCPTransport
    metadata: Optional[Dict[str, Any]] = None

class MCPServerUpdate(BaseModel):
    """更新 MCP Server 请求"""
    name: Optional[str] = None
    enabled: Optional[bool] = None
    transport: Optional[MCPTransport] = None
    metadata: Optional[Dict[str, Any]] = None

def load_mcp_config() -> List[Dict[str, Any]]:
    """加载 MCP 配置"""
    config_path = _get_mcp_config_path()
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_mcp_config(servers: List[Dict[str, Any]]):
    """保存 MCP 配置"""
    config_path = _get_mcp_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(servers, f, ensure_ascii=False, indent=2)

@router.get("/settings/mcp")
async def get_mcp_servers():
    """获取 MCP Server 列表"""
    servers = load_mcp_config()
    mcp_manager = await _mcp_runtime_for_request()

    # 确保已连接非 lazy 且尚未连接的 server
    try:
        # 对每个已启用且尚未连接的 server 尝试连接（包括 HTTP 远程 server）
        for config in mcp_manager.server_configs:
            server_id = config.get("id", "")
            if not config.get("enabled", True):
                continue
            # lazy server：只在真正需要工具时连接，避免在状态页被提前拉起
            if config.get("lazy", False):
                continue
            if server_id in mcp_manager.sessions:
                continue
            try:
                await mcp_manager.connect_server(server_id, config)
            except asyncio.CancelledError:
                # 请求被取消（如前端断开、超时），不再继续连接，直接返回当前状态
                break
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"MCP Server {server_id} 连接失败: {e}")
    except asyncio.CancelledError:
        pass  # 被取消时不再抛错，下面会按当前 sessions 返回列表
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"MCP 配置加载失败: {e}")
    
    # 统计每个 server 的工具数量
    server_tool_counts = {}
    for tool_name, tool in mcp_manager.tools.items():
        # 工具名称格式: server_id_tool_name
        if '_' in tool_name:
            server_id = tool_name.split('_', 1)[0]
            server_tool_counts[server_id] = server_tool_counts.get(server_id, 0) + 1
    
    # 检查连接状态
    server_status = {}
    for server_id in mcp_manager.sessions.keys():
        server_status[server_id] = "connected"
    
    # 添加状态信息
    result = []
    for server in servers:
        server_id = server.get("id", "")
        tool_count = server_tool_counts.get(server_id, 0)
        status = server_status.get(server_id, "disconnected")
        
        # 如果启用了但未连接，可能是连接失败
        if server.get("enabled", False) and status == "disconnected":
            status = "disconnected"
        
        server_info = {
            "id": server_id,
            "name": server.get("name", ""),
            "enabled": server.get("enabled", False),
            "tool_count": tool_count,
            "status": status,
            "transport": server.get("transport", {}),
            "metadata": server.get("metadata", {})
        }
        result.append(server_info)
    
    return {
        "status": "ok",
        "data": {
            "servers": result
        }
    }

@router.post("/settings/mcp")
async def create_mcp_server(server: MCPServerCreate):
    """创建 MCP Server"""
    servers = load_mcp_config()
    
    # 生成 ID
    server_id = f"mcp-{uuid.uuid4().hex[:8]}"
    
    new_server = {
        "id": server_id,
        "name": server.name,
        "enabled": server.enabled,
        "transport": server.transport.dict(exclude_none=True),
        "metadata": server.metadata or {}
    }
    
    servers.append(new_server)
    save_mcp_config(servers)
    await _invalidate_mcp_runtime_after_config_change()

    return {
        "status": "ok",
        "data": new_server
    }

@router.put("/settings/mcp/{server_id}")
async def update_mcp_server(server_id: str, server_update: MCPServerUpdate):
    """更新 MCP Server"""
    servers = load_mcp_config()
    
    # 查找服务器
    server_index = None
    for i, s in enumerate(servers):
        if s.get("id") == server_id:
            server_index = i
            break
    
    if server_index is None:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    
    # 更新字段
    server = servers[server_index]
    if server_update.name is not None:
        server["name"] = server_update.name
    if server_update.enabled is not None:
        server["enabled"] = server_update.enabled
    if server_update.transport is not None:
        server["transport"] = server_update.transport.dict(exclude_none=True)
    if server_update.metadata is not None:
        server["metadata"] = server_update.metadata
    
    save_mcp_config(servers)
    await _invalidate_mcp_runtime_after_config_change()

    return {
        "status": "ok",
        "data": server
    }

@router.delete("/settings/mcp/{server_id}")
async def delete_mcp_server(server_id: str):
    """删除 MCP Server"""
    servers = load_mcp_config()
    
    # 查找并删除
    original_count = len(servers)
    servers = [s for s in servers if s.get("id") != server_id]
    
    if len(servers) == original_count:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    
    save_mcp_config(servers)
    await _invalidate_mcp_runtime_after_config_change()

    return {
        "status": "ok",
        "data": {
            "id": server_id,
            "deleted": True
        }
    }

@router.post("/settings/mcp/{server_id}/enable")
async def enable_mcp_server(server_id: str):
    """启用 MCP Server"""
    servers = load_mcp_config()
    
    for server in servers:
        if server.get("id") == server_id:
            server["enabled"] = True
            save_mcp_config(servers)
            await _invalidate_mcp_runtime_after_config_change()
            return {
                "status": "ok",
                "data": server
            }
    
    raise HTTPException(status_code=404, detail="MCP Server not found")

@router.post("/settings/mcp/{server_id}/disable")
async def disable_mcp_server(server_id: str):
    """禁用 MCP Server"""
    servers = load_mcp_config()
    
    for server in servers:
        if server.get("id") == server_id:
            server["enabled"] = False
            save_mcp_config(servers)
            await _invalidate_mcp_runtime_after_config_change()
            return {
                "status": "ok",
                "data": server
            }
    
    raise HTTPException(status_code=404, detail="MCP Server not found")

@router.post("/settings/mcp/{server_id}/test")
async def test_mcp_server(server_id: str):
    """测试 MCP Server 连接（真实调用 MCP Manager）"""
    servers = load_mcp_config()

    # 查找服务器配置
    server = next((s for s in servers if s.get("id") == server_id), None)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP Server not found")

    mcp_manager = await _mcp_runtime_for_request()

    import time

    start = time.perf_counter()
    try:
        # 如果当前没有 session，则尝试连接
        if server_id not in mcp_manager.sessions:
            ok = await mcp_manager.connect_server(server_id, server)
            if not ok:
                elapsed = int((time.perf_counter() - start) * 1000)
                return {
                    "status": "ok",
                    "data": {
                        "connected": False,
                        "response_time": elapsed,
                        "error": f"Failed to connect to MCP server {server_id}",
                    },
                }
        # 调用 list_tools 做一次简单健康检查
        session = mcp_manager.sessions.get(server_id)
        if not session:
            elapsed = int((time.perf_counter() - start) * 1000)
            return {
                "status": "ok",
                "data": {
                    "connected": False,
                    "response_time": elapsed,
                    "error": f"No active session for MCP server {server_id}",
                },
            }
        try:
            tools_result = await session.list_tools()
            tool_count = len(getattr(tools_result, "tools", []) or [])
            elapsed = int((time.perf_counter() - start) * 1000)
            return {
                "status": "ok",
                "data": {
                    "connected": True,
                    "response_time": elapsed,
                    "tool_count": tool_count,
                    "error": None,
                },
            }
        except Exception as e:
            elapsed = int((time.perf_counter() - start) * 1000)
            return {
                "status": "ok",
                "data": {
                    "connected": False,
                    "response_time": elapsed,
                    "error": f"list_tools error: {e}",
                },
            }
    except asyncio.CancelledError:
        raise
    except Exception as e:
        elapsed = int((time.perf_counter() - start) * 1000)
        return {
            "status": "ok",
            "data": {
                "connected": False,
                "response_time": elapsed,
                "error": f"Unexpected error: {e}",
            },
        }

@router.get("/settings/mcp/{server_id}/tools")
async def get_mcp_server_tools(server_id: str):
    """获取 MCP Server 工具列表（含 input_schema），用于前端动态渲染参数表单"""
    mcp_manager = await _mcp_runtime_for_request()

    # 找到对应 server 配置
    config = next((c for c in mcp_manager.server_configs if c.get("id") == server_id), None)
    if not config:
        raise HTTPException(status_code=404, detail="MCP Server not found")

    # 确保已连接
    if server_id not in mcp_manager.sessions:
        ok = await mcp_manager.connect_server(server_id, config)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to connect MCP server {server_id}")

    session = mcp_manager.sessions.get(server_id)
    if not session:
        raise HTTPException(status_code=500, detail=f"No active session for MCP server {server_id}")

    try:
        tools_result = await session.list_tools()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_tools error: {e}")

    tools_payload = []
    for t in getattr(tools_result, "tools", []) or []:
        # mcp Tool 对象通常有 name / description / inputSchema
        input_schema = getattr(t, "inputSchema", None)
        # 尽量转换为原生 dict 以便前端消费
        if hasattr(input_schema, "model_dump"):
            input_schema = input_schema.model_dump()
        tools_payload.append(
            {
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", "") or "",
                "input_schema": input_schema or {},
            }
        )

    return {
        "status": "ok",
        "data": {
            "tools": tools_payload,
        },
    }


class MCPToolCallBody(BaseModel):
    """调用 MCP 工具的请求体（用于前端测试）"""

    arguments: Dict[str, Any] = {}


@router.post("/settings/mcp/{server_id}/tools/{tool_name}/call")
async def call_mcp_tool(server_id: str, tool_name: str, body: MCPToolCallBody):
    """调用指定 MCP Server 上的某个工具，用于前端测试面板"""
    mcp_manager = await _mcp_runtime_for_request()

    config = next((c for c in mcp_manager.server_configs if c.get("id") == server_id), None)
    if not config:
        raise HTTPException(status_code=404, detail="MCP Server not found")

    # 确保连接
    if server_id not in mcp_manager.sessions:
        ok = await mcp_manager.connect_server(server_id, config)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to connect MCP server {server_id}")

    session = mcp_manager.sessions.get(server_id)
    if not session:
        raise HTTPException(status_code=500, detail=f"No active session for MCP server {server_id}")

    ok, result, err = await execute_mcp_call(
        server_id=server_id,
        tool_name=tool_name,
        kwargs=body.arguments or {},
        session=session,
        timeout_sec=60.0,
    )
    if not ok:
        return {
            "status": "ok",
            "data": {
                "ok": False,
                "error": err,
                "raw": None,
            },
        }

    # 将 MCP ToolResult 内容序列化为易读结构
    blocks = []
    for block in getattr(result, "content", []) or []:
        # 文本内容
        if hasattr(block, "text"):
            blocks.append({"type": "text", "text": block.text})
        else:
            # 兜底：直接转字符串
            blocks.append({"type": "unknown", "raw": str(block)})

    return {
        "status": "ok",
        "data": {
            "ok": True,
            "blocks": blocks,
        },
    }


class MCPSandboxCallBody(BaseModel):
    """沙箱调用：不关心具体工具名，只在该 MCP Server 上调用第一个工具"""

    arguments: Dict[str, Any] = {}


@router.post("/settings/mcp/{server_id}/sandbox-call")
async def call_mcp_sandbox(server_id: str, body: MCPSandboxCallBody):
    """
    沙箱调用：在指定 MCP Server 上选择第一个可用工具进行一次调用。
    前端只需提供 arguments，不需要关心工具名。
    """
    mcp_manager = await _mcp_runtime_for_request()

    config = next((c for c in mcp_manager.server_configs if c.get("id") == server_id), None)
    if not config:
        raise HTTPException(status_code=404, detail="MCP Server not found")

    # 确保连接
    if server_id not in mcp_manager.sessions:
        ok = await mcp_manager.connect_server(server_id, config)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to connect MCP server {server_id}")

    session = mcp_manager.sessions.get(server_id)
    if not session:
        raise HTTPException(status_code=500, detail=f"No active session for MCP server {server_id}")

    # 获取工具列表，选择第一个工具名
    try:
        tools_result = await session.list_tools()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_tools error: {e}")

    tools = getattr(tools_result, "tools", []) or []
    if not tools:
        raise HTTPException(status_code=500, detail=f"MCP server {server_id} has no tools")

    tool_name = getattr(tools[0], "name", None)
    if not tool_name:
        raise HTTPException(status_code=500, detail=f"First tool of MCP server {server_id} has no name")

    # 调用第一个工具
    ok, result, err = await execute_mcp_call(
        server_id=server_id,
        tool_name=tool_name,
        kwargs=body.arguments or {},
        session=session,
        timeout_sec=60.0,
    )
    if not ok:
        return {
            "status": "ok",
            "data": {
                "ok": False,
                "error": err,
                "raw": None,
            },
        }

    blocks = []
    for block in getattr(result, "content", []) or []:
        if hasattr(block, "text"):
            blocks.append({"type": "text", "text": block.text})
        else:
            blocks.append({"type": "unknown", "raw": str(block)})

    return {
        "status": "ok",
        "data": {
            "ok": True,
            "tool_name": tool_name,
            "blocks": blocks,
        },
    }

# ========== Skills 配置 API ==========

class SkillCreate(BaseModel):
    """创建 Skill 请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    source: str = "local"  # local or git
    path: Optional[str] = None
    url: Optional[str] = None
    enabled: bool = True
    write_mode: str = "readonly"  # readonly or workspace_all

class SkillUpdate(BaseModel):
    """更新 Skill 请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    enabled: Optional[bool] = None
    body: Optional[str] = None  # SKILL.md frontmatter 之后的正文
    mcp_server_ids: Optional[List[str]] = None  # 该 skill 依赖的 MCP server id 列表，空表示只用内置工具
    write_mode: Optional[str] = None  # readonly or workspace_all


_GIT_URL_RE = re.compile(r"^(https://[^\s]+|git@[^\s:]+:[^\s]+)$")


def _validate_skill_write_mode(write_mode: str) -> str:
    mode = (write_mode or "readonly").strip()
    if mode not in {"readonly", "workspace_all"}:
        raise HTTPException(status_code=400, detail="Invalid write_mode, must be readonly or workspace_all")
    return mode


def _validate_git_url(url: Optional[str]) -> str:
    raw = (url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="url is required when source=git")
    if ".." in raw:
        raise HTTPException(status_code=400, detail="Invalid git url")
    if not _GIT_URL_RE.match(raw):
        raise HTTPException(status_code=400, detail="Only https:// or git@ URLs are allowed")
    return raw


def _normalize_git_import_source(url: str) -> tuple[str, str]:
    """将导入 URL 归一化为 (clone_url, subdir)。

    支持：
    - https://github.com/owner/repo(.git)
    - https://github.com/owner/repo/tree/<branch>/<subdir>
    - git@github.com:owner/repo(.git)
    """
    raw = _validate_git_url(url)
    if raw.startswith("git@"):
        return (raw if raw.endswith(".git") else f"{raw}.git", "")
    p = urlparse(raw)
    path_parts = [x for x in p.path.split("/") if x]
    if len(path_parts) >= 2 and path_parts[2:3] == ["tree"]:
        owner, repo = path_parts[0], path_parts[1]
        subdir_parts = path_parts[4:]  # tree/<branch>/<subdir...>
        subdir = "/".join(subdir_parts).strip("/")
        if ".." in subdir:
            raise HTTPException(status_code=400, detail="Invalid git tree path")
        clone_url = f"{p.scheme}://{p.netloc}/{owner}/{repo}.git"
        return clone_url, subdir
    return (raw if raw.endswith(".git") else f"{raw}.git", "")


def _suggest_skill_id_from_git_url(url: str) -> str:
    """根据 git 导入 URL 生成更可管理的默认 skill_id（目录名）。"""
    clone_url, subdir = _normalize_git_import_source(url)
    # git@github.com:owner/repo.git
    if clone_url.startswith("git@"):
        repo_part = clone_url.split(":", 1)[1] if ":" in clone_url else clone_url
    else:
        p = urlparse(clone_url)
        repo_part = p.path.strip("/")
    parts = [x for x in repo_part.split("/") if x]
    repo_name = parts[-1] if parts else "skill"
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    # tree 子目录导入时，把最后一级目录拼到 id，避免同仓库不同子 skill 冲突
    tail = ""
    if subdir:
        sub_parts = [x for x in subdir.split("/") if x]
        if sub_parts:
            tail = sub_parts[-1]
    base = f"{repo_name}-{tail}" if tail else repo_name
    return _slugify(base)


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


def _run_git(repo_dir: Path, args: List[str], timeout_sec: int = 120) -> None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env={**os.environ},
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=400,
            detail="Git command failed: git is not installed in runtime environment. Please install git in your container/image.",
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Git command failed: {e}")
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise HTTPException(status_code=400, detail=f"Git command failed: {msg}")


def _import_skill_from_git(skill_dir: Path, git_url: str) -> None:
    """将 skill 同步到 skill_dir。目录存在则 pull，不存在则 clone。"""
    timeout_sec = int(os.getenv("SKILL_GIT_TIMEOUT", "120"))
    if (skill_dir / ".git").is_dir():
        _run_git(skill_dir, ["fetch", "--all"], timeout_sec=timeout_sec)
        _run_git(skill_dir, ["pull", "--ff-only"], timeout_sec=timeout_sec)
    elif skill_dir.exists():
        raise HTTPException(status_code=400, detail="Skill directory exists but is not a git repository")
    else:
        parent = skill_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        _run_git(parent, ["clone", git_url, skill_dir.name], timeout_sec=timeout_sec)


def _import_skill_from_git_subdir(skill_dir: Path, git_url: str, subdir: str) -> None:
    """从 git 仓库的子目录导入 skill 内容到 skill_dir。"""
    timeout_sec = int(os.getenv("SKILL_GIT_TIMEOUT", "120"))
    with tempfile.TemporaryDirectory(prefix="skill-import-") as tmp:
        tmp_path = Path(tmp).resolve()
        _run_git(tmp_path, ["clone", git_url, "repo"], timeout_sec=timeout_sec)
        src_root = (tmp_path / "repo").resolve()
        source = (src_root / subdir).resolve() if subdir else src_root
        if not str(source).startswith(str(src_root)) or not source.is_dir():
            raise HTTPException(status_code=400, detail=f"Skill subdir not found: {subdir}")
        if not (source / "SKILL.md").is_file():
            raise HTTPException(status_code=400, detail="SKILL.md not found in imported path")
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        shutil.copytree(source, skill_dir)

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
        fm_mcp = frontmatter.get("mcp_server_ids")
        mcp_ids = fm_mcp if isinstance(fm_mcp, list) else []
        item: Dict[str, Any] = {
            "id": skill_id,
            "name": frontmatter.get("name", skill_id),
            "description": frontmatter.get("description", ""),
            "enabled": frontmatter.get("enabled", True),
            "source": frontmatter.get("source", "local"),
            "path": str(skill_dir),
            "write_mode": frontmatter.get("write_mode", "readonly"),
        }
        if frontmatter.get("url"):
            item["url"] = frontmatter.get("url")
        if "mcp_server_ids" in frontmatter:
            item["mcp_server_ids"] = mcp_ids
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
                if not item.get("source"):
                    item["source"] = "builtin"
                skills.append(item)
                seen.add(sid)
    skills.sort(key=lambda x: (x.get("name") or x.get("id") or "").strip())
    return skills

# 当 skill 的 frontmatter 未显式配置 mcp_server_ids 时使用的默认映射（向后兼容）
# 与 backend/config/mcp_servers.json 中的 id 对应
_SKILL_MCP_SERVERS_FALLBACK: Dict[str, List[str]] = {
    # 兜底仅使用当前保留的 5 个 MCP：linkup / exa / amap-maps / file-reader / playwright-mcp
    "wechat-article-writer": ["linkup", "exa", "file-reader"],
    "amap-maps": ["amap-maps"],
    "app-icon-generator": [],
    "webnovel-illustration": [],
    "cover-image": [],
    "article-illustrator": [],
    "blog-write": ["linkup", "exa", "file-reader"],
    "data-report": ["linkup", "exa", "file-reader"],
    "zhipu-web-search": [],
    "weather-service": [],
    "news-summary": ["linkup", "exa", "file-reader"],
    "article-review": ["file-reader"],
    "deep-research": ["linkup", "exa", "file-reader"],
    "web-research": ["linkup", "exa", "file-reader"],
    "doc-coauthoring": ["file-reader"],
    "docs-write": ["file-reader"],
    "xlsx": ["file-reader"],
    "math-assistant": [],
    "group-host": ["file-reader"],
    "group-host-webnovel": ["file-reader"],
    "url-fetch": ["file-reader"],
    "seminar-companion": [],
    "seminar-guide": [],
    "seminar-divergence": [],
    "seminar-research-progress": [],
    "browser-playwright": ["playwright-mcp"],
    "session-export": [],
    "default": [],
    "script-demo": [],
    "prompt-engineering-patterns": [],
}

def get_mcp_servers_for_skill(skill_id: str) -> List[str]:
    """根据 skill_id 返回其关联的 MCP server_id 列表。
    优先从 SKILL.md frontmatter 的 mcp_server_ids 读取（前端可配置）；
    若未配置则使用 _SKILL_MCP_SERVERS_FALLBACK。"""
    skills = load_skills_config()
    enabled_ids = {s.get("id") for s in load_mcp_config() if s.get("enabled", True)}
    s = next((x for x in skills if x.get("id") == skill_id), None)
    if s is not None and "mcp_server_ids" in s:
        return [x for x in (s.get("mcp_server_ids") or []) if x in enabled_ids]
    return [x for x in list(_SKILL_MCP_SERVERS_FALLBACK.get(skill_id, [])) if x in enabled_ids]


def get_write_mode_for_skill(skill_id: str) -> str:
    """返回 skill 的写入模式。未配置时默认为 readonly。"""
    _ = skill_id
    return "workspace_all"

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


def _replace_skill_id_in_user_configs(old_id: str, new_id: str) -> None:
    """技能目录重命名后，同步当前用户 dha_instances.json 里各专家的 skill_ids，避免仍指向旧目录、触发空壳 scripts/。"""
    if not old_id or not new_id or old_id == new_id:
        return
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    path = (user_ctx.config_dir / "dha_instances.json").resolve()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(raw, list):
        return
    changed = False
    for inst in raw:
        if not isinstance(inst, dict):
            continue
        sids = inst.get("skill_ids")
        if not isinstance(sids, list):
            continue
        orig = [str(x).strip() for x in sids if str(x).strip()]
        out: List[str] = []
        seen: Set[str] = set()
        for sid in orig:
            sid = new_id if sid == old_id else sid
            if sid not in seen:
                seen.add(sid)
                out.append(sid)
        if out != orig:
            inst["skill_ids"] = out
            changed = True
    if changed:
        try:
            path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass


def _remove_skill_id_from_user_configs(skill_id: str) -> None:
    """删除技能后，从当前用户 dha_instances.json 各专家的 skill_ids 中移除该 id。"""
    sid = (skill_id or "").strip()
    if not sid:
        return
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    path = (user_ctx.config_dir / "dha_instances.json").resolve()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(raw, list):
        return
    changed = False
    for inst in raw:
        if not isinstance(inst, dict):
            continue
        sids = inst.get("skill_ids")
        if not isinstance(sids, list):
            continue
        out = [str(x).strip() for x in sids if str(x).strip() and str(x).strip() != sid]
        if len(out) != len(sids):
            inst["skill_ids"] = out
            changed = True
    if changed:
        try:
            path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass


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
    source = (skill.source or "local").strip().lower()
    if source not in {"local", "git"}:
        raise HTTPException(status_code=400, detail="source must be local or git")
    write_mode = "workspace_all"
    # local：仍要求 name；git：允许仅 url（name/description 从 SKILL.md 自动提取）
    if source == "local" and not (skill.name or "").strip():
        raise HTTPException(status_code=400, detail="name is required when source=local")
    if source == "git" and not (skill.name or "").strip():
        raw_id = _suggest_skill_id_from_git_url(skill.url or "")
    else:
        raw_id = _slugify((skill.name or "skill").strip())
    skill_id = _next_available_skill_id(base, raw_id)
    skill_dir = base / skill_id
    if source == "git":
        git_url, git_subdir = _normalize_git_import_source(skill.url or "")
        if git_subdir:
            _import_skill_from_git_subdir(skill_dir, git_url, git_subdir)
        else:
            _import_skill_from_git(skill_dir, git_url)
        fm, body = _read_skill_file(skill_dir)
        # 自动提取元数据：仅当请求未显式提供时才覆盖
        final_name = (skill.name or fm.get("name") or skill_dir.name or skill_id).strip()
        final_desc = skill.description if skill.description is not None else (fm.get("description") or "")
        fm["name"] = final_name
        fm["description"] = final_desc
        fm["enabled"] = skill.enabled
        fm["source"] = "git"
        fm["url"] = skill.url or git_url
        fm["write_mode"] = write_mode
        _write_skill_file(skill_dir, fm, body)
    else:
        skill_dir.mkdir(parents=True, exist_ok=True)
        body = "\n## 说明\n\n（待补充）\n"
        frontmatter = {
            "name": (skill.name or "").strip(),
            "description": skill.description or "",
            "enabled": skill.enabled,
            "source": "local",
            "write_mode": "workspace_all",
        }
        content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n" + body
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    _refresh_skills_loader()
    if source == "git":
        # 以 SKILL.md 的最终内容回填返回字段
        fm2, _body2 = _read_skill_file(skill_dir)
        ret_name = (fm2.get("name") or skill_id).strip()
        ret_desc = fm2.get("description") or ""
    else:
        ret_name = (skill.name or skill_id).strip()
        ret_desc = skill.description or ""
    new_skill = {
        "id": skill_id,
        "name": ret_name,
        "description": ret_desc,
        "enabled": skill.enabled,
        "source": source,
        "path": str(skill_dir),
        "url": skill.url,
        "write_mode": "workspace_all",
    }
    return {"status": "ok", "data": new_skill}


@router.post("/settings/skills/import-zip")
async def import_skill_zip(file: UploadFile = File(...), enabled: bool = Form(True)):
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

    base = _get_skills_dir()
    base.mkdir(parents=True, exist_ok=True)
    fallback_seed = _slugify(Path(filename).stem or "skill")
    skill_id = _next_available_skill_id(base, fallback_seed)
    skill_dir = base / skill_id

    try:
        with tempfile.TemporaryDirectory(prefix="skill-zip-import-") as tmp:
            src_dir = Path(tmp) / "skill"
            src_dir.mkdir(parents=True, exist_ok=True)
            for raw_name, rel_parts in normalized:
                if len(rel_parts) == 1 and rel_parts[0].lower() == "skill.md":
                    dst = src_dir / "SKILL.md"
                else:
                    dst = src_dir / Path(*rel_parts)
                dst.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(raw_name, "r") as rf:
                    dst.write_bytes(rf.read())

            if not (src_dir / "SKILL.md").is_file():
                raise HTTPException(status_code=400, detail="ZIP 根目录必须包含 SKILL.md")

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
        fm["enabled"] = bool(enabled)
        fm["source"] = "local"
        fm["write_mode"] = "workspace_all"
        if "url" in fm:
            fm.pop("url", None)
        _write_skill_file(skill_dir, fm, body)
        _refresh_skills_loader()

        return {
            "status": "ok",
            "data": {
                "id": skill_id,
                "name": final_name,
                "description": final_desc,
                "enabled": bool(enabled),
                "source": "local",
                "path": str(skill_dir),
                "write_mode": "workspace_all",
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


def _build_skill_zip_bytes(skill_dir: Path) -> bytes:
    """将技能目录打包为 ZIP（根目录含 SKILL.md，与 import-zip 约定一致）；跳过 .git。"""
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
            zf.write(fp, arcname)
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
    raw = _build_skill_zip_bytes(skill_dir)
    filename = f"{skill_id}.zip"
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_attachment(filename)},
    )


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
    if skill_update.enabled is not None:
        fm["enabled"] = skill_update.enabled
    if skill_update.mcp_server_ids is not None:
        fm["mcp_server_ids"] = skill_update.mcp_server_ids
    if skill_update.write_mode is not None:
        fm["write_mode"] = "workspace_all"
    if skill_update.source is not None:
        src = (skill_update.source or "").strip().lower()
        if src not in {"local", "git"}:
            raise HTTPException(status_code=400, detail="source must be local or git")
        fm["source"] = src
    if skill_update.url is not None:
        if fm.get("source", "local") == "git":
            fm["url"] = _validate_git_url(skill_update.url)
        else:
            fm["url"] = skill_update.url
    if skill_update.body is not None:
        body = skill_update.body
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
    shutil.rmtree(skill_dir)
    _remove_skill_id_from_user_configs(skill_id)
    _refresh_skills_loader()
    return {"status": "ok", "data": {"id": skill_id, "deleted": True}}

@router.post("/settings/skills/{skill_id}/enable")
async def enable_skill(skill_id: str):
    """启用 Skill"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    fm, body = _read_skill_file(skill_dir)
    fm["enabled"] = True
    _write_skill_file(skill_dir, fm, body)
    _refresh_skills_loader()
    return {"status": "ok", "data": {"id": skill_id, "enabled": True}}

@router.post("/settings/skills/{skill_id}/disable")
async def disable_skill(skill_id: str):
    """禁用 Skill"""
    base = _get_skills_dir()
    skill_dir = base / skill_id
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    fm, body = _read_skill_file(skill_dir)
    fm["enabled"] = False
    _write_skill_file(skill_dir, fm, body)
    _refresh_skills_loader()
    return {"status": "ok", "data": {"id": skill_id, "enabled": False}}


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
    if "mcp_server_ids" in fm:
        mcp_ids = fm["mcp_server_ids"] if isinstance(fm["mcp_server_ids"], list) else []
    else:
        mcp_ids = get_mcp_servers_for_skill(skill_id)  # 未配置时返回 fallback，便于前端展示
    return {
        "status": "ok",
        "data": {
            "raw": raw,
            "name": fm.get("name", skill_id),
            "description": fm.get("description", ""),
            "enabled": fm.get("enabled", True),
            "source": fm.get("source", "local"),
            "url": fm.get("url"),
            "write_mode": fm.get("write_mode", "readonly"),
            "body": body,
            "mcp_server_ids": mcp_ids,
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
