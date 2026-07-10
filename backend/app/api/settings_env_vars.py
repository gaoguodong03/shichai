"""Platform-scoped user environment variable settings API."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.request_models import StrictRequestModel
from app.core.atomic_json import atomic_write_json
from app.core.security import user_context_dependency
from app.core.user_context import get_current_user_context, get_user_context_for
from app.core.user_settings_paths import env_vars_path

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])


def _normalize_env_var_name(raw: str) -> str:
    """Validate the product-level environment variable identity field."""
    name = (raw or "").strip()
    if not re.match(r"^[A-Z_][A-Z0-9_]{0,127}$", name):
        raise HTTPException(
            status_code=400,
            detail="环境变量名只能使用大写字母、数字和下划线，且不能以数字开头。",
        )
    return name


def _load_env_values_from_path(path: Path) -> Dict[str, str]:
    """Load server-only variable values from env.enc.json."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return {}
    values: Dict[str, str] = {}
    for name, meta in items.items():
        if not isinstance(meta, dict):
            continue
        value = str(meta.get("value") or "").strip()
        if value:
            values[str(name)] = value
    return values


def load_env_vars_raw() -> Dict[str, Any]:
    """Load the current user's raw env variable JSON; values stay server-side."""
    path = env_vars_path()
    if not path.exists():
        return {"items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"items": {}}
    items = data.get("items") if isinstance(data, dict) else None
    return {"items": dict(items)} if isinstance(items, dict) else {"items": {}}


def save_env_vars_raw(data: Dict[str, Any]) -> None:
    """Persist the current user's env variable JSON atomically."""
    atomic_write_json(env_vars_path(), data)


def load_env_var_values_for_user(username: str) -> Dict[str, str]:
    """Load platform env values for a user without requiring request context."""
    username = (username or "").strip()
    if not username:
        return {}
    return _load_env_values_from_path((get_user_context_for(username).settings_dir / "env.enc.json").resolve())


def load_env_var_values() -> Dict[str, str]:
    """Load current request user's platform env values."""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return {}
    return _load_env_values_from_path((user_ctx.settings_dir / "env.enc.json").resolve())


def resolve_platform_env_value(name: str, values: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Resolve one variable through user settings first, then host process env."""
    env_name = (name or "").strip()
    if not env_name:
        return None
    if values and env_name in values:
        value = str(values.get(env_name) or "").strip()
        if value:
            return value
    value = os.getenv(env_name)
    return str(value).strip() if value and str(value).strip() else None


class EnvVarCreate(StrictRequestModel):
    name: str
    label: Optional[str] = None
    value: str = ""
    sensitive: bool = True


class EnvVarUpdate(StrictRequestModel):
    label: Optional[str] = None
    value: Optional[str] = None
    sensitive: Optional[bool] = None


def _env_var_response(name: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Return a redacted env variable row for frontend settings screens."""
    value = str(meta.get("value") or "").strip()
    return {
        "name": name,
        "label": str(meta.get("label") or "").strip() or name,
        "value_set": bool(value),
        "sensitive": meta.get("sensitive") is not False,
    }


@router.get("/settings/env-vars")
async def list_env_vars():
    """List current user's env variables without exposing values."""
    raw = load_env_vars_raw()
    items = raw.get("items") if isinstance(raw.get("items"), dict) else {}
    rows: List[Dict[str, Any]] = []
    for name in sorted(items):
        meta = items.get(name)
        if isinstance(meta, dict):
            rows.append(_env_var_response(str(name), meta))
    return {"status": "ok", "data": {"items": rows}}


@router.post("/settings/env-vars")
async def create_env_var(body: EnvVarCreate):
    raw = load_env_vars_raw()
    items = raw.setdefault("items", {})
    if not isinstance(items, dict):
        items = {}
        raw["items"] = items
    name = _normalize_env_var_name(body.name)
    if name in items:
        raise HTTPException(status_code=409, detail="该环境变量已存在")
    value = (body.value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="请填写环境变量值")
    items[name] = {
        "label": (body.label or "").strip() or name,
        "value": value,
        "sensitive": body.sensitive is not False,
    }
    save_env_vars_raw(raw)
    return {"status": "ok", "data": _env_var_response(name, items[name])}


@router.put("/settings/env-vars/{name}")
async def update_env_var(name: str, body: EnvVarUpdate):
    raw = load_env_vars_raw()
    items = raw.setdefault("items", {})
    if not isinstance(items, dict):
        raise HTTPException(status_code=500, detail="环境变量文件格式错误")
    key = _normalize_env_var_name(name)
    if key not in items:
        raise HTTPException(status_code=404, detail="环境变量不存在")
    meta = dict(items[key]) if isinstance(items[key], dict) else {}
    if body.label is not None:
        meta["label"] = (body.label or "").strip() or key
    if body.value is not None:
        value = body.value.strip()
        if value:
            meta["value"] = value
        else:
            meta.pop("value", None)
    if body.sensitive is not None:
        meta["sensitive"] = bool(body.sensitive)
    items[key] = meta
    save_env_vars_raw(raw)
    return {"status": "ok", "data": _env_var_response(key, meta)}


@router.delete("/settings/env-vars/{name}")
async def delete_env_var(name: str):
    raw = load_env_vars_raw()
    items = raw.setdefault("items", {})
    if not isinstance(items, dict):
        raise HTTPException(status_code=404, detail="环境变量不存在")
    key = _normalize_env_var_name(name)
    if key not in items:
        raise HTTPException(status_code=404, detail="环境变量不存在")
    del items[key]
    save_env_vars_raw(raw)
    return {"status": "ok"}
