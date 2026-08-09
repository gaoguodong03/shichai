"""Canonical host messages built from the strict scheduler message body."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


HOST_ZERO_EXPERT_RECOMMENDATION = "当前会话还没有专家，请先邀请专家后继续。"


def build_zero_expert_selection_prompt(agent_names: Sequence[str]) -> str:
    """Compose the empty-session host prompt; names are offered via UI, not inline text."""
    names = [str(name or "").strip() for name in agent_names or [] if str(name or "").strip()]
    if not names:
        return HOST_ZERO_EXPERT_RECOMMENDATION
    return "当前会话还没有专家。请从下述专家中选择并邀请进入。"


def _now_storage_timestamp() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d%H%M%S") + f"{dt.microsecond // 10000:02d}"


def _build_host_scheduler_message(
    *,
    message: Mapping[str, Any],
    host_agent_name: str,
    skill: str = "",
) -> dict[str, Any]:
    """Wrap one validated scheduler MessageBody in ChatMessageRecord."""
    speaker: dict[str, Any] = {
        "type": "host",
        "agent_name": str(host_agent_name or "四九").strip() or "四九",
    }
    skill_directory = str(skill or "").strip()
    if skill_directory:
        speaker["skill"] = skill_directory
    return {
        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
        "speaker": speaker,
        "message": dict(message),
        "created_at": _now_storage_timestamp(),
    }


def _build_host_recommendation_message(
    *,
    skill: str,
    content: str,
    picked: Sequence[str],
    host_agent_name: str = "",
) -> dict[str, Any]:
    _ = picked
    return _build_host_scheduler_message(
        message={"content": content or HOST_ZERO_EXPERT_RECOMMENDATION},
        host_agent_name=host_agent_name or "四九",
        skill=skill,
    )


def _build_host_notice_message(
    *,
    skill: str,
    content: str,
    host_agent_name: str = "",
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _ = meta
    return _build_host_scheduler_message(
        message={"content": content},
        host_agent_name=host_agent_name,
        skill=skill,
    )
