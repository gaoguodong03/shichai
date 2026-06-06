"""Group-chat API shell.

The runtime implementation lives in ``app.agent.group_chat_runtime`` so this
module stays small enough to audit as a route boundary.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.agent.group_chat_runtime import (
    GroupChatRequest,
    _ACTIVE_GROUP_RUNS,
    _GROUP_SESSION_EVENT_SUBSCRIBERS,
    _GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK,
    _clear_completed_skill_session_lock_from_history,
    _iter_with_keepalive,
    _publish_group_session_event,
    _store_skill_session_lock_for_turn,
    _stream_background_events,
    get_group_archive,
    group_chat_stream,
)
from app.agent.group_session_service import (
    GroupSessionUpdate,
    _build_session_payload,
    _load_group_meta,
    create_session_internal,
    delete_group_message,
    delete_group_session,
    export_session_to_markdown,
    get_group_session,
    group_session_events_stream,
    stop_group_session_run,
    update_group_session,
)

router = APIRouter(tags=["group_chat"])
router.add_api_route(
    "/sessions/{group_session_id}/archive",
    get_group_archive,
    methods=["GET"],
)

__all__ = [
    "GroupChatRequest",
    "GroupSessionUpdate",
    "_ACTIVE_GROUP_RUNS",
    "_GROUP_SESSION_EVENT_SUBSCRIBERS",
    "_GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK",
    "_build_session_payload",
    "_clear_completed_skill_session_lock_from_history",
    "_iter_with_keepalive",
    "_load_group_meta",
    "_publish_group_session_event",
    "_store_skill_session_lock_for_turn",
    "_stream_background_events",
    "create_session_internal",
    "delete_group_message",
    "delete_group_session",
    "export_session_to_markdown",
    "get_group_archive",
    "get_group_session",
    "group_chat_stream",
    "group_session_events_stream",
    "router",
    "stop_group_session_run",
    "update_group_session",
]
