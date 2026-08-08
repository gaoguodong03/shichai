"""Strict host decision parsing and message-based route derivation."""
from __future__ import annotations

from typing import Any, Dict, List

from app.agent.structured_output_contracts import (
    HostSchedulerDecisionPayload,
    StructuredOutputProtocolError,
    parse_strict_pydantic_object,
)


HOST_PROTOCOL_ERROR_MESSAGE = "主持人输出格式错误，请重试或联系管理员。"


def host_protocol_error_decision(reason: str = "protocol_error") -> Dict[str, Any]:
    """Return a valid host message that pauses instead of guessing a route."""
    _ = reason
    return {
        "current_phase": "协议错误",
        "message": {"content": HOST_PROTOCOL_ERROR_MESSAGE},
        "suggested_add_agent_names": [],
    }


def is_host_protocol_error_decision(decision: Dict[str, Any]) -> bool:
    message = decision.get("message") if isinstance(decision.get("message"), dict) else {}
    return (
        str(message.get("content") or "").strip() == HOST_PROTOCOL_ERROR_MESSAGE
        and not str(message.get("target_agent_name") or "").strip()
        and list(decision.get("suggested_add_agent_names") or []) == []
    )


def _agent_name_map(agent_profiles: List[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for profile in agent_profiles or []:
        name = str((profile or {}).get("name") or "").strip()
        if name:
            out[name.casefold()] = name
    return out


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
    if target:
        canonical = _agent_name_map(agent_profiles).get(target.casefold())
        if not canonical:
            raise StructuredOutputProtocolError(
                "message.target_agent_name is not in allowed participants",
                schema_name="HostSchedulerDecisionPayload",
            )
        message["target_agent_name"] = canonical
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
        message.pop("target_agent_name", None)
    out["message"] = message
    out["suggested_add_agent_names"] = suggested
    return out


def _apply_decision_to_ctx(decision: Dict[str, Any], *, default_next_action: str) -> Dict[str, Any]:
    """Derive temporary execution variables from the canonical host message."""
    message = dict(decision.get("message") or {}) if isinstance(decision.get("message"), dict) else {}
    content = str(message.get("content") or "").strip() or str(default_next_action or "").strip()
    target = str(message.get("target_agent_name") or "").strip()
    current_phase = str(decision.get("current_phase") or "").strip()
    suggested = [str(item).strip() for item in decision.get("suggested_add_agent_names") or [] if str(item).strip()]
    return {
        "next_speaker": target or ("end" if current_phase.casefold() == "end" else "user"),
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
