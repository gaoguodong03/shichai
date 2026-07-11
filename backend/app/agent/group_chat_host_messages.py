"""Canonical host message builders for the group-chat history contract."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

HOST_DELEGATE_PREFIX = "下面由"
HOST_END_MESSAGE = "任务结束。"
HOST_USER_PAUSE_MESSAGE = "请继续补充你的需求。"
HOST_ZERO_EXPERT_RECOMMENDATION = "当前会话还没有专家，请先邀请专家后继续。"


def _now_storage_timestamp() -> str:
    """Return the compact UTC timestamp used by session storage."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d%H%M%S") + f"{dt.microsecond // 10000:02d}"


def _host_message_base(
    *,
    content: str,
    host_agent_name: str,
    skill: str = "",
    current_phase: str = "",
    next_speaker: str = "",
    next_action: str = "",
) -> dict[str, Any]:
    """Build one host message in the current nested ChatMessageRecord shape."""
    message_content = str(content or "").strip()
    if not message_content:
        message_content = HOST_USER_PAUSE_MESSAGE
    speaker: dict[str, Any] = {"type": "host", "agent_name": str(host_agent_name or "四九").strip() or "四九"}
    skill_directory = str(skill or "").strip()
    row: dict[str, Any] = {
        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
        "speaker": speaker,
        "message": {"content": message_content},
        "created_at": _now_storage_timestamp(),
    }
    if skill_directory:
        speaker["skill"] = skill_directory
        row["skill_result"] = {
            "execution_status": "succeeded",
            "content": message_content,
            "artifacts": [],
            "next_action": {
                "handoff": "host",
                "resume": "none",
                "reason": "stage_completed",
                "instruction": message_content,
            },
        }
    return row


def _agent_display_name(agent_name: str, agent_map: Mapping[str, Mapping[str, Any]]) -> str:
    """Resolve the display name for an expert without changing the identity field."""
    agent = agent_map.get(agent_name)
    if isinstance(agent, Mapping):
        return str(agent.get("name") or agent_name)
    return agent_name


def _build_host_recruit_message(
    *,
    skill: str,
    suggested_add: Sequence[str],
    host_agent_name: str = "",
) -> dict[str, Any] | None:
    """Recruiting is represented by the SSE end payload, not a history message."""
    _ = (skill, suggested_add, host_agent_name)
    return None


def _build_host_next_speaker_message(
    *,
    skill: str,
    next_speaker: str,
    agent_map: Mapping[str, Mapping[str, Any]],
    current_phase: str | None = None,
    next_action: str | None = None,
    host_agent_name: str = "",
) -> dict[str, Any]:
    """Build the fixed host handoff bubble for an expert turn."""
    action = str(next_action or "").strip()
    if str(next_speaker or "").strip().lower() == "end" or str(current_phase or "").strip().lower() == "end":
        return _build_host_pause_message(
            skill=skill,
            next_speaker="end",
            current_phase=current_phase or "end",
            next_action=action,
            host_agent_name=host_agent_name,
        ) or _host_message_base(content=HOST_END_MESSAGE, host_agent_name=host_agent_name, skill=skill)
    next_name = _agent_display_name(next_speaker, agent_map)
    return _host_message_base(
        content=f"{HOST_DELEGATE_PREFIX} {next_name} 发言。",
        host_agent_name=host_agent_name,
        skill=skill,
        current_phase=str(current_phase or ""),
        next_speaker=next_speaker,
        next_action=action,
    )


def _build_host_pause_message(
    *,
    skill: str,
    next_speaker: str,
    current_phase: str | None = None,
    next_action: str | None = None,
    host_agent_name: str = "",
) -> dict[str, Any] | None:
    """Build a host pause or completion message for user-visible scheduler output."""
    action = str(next_action or "").strip()
    if str(next_speaker or "").strip().lower() == "end" or str(current_phase or "").strip().lower() == "end":
        return _host_message_base(
            content=action or HOST_END_MESSAGE,
            host_agent_name=host_agent_name,
            skill=skill,
            current_phase=str(current_phase or "end"),
            next_speaker="end",
            next_action=action,
        )
    if str(next_speaker or "").strip().lower() == "user":
        return _host_message_base(
            content=action or HOST_USER_PAUSE_MESSAGE,
            host_agent_name=host_agent_name,
            skill=skill,
            current_phase=str(current_phase or ""),
            next_speaker="user",
            next_action=action,
        )
    return None


def _build_host_recommendation_message(
    *,
    skill: str,
    content: str,
    picked: Sequence[str],
    host_agent_name: str = "",
) -> dict[str, Any]:
    """Build the no-expert host message."""
    _ = picked
    return _host_message_base(content=content or HOST_ZERO_EXPERT_RECOMMENDATION, host_agent_name=host_agent_name or "四九", skill=skill)


def _build_host_notice_message(
    *,
    skill: str,
    content: str,
    host_agent_name: str = "",
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a host notice from platform or credential errors."""
    _ = meta
    return _host_message_base(content=content, host_agent_name=host_agent_name, skill=skill)
