"""设置 API - MCP / Skills / 主持人提示词"""
from __future__ import annotations

import asyncio
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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Set, Tuple

from app.core.user_context import get_current_user_context, get_current_username
from app.core.host_config import normalize_host_config_dict
from app.core.session_preset_validate import (
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
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
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


def _get_sandbox_requirements_path() -> Path:
    """当前用户沙箱依赖清单 requirements.txt 路径。"""
    user_ctx = _require_user_ctx()
    return (user_ctx.config_dir / "sandbox" / "requirements.txt").resolve()


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
_JENIYA_BASE = "https://jeniya.top/v1"
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
    return merged, imported_ids, skipped_by_name, overwritten_existing_ids


def _remap_id_list(values: Any, id_map: Dict[str, str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for raw in values or []:
        item = str(raw).strip()
        if not item:
            continue
        item = id_map.get(item, item)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _remap_bundle_references(
    preset: Dict[str, Any],
    experts: List[Dict[str, Any]],
    *,
    skill_id_map: Dict[str, str],
    mcp_id_map: Dict[str, str],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    preset_out = dict(preset)
    hc_raw = preset_out.get("host_config")
    if isinstance(hc_raw, dict):
        hc = dict(hc_raw)
        hc["skill_ids"] = _remap_id_list(hc.get("skill_ids"), skill_id_map)
        hc["mcp_server_ids"] = _remap_id_list(hc.get("mcp_server_ids"), mcp_id_map)
        preset_out["host_config"] = hc
    experts_out: List[Dict[str, Any]] = []
    for row in experts:
        work = dict(row)
        work["skill_ids"] = _remap_id_list(work.get("skill_ids"), skill_id_map)
        work["mcp_server_ids"] = _remap_id_list(work.get("mcp_server_ids"), mcp_id_map)
        experts_out.append(work)
    return preset_out, experts_out


def _mcp_conflict_id_map(existing_servers: List[Dict[str, Any]], bundle_servers: List[Dict[str, Any]]) -> Dict[str, str]:
    by_id = {str(s.get("id") or "").strip(): s for s in existing_servers if str(s.get("id") or "").strip()}
    id_map: Dict[str, str] = {}
    for incoming in bundle_servers:
        incoming_id = str(incoming.get("id") or "").strip()
        incoming_name = _normalized_name_key(incoming.get("name"))
        if not incoming_id:
            continue
        for old_id, old in by_id.items():
            if old_id == incoming_id:
                continue
            if incoming_name and _normalized_name_key(old.get("name")) == incoming_name:
                id_map[old_id] = incoming_id
    return id_map


def _skill_conflict_id_map(bundle_dir: Path, user_skills_dir: Path, skill_ids: List[str]) -> Dict[str, str]:
    id_map: Dict[str, str] = {}
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    existing_by_id: Dict[str, str] = {}
    existing_name_to_ids: Dict[str, List[str]] = {}
    for child in sorted(user_skills_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        try:
            fm, _ = _read_skill_file(child)
        except Exception:
            continue
        sid = child.name
        existing_by_id[sid] = _normalized_name_key(fm.get("name") or sid)
        if existing_by_id[sid]:
            existing_name_to_ids.setdefault(existing_by_id[sid], []).append(sid)

    for incoming_id in skill_ids:
        src = bundle_dir / "skills" / incoming_id
        if not src.is_dir() or not (src / "SKILL.md").is_file():
            continue
        try:
            fm, _ = _read_skill_file(src)
        except Exception:
            continue
        incoming_name_key = _normalized_name_key(fm.get("name") or incoming_id)
        conflict_ids: List[str] = []
        if incoming_id in existing_by_id:
            conflict_ids.append(incoming_id)
        if incoming_name_key:
            conflict_ids.extend(old_id for old_id in existing_name_to_ids.get(incoming_name_key, []) if old_id != incoming_id)
        for old_id in dict.fromkeys(conflict_ids):
            id_map[old_id] = incoming_id
    return id_map


def _copy_bundle_skills_to_user_by_name(bundle_dir: Path, user_skills_dir: Path) -> Tuple[List[str], List[str], Dict[str, str]]:
    skill_ids = list_skill_ids_in_bundle_skills_dir(bundle_dir)
    id_map = _skill_conflict_id_map(bundle_dir, user_skills_dir, skill_ids)
    overwritten = sorted(id_map.keys())
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    for old_id in overwritten:
        old_dir = user_skills_dir / old_id
        if old_dir.is_dir():
            shutil.rmtree(old_dir, ignore_errors=True)
    imported, skipped = copy_bundle_skills_to_user(bundle_dir, user_skills_dir, overwrite=True)
    for old_id, new_id in id_map.items():
        _replace_skill_id_in_user_configs(old_id, new_id)
    return imported, overwritten, id_map


def _requirement_key(line: str) -> str:
    item = (line or "").strip()
    if not item or item.startswith("#"):
        return ""
    if item.startswith(("-", "git+", "http://", "https://")):
        return item.lower()
    item = item.split("#", 1)[0].strip()
    item = item.split(";", 1)[0].strip()
    m = re.match(r"^\s*([A-Za-z0-9_.-]+)", item)
    return (m.group(1) if m else item).lower().replace("_", "-")


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
        key = _requirement_key(item)
        if not item or item.startswith("#") or not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _merge_sandbox_requirements_lines(incoming: List[str]) -> Tuple[List[str], str]:
    path = _get_sandbox_requirements_path()
    current = ""
    if path.is_file():
        current = path.read_text(encoding="utf-8")
    existing_keys = {_requirement_key(line) for line in current.splitlines()}
    existing_keys.discard("")
    added: List[str] = []
    for line in incoming:
        key = _requirement_key(line)
        if not key or key in existing_keys:
            continue
        existing_keys.add(key)
        added.append(line.strip())
    if not added:
        return [], current
    prefix = current.rstrip("\n")
    merged = (prefix + "\n" if prefix else "") + "\n".join(added) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(merged, encoding="utf-8")
    return added, merged


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
                        "name_conflict_existing_ids": preset_name_conflicts,
                        "name_conflict_mode": conflict,
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
            load_dha_instances(), dha_bundle, overwrite=overwrite_experts
        )
        save_dha_instances(merged_dha)

        merged_mcp, mcp_added, mcp_skipped, mcp_updated = merge_mcp_servers_for_bundle(
            load_mcp_config(), mcp_bundle, skip_existing=mcp_skip_existing
        )
        save_mcp_config(merged_mcp)
        await _invalidate_mcp_runtime_after_config_change()

        merged_presets, imported_ids, skipped_by_name, overwritten_existing_ids = _merge_session_presets_into_file([norm], conflict)
        val_after = _session_preset_validation_payload(norm)

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


async def _import_skill_from_bundle_bytes(raw: bytes, *, dry_run: bool) -> Dict[str, Any]:
    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        skill_ids = list_skill_ids_in_bundle_skills_dir(tmp)
        if not skill_ids:
            raise HTTPException(status_code=400, detail="分享包中缺少技能目录")
        sid0 = skill_ids[0]
        src = tmp / "skills" / sid0
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
            return {
                "object_type": "skill",
                "title": incoming_name,
                "preview": {
                    "skill_id": sid0,
                    "name": incoming_name,
                    "overwrite_skill_ids": overwrite_skill_ids,
                    "python_requirements": req_preview,
                },
            }
        for old_id in overwrite_skill_ids:
            old_dir = base / old_id
            if old_dir.is_dir():
                shutil.rmtree(old_dir, ignore_errors=True)
                _remove_skill_id_from_user_configs(old_id)
        target_id = _next_available_skill_id(base, _slugify(incoming_name))
        dest = base / target_id
        shutil.copytree(src, dest)
        fm2, body2 = _read_skill_file(dest)
        fm2["name"] = str(fm2.get("name") or incoming_name)
        fm2["description"] = str(fm2.get("description") or "")
        _sanitize_skill_frontmatter_for_write(fm2)
        _write_skill_file(dest, fm2, body2)
        _refresh_skills_loader()
        requirements_result = await _merge_imported_skill_requirements_and_prewarm([target_id], base)
        return {
            "object_type": "skill",
            "imported_skill_id": target_id,
            "name": str(fm2.get("name") or target_id),
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
                },
            }
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
                **requirements_result,
            },
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


async def _import_scene_from_bundle_bytes(raw: bytes, *, dry_run: bool) -> Dict[str, Any]:
    from app.api.dha import load_dha_instances, save_dha_instances

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


class SandboxRequirementsBody(BaseModel):
    content: str = ""


def _sandbox_requirements_error_detail(exc: Exception) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    return f"已保存 requirements.txt，但沙箱依赖安装验证失败：{msg}"


@router.get("/settings/sandbox/requirements")
async def get_sandbox_requirements():
    path = _get_sandbox_requirements_path()
    if not path.exists():
        return {"status": "ok", "data": {"content": ""}}
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取 requirements.txt 失败: {e}")
    return {"status": "ok", "data": {"content": content}}


@router.put("/settings/sandbox/requirements")
async def save_sandbox_requirements(body: SandboxRequirementsBody):
    path = _get_sandbox_requirements_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.content or "", encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存 requirements.txt 失败: {e}")
    username = (get_current_username() or "").strip()
    if not username:
        return {"status": "ok", "data": {"saved": True, "validated": False}}
    try:
        timeout_ms = int(os.getenv("SANDBOX_REQUIREMENTS_VALIDATE_TIMEOUT_MS", "600000") or "600000")
    except Exception:
        timeout_ms = 600_000
    try:
        await get_shared_sandbox_service().prewarm_user_sandbox(
            username,
            reason="requirements_saved",
            timeout_ms=max(120_000, timeout_ms),
        )
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("sandbox_requirements_validate_failed user=%s err=%s", username, e)
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "code": "sandbox_requirements_install_failed",
                "detail": _sandbox_requirements_error_detail(e),
                "data": {"saved": True, "validated": False, "error": str(e)},
            },
        )
    return {"status": "ok", "data": {"saved": True, "validated": True}}


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


