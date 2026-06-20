from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

HOST_DELEGATE_PREFIX = "下面由"
HOST_END_MESSAGE = "任务结束，请打开新对话。"
HOST_USER_PAUSE_MESSAGE = "请继续补充你的需求。"
HOST_ZERO_EXPERT_RECOMMENDATION = (
    "我推荐以下专家加入讨论：\n\n"
    "文字创作专家 (核心角色) — 负责与你确认文章方向、搭建大纲、撰写正文、后续的续写/改写/润色。\n"
    "信息检索专家 (辅助角色) — 如果需要查找资料、核实数据、或者参考其他文章素材，他可以提供支持。\n"
    "图片生成专家 (可选角色) — 如果文章需要配图，可以在文字完成后请他生成合适的图片并排版。"
)


def _is_task_end(*, next_speaker: str, current_phase: str | None = None) -> bool:
    if str(next_speaker or "").strip().lower() == "end":
        return True
    return str(current_phase or "").strip().lower() == "end"


def _scheduler_state_meta(
    meta: Mapping[str, Any] | None = None,
    *,
    current_phase: str | None = None,
    next_speaker: str | None = None,
    speaker_task: str | None = None,
) -> dict[str, Any] | None:
    out: dict[str, Any] = dict(meta or {})
    state = {
        "current_phase": str(current_phase or "").strip(),
        "next_speaker": str(next_speaker or "").strip(),
        "speaker_task": str(speaker_task or "").strip(),
    }
    if any(state.values()):
        out["scheduler_state"] = state
    return out or None


def _host_message_base(
    *,
    content: str,
    skill_id: str,
    leader_agent_id: str = "",
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
        "role": "host",
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill_id": skill_id,
    }
    if leader_agent_id:
        msg["agent_id"] = leader_agent_id
    if meta:
        msg["meta"] = dict(meta)
    return msg


def _agent_display_name(agent_id: str, agent_map: Mapping[str, Mapping[str, Any]]) -> str:
    agent = agent_map.get(agent_id)
    if isinstance(agent, Mapping):
        return str(agent.get("name") or agent_id)
    return agent_id


def _build_host_recruit_message(
    *,
    skill_id: str,
    suggested_add: Sequence[str],
    leader_agent_id: str = "",
) -> dict[str, Any] | None:
    # 主持人仅三种固定话术；场内补人不单独发气泡，由系统邀请状态提示用户。
    _ = (skill_id, suggested_add, leader_agent_id)
    return None


def _build_host_next_speaker_message(
    *,
    skill_id: str,
    next_speaker: str,
    agent_map: Mapping[str, Mapping[str, Any]],
    announcement: str | None = None,
    current_phase: str | None = None,
    speaker_task: str | None = None,
    suggested_order: Any = None,
    leader_agent_id: str = "",
) -> dict[str, Any]:
    if _is_task_end(next_speaker=next_speaker, current_phase=current_phase):
        pause = _build_host_pause_message(
            skill_id=skill_id,
            next_speaker="end",
            current_phase=current_phase or "end",
            speaker_task=speaker_task,
            leader_agent_id=leader_agent_id,
        )
        if pause is not None:
            return pause
    _ = announcement
    next_name = _agent_display_name(next_speaker, agent_map)
    content = f"{HOST_DELEGATE_PREFIX} {next_name} 发言。"
    meta = _scheduler_state_meta(
        current_phase=current_phase,
        next_speaker=next_speaker,
        speaker_task=speaker_task,
    )
    msg = _host_message_base(content=content, skill_id=skill_id, leader_agent_id=leader_agent_id, meta=meta)
    msg["next_agent_name"] = next_name
    if suggested_order:
        msg["suggested_order"] = suggested_order
    return msg


def _build_host_pause_message(
    *,
    skill_id: str,
    next_speaker: str,
    announcement: str | None = None,
    current_phase: str | None = None,
    reason: str | None = None,
    speaker_task: str | None = None,
    leader_agent_id: str = "",
) -> dict[str, Any] | None:
    _ = announcement
    if _is_task_end(next_speaker=next_speaker, current_phase=current_phase):
        meta = _scheduler_state_meta(
            current_phase=current_phase or "end",
            next_speaker="end",
            speaker_task=speaker_task,
        )
        return _host_message_base(
            content=HOST_END_MESSAGE,
            skill_id=skill_id,
            leader_agent_id=leader_agent_id,
            meta=meta,
        )
    if str(next_speaker or "").strip().lower() == "user":
        content = str(speaker_task or reason or "").strip() or HOST_USER_PAUSE_MESSAGE
        meta = _scheduler_state_meta(
            current_phase=current_phase,
            next_speaker="user",
            speaker_task=speaker_task,
        )
        return _host_message_base(
            content=content,
            skill_id=skill_id,
            leader_agent_id=leader_agent_id,
            meta=meta,
        )
    return None


def _build_host_recommendation_message(
    *,
    skill_id: str,
    content: str,
    picked: Sequence[str],
) -> dict[str, Any]:
    _ = content
    msg = _host_message_base(content=HOST_ZERO_EXPERT_RECOMMENDATION, skill_id=skill_id)
    if picked:
        msg["suggested_add_agent_ids"] = list(picked)
    return msg


def _build_host_fallback_message(*, skill_id: str, leader_agent_id: str = "") -> dict[str, Any] | None:
    _ = (skill_id, leader_agent_id)
    return None


def _build_host_notice_message(
    *,
    skill_id: str,
    content: str,
    leader_agent_id: str = "",
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _host_message_base(content=content, skill_id=skill_id, leader_agent_id=leader_agent_id, meta=meta)
