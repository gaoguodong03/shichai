"""用户沙箱设置与 Python requirements API。"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.agent.sandbox_image_policy import (
    image_for_variant,
    normalize_sandbox_variant,
    read_sandbox_variant,
    sandbox_image_options,
    write_sandbox_variant,
)
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.core.python_dependency_status import resolve_dependency_status
from app.core.sandbox_requirements import merge_requirements_lines, sandbox_requirements_error_detail
from app.core.security import user_context_dependency
from app.core.user_context import get_current_user_context, get_current_username

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])


class SandboxRequirementsBody(BaseModel):
    content: str = ""


class SandboxSettingsBody(BaseModel):
    image_variant: str = "standard"


class SandboxRequirementsMergeBody(BaseModel):
    requirements: List[str] = []


class SandboxRequirementsStatusBody(BaseModel):
    requirements: List[str] = []


def _require_user_ctx():
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise RuntimeError("缺少用户上下文，无法读取用户级沙箱设置。")
    return user_ctx


def _sandbox_settings_dir() -> Path:
    return (_require_user_ctx().settings_dir / "sandbox").resolve()


def _sandbox_requirements_path() -> Path:
    return (_sandbox_settings_dir() / "requirements.txt").resolve()


def _settings_validate_timeout_ms() -> int:
    try:
        return int(os.getenv("SANDBOX_SETTINGS_VALIDATE_TIMEOUT_MS", "120000") or "120000")
    except Exception:
        return 120_000


def _requirements_validate_timeout_ms() -> int:
    try:
        return int(os.getenv("SANDBOX_REQUIREMENTS_VALIDATE_TIMEOUT_MS", "600000") or "600000")
    except Exception:
        return 600_000


async def _prewarm_current_user(reason: str, timeout_ms: int) -> Dict[str, Any] | None:
    username = (get_current_username() or "").strip()
    if not username:
        return None
    return await get_shared_sandbox_service().prewarm_user_sandbox(
        username,
        reason=reason,
        timeout_ms=timeout_ms,
    )


@router.get("/settings/sandbox")
async def get_sandbox_settings():
    variant = read_sandbox_variant(_sandbox_settings_dir())
    return {
        "status": "ok",
        "data": {
            "image_variant": variant,
            "image": image_for_variant(variant),
            "options": sandbox_image_options(),
        },
    }


@router.put("/settings/sandbox")
async def save_sandbox_settings(body: SandboxSettingsBody):
    variant = normalize_sandbox_variant(body.image_variant)
    try:
        saved_variant = write_sandbox_variant(_sandbox_settings_dir(), variant)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存沙箱设置失败: {e}")

    prewarm: Dict[str, Any] = {"validated": False}
    try:
        result = await _prewarm_current_user(
            reason="sandbox_image_saved",
            timeout_ms=max(60_000, _settings_validate_timeout_ms()),
        )
        if result is not None:
            prewarm = {"validated": True, **result}
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("sandbox_settings_validate_failed user=%s err=%s", get_current_username(), e)
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "code": "sandbox_image_switch_failed",
                "detail": f"已保存沙箱设置，但切换/预热沙箱失败：{e}",
                "data": {
                    "saved": True,
                    "image_variant": saved_variant,
                    "image": image_for_variant(saved_variant),
                    "validated": False,
                    "error": str(e),
                },
            },
        )
    return {
        "status": "ok",
        "data": {
            "saved": True,
            "image_variant": saved_variant,
            "image": image_for_variant(saved_variant),
            **prewarm,
        },
    }


@router.get("/settings/sandbox/requirements")
async def get_sandbox_requirements():
    path = _sandbox_requirements_path()
    if not path.exists():
        return {"status": "ok", "data": {"content": ""}}
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取 requirements.txt 失败: {e}")
    return {"status": "ok", "data": {"content": content}}


@router.put("/settings/sandbox/requirements")
async def save_sandbox_requirements(body: SandboxRequirementsBody):
    path = _sandbox_requirements_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.content or "", encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存 requirements.txt 失败: {e}")
    try:
        prewarm = await _prewarm_current_user(
            reason="requirements_saved",
            timeout_ms=max(120_000, _requirements_validate_timeout_ms()),
        )
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("sandbox_requirements_validate_failed user=%s err=%s", get_current_username(), e)
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "code": "sandbox_requirements_install_failed",
                "detail": sandbox_requirements_error_detail(e),
                "data": {"saved": True, "validated": False, "error": str(e)},
            },
        )
    if prewarm is None:
        return {"status": "ok", "data": {"saved": True, "validated": False}}
    return {"status": "ok", "data": {"saved": True, "validated": True, **prewarm}}


@router.post("/settings/sandbox/requirements/merge")
async def merge_sandbox_requirements(body: SandboxRequirementsMergeBody):
    incoming = [str(x or "").strip() for x in (body.requirements or []) if str(x or "").strip()]
    added, merged = merge_requirements_lines(_sandbox_requirements_path(), incoming)
    if not added:
        return {"status": "ok", "data": {"added": [], "content": merged, "saved": True, "validated": True}}
    try:
        prewarm = await _prewarm_current_user(
            reason="requirements_merged",
            timeout_ms=max(120_000, _requirements_validate_timeout_ms()),
        )
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("sandbox_requirements_merge_validate_failed user=%s err=%s", get_current_username(), e)
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "code": "sandbox_requirements_install_failed",
                "detail": sandbox_requirements_error_detail(e),
                "data": {"added": added, "content": merged, "saved": True, "validated": False, "error": str(e)},
            },
        )
    if prewarm is None:
        return {"status": "ok", "data": {"added": added, "content": merged, "saved": True, "validated": False}}
    return {"status": "ok", "data": {"added": added, "content": merged, "saved": True, "validated": True, **prewarm}}


@router.post("/settings/sandbox/requirements/status")
async def sandbox_requirements_status(body: SandboxRequirementsStatusBody):
    path = _sandbox_requirements_path()
    settings_content = ""
    if path.exists():
        try:
            settings_content = path.read_text(encoding="utf-8")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"读取 requirements.txt 失败: {e}")
    result = await asyncio.to_thread(
        resolve_dependency_status,
        settings_requirements=settings_content,
        skill_requirements=body.requirements or [],
    )
    return {"status": "ok", "data": result}
