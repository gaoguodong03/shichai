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


def _scheduler_state_snapshot(
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
    skill: str,
    leader_agent_name: str = "",
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    speaker: dict[str, Any] = {"type": "host"}
    if leader_agent_name:
        speaker["agent_name"] = leader_agent_name
    msg: dict[str, Any] = {
        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
        "speaker": speaker,
        "content": content,
        "created_at": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "00",
    }
    meta_payload = dict(meta or {})
    scheduler_state = meta_payload.pop("scheduler_state", None)
    if isinstance(scheduler_state, Mapping):
        current_phase = str(scheduler_state.get("current_phase") or "").strip()
        next_speaker = str(scheduler_state.get("next_speaker") or "").strip()
        if current_phase and next_speaker:
            msg["routing"] = {
                "scheduler_state": {
                    "current_phase": current_phase,
                    "next_speaker": next_speaker,
                    "speaker_task": str(scheduler_state.get("speaker_task") or "").strip(),
                }
            }
    if meta_payload:
        msg["debug"] = {
            "tool_trace": [
                {
                    "event": "host_notice",
                    "tool_name": skill,
                    "data": meta_payload,
                }
            ]
        }
    return msg


def _merge_host_route_debug(msg: dict[str, Any], values: Mapping[str, Any]) -> None:
    cleaned = {str(k): v for k, v in values.items() if v not in (None, "", [])}
    if not cleaned:
        return
    routing = msg.setdefault("routing", {})
    route_debug = routing.setdefault("expert_route_debug", {})
    if isinstance(route_debug, dict):
        route_debug.update(cleaned)


def _agent_display_name(agent_name: str, agent_map: Mapping[str, Mapping[str, Any]]) -> str:
    agent = agent_map.get(agent_name)
    if isinstance(agent, Mapping):
        return str(agent.get("name") or agent_name)
    return agent_name


def _build_host_recruit_message(
    *,
    skill: str,
    suggested_add: Sequence[str],
    leader_agent_name: str = "",
) -> dict[str, Any] | None:
    # 主持人仅三种固定话术；场内补人不单独发气泡，由系统邀请状态提示用户。
    _ = (skill, suggested_add, leader_agent_name)
    return None


def _build_host_next_speaker_message(
    *,
    skill: str,
    next_speaker: str,
    agent_map: Mapping[str, Mapping[str, Any]],
    announcement: str | None = None,
    current_phase: str | None = None,
    speaker_task: str | None = None,
    suggested_order: Any = None,
    leader_agent_name: str = "",
) -> dict[str, Any]:
    if _is_task_end(next_speaker=next_speaker, current_phase=current_phase):
        pause = _build_host_pause_message(
            skill=skill,
            next_speaker="end",
            current_phase=current_phase or "end",
            speaker_task=speaker_task,
            leader_agent_name=leader_agent_name,
        )
        if pause is not None:
            return pause
    _ = announcement
    next_name = _agent_display_name(next_speaker, agent_map)
    content = f"{HOST_DELEGATE_PREFIX} {next_name} 发言。"
    meta = _scheduler_state_snapshot(
        current_phase=current_phase,
        next_speaker=next_speaker,
        speaker_task=speaker_task,
    )
    msg = _host_message_base(content=content, skill=skill, leader_agent_name=leader_agent_name, meta=meta)
    _merge_host_route_debug(
        msg,
        {
            "next_agent_name": next_name,
            "suggested_order": suggested_order,
        },
    )
    return msg


def _build_host_pause_message(
    *,
    skill: str,
    next_speaker: str,
    announcement: str | None = None,
    current_phase: str | None = None,
    reason: str | None = None,
    speaker_task: str | None = None,
    leader_agent_name: str = "",
) -> dict[str, Any] | None:
    _ = announcement
    if _is_task_end(next_speaker=next_speaker, current_phase=current_phase):
        meta = _scheduler_state_snapshot(
            current_phase=current_phase or "end",
            next_speaker="end",
            speaker_task=speaker_task,
        )
        return _host_message_base(
            content=HOST_END_MESSAGE,
            skill=skill,
            leader_agent_name=leader_agent_name,
            meta=meta,
        )
    if str(next_speaker or "").strip().lower() == "user":
        content = str(speaker_task or reason or "").strip() or HOST_USER_PAUSE_MESSAGE
        meta = _scheduler_state_snapshot(
            current_phase=current_phase,
            next_speaker="user",
            speaker_task=speaker_task,
        )
        return _host_message_base(
            content=content,
            skill=skill,
            leader_agent_name=leader_agent_name,
            meta=meta,
        )
    return None


def _build_host_recommendation_message(
    *,
    skill: str,
    content: str,
    picked: Sequence[str],
) -> dict[str, Any]:
    _ = content
    msg = _host_message_base(content=HOST_ZERO_EXPERT_RECOMMENDATION, skill=skill)
    if picked:
        _merge_host_route_debug(msg, {"suggested_add_agent_names": list(picked)})
    return msg


def _build_host_fallback_message(*, skill: str, leader_agent_name: str = "") -> dict[str, Any] | None:
    _ = (skill, leader_agent_name)
    return None


def _build_host_notice_message(
    *,
    skill: str,
    content: str,
    leader_agent_name: str = "",
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _host_message_base(content=content, skill=skill, leader_agent_name=leader_agent_name, meta=meta)
