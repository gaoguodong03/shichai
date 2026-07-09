"""API 密钥库设置 API。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.request_models import StrictRequestModel
from app.core.atomic_json import atomic_write_json
from app.core.security import user_context_dependency
from app.core.user_context import get_current_user_context
from app.core.user_settings_paths import vault_secrets_path

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])


def _load_api_secret_values_from_path(path: Path) -> Dict[str, str]:
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


def load_api_secrets_raw() -> Dict[str, Any]:
    """加载密钥库原始 JSON（含 api_key 明文，仅服务端使用）。"""
    path = vault_secrets_path()
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
    path = vault_secrets_path()
    atomic_write_json(path, data)


def load_api_secret_values_for_user(username: str) -> Dict[str, str]:
    """指定用户密钥 id -> api_key（无 HTTP 上下文时使用，如 MCP 连接）。"""
    from app.core.user_context import get_user_context_for

    un = (username or "").strip()
    if not un:
        return {}
    path = (get_user_context_for(un).settings_dir / "secrets.enc.json").resolve()
    return _load_api_secret_values_from_path(path)


def load_api_secret_values() -> Dict[str, str]:
    """当前请求用户密钥 id -> api_key，供 LLM 解析 api_key_ref。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return {}
    path = (user_ctx.settings_dir / "secrets.enc.json").resolve()
    return _load_api_secret_values_from_path(path)


def _normalize_api_secret_id(raw: str) -> str:
    """与常见环境变量名一致，允许大写字母，区分大小写。"""
    s = (raw or "").strip().replace(" ", "-")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$", s):
        raise HTTPException(
            status_code=400,
            detail="密钥标识仅能使用字母、数字、连字符与下划线，长度 1～63，区分大小写",
        )
    return s


class ApiSecretCreate(StrictRequestModel):
    id: str
    label: Optional[str] = None
    api_key: str = ""


class ApiSecretUpdate(StrictRequestModel):
    label: Optional[str] = None
    api_key: Optional[str] = None


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
