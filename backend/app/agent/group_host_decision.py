"""Pure host-decision parsing helpers for group chat.

This file accepts only the host JSON contract from
docs/contracts/runtime-interface-contract.md. It rejects every field outside
the current next_action protocol.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.structured_output_contracts import (
    HostSchedulerDecisionPayload,
    StructuredOutputProtocolError,
    parse_strict_pydantic_object,
)


HOST_PROTOCOL_ERROR_MESSAGE = "主持人输出格式错误，请重试或联系管理员。"


def host_protocol_error_decision(reason: str = "protocol_error") -> Dict[str, Any]:
    """Return the canonical protection decision for invalid host JSON."""
    return {
        "next_speaker": "user",
        "current_phase": "",
        "next_action": HOST_PROTOCOL_ERROR_MESSAGE,
        "suggested_add_agent_names": [],
    }


def _agent_name_map(agent_profiles: List[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for profile in agent_profiles or []:
        name = str((profile or {}).get("name") or "").strip()
        if name:
            out[name.casefold()] = name
    return out


def _strict_host_decision_from_payload(
    payload: HostSchedulerDecisionPayload,
    agent_profiles: List[Dict[str, Any]],
    *,
    host_mode: str = "recruitment",
) -> Dict[str, Any]:
    """Validate host routing against current session members and return canonical fields."""
    scene_mode = str(host_mode or "").strip().lower() == "scene"
    raw_next = payload.next_speaker.strip()
    next_key = raw_next.casefold()
    names = _agent_name_map(agent_profiles)
    suggested = list(payload.suggested_add_agent_names or [])
    if scene_mode and suggested:
        raise StructuredOutputProtocolError("scene mode forbids suggested_add_agent_names", schema_name="HostSchedulerDecisionPayload")
    if suggested and next_key != "user":
        raise StructuredOutputProtocolError("suggested_add_agent_names requires next_speaker=user", schema_name="HostSchedulerDecisionPayload")
    if next_key == "end":
        return {
            "next_speaker": "end",
            "current_phase": payload.current_phase,
            "next_action": payload.next_action,
            "suggested_add_agent_names": suggested or None,
        }
    if next_key == "user":
        return {
            "next_speaker": "user",
            "current_phase": payload.current_phase,
            "next_action": payload.next_action,
            "suggested_add_agent_names": suggested or None,
        }
    agent_name = names.get(next_key)
    if not agent_name:
        raise StructuredOutputProtocolError("next_speaker is not in allowed participants", schema_name="HostSchedulerDecisionPayload")
    return {
        "next_speaker": agent_name,
        "current_phase": payload.current_phase,
        "next_action": payload.next_action,
        "suggested_add_agent_names": suggested or None,
    }


def parse_strict_host_scheduler_output(
    content: str,
    agent_profiles: List[Dict[str, Any]],
    *,
    host_mode: str = "recruitment",
) -> Dict[str, Any]:
    """Parse host scheduler JSON without legacy cleanup or natural-language fallback."""
    try:
        payload = parse_strict_pydantic_object(content, HostSchedulerDecisionPayload)
        return _strict_host_decision_from_payload(
            payload,
            agent_profiles,
            host_mode=host_mode,
        )
    except StructuredOutputProtocolError as exc:
        return host_protocol_error_decision(str(exc))


def heuristic_recommend_agents(
    discussion_goal: str, all_instances: List[Dict[str, Any]], max_n: Optional[int] = None
) -> List[str]:
    """Recommend Agent names with simple keyword matching."""
    goal = (discussion_goal or "").strip().lower()
    scored = []
    for d in all_instances or []:
        name_raw = (d.get("name") or "").strip()
        if not name_raw:
            continue
        name = name_raw.lower()
        description = str(d.get("description") or "").lower()
        hay = f"{name} {description}"
        score = 0
        for token in (goal.replace("，", " ").replace("。", " ").replace(",", " ").split() if goal else []):
            if token and token in hay:
                score += 3
        if any(k in goal for k in ("天气", "气温", "下雨", "预报")) and any(k in hay for k in ("天气", "气象")):
            score += 5
        if any(k in goal for k in ("写", "文案", "公众号", "文章", "标题")) and any(k in hay for k in ("写作", "文案", "编辑", "公众号", "内容")):
            score += 5
        if any(k in goal for k in ("图", "封面", "配图", "logo", "海报")) and any(k in hay for k in ("设计", "封面", "配图", "海报", "图像", "logo")):
            score += 5
        if any(k in goal for k in ("数据", "报表", "分析", "表格", "excel")) and any(k in hay for k in ("数据", "分析", "报表", "excel")):
            score += 5
        scored.append((score, name_raw))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [name for s, name in scored if s > 0]
    if max_n is not None:
        picked = picked[: max(0, int(max_n))]
    if not picked:
        for d in all_instances or []:
            name = (d.get("name") or "").strip()
            if name and name not in picked:
                picked.append(name)
            if max_n is not None and len(picked) >= max_n:
                break
    if max_n is not None:
        return picked[:max(0, int(max_n))]
    return picked
