"""Pure host-decision parsing helpers for group chat."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


def _to_agent_style_id(raw_id: str) -> str:
    sid = str(raw_id or "").strip()
    if not sid:
        return sid
    if sid.startswith("agent-"):
        return sid
    return f"agent-{sid}"


def extract_json_object_from_llm_text(text: str) -> Optional[Dict[str, Any]]:
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    if "```json" in s:
        try:
            inner = s.split("```json", 1)[1].split("```", 1)[0].strip()
            obj = json.loads(inner)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
    if "```" in s:
        try:
            inner = s.split("```", 1)[1].split("```", 1)[0].strip()
            if inner.startswith("json"):
                inner = inner[4:].strip()
            obj = json.loads(inner)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
    try:
        lo = s.find("{")
        hi = s.rfind("}")
        if lo >= 0 and hi > lo:
            obj = json.loads(s[lo : hi + 1])
            return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    return None


def parse_host_response(content: str) -> Optional[Dict[str, Any]]:
    """Parse host output and extract the host announcement plus JSON decision."""
    if not content or not content.strip():
        return None
    text = content.strip()
    announcement = ""
    json_str = ""
    if "```json" in text:
        parts = text.split("```json", 1)
        announcement = (parts[0] or "").strip()
        rest = parts[1].split("```", 1)[0].strip() if len(parts) > 1 else ""
        json_str = rest
    elif "```" in text:
        parts = text.split("```", 2)
        announcement = (parts[0] or "").strip()
        if len(parts) >= 2:
            json_str = (parts[1] or "").strip()
    else:
        for sep in ("\n{", "{"):
            if sep in text:
                idx = text.find(sep) if sep == "{" else text.find(sep) + 1
                announcement = text[:idx].strip()
                json_str = text[idx:].strip()
                break
        else:
            return None
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
        task_done = data.get("task_done", True)
        next_speaker = (data.get("next_speaker") or "user").strip().lower()
        reason = data.get("reason", "")
        suggested_add_agent_ids = None
        ids_raw = data.get("suggested_add_expert_ids")
        if not isinstance(ids_raw, list) or not ids_raw:
            ids_raw = data.get("suggested_add_agent_ids")
        if isinstance(ids_raw, list) and ids_raw:
            cleaned = [str(x).strip() for x in ids_raw if str(x).strip()]
            if cleaned:
                suggested_add_agent_ids = list(dict.fromkeys(cleaned))
        if not suggested_add_agent_ids:
            sid = (data.get("suggested_add_expert_id") or data.get("suggested_add_agent_id") or "").strip()
            if sid:
                suggested_add_agent_ids = [sid]
        suggested_order = data.get("suggested_order")
        if isinstance(suggested_order, list):
            suggested_order = [str(x).strip().lower() for x in suggested_order if str(x).strip()]
        else:
            suggested_order = None
        phase = (data.get("phase") or "").strip().lower() or None
        owner_agent_id = (data.get("owner_agent_id") or "").strip() or None
        interrupt_reason = (data.get("interrupt_reason") or "").strip().lower() or None
        decision_source = (data.get("decision_source") or "").strip().lower() or "legacy"
        handoff_reason = (data.get("handoff_reason") or "").strip() or None
        required_user_fields = data.get("required_user_fields")
        if not isinstance(required_user_fields, list):
            required_user_fields = []
        if not announcement and reason:
            announcement = reason
        raw_np = data.get("next_prompt")
        next_prompt_val: Optional[str] = None
        if raw_np is not None and str(raw_np).strip():
            next_prompt_val = str(raw_np).strip()
        return {
            "task_done": task_done,
            "next_speaker": next_speaker,
            "reason": reason,
            "announcement": announcement or "请下一位发言。",
            "next_prompt": next_prompt_val,
            "suggested_order": suggested_order,
            "suggested_add_agent_ids": suggested_add_agent_ids,
            "suggested_add_expert_ids": suggested_add_agent_ids,
            "phase": phase,
            "owner_agent_id": owner_agent_id,
            "interrupt_reason": interrupt_reason,
            "decision_source": decision_source,
            "handoff_reason": handoff_reason,
            "required_user_fields": required_user_fields,
        }
    except Exception:
        return None


def match_workspace_speaker_to_agent_id(raw_speaker: str, dha_list: List[Dict[str, Any]]) -> str:
    raw = str(raw_speaker or "").strip()
    raw_lower = raw.lower()
    if not raw:
        return ""
    for dha in dha_list or []:
        aid = str((dha or {}).get("agent_id") or "").strip()
        if aid and aid.lower() == raw_lower:
            return aid
    for dha in dha_list or []:
        aid = str((dha or {}).get("agent_id") or "").strip()
        name = str((dha or {}).get("name") or "").strip()
        if aid and name and name == raw:
            return aid
    for dha in dha_list or []:
        aid = str((dha or {}).get("agent_id") or "").strip()
        name = str((dha or {}).get("name") or "").strip()
        role = str((dha or {}).get("role") or "").strip()
        if aid and raw and (raw in name or raw in role):
            return aid
    return ""


def host_text_field(content: str, names: tuple[str, ...]) -> str:
    labels = [re.escape(name) for name in names if name]
    if not labels:
        return ""
    all_labels = (
        r"current_phase(?:\.txt)?|next_speaker(?:\.txt)?|speaker_task(?:\.txt)?|"
        r"current_phase\.txt|next_speaker\.txt|speaker_task\.txt"
    )
    pattern = (
        r"(?ims)^\s*`?(?:"
        + "|".join(labels)
        + r")`?\s*[:：]\s*(.*?)"
        + r"(?=^\s*`?(?:"
        + all_labels
        + r")`?\s*[:：]|\Z)"
    )
    match = re.search(pattern, content or "")
    return match.group(1).strip() if match else ""


def extract_host_scheduler_state(content: str) -> Dict[str, str]:
    """Extract scheduler file state from host output without requiring tool calls."""
    text = str(content or "").strip()
    state = {"current_phase": "", "next_speaker": "", "speaker_task": ""}
    if not text:
        return state
    obj = extract_json_object_from_llm_text(text)
    if isinstance(obj, dict):
        state["current_phase"] = str(
            obj.get("current_phase")
            or obj.get("current_phase.txt")
            or obj.get("phase_label")
            or ""
        ).strip()
        state["next_speaker"] = str(obj.get("next_speaker") or obj.get("next_speaker.txt") or "").strip()
        state["speaker_task"] = str(
            obj.get("speaker_task")
            or obj.get("speaker_task.txt")
            or obj.get("next_prompt")
            or ""
        ).strip()
    if not state["current_phase"]:
        state["current_phase"] = host_text_field(text, ("current_phase.txt", "current_phase"))
    if not state["next_speaker"]:
        state["next_speaker"] = host_text_field(text, ("next_speaker.txt", "next_speaker"))
    if not state["speaker_task"]:
        state["speaker_task"] = host_text_field(text, ("speaker_task.txt", "speaker_task"))
    return state


def host_decision_from_scheduler_state(
    state: Dict[str, str],
    dha_list: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    raw_speaker = str((state or {}).get("next_speaker") or "").strip()
    task = str((state or {}).get("speaker_task") or "").strip()
    phase_text = str((state or {}).get("current_phase") or "").strip()
    if not raw_speaker:
        return None
    raw_lower = raw_speaker.lower()
    user_speakers = {"user", "用户", "用户输入", "学生", "student"}
    reason = "主持人已输出调度状态，平台已写入工作区"
    if phase_text:
        reason += f"（{phase_text}）"
    if raw_lower in user_speakers:
        return {
            "task_done": True,
            "next_speaker": "user",
            "reason": reason,
            "announcement": "请用户继续发言。",
            "next_prompt": task or None,
            "suggested_order": None,
            "suggested_add_agent_ids": None,
            "suggested_add_expert_ids": None,
            "phase": None,
            "owner_agent_id": None,
            "interrupt_reason": None,
            "decision_source": "host_scheduler_state",
            "handoff_reason": reason,
            "required_user_fields": [],
        }
    if not task:
        return None
    agent_id = match_workspace_speaker_to_agent_id(raw_speaker, dha_list)
    if not agent_id:
        return None
    dha = next((d for d in dha_list if str((d or {}).get("agent_id") or "").strip() == agent_id), {})
    name = str((dha or {}).get("name") or raw_speaker or agent_id).strip()
    return {
        "task_done": True,
        "next_speaker": agent_id,
        "reason": reason,
        "announcement": f"下面由 {name} 发言。",
        "next_prompt": task,
        "suggested_order": None,
        "suggested_add_agent_ids": None,
        "suggested_add_expert_ids": None,
        "phase": None,
        "owner_agent_id": None,
        "interrupt_reason": None,
        "decision_source": "host_scheduler_state",
        "handoff_reason": reason,
        "required_user_fields": [],
    }


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


def heuristic_recommend_dhas(
    discussion_goal: str, all_instances: List[Dict[str, Any]], max_n: Optional[int] = None
) -> List[str]:
    """Recommend DHA ids with simple keyword matching."""
    goal = (discussion_goal or "").strip().lower()
    scored = []
    for d in all_instances or []:
        did = (d.get("agent_id") or "").strip()
        if not did:
            continue
        name = str(d.get("name") or "").lower()
        role = str(d.get("role") or "").lower()
        hay = f"{did} {name} {role}"
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
        scored.append((score, did))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [did for s, did in scored if s > 0]
    if max_n is not None:
        picked = picked[: max(0, int(max_n))]
    if not picked:
        for d in all_instances or []:
            did = (d.get("agent_id") or "").strip()
            if did and did not in picked:
                picked.append(did)
            if max_n is not None and len(picked) >= max_n:
                break
    if max_n is not None:
        return picked[:max(0, int(max_n))]
    return picked


def extract_candidate_agent_ids_from_text(
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
    for aid in re.findall(r"agent-[a-zA-Z0-9\-]+", t, flags=re.I):
        s = str(aid or "").strip()
        if s:
            out.append(s)
        if len(out) >= max_n:
            return list(dict.fromkeys(out))[:max_n]
    for d in all_instances or []:
        did = str(d.get("agent_id") or "").strip()
        if not did:
            continue
        name = str(d.get("name") or "").strip().lower()
        role = str(d.get("role") or "").strip().lower()
        if name and name in t:
            out.append(did)
        elif role and role in t:
            out.append(did)
        if len(out) >= max_n:
            break
    return list(dict.fromkeys(out))[:max_n]


def extract_explicit_requested_agent_ids(user_text: str, all_instances: List[Dict[str, Any]]) -> List[str]:
    """Extract experts explicitly named by the user."""
    text = (user_text or "").strip().lower()
    if not text:
        return []
    out: List[str] = []
    for d in all_instances or []:
        did = (d.get("agent_id") or "").strip()
        if not did:
            continue
        name = str(d.get("name") or "").strip()
        did_hit = did.lower() in text
        name_hit = bool(name) and (name.lower() in text)
        if did_hit or name_hit:
            out.append(did)
    return list(dict.fromkeys(out))


def extract_forced_at_mention_agent_id(user_text: str, all_instances: List[Dict[str, Any]]) -> Optional[str]:
    """Return an agent id only when the message starts with an expert @ mention."""
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
        did = str(d.get("agent_id") or "").strip()
        name = str(d.get("name") or "").strip()
        role = str(d.get("role") or "").strip()
        if not did:
            continue
        candidates = {
            did.lower(),
            _to_agent_style_id(did).lower(),
            did.replace("agent-", "").lower(),
        }
        if name:
            candidates.add(name.lower())
        if role:
            candidates.add(role.lower())
        if mention in candidates:
            return did
    return None