def _build_single_mcp_bundle_zip_bytes(server: Dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mcp_servers.json", json.dumps([server], ensure_ascii=False, indent=2) + "\n")
    return buf.getvalue()

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


@router.get("/settings/mcp/{server_id}/share-link")
async def get_mcp_share_link(server_id: str):
    from app.core.scenario_share_store import find_share_id_for_object

    sid = str(server_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="server_id required")
    hit = next((x for x in load_mcp_config() if str(x.get("id") or "").strip() == sid), None)
    if not hit:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    share_id = find_share_id_for_object(get_current_username() or "", "mcp", sid)
    if not share_id:
        return {"status": "ok", "data": {"share_id": None, "open_path": None}}
    return {"status": "ok", "data": {"share_id": share_id, "open_path": f"/share/run?id={share_id}"}}


@router.post("/settings/mcp/{server_id}/publish-share")
async def publish_mcp_share(server_id: str):
    from app.core.scenario_share_store import upsert_public_share

    sid = str(server_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="server_id required")
    hit = next((x for x in load_mcp_config() if str(x.get("id") or "").strip() == sid), None)
    if not hit:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    zip_bytes = _build_single_mcp_bundle_zip_bytes(dict(hit))
    name = str(hit.get("name") or sid)
    share_id = upsert_public_share(
        zip_bytes,
        {
            "object_type": "mcp",
            "source_ref": sid,
            "title": name,
            "mcp_name": name,
            "created_by": get_current_username() or "",
            "summary": {"mcp_count": 1},
        },
    )
    return {
        "status": "ok",
        "data": {"share_id": share_id, "open_path": f"/share/run?id={share_id}", "server_id": sid, "server_name": name},
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

class SkillUpdate(BaseModel):
    """更新 Skill 请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    body: Optional[str] = None  # SKILL.md frontmatter 之后的正文
    allowed_tools: Optional[Dict[str, Any]] = None  # allowed-tools：mcp 为运行时声明；python 会同步到沙箱 requirements


# SKILL.md frontmatter 标准键：与 YAML 中 `allowed-tools` 一致
ALLOWED_TOOLS_FM_KEY = "allowed-tools"
AUTO_TOOLS_FM_KEY = "auto-tools"


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
    if isinstance(at, dict):
        py = at.get("python")
    if (py is None or py == "") and isinstance(auto, dict):
        py = auto.get("python")
    if isinstance(py, str):
        return py
    if py is None:
        return ""
    if isinstance(py, list):
        return "\n".join(str(x).strip() for x in py if str(x).strip())
    return str(py)


def _normalized_allowed_tools_dict(fm: Dict[str, Any]) -> Dict[str, Any]:
    """从当前 frontmatter 归一化 allowed-tools（合并旧 mcp_server_ids）。"""
    return {
        "mcp": list(_mcp_ids_from_frontmatter(fm)),
        "python": _python_doc_from_allowed_tools(fm),
    }


def _normalize_allowed_tools_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """校验并归一化 API 传入的 allowed_tools 体。"""
    mcp_raw = raw.get("mcp")
    mcp_list = _validate_skill_mcp_server_ids(list(mcp_raw) if isinstance(mcp_raw, list) else [])
    py = raw.get("python", "")
    py_str = py if isinstance(py, str) else ("" if py is None else str(py))
    return {"mcp": mcp_list, "python": py_str}


def _sanitize_skill_frontmatter_for_write(fm: Dict[str, Any]) -> None:
    """写入前：保证 allowed-tools 存在并剥离已废弃键。"""
    fm[ALLOWED_TOOLS_FM_KEY] = _normalized_allowed_tools_dict(fm)
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
    """校验 skill 声明的 MCP id 均存在且已启用。"""
    raw = [str(x).strip() for x in (mcp_ids or []) if str(x).strip()]
    cfg = load_mcp_config()
    allowed = {
        str(s.get("id")).strip()
        for s in cfg
        if s.get("enabled", True) and str(s.get("id") or "").strip()
    }
    unknown = [x for x in raw if x not in allowed]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail="Unknown or disabled MCP server id: " + ", ".join(unknown),
        )
    return list(dict.fromkeys(raw))


def get_mcp_servers_for_skill(skill_id: str) -> List[str]:
    """根据 skill_id 从 SKILL.md 的 allowed-tools.mcp（或兼容旧 mcp_server_ids）解析 MCP server_id 列表。"""
    skill_dir = _skill_dir_for_id(skill_id)
    if skill_dir is None:
        return []
    fm, _ = _read_skill_file(skill_dir)
    ids = _mcp_ids_from_frontmatter(fm)
    enabled_ids = {s.get("id") for s in load_mcp_config() if s.get("enabled", True)}
    return [x for x in ids if x in enabled_ids]


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
    """技能 id 变化后，同步当前用户专家与场景主持人配置里的 skill_ids。"""
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
    preset_path = (user_ctx.config_dir / "session_presets.json").resolve()
    if not preset_path.is_file():
        return
    try:
        presets = json.loads(preset_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(presets, list):
        return
    changed = False
    for preset in presets:
        if not isinstance(preset, dict) or not isinstance(preset.get("host_config"), dict):
            continue
        hc = preset["host_config"]
        sids = hc.get("skill_ids")
        if not isinstance(sids, list):
            continue
        orig = [str(x).strip() for x in sids if str(x).strip()]
        out = _remap_id_list(orig, {old_id: new_id})
        if out != orig:
            hc["skill_ids"] = out
            changed = True
    if changed:
        try:
            preset_path.write_text(json.dumps(presets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass


def _replace_mcp_server_id_in_user_configs(old_id: str, new_id: str) -> None:
    if not old_id or not new_id or old_id == new_id:
        return
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    paths = [
        (user_ctx.config_dir / "dha_instances.json").resolve(),
        (user_ctx.config_dir / "session_presets.json").resolve(),
    ]
    for path in paths:
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, list):
            continue
        changed = False
        for row in raw:
            if not isinstance(row, dict):
                continue
            targets = [row]
            if isinstance(row.get("host_config"), dict):
                targets.append(row["host_config"])
            for target in targets:
                mids = target.get("mcp_server_ids")
                if not isinstance(mids, list):
                    continue
                orig = [str(x).strip() for x in mids if str(x).strip()]
                out = _remap_id_list(orig, {old_id: new_id})
                if out != orig:
                    target["mcp_server_ids"] = out
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
                    shutil.rmtree(old_dir, ignore_errors=True)
                    _remove_skill_id_from_user_configs(sid)

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
    zip_bytes = _build_skill_zip_bytes(sdir)
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
            "summary": {"skill_count": 1},
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
        fm[ALLOWED_TOOLS_FM_KEY] = _normalize_allowed_tools_payload(skill_update.allowed_tools)
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
    shutil.rmtree(skill_dir)
    _remove_skill_id_from_user_configs(skill_id)
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
