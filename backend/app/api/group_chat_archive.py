"""Group-chat archive view helpers.

This module shapes canonical chat messages into export/archive segments. It does
not read or write session files; storage remains owned by `group_chat_state.py`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_archive_segments(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group messages into archive segments by user turn, excluding host messages."""
    segments: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def _ensure_current() -> Dict[str, Any]:
        nonlocal current
        if current is None:
            current = {
                "user": None,
                "experts": {},
            }
        return current

    def _flush() -> None:
        nonlocal current
        if not current:
            current = None
            return
        has_user = bool(current.get("user"))
        experts = current.get("experts") or {}
        has_expert = any((v.get("messages") or []) for v in experts.values()) if isinstance(experts, dict) else False
        if has_user or has_expert:
            expert_list = []
            if isinstance(experts, dict):
                for _, value in experts.items():
                    if isinstance(value, dict):
                        expert_list.append(value)
            segments.append(
                {
                    "user": current.get("user"),
                    "experts": expert_list,
                }
            )
        current = None

    for message in messages or []:
        if not isinstance(message, dict):
            continue
        speaker = message.get("speaker") if isinstance(message.get("speaker"), dict) else {}
        speaker_type = str(speaker.get("type") or "").strip()
        if speaker_type == "host":
            continue
        if speaker_type == "user":
            _flush()
            cur = _ensure_current()
            cur["user"] = {
                "message_id": message.get("message_id"),
                "content": _message_content(message),
                "created_at": message.get("created_at"),
            }
            continue
        if speaker_type == "expert":
            cur = _ensure_current()
            agent_name = str(speaker.get("agent_name") or "").strip()
            if not agent_name:
                continue
            experts = cur.get("experts")
            if not isinstance(experts, dict):
                experts = {}
                cur["experts"] = experts
            if agent_name not in experts:
                experts[agent_name] = {"agent_name": agent_name, "messages": []}
            item = {
                "message_id": message.get("message_id"),
                "content": _message_content(message),
                "created_at": message.get("created_at"),
            }
            if speaker.get("skill") is not None:
                item["skill"] = speaker.get("skill")
            experts[agent_name]["messages"].append(item)

    _flush()
    return segments


def _message_content(message: Dict[str, Any]) -> str:
    body = message.get("message") if isinstance(message.get("message"), dict) else {}
    return str(body.get("content") or "")
