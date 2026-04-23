"""无需登录的公开分享：元数据与分享包下载。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.scenario_share_store import (
    bundle_path_for_share,
    get_share_entry,
    validate_share_id,
)

router = APIRouter(tags=["public-scenarios"])


@router.get("/public/scenarios/{share_id}")
async def public_scenario_meta(share_id: str):
    # 兼容旧路由：scene 专用元数据
    if not validate_share_id(share_id):
        raise HTTPException(status_code=404, detail="未找到")
    e = get_share_entry(share_id)
    if not e:
        raise HTTPException(status_code=404, detail="未找到")
    return {
        "status": "ok",
        "data": {
            "share_id": share_id,
            "preset_name": str(e.get("preset_name") or ""),
            "source_preset_id": str(e.get("source_preset_id") or ""),
            "created_at": str(e.get("created_at") or ""),
        },
    }


@router.get("/public/scenarios/{share_id}/bundle")
async def public_scenario_bundle(share_id: str):
    # 兼容旧路由：scene 专用 bundle 下载
    if not validate_share_id(share_id):
        raise HTTPException(status_code=404, detail="未找到")
    p = bundle_path_for_share(share_id)
    if not p:
        raise HTTPException(status_code=404, detail="未找到")
    return FileResponse(
        path=p,
        filename=f"scenario-share-{share_id}.zip",
        media_type="application/zip",
    )


@router.get("/public/shares/{share_id}/meta")
async def public_share_meta(share_id: str):
    if not validate_share_id(share_id):
        raise HTTPException(status_code=404, detail="未找到")
    e = get_share_entry(share_id)
    if not e:
        raise HTTPException(status_code=404, detail="未找到")
    object_type = str(e.get("object_type") or "scene")
    source_ref = str(e.get("source_ref") or e.get("source_preset_id") or "")
    return {
        "status": "ok",
        "data": {
            "share_id": share_id,
            "object_type": object_type,
            "source_ref": source_ref,
            "title": str(
                e.get("title")
                or e.get("preset_name")
                or e.get("expert_name")
                or e.get("skill_name")
                or e.get("mcp_name")
                or source_ref
            ),
            "summary": e.get("summary") if isinstance(e.get("summary"), dict) else {},
            "created_at": str(e.get("created_at") or ""),
        },
    }


@router.get("/public/shares/{share_id}/bundle")
async def public_share_bundle(share_id: str):
    if not validate_share_id(share_id):
        raise HTTPException(status_code=404, detail="未找到")
    p = bundle_path_for_share(share_id)
    if not p:
        raise HTTPException(status_code=404, detail="未找到")
    return FileResponse(
        path=p,
        filename=f"share-{share_id}.zip",
        media_type="application/zip",
    )
