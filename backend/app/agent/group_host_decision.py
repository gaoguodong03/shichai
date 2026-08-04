"""Strict host decision parsing and message-based route derivation."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.structured_output_contracts import (
    HostMessagePayload,
    HostSchedulerDecisionPayload,
    HostSpeakerSelectionPayload,
    StructuredOutputProtocolError,
    parse_strict_pydantic_object,
)


HOST_PROTOCOL_ERROR_MESSAGE = "主持人输出格式错误，请重试或联系管理员。"


def host_protocol_error_decision(reason: str = "protocol_error") -> Dict[str, Any]:
    """Return a valid host message that pauses instead of guessing a route."""
    _ = reason
    return {
        "current_phase": "协议错误",
        "message": {"content": HOST_PROTOCOL_ERROR_MESSAGE, "target_agent_name": "user"},
        "suggested_add_agent_names": [],
    }


def is_host_protocol_error_decision(decision: Dict[str, Any]) -> bool:
    message = decision.get("message") if isinstance(decision.get("message"), dict) else {}
    return (
        str(message.get("content") or "").strip() == HOST_PROTOCOL_ERROR_MESSAGE
        and str(message.get("target_agent_name") or "").strip().casefold() == "user"
        and list(decision.get("suggested_add_agent_names") or []) == []
    )


def _agent_name_map(agent_profiles: List[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for profile in agent_profiles or []:
        name = str((profile or {}).get("name") or "").strip()
        if name:
            out[name.casefold()] = name
    return out


def _canonical_host_target(target: str, agent_profiles: List[Dict[str, Any]], *, schema_name: str) -> str:
    """Accept explicit user/end sentinels or canonicalize one current expert name."""
    value = str(target or "").strip()
    folded = value.casefold()
    if folded in {"user", "end"}:
        return folded
    canonical = _agent_name_map(agent_profiles).get(folded)
    if not canonical:
        raise StructuredOutputProtocolError(
            "target_agent_name is not user, end, or an allowed participant",
            schema_name=schema_name,
        )
    return canonical


def host_speaker_selection_from_payload(
    payload: HostSpeakerSelectionPayload,
    agent_profiles: List[Dict[str, Any]],
    *,
    host_mode: str = "recruitment",
) -> Dict[str, Any]:
    """Validate the selector-only LLM result without deriving a route from prose."""
    scene_mode = str(host_mode or "").strip().lower() == "scene"
    suggested = list(payload.suggested_add_agent_names or [])
    if scene_mode and suggested:
        raise StructuredOutputProtocolError(
            "scene mode forbids suggested_add_agent_names",
            schema_name="HostSpeakerSelectionPayload",
        )
    return {
        "current_phase": payload.current_phase,
        "target_agent_name": _canonical_host_target(
            payload.target_agent_name,
            agent_profiles,
            schema_name="HostSpeakerSelectionPayload",
        ),
        "suggested_add_agent_names": suggested or None,
    }


def compose_host_scheduler_decision(
    selection: HostSpeakerSelectionPayload | Dict[str, Any],
    message_payload: HostMessagePayload,
) -> Dict[str, Any]:
    """Combine a fixed speaker selection with target-free host presentation fields."""
    selected = (
        selection.model_dump(exclude_none=True)
        if isinstance(selection, HostSpeakerSelectionPayload)
        else dict(selection)
    )
    message = message_payload.model_dump(exclude_none=True, exclude_defaults=True)
    message["target_agent_name"] = str(selected.get("target_agent_name") or "").strip()
    return {
        "current_phase": str(selected.get("current_phase") or "").strip(),
        "message": message,
        "suggested_add_agent_names": list(selected.get("suggested_add_agent_names") or []),
    }


def host_scheduler_decision_from_payload(
    payload: HostSchedulerDecisionPayload,
    agent_profiles: List[Dict[str, Any]],
    *,
    host_mode: str = "recruitment",
) -> Dict[str, Any]:
    """Validate the message target against current members and return canonical fields."""
    scene_mode = str(host_mode or "").strip().lower() == "scene"
    message = payload.message.model_dump(exclude_none=True, exclude_defaults=True)
    target = str(message.get("target_agent_name") or "").strip()
    suggested = list(payload.suggested_add_agent_names or [])
    if scene_mode and suggested:
        raise StructuredOutputProtocolError(
            "scene mode forbids suggested_add_agent_names",
            schema_name="HostSchedulerDecisionPayload",
        )
    message["target_agent_name"] = _canonical_host_target(
        target,
        agent_profiles,
        schema_name="HostSchedulerDecisionPayload",
    )
    return {
        "current_phase": payload.current_phase,
        "message": message,
        "suggested_add_agent_names": suggested or None,
    }


def _user_requests_recruitment(text: str) -> bool:
    value = str(text or "").strip()
    return bool(value) and any(token in value for token in ("邀请", "加人", "加入专家", "添加专家", "再加", "请加", "拉进来"))


def finalize_host_scheduler_decision(
    decision: Dict[str, Any],
    *,
    agent_names: List[str],
    available_to_add: List[Dict[str, Any]],
    user_text: str,
) -> Dict[str, Any]:
    """Filter recruitment suggestions without inventing host message content."""
    out = dict(decision or {})
    message = dict(out.get("message") or {}) if isinstance(out.get("message"), dict) else {"content": ""}
    available = {
        str(item.get("name") or "").strip()
        for item in available_to_add or []
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    suggested: list[str] = []
    for raw in out.get("suggested_add_agent_names") or []:
        name = str(raw or "").strip()
        if name and name in available and name not in suggested:
            suggested.append(name)
    if suggested and agent_names and not _user_requests_recruitment(user_text):
        suggested = []
    if suggested:
        message["target_agent_name"] = "user"
    out["message"] = message
    out["suggested_add_agent_names"] = suggested
    return out


def _apply_decision_to_ctx(decision: Dict[str, Any], *, default_next_action: str) -> Dict[str, Any]:
    """Derive temporary execution variables from the canonical host message."""
    message = dict(decision.get("message") or {}) if isinstance(decision.get("message"), dict) else {}
    content = str(message.get("content") or "").strip() or str(default_next_action or "").strip()
    target = str(message.get("target_agent_name") or "").strip()
    if not target:
        raise ValueError("host decision requires explicit message.target_agent_name")
    current_phase = str(decision.get("current_phase") or "").strip()
    suggested = [str(item).strip() for item in decision.get("suggested_add_agent_names") or [] if str(item).strip()]
    return {
        "next_speaker": target,
        "next_action": content,
        "suggested_add_agent_names": suggested,
        "host_scheduler": {"current_phase": current_phase, "message": message},
    }


def parse_strict_host_scheduler_output(
    content: str,
    agent_profiles: List[Dict[str, Any]],
    *,
    host_mode: str = "recruitment",
) -> Dict[str, Any]:
    try:
        payload = parse_strict_pydantic_object(content, HostSchedulerDecisionPayload)
        return host_scheduler_decision_from_payload(payload, agent_profiles, host_mode=host_mode)
    except StructuredOutputProtocolError as exc:
        return host_protocol_error_decision(str(exc))


def heuristic_recommend_agents(
    discussion_goal: str, all_instances: List[Dict[str, Any]], max_n: Optional[int] = None
) -> List[str]:
    """Recommend Agent names with simple keyword matching."""
    goal = (discussion_goal or "").strip().lower()
    scored = []
    for item in all_instances or []:
        name_raw = str(item.get("name") or "").strip()
        if not name_raw:
            continue
        hay = f"{name_raw.lower()} {str(item.get('description') or '').lower()}"
        score = sum(3 for token in goal.replace("，", " ").replace("。", " ").replace(",", " ").split() if token in hay)
        if any(k in goal for k in ("写", "文案", "文章", "标题")) and any(k in hay for k in ("写作", "文案", "编辑", "内容")):
            score += 5
        if any(k in goal for k in ("图", "封面", "配图", "海报")) and any(k in hay for k in ("设计", "封面", "配图", "图像")):
            score += 5
        if any(k in goal for k in ("数据", "报表", "分析", "表格")) and any(k in hay for k in ("数据", "分析", "报表")):
            score += 5
        scored.append((score, name_raw))
    scored.sort(key=lambda row: row[0], reverse=True)
    picked = [name for score, name in scored if score > 0]
    if not picked:
        picked = [str(item.get("name") or "").strip() for item in all_instances or [] if str(item.get("name") or "").strip()]
    return picked[: max(0, int(max_n))] if max_n is not None else picked
