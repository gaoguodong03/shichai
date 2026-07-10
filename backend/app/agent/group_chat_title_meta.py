"""Title helpers for group chat."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List

from app.agent.messages import HumanMessage, SystemMessage  # type: ignore

from app.agent.group_context import (
    normalize_discussion_goal as _normalize_discussion_goal,
    title_from_first_message as _title_from_first_message,
)
from app.agent.llm_client import get_llm_from_config
from app.api.group_chat_state import (
    format_storage_timestamp,
    load_session_definitions as _load_session_definitions,
    save_group_history as _save_group_history,
    save_session_definitions as _save_session_definitions,
)
from app.agent.platform_prompts import render_platform_prompt
from app.api.settings_app import load_app_settings
from app.api.settings_env_vars import load_env_var_values
logger = logging.getLogger(__name__)


def _message_speaker_type(message: Dict[str, Any]) -> str:
    speaker = message.get("speaker") if isinstance(message.get("speaker"), dict) else {}
    return str(speaker.get("type") or "").strip()


def _message_content(message: Dict[str, Any]) -> str:
    """Read message text from the nested history shape."""
    body = message.get("message") if isinstance(message, dict) else None
    if isinstance(body, dict):
        return str(body.get("content") or "").strip()
    return ""


def _ensure_scene_profile_contract(session_item: Dict[str, Any]) -> bool:
    """No-op after the name-based session contract removed legacy upgrades."""
    _ = session_item
    return False


async def _ai_title_from_recent_user_messages(
    llm: Any,
    messages: List[Dict[str, Any]],
    max_chars: int = 18,
    max_user_messages: int = 6,
    group_session_id: str = "",
    llm_name: str = "",
) -> str:
    """Generate a short Chinese title from recent user messages."""
    try:
        user_texts: List[str] = []
        for m in reversed(messages or []):
            if not isinstance(m, dict):
                continue
            if _message_speaker_type(m) != "user":
                continue
            content = _message_content(m)
            if not content:
                continue
            user_texts.append(_normalize_discussion_goal(content))
            if len(user_texts) >= max_user_messages:
                break
        user_texts.reverse()
        if not user_texts:
            return ""

        client = llm.get_client()
        system_prompt = render_platform_prompt("title.group_topic.v1", {"max_chars": max_chars})
        content = "最近用户发言：\n" + "\n\n".join([f"{i+1}. {t}" for i, t in enumerate(user_texts)])
        resp = await client.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=content)])
        raw = (getattr(resp, "content", "") or "").strip()
        if not raw:
            return ""
        title = raw.splitlines()[0].strip()
        title = re.sub(r"^(主题|讨论主题|标题|群聊主题|当前主题)\s*[:：]\s*", "", title)
        title = title.strip().strip("“”\"'（）()[]【】")
        while title and title[-1] in "。！？…":
            title = title[:-1].strip()
        if len(title) > max_chars:
            title = title[:max_chars].rstrip()
        return title
    except Exception as e:
        logger.error("AI 生成群聊主题失败: %s", e, exc_info=True)
        return ""


def _schedule_group_title_refresh(
    group_session_id: str,
    messages_snapshot: List[Dict[str, Any]],
    *,
    max_chars: int = 18,
    max_user_messages: int = 6,
) -> None:
    """Refresh group title in the background so the main chat path stays responsive."""
    session_id = (group_session_id or "").strip()
    if not session_id:
        return

    async def _runner() -> None:
        started = time.perf_counter()
        try:
            app_settings = load_app_settings()
            llm_name = app_settings.get("default_llm", "qwen3-max")
            env_vars = load_env_var_values()
            llm = get_llm_from_config(llm_name, app_settings.get("llm_providers"), env_vars)
            ai_title = await _ai_title_from_recent_user_messages(
                llm,
                messages_snapshot,
                max_chars=max_chars,
                max_user_messages=max_user_messages,
                group_session_id=session_id,
                llm_name=str(llm_name or ""),
            )
            if not ai_title:
                logger.info(
                    "group_chat_title_background_skip session=%s reason=empty elapsed_ms=%s",
                    session_id,
                    int((time.perf_counter() - started) * 1000),
                )
                return
            latest_session_definitions = _load_session_definitions()
            session_item = latest_session_definitions.get(session_id)
            if not isinstance(session_item, dict):
                return
            current_title = (session_item.get("title") or "").strip()
            title_auto_generated = session_item.get("title_auto_generated") is True
            if not title_auto_generated:
                logger.info(
                    "group_chat_title_background_skip session=%s reason=manual_title title=%r",
                    session_id,
                    current_title,
                )
                return
            session_item["title"] = ai_title
            session_item["title_auto_generated"] = True
            _save_session_definitions(latest_session_definitions)
            logger.debug(
                "group_chat_title_background_done session=%s title=%r elapsed_ms=%s",
                session_id,
                ai_title,
                int((time.perf_counter() - started) * 1000),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("group_chat_title_background_failed session=%s err=%s", session_id, e)

    asyncio.create_task(_runner())


def _title_refresh_every_user_message() -> bool:
    return (os.getenv("GROUP_CHAT_TITLE_REFRESH_EVERY_MESSAGE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _record_user_message_and_refresh_title(
    *,
    group_session_id: str,
    session_definitions: Dict[str, Dict[str, Any]],
    messages: List[Dict[str, Any]],
    user_message: str,
    client_message_id: str,
    attachments: List[Dict[str, Any]] | None = None,
    target_agent_name: str | None = None,
) -> None:
    """Append a user message once and schedule title refresh while title is automatic."""
    if not user_message and not attachments and not target_agent_name:
        return
    session_item = session_definitions[group_session_id]
    duplicate_user_message = bool(
        client_message_id
        and any(
            _message_speaker_type(msg) == "user" and str(msg.get("client_message_id") or "").strip() == client_message_id
            for msg in messages
        )
    )
    first_user_message = not any(_message_speaker_type(m) == "user" for m in messages)
    if not duplicate_user_message:
        message_body: Dict[str, Any] = {"content": user_message}
        if attachments:
            message_body["attachments"] = list(attachments)
        if target_agent_name:
            message_body["target_agent_name"] = target_agent_name
        user_msg: Dict[str, Any] = {
            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
            "speaker": {"type": "user"},
            "message": message_body,
            "created_at": format_storage_timestamp(),
        }
        if client_message_id:
            user_msg["client_message_id"] = client_message_id
        messages.append(user_msg)
        _save_group_history(group_session_id, messages, checkpoint_trigger="turn_started")
        session_item["updated_at"] = format_storage_timestamp()

    current_title = (session_item.get("title") or "").strip()
    title_auto_generated = session_item.get("title_auto_generated") is True
    should_refresh_title = bool(
        not duplicate_user_message
        and (
            (first_user_message and title_auto_generated)
            or (title_auto_generated and _title_refresh_every_user_message())
        )
    )
    if should_refresh_title and first_user_message:
        auto_title = _title_from_first_message(user_message, max_chars=10)
        if auto_title:
            session_item["title"] = auto_title
            session_item["title_auto_generated"] = True
    _save_session_definitions(session_definitions)
    if should_refresh_title:
        _schedule_group_title_refresh(
            group_session_id,
            list(messages),
            max_chars=18,
            max_user_messages=6,
        )
