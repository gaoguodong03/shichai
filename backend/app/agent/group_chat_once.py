"""Non-stream group-chat aggregation built from the current SSE contract."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.agent.group_chat_runtime import group_chat_stream
from app.agent.session_contracts import GroupChatRequest, SseErrorEvent

logger = logging.getLogger(__name__)


async def group_chat_once(session_id: str, request: GroupChatRequest) -> Dict[str, Any]:
    """Aggregate the strict group-chat SSE stream into the non-stream response shape."""
    stream_resp = await group_chat_stream(session_id, request)
    body_iter = getattr(stream_resp, "body_iterator", None)
    if body_iter is None:
        raise HTTPException(status_code=500, detail="chat stream aggregation unavailable")

    route_event: Optional[Dict[str, Any]] = None
    progress_events: List[Dict[str, Any]] = []
    message_events: List[Dict[str, Any]] = []
    end_event: Optional[Dict[str, Any]] = None
    error_event: Optional[Dict[str, Any]] = None

    buffer = ""
    try:
        async for chunk in body_iter:
            part = chunk.decode("utf-8", errors="ignore") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
            buffer += part.replace("\r", "")
            blocks = buffer.split("\n\n")
            buffer = blocks.pop() or ""
            for block_raw in blocks:
                block = block_raw.strip()
                if not block.startswith("event: "):
                    continue
                event_type = (block.split("\n")[0] or "").replace("event: ", "").strip()
                data_lines = [line[6:].strip() for line in block.split("\n") if line.startswith("data: ")]
                data_str = "\n".join(data_lines).strip()
                if not data_str:
                    continue
                try:
                    payload = json.loads(data_str)
                except Exception:
                    continue
                if event_type == "route":
                    route_event = payload
                elif event_type == "progress":
                    progress_events.append(payload)
                elif event_type == "message":
                    message_events.append(payload)
                elif event_type == "end":
                    end_event = payload
                elif event_type == "error":
                    error_event = payload
    except asyncio.CancelledError as exc:
        logger.warning("session_chat_once 聚合流被取消: session=%s err=%s", session_id, exc)
        error_event = error_event or SseErrorEvent(
            type="error",
            run_id=None,
            code="chat_once_cancelled",
            message=str(exc) or "chat once stream cancelled",
        ).model_dump(exclude_none=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("session_chat_once 聚合流失败: session=%s err=%s", session_id, exc)
        error_event = error_event or SseErrorEvent(
            type="error",
            run_id=None,
            code="chat_once_stream_error",
            message=str(exc) or exc.__class__.__name__,
        ).model_dump(exclude_none=False)

    primary_message = message_events[-1] if message_events else None
    route_agent_name = route_event.get("agent_name") if isinstance(route_event, dict) else None
    if route_agent_name:
        primary_message = next(
            (
                msg
                for msg in reversed(message_events)
                if isinstance(msg.get("speaker"), dict)
                and str((msg.get("speaker") or {}).get("agent_name") or "").strip() == route_agent_name
            ),
            primary_message,
        )

    return {
        "status": "ok",
        "data": {
            "route": route_event,
            "progress": progress_events,
            "messages": message_events,
            "message": primary_message,
            "end": end_event,
            "error": error_event,
        },
    }
