"""应用设置与主持人 profile API。"""
from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.llm_bundle import (
    build_llm_bundle_zip_bytes,
    provider_for_settings_import,
    read_llm_bundle_manifest,
)
from app.core.scenario_bundle import extract_scenario_bundle_dir
from app.core.resource_store import mirror_rows_to_resource_dir
from app.core.security import user_context_dependency
from app.core.user_context import get_current_user_context
from app.core.user_settings_paths import app_settings_path

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])


class AppSettingsBody(BaseModel):
    """应用设置请求体"""

    default_llm: Optional[str] = None
    llm_providers: Optional[Dict[str, Dict[str, Any]]] = None
    system_prompt: Optional[str] = None


_JENIYA_BASE = "https://jeniya.top/v1"
_JENIYA_KEY = "JENIYA_API_KEY"
_DEFAULT_LLM_PROVIDERS = {
    "qwen3-max": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3-max",
        "api_key_env": "QWEN_API_KEY",
    },
    "gpt-4o": {
        "base_url": _JENIYA_BASE,
        "model": "gpt-4o",
        "api_key_env": _JENIYA_KEY,
    },
    "gemini-3-pro-preview": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3-pro-preview",
        "api_key_env": "GEMINI_API_KEY",
    },
    "claude-sonnet-4-6": {
        "base_url": _JENIYA_BASE,
        "model": "claude-sonnet-4-6",
        "api_key_env": _JENIYA_KEY,
    },
    "glm-4.7": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.7",
        "api_key_env": "ZHIPUAI_API_KEY",
    },
    "deepseek-chat": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "thinking": False,
    },
    "moonshot-v1-128k": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-128k",
        "api_key_env": "MOONSHOT_API_KEY",
    },
}

_DEFAULT_HOST_PROFILE: Dict[str, Any] = {
    "name": "四九",
    "system_prompt": "",
    "llm_name": "",
    "skill_name": "",
    "skill_directory": "",
}


def normalize_host_profile(raw: Any) -> Dict[str, Any]:
    """Normalize the account-level default host snapshot."""
    if not isinstance(raw, dict):
        raw = {}
    out = dict(_DEFAULT_HOST_PROFILE)
    out.update(
        {
            "name": str(raw.get("name") or raw.get("leader_agent_name") or _DEFAULT_HOST_PROFILE["name"]).strip() or "四九",
            "system_prompt": str(raw.get("system_prompt") or ""),
            "llm_name": str(raw.get("llm_name") or "").strip(),
            "skill_name": str(raw.get("skill_name") or "").strip(),
            "skill_directory": str(raw.get("skill_directory") or "").strip().replace("\\", "/").strip("/"),
        }
    )
    return out


def _refresh_builtin_llm_provider_presets(providers: Any) -> Dict[str, Dict[str, Any]]:
    """Merge built-in providers and refresh old bundled Jeniya presets only."""
    if not isinstance(providers, dict):
        providers = {}
    out: Dict[str, Dict[str, Any]] = {
        str(k): dict(v or {}) if isinstance(v, dict) else {}
        for k, v in providers.items()
    }
    for k, v in _DEFAULT_LLM_PROVIDERS.items():
        if k not in out:
            out[k] = dict(v)
            continue
        meta = out.get(k)
        if not isinstance(meta, dict):
            out[k] = dict(v)
            continue
        if not meta.get("base_url"):
            meta["base_url"] = v.get("base_url")
        if not meta.get("model"):
            meta["model"] = v.get("model")
        if not meta.get("api_key_env"):
            meta["api_key_env"] = v.get("api_key_env")
    return out


def _load_llm_provider_resources() -> Dict[str, Dict[str, Any]]:
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return {}
    root = user_ctx.models_dir.resolve()
    if not root.is_dir():
        return {}
    providers: Dict[str, Dict[str, Any]] = {}
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        body = child / "model.json"
        if not body.is_file():
            continue
        try:
            raw = json.loads(body.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or child.name).strip()
        if not name:
            continue
        meta = dict(raw)
        meta.pop("name", None)
        providers[name] = meta
    return providers


def _save_llm_provider_resources(providers: Dict[str, Dict[str, Any]]) -> None:
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    rows = []
    for name, meta in providers.items():
        if not isinstance(meta, dict):
            continue
        row = dict(meta)
        row["name"] = str(name)
        rows.append(row)
    mirror_rows_to_resource_dir(
        rows,
        user_ctx.models_dir.resolve(),
        "name",
        body_filename="model.json",
    )


