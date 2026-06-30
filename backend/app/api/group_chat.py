from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.agents import load_agent_instances
from app.api.group_chat_state import build_archive_segments, load_group_history, load_group_meta

router = APIRouter(tags=["group_chat"])


async def get_group_archive(group_session_id: str):
    meta = load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    messages = load_group_history(group_session_id)
    instances = load_agent_instances()
    agent_map = {
        str(d.get("name") or "").strip(): {
            "name": str(d.get("name") or "").strip(),
            "description": d.get("description") or "",
        }
        for d in instances
        if str(d.get("name") or "").strip()
    }
    return {
        "status": "ok",
        "data": {
            "segments": build_archive_segments(messages),
            "agent_map": agent_map,
        },
    }


router.add_api_route(
    "/sessions/{group_session_id}/archive",
    get_group_archive,
    methods=["GET"],
)
