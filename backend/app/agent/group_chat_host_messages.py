from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.core.scene_scheduler import RECRUIT_FIXED_MESSAGE

_GENERIC_HOST_ANNOUNCEMENTS = frozenset({"", "请下一位发言。", "请下一位发言", "请下一位发言。 "})


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


def _append_suggested_order_if_needed(
    content: str,
    suggested_order: Any,
    agent_map: Mapping[str, Mapping[str, Any]],
) -> str:
    if not isinstance(suggested_order, list) or not suggested_order:
        return content
    ordered_names: list[str] = []
    for aid in suggested_order:
        sid = str(aid or "").strip()
        if not sid:
            continue
        ordered_names.append(_agent_display_name(sid, agent_map))
    if not ordered_names:
        return content
    has_list_marker = ("1." in content) or ("- " in content)
    if has_list_marker:
        return content
    lines = [f"{idx + 1}. {name}" for idx, name in enumerate(ordered_names[:5])]
    return (content.rstrip() + "\n\n" + "建议顺序：\n" + "\n".join(lines)).strip()


def _build_host_recruit_message(
    *,
    skill_id: str,
    suggested_add: Sequence[str],
    leader_agent_id: str = "",
) -> dict[str, Any]:
    msg = _host_message_base(content=RECRUIT_FIXED_MESSAGE, skill_id=skill_id, leader_agent_id=leader_agent_id)
    msg["suggested_add_agent_ids"] = list(suggested_add or [])
    return msg


def _build_host_next_speaker_message(
    *,
    skill_id: str,
    next_speaker: str,
    agent_map: Mapping[str, Mapping[str, Any]],
    announcement: str | None = None,
    suggested_order: Any = None,
    leader_agent_id: str = "",
) -> dict[str, Any]:
    next_name = _agent_display_name(next_speaker, agent_map)
    ann = (announcement or "").strip()
    content = f"下面由 {next_name} 发言。" if not ann or ann in _GENERIC_HOST_ANNOUNCEMENTS else ann
    content = _append_suggested_order_if_needed(content, suggested_order, agent_map)
    msg = _host_message_base(content=content, skill_id=skill_id, leader_agent_id=leader_agent_id)
    msg["next_agent_name"] = next_name
    if suggested_order:
        msg["suggested_order"] = suggested_order
    return msg


def _build_host_pause_message(
    *,
    skill_id: str,
    next_speaker: str,
    announcement: str | None = None,
    reason: str | None = None,
    leader_agent_id: str = "",
) -> dict[str, Any] | None:
    ann = (announcement or "").strip()
    if (not ann or ann in _GENERIC_HOST_ANNOUNCEMENTS) and next_speaker == "user":
        reason_text = str(reason or "").strip()
        ann = (
            f"已暂停自动推进：{reason_text}\n\n请补充更具体要求，或直接指定下一位专家继续。"
            if reason_text
            else "已暂停自动推进，请补充更具体要求，或直接指定下一位专家继续。"
        )
    if not ann or ann in _GENERIC_HOST_ANNOUNCEMENTS:
        return None
    return _host_message_base(content=ann, skill_id=skill_id, leader_agent_id=leader_agent_id)


def _build_host_recommendation_message(
    *,
    skill_id: str,
    content: str,
    picked: Sequence[str],
) -> dict[str, Any]:
    msg = _host_message_base(content=content, skill_id=skill_id)
    if picked:
        msg["suggested_add_agent_ids"] = list(picked)
    return msg


def _build_host_fallback_message(*, skill_id: str, leader_agent_id: str = "") -> dict[str, Any]:
    return _host_message_base(
        content="主持人暂未选出下一位专家，已暂停自动推进。请补充更具体要求，或直接指定下一位专家继续。",
        skill_id=skill_id,
        leader_agent_id=leader_agent_id,
        meta={"reason": "next_speaker_missing"},
    )


def _build_host_notice_message(
    *,
    skill_id: str,
    content: str,
    leader_agent_id: str = "",
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _host_message_base(content=content, skill_id=skill_id, leader_agent_id=leader_agent_id, meta=meta)