def load_app_settings() -> Dict[str, Any]:
    """加载应用设置；合并默认 provider，保证新增的模型在未保存前也可用"""
    path = app_settings_path()
    data = {
        "default_llm": "qwen3-max",
        "system_prompt": "",
        "host_profile": dict(_DEFAULT_HOST_PROFILE),
    }
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    hp = loaded.get("host_profile")
                    if isinstance(hp, dict):
                        loaded = dict(loaded)
                        loaded["host_profile"] = normalize_host_profile(hp)
                    if "system_prompt" in loaded:
                        loaded = dict(loaded)
                        loaded["system_prompt"] = str(loaded.get("system_prompt") or "")
                    loaded.pop("llm_providers", None)
                data.update(loaded)
                data.pop("router_tfidf", None)
        except Exception:
            pass
    providers = _refresh_builtin_llm_provider_presets(_load_llm_provider_resources())
    deleted = {
        str(x).strip()
        for x in (data.get("_deleted_llm_providers") or [])
        if str(x).strip()
    }
    for k, v in _DEFAULT_LLM_PROVIDERS.items():
        if k not in providers and k not in deleted:
            providers[k] = v
    for k in deleted:
        providers.pop(k, None)
    data["llm_providers"] = providers
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
    safe.pop("_deleted_llm_providers", None)
    return safe


class HostProfileBody(BaseModel):
    """主持人独立配置（账号级默认）。"""

    name: Optional[str] = None
    system_prompt: Optional[str] = None
    llm_name: Optional[str] = None
    skill_name: Optional[str] = None
    skill_directory: Optional[str] = None


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
        "name",
        "system_prompt",
        "llm_name",
        "skill_name",
        "skill_directory",
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


def save_app_settings(data: Dict[str, Any]):
    """保存应用设置"""
    path = app_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_app_settings()
    patch = {k: v for k, v in data.items() if v is not None}

    if "llm_providers" in patch and isinstance(patch["llm_providers"], dict):
        existing = (current.get("llm_providers") or {}) if isinstance(current.get("llm_providers"), dict) else {}
        merged: Dict[str, Dict[str, Any]] = {}
        incoming = patch["llm_providers"]
        for pid, meta in incoming.items():
            if not isinstance(meta, dict):
                continue
            base: Dict[str, Any] = dict(meta)
            old = existing.get(pid, {}) if isinstance(existing.get(pid), dict) else {}
            if "api_key" not in meta and "api_key" in old:
                base["api_key"] = old.get("api_key")
            if isinstance(meta.get("api_key"), str) and meta.get("api_key") == "":
                base.pop("api_key", None)
            if "api_key_ref" not in meta and "api_key_ref" in old:
                base["api_key_ref"] = old.get("api_key_ref")
            if isinstance(meta.get("api_key_ref"), str) and not (meta.get("api_key_ref") or "").strip():
                base.pop("api_key_ref", None)
            merged[str(pid)] = base
        deleted_defaults = sorted(k for k in _DEFAULT_LLM_PROVIDERS if k not in merged)
        if deleted_defaults:
            patch["_deleted_llm_providers"] = deleted_defaults
        else:
            current.pop("_deleted_llm_providers", None)
        _save_llm_provider_resources(merged)
        patch.pop("llm_providers", None)

    current.update(patch)
    current.pop("router_tfidf", None)
    current.pop("llm_providers", None)
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


@router.get("/settings/llm-providers/{llm_name}/export-bundle")
async def export_llm_provider_bundle(llm_name: str):
    settings = load_app_settings()
    providers = settings.get("llm_providers") if isinstance(settings.get("llm_providers"), dict) else {}
    provider = providers.get(llm_name) if isinstance(providers, dict) else None
    if not isinstance(provider, dict):
        raise HTTPException(status_code=404, detail="模型不存在")

    raw = build_llm_bundle_zip_bytes(llm_name, provider, default_llm=str(settings.get("default_llm") or ""))
    safe = str(llm_name).replace("..", "").replace("/", "").replace("\\", "") or "llm"
    filename = f"llm-bundle-{safe}.zip"
    from app.api.settings_skills import _content_disposition_attachment

    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_attachment(filename)},
    )


@router.post("/settings/llm-providers/import-bundle")
async def import_llm_provider_bundle(
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
):
    fn = (file.filename or "").strip().lower()
    if not fn.endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 ZIP 模型包")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")

    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        manifest, llm_name, provider = read_llm_bundle_manifest(tmp)
        current = load_app_settings()
        current_providers = current.get("llm_providers") if isinstance(current.get("llm_providers"), dict) else {}
        preview = {
            "name": llm_name,
            "provider": provider,
            "default_llm": str(manifest.get("default_llm") or ""),
            "would_conflict_name": llm_name in (current_providers or {}),
        }
        if dry_run:
            return {
                "status": "ok",
                "data": {
                    "dry_run": True,
                    "bundle_preview": preview,
                    "note": "确认后将写入模型配置；API Key 明文不会从模型包导入。",
                },
            }

        next_providers = dict(current_providers or {})
        if llm_name in next_providers:
            raise HTTPException(status_code=409, detail="同名模型已存在")
        next_providers[llm_name] = provider_for_settings_import(provider)
        default_llm = str(current.get("default_llm") or "")
        if not default_llm:
            default_llm = llm_name
        save_app_settings({"default_llm": default_llm, "llm_providers": next_providers})
        return {
            "status": "ok",
            "data": {
                "dry_run": False,
                "summary": {
                    "imported_name": llm_name,
                    "overwritten": False,
                },
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e) or "无效的模型包") from e
    except HTTPException:
        raise
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
