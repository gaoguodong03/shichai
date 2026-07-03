"""Pure host-decision parsing helpers for group chat."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.agent.group_chat_host_messages import HOST_END_MESSAGE
from app.agent.orchestrator_state import InterruptReason, OrchestrationPhase
from app.agent.structured_output_contracts import (
    HostSchedulerDecisionPayload,
    StructuredOutputProtocolError,
    parse_strict_pydantic_object,
)


HOST_PROTOCOL_ERROR_MESSAGE = "主持人输出格式错误，请重试或联系管理员。"


def host_protocol_error_decision(reason: str = "protocol_error") -> Dict[str, Any]:
    return {
        "task_done": True,
        "next_speaker": "user",
        "reason": reason,
        "announcement": HOST_PROTOCOL_ERROR_MESSAGE,
        "next_prompt": None,
        "current_phase": "",
        "speaker_task": HOST_PROTOCOL_ERROR_MESSAGE,
        "suggested_order": None,
        "suggested_add_agent_names": None,
        "phase": OrchestrationPhase.AWAITING_USER.value,
        "owner_agent_name": None,
        "interrupt_reason": InterruptReason.PROTOCOL_ERROR.value,
        "decision_source": "system_guard",
        "handoff_reason": reason,
        "required_user_fields": [],
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
    orchestration_profile: str = "recruitment",
) -> Dict[str, Any]:
    scene_mode = str(orchestration_profile or "").strip().lower() == "scene"
    raw_next = payload.next_speaker.strip()
    next_key = raw_next.casefold()
    names = _agent_name_map(agent_profiles)
    suggested = list(payload.suggested_add_agent_names or [])
    if scene_mode and suggested:
        raise StructuredOutputProtocolError("scene mode forbids suggested_add_agent_names", schema_name="HostSchedulerDecisionPayload")
    if suggested and next_key != "user":
        raise StructuredOutputProtocolError("suggested_add_agent_names requires next_speaker=user", schema_name="HostSchedulerDecisionPayload")
    if next_key == "invite" and scene_mode:
        raise StructuredOutputProtocolError("scene mode forbids invite", schema_name="HostSchedulerDecisionPayload")
    if next_key == "end":
        if payload.current_phase.strip() != "end":
            raise StructuredOutputProtocolError("end requires current_phase=end", schema_name="HostSchedulerDecisionPayload")
        return {
            "task_done": True,
            "next_speaker": "end",
            "reason": payload.reason or "主持人严格协议调度",
            "announcement": HOST_END_MESSAGE,
            "next_prompt": None,
            "current_phase": payload.current_phase,
            "speaker_task": payload.speaker_task,
            "suggested_order": None,
            "suggested_add_agent_names": suggested or None,
            "phase": None,
            "owner_agent_name": None,
            "interrupt_reason": None,
            "decision_source": "host_scheduler_state",
            "handoff_reason": payload.reason,
            "required_user_fields": [],
        }
    if next_key == "user":
        if not payload.speaker_task.strip():
            raise StructuredOutputProtocolError("user requires speaker_task", schema_name="HostSchedulerDecisionPayload")
        return {
            "task_done": True,
            "next_speaker": "user",
            "reason": payload.reason or "主持人严格协议调度",
            "announcement": "请用户继续发言。",
            "next_prompt": None,
            "current_phase": payload.current_phase,
            "speaker_task": payload.speaker_task,
            "suggested_order": None,
            "suggested_add_agent_names": suggested or None,
            "phase": None,
            "owner_agent_name": None,
            "interrupt_reason": InterruptReason.NEED_RECRUIT_EXPERT.value if suggested else None,
            "decision_source": "host_scheduler_state",
            "handoff_reason": payload.reason,
            "required_user_fields": [],
        }
    if next_key == "invite":
        if not payload.speaker_task.strip():
            raise StructuredOutputProtocolError("invite requires speaker_task", schema_name="HostSchedulerDecisionPayload")
        return {
            "task_done": True,
            "next_speaker": "invite",
            "reason": payload.reason or "主持人严格协议调度",
            "announcement": "",
            "next_prompt": None,
            "current_phase": payload.current_phase,
            "speaker_task": payload.speaker_task,
            "suggested_order": None,
            "suggested_add_agent_names": suggested or None,
            "phase": None,
            "owner_agent_name": None,
            "interrupt_reason": InterruptReason.NEED_RECRUIT_EXPERT.value,
            "decision_source": "host_scheduler_state",
            "handoff_reason": payload.reason,
            "required_user_fields": [],
        }
    agent_name = names.get(next_key)
    if not agent_name:
        raise StructuredOutputProtocolError("next_speaker is not in allowed participants", schema_name="HostSchedulerDecisionPayload")
    if not payload.speaker_task.strip():
        raise StructuredOutputProtocolError("agent next_speaker requires speaker_task", schema_name="HostSchedulerDecisionPayload")
    profile = next((d for d in agent_profiles if str((d or {}).get("name") or "").strip() == agent_name), {})
    display_name = str((profile or {}).get("name") or agent_name).strip()
    return {
        "task_done": True,
        "next_speaker": agent_name,
        "reason": payload.reason or "主持人严格协议调度",
        "announcement": f"下面由 {display_name} 发言。",
        "next_prompt": None,
        "current_phase": payload.current_phase,
        "speaker_task": payload.speaker_task,
        "suggested_order": None,
        "suggested_add_agent_names": suggested or None,
        "phase": None,
        "owner_agent_name": None,
        "interrupt_reason": None,
        "decision_source": "host_scheduler_state",
        "handoff_reason": payload.reason,
        "required_user_fields": [],
    }


def parse_strict_host_scheduler_output(
    content: str,
    agent_profiles: List[Dict[str, Any]],
    *,
    orchestration_profile: str = "recruitment",
) -> Dict[str, Any]:
    try:
        payload = parse_strict_pydantic_object(content, HostSchedulerDecisionPayload)
        return _strict_host_decision_from_payload(
            payload,
            agent_profiles,
            orchestration_profile=orchestration_profile,
        )
    except StructuredOutputProtocolError as exc:
        return host_protocol_error_decision(str(exc))


def user_requests_host_takeover(
    message: str,
    *,
    explicit_flag: Optional[bool],
    host_display_name: str = "四九",
) -> bool:
    """Only allow host orchestration when user explicitly asks for host."""
    if explicit_flag is True:
        return True
    text = str(message or "").strip()
    if not text:
        return False
    host_name = (host_display_name or "四九").strip()
    lowered = text.lower()
    if "@主持人" in text or "@四九" in text or (host_name and f"@{host_name}" in text):
        return True
    host_aliases = ["主持人", "四九"]
    if host_name and host_name not in host_aliases:
        host_aliases.append(host_name)
    alias_pattern = "|".join([re.escape(x) for x in host_aliases if x])
    summon_patterns = [
        rf"(请|让|由|麻烦|需要)?\s*({alias_pattern})\s*(来|接管|安排|协调|分配|调度|负责|处理|决策)",
        rf"(请|让|由|麻烦|需要)\s*({alias_pattern})\b",
    ]
    for pat in summon_patterns:
        if re.search(pat, text, flags=re.I):
            return True
    if host_name and host_name.lower() in lowered and re.search(r"(接管|安排|协调|分配|调度|负责|处理|决策)", text):
        return True
    return False


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


def extract_candidate_agent_names_from_text(
    text: str,
    all_instances: List[Dict[str, Any]],
    *,
    max_n: int = 2,
) -> List[str]:
    """Extract candidate experts from host natural-language text."""
    t = (text or "").strip().lower()
    if not t:
        return []
    out: List[str] = []
    for d in all_instances or []:
        name = str(d.get("name") or "").strip().lower()
        description = str(d.get("description") or "").strip().lower()
        if name and name in t:
            out.append(str(d.get("name") or "").strip())
        elif description and description in t:
            out.append(str(d.get("name") or "").strip())
        if len(out) >= max_n:
            break
    return list(dict.fromkeys(out))[:max_n]


def extract_explicit_requested_agent_names(user_text: str, all_instances: List[Dict[str, Any]]) -> List[str]:
    """Extract experts explicitly named by the user."""
    text = (user_text or "").strip().lower()
    if not text:
        return []
    out: List[str] = []
    for d in all_instances or []:
        name = str(d.get("name") or "").strip()
        name_hit = bool(name) and (name.lower() in text)
        if name_hit:
            out.append(name)
    return list(dict.fromkeys(out))


def extract_forced_at_mention_agent_name(user_text: str, all_instances: List[Dict[str, Any]]) -> Optional[str]:
    """Return an Agent name only when the message starts with an expert @ mention."""
    text = (user_text or "").strip()
    if not text.startswith("@"):
        return None
    m = re.match(r"^\s*@([^\s，。,；;：:！!？?\)\]】】]+)", text, flags=re.I)
    if not m:
        return None
    mention = (m.group(1) or "").strip().lower()
    if not mention:
        return None
    for d in all_instances or []:
        name = str(d.get("name") or "").strip()
        description = str(d.get("description") or "").strip()
        if not name:
            continue
        candidates = set()
        if name:
            candidates.add(name.lower())
        if description:
            candidates.add(description.lower())
        if mention in candidates:
            return name
    return None
