"""群聊 API - 多 DHA 群聊会话与消息"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import uuid
import difflib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage  # type: ignore

from app.api.dha import load_dha_instances
from app.api.settings import load_app_settings
from app.api.files import get_workspace_root_path
from app.agent.llm_client import get_llm_from_config
from app.agent.graph import create_skill_execution_agent
from app.agent.leader_scheduler import leader_decide
from app.agent.group_memory_store import (
    append_turn_log,
    upsert_facts,
    build_dispatch_context,
    append_expert_message_file,
)
from app.agent.orchestrator_state import (
    DecisionSource,
    InterruptReason,
    OrchestrationContext,
    OrchestrationDecision,
    OrchestrationPhase,
    build_end_payload,
)
from app.agent.orchestrator_reducer import apply_decision, move_to_interrupt, start_turn
from app.agent.orchestrator_runtime import normalize_scheduler_decision
from app.agent.orchestrator_audit import append_audit_event
from app.agent.hook_pipeline import HookPipeline, HookPriority, HookResult
from app.agent.tools_for_skill import build_tools_for_group_chat
from app.skills.loader import get_skills_loader_for_user
from app.core.init import ensure_mcp_and_skills_initialized
from app.core.user_context import get_current_user_context
from app.core.security import user_context_dependency, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["group_chat"], dependencies=[Depends(user_context_dependency)])

GROUP_META_FILE = "group_sessions_meta.json"
GROUP_HISTORY_PREFIX = "group_history_"

# 已废弃：不再使用 dha-chat，新建会话 0 个 DHA 时由主持人先与用户交流并推荐 DHA 加入
CHAT_DHA_ID = "dha-chat"

def _request_skills_loader():
    u = get_current_user()
    return get_skills_loader_for_user(u.username, u.ctx.skills_dir)


async def _ensure_initialized():
    await ensure_mcp_and_skills_initialized()


def _safe_format_template(tpl: str, **kwargs) -> str:
    """安全渲染设置中的主持人模板。

    约定变量写法为 `{var}`。注意模板内可能包含 JSON 示例（大量 `{}`），
    因此不能直接使用 str.format（会把 JSON 大括号当成占位符并报错）。
    这里采用“只替换已知变量 token”的方式，保证不会因模板内容导致群聊中断。
    """
    out = str(tpl or "")
    for k, v in (kwargs or {}).items():
        out = out.replace("{" + str(k) + "}", "" if v is None else str(v))
    return out


def _ensure_sessions_dir() -> Path:
    """根据当前用户返回群聊会话目录，实现多用户隔离。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise RuntimeError("缺少用户上下文，无法解析会话目录。")
    root = user_ctx.sessions_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _normalize_agent_ids(
    legacy_dha_ids: Optional[List[str]] = None,
    agent_ids: Optional[List[str]] = None,
    expert_ids: Optional[List[str]] = None,
) -> List[str]:
    """统一兼容字段优先级：expert_ids > agent_ids > dha_ids。"""
    return list(expert_ids or agent_ids or legacy_dha_ids or [])


def _build_session_payload(session_id: str, meta_item: Dict[str, Any]) -> Dict[str, Any]:
    """统一会话输出结构：新字段优先，兼容旧字段。"""
    ids = list(meta_item.get("dha_ids", []))
    leader_id = meta_item.get("leader_dha_id", "")
    return {
        "id": session_id,
        "title": meta_item.get("title", "新对话"),
        "agent_ids": ids,
        "dha_ids": ids,
        "expert_ids": ids,
        "leader_agent_id": leader_id,
        "leader_dha_id": leader_id,
        "speak_mode": meta_item.get("speak_mode", "auto"),
        "created_at": meta_item.get("created_at", ""),
        "updated_at": meta_item.get("updated_at", ""),
    }


def _set_group_alias_deprecated_header(response: Response) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-06-30"
    response.headers["Link"] = '</api/sessions>; rel="successor-version"'


def _load_group_meta() -> Dict[str, Dict[str, Any]]:
    path = _ensure_sessions_dir() / GROUP_META_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _save_group_meta(meta: Dict[str, Dict[str, Any]]) -> None:
    path = _ensure_sessions_dir() / GROUP_META_FILE
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_group_history(group_session_id: str) -> List[Dict[str, Any]]:
    path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def _save_group_history(group_session_id: str, messages: List[Dict[str, Any]]) -> None:
    path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


def _cleanup_orphan_group_histories(meta: Dict[str, Dict[str, Any]]) -> int:
    """清理不在 meta 中的群聊历史文件，返回删除数量。"""
    root = _ensure_sessions_dir()
    valid_ids = set((meta or {}).keys())
    deleted = 0
    for p in root.glob(f"{GROUP_HISTORY_PREFIX}*.json"):
        sid = p.stem.replace(GROUP_HISTORY_PREFIX, "")
        if sid in valid_ids:
            continue
        try:
            p.unlink()
            deleted += 1
        except OSError:
            logger.warning("清理孤儿会话历史失败: %s", p, exc_info=True)
    return deleted


def _build_archive_segments(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将会话消息归档分段（按轮次）并按专家聚合，不包含主持人。

    轮次定义（尽量符合用户直觉）：
    - 遇到 user 消息，开启新一轮；
    - 在这一轮内收集后续 assistant（专家）发言（按 dha_id 分组，保留顺序）；
    - role=host 的消息跳过（不归档）。
    """
    segments: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def _ensure_current() -> Dict[str, Any]:
        nonlocal current
        if current is None:
            current = {
                "user": None,
                "experts": {},  # dha_id -> {dha_id, messages:[{message_id, content, timestamp, skill_id?}]}
            }
        return current

    def _flush():
        nonlocal current
        if not current:
            current = None
            return
        # 只要这一轮有 user 或有专家发言就保留
        has_user = bool(current.get("user"))
        experts = current.get("experts") or {}
        has_expert = any((v.get("messages") or []) for v in experts.values()) if isinstance(experts, dict) else False
        if has_user or has_expert:
            # experts 由 dict 转 list，保持插入顺序（Python 3.7+ dict 有序）
            expert_list = []
            if isinstance(experts, dict):
                for _, v in experts.items():
                    if isinstance(v, dict):
                        expert_list.append(v)
            segments.append(
                {
                    "user": current.get("user"),
                    "experts": expert_list,
                }
            )
        current = None

    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = (m.get("role") or "").strip()
        if role == "host":
            continue
        if role == "user":
            _flush()
            cur = _ensure_current()
            cur["user"] = {
                "message_id": m.get("message_id"),
                "content": m.get("content") or "",
                "timestamp": m.get("timestamp"),
            }
            continue
        if role == "assistant":
            cur = _ensure_current()
            dha_id = (m.get("dha_id") or "").strip()
            if not dha_id:
                continue
            experts = cur.get("experts")
            if not isinstance(experts, dict):
                experts = {}
                cur["experts"] = experts
            if dha_id not in experts:
                experts[dha_id] = {"dha_id": dha_id, "messages": []}
            item = {
                "message_id": m.get("message_id"),
                "content": m.get("content") or "",
                "timestamp": m.get("timestamp"),
            }
            if m.get("skill_id") is not None:
                item["skill_id"] = m.get("skill_id")
            experts[dha_id]["messages"].append(item)
            continue
        # 其他 role 忽略

    _flush()
    return segments


@router.get("/sessions/{group_session_id}/archive")
async def get_group_archive(group_session_id: str):
    """会话归档：按轮次分段，并展示每位专家发言（不包含主持人）。"""
    # 确保会话存在
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    messages = _load_group_history(group_session_id)
    segments = _build_archive_segments(messages)
    # dha_map 用于前端展示名字
    instances = load_dha_instances()
    dha_map = {d.get("dha_id"): {"name": d.get("name") or d.get("dha_id"), "role": d.get("role") or ""} for d in instances if d.get("dha_id")}
    return {"status": "ok", "data": {"segments": segments, "dha_map": dha_map, "expert_map": dha_map}}


def _messages_to_context(
    messages: List[Dict[str, Any]],
    max_turns: int = 15,
    max_chars: int = 12000,
    max_chars_per_message: int = 1200,
) -> str:
    """将群聊消息转为供领导人/DHA 使用的上下文字符串（带长度保护）。

    - 限制每条消息长度，避免单条工具结果把上下文撑爆
    - 限制总上下文长度，超限时仅保留尾部（最近信息优先）
    """
    recent = messages[-max_turns * 2:] if len(messages) > max_turns * 2 else messages
    lines = []
    for m in recent:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if len(content) > max_chars_per_message:
            content = content[:max_chars_per_message].rstrip() + "\n...[内容已截断]"
        dha_id = m.get("dha_id", "")
        if role == "user":
            lines.append(f"【用户】{content}")
        elif role == "host":
            lines.append(f"【主持人】{content}")
        else:
            name = dha_id or "助手"
            lines.append(f"【{name}】{content}")
    context = "\n\n".join(lines)
    if len(context) > max_chars:
        context = "...[较早历史已省略]\n\n" + context[-max_chars:]
    return context


def _normalize_discussion_goal(raw: str, max_len: int = 200) -> str:
    """从首条用户消息中提取纯讨论目标，去掉前端的「【讨论目标】」前缀，避免在 prompt 中重复出现。"""
    if not raw or not isinstance(raw, str):
        return (raw or "").strip()[:max_len] if raw else ""
    s = (raw or "").strip()
    prefix = "【讨论目标】"
    if s.startswith(prefix):
        s = s[len(prefix) :].lstrip("\n ")
    return s[:max_len] if len(s) > max_len else s


def _title_from_first_message(text: str, max_chars: int = 10) -> str:
    """根据用户首次发送生成会话标题，约 max_chars 字以内。去掉【讨论目标】等前缀，取首行或截断。"""
    if not text or not isinstance(text, str):
        return ""
    s = text.strip()
    for prefix in ("【讨论目标】", "【给下一 DHA 的提示】"):
        if s.startswith(prefix):
            s = s[len(prefix) :].lstrip("\n ")
    first_line = s.split("\n")[0].strip() if s else ""
    if not first_line:
        return ""
    if len(first_line) > max_chars:
        return first_line[:max_chars].rstrip()
    return first_line


async def _ai_title_from_recent_user_messages(
    llm: Any,
    messages: List[Dict[str, Any]],
    max_chars: int = 18,
    max_user_messages: int = 6,
) -> str:
    """根据最近用户发言，AI 生成约 15 字主题（用于群聊标题）。"""
    try:
        user_texts: List[str] = []
        for m in reversed(messages or []):
            if not isinstance(m, dict):
                continue
            if (m.get("role") or "").strip() != "user":
                continue
            content = (m.get("content") or "").strip()
            if not content:
                continue
            user_texts.append(_normalize_discussion_goal(content))
            if len(user_texts) >= max_user_messages:
                break
        user_texts.reverse()
        if not user_texts:
            return ""

        client = llm.get_client()
        system_prompt = (
            "你是中文会议主题提取器。根据下面用户在群聊中的发言，提取当前讨论的核心主题。\n"
            "输出要求：\n"
            f"- 只输出“主题本身”，不要输出任何前缀（如：主题/讨论主题/群聊/标题/：）\n"
            f"- 中文主题，长度约 15 字（允许最多 {max_chars} 字）\n"
            "- 不要使用引号或括号，不要以句号/感叹号/问号结尾\n"
        )
        content = "最近用户发言：\n" + "\n\n".join([f"{i+1}. {t}" for i, t in enumerate(user_texts)])
        resp = await client.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=content)])
        raw = (getattr(resp, "content", "") or "").strip()
        if not raw:
            return ""
        # 只取第一行，去掉常见前缀/标点
        s = raw.splitlines()[0].strip()
        s = re.sub(r"^(主题|讨论主题|标题|群聊主题|当前主题)\\s*[:：]\\s*", "", s)
        s = s.strip().strip("“”\"'（）()[]【】")
        while s and s[-1] in "。！？…":
            s = s[:-1].strip()
        if len(s) > max_chars:
            s = s[:max_chars].rstrip()
        return s
    except Exception as e:
        logger.error(f"AI 生成群聊主题失败: {e}", exc_info=True)
        return ""


def _build_next_prompt_fallback(discussion_goal: str, context: str) -> str:
    """当主持人未输出 next_prompt 时使用的默认提示词模板。
    刻意给出较完整的最近讨论内容，便于下一位专家（尤其是配图/生成类）有足够信息执行。"""
    return (
        f"【群聊讨论目标】\n{discussion_goal}\n\n"
        f"【最近几轮讨论内容（按时间顺序，含用户与各位专家的发言要点）】\n{context}\n\n"
        "【你这一轮的任务】\n"
        "1. 先用 1～3 句话总结当前讨论已达成的结论或共识。\n"
        "2. 结合你的角色与专长，完成本轮的 1～2 个具体子任务；可从上方「最近几轮讨论内容」中摘取关键信息（链接、主题、用户偏好、已有文案等）直接使用。\n"
        "3. 若涉及生成图片/配图/封面：请根据讨论中的文案或要点确定配图主题与风格，并说明所需尺寸或数量（若已提及）。\n"
        "4. 仅输出你本轮可交付结果，不要在正文中安排下一位角色。\n\n"
        "【输出要求】信息量充足、紧扣目标；可分条书写；避免大段照抄全文，侧重提炼与执行。"
    )


def _get_group_memory_settings(app_settings: Dict[str, Any]) -> Dict[str, Any]:
    cfg = app_settings.get("group_memory") if isinstance(app_settings, dict) else {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "max_logs": int(cfg.get("max_logs", 20)),
        "max_facts": int(cfg.get("max_facts", 60)),
        "dispatch_top_k": int(cfg.get("dispatch_top_k", 3)),
    }


def _extract_facts_from_response(text: str, max_items: int = 4) -> List[str]:
    s = (text or "").strip()
    if not s:
        return []
    lines: List[str] = []
    for line in s.splitlines():
        t = line.strip()
        if not t:
            continue
        if t.startswith(("-", "*", "1.", "2.", "3.", "4.", "5.")):
            t = t.lstrip("-*0123456789. ").strip()
        if len(t) < 6:
            continue
        lines.append(t[:220])
        if len(lines) >= max_items:
            break
    if lines:
        return lines
    compact = s.replace("\n", " ")
    chunks = [x.strip() for x in re.split(r"[。；;.!?！？]", compact) if x.strip()]
    return [c[:220] for c in chunks[:max_items]]


def _build_next_prompt_with_memory(
    session_id: str,
    target_dha_id: str,
    discussion_goal: str,
    context: str,
    app_settings: Dict[str, Any],
    decision_next_prompt: Optional[str] = None,
) -> str:
    mem = _get_group_memory_settings(app_settings)
    if not mem["enabled"]:
        return (decision_next_prompt or "").strip() or _build_next_prompt_fallback(discussion_goal, context)

    dispatch = {"has_memory": False, "rendered": ""}
    try:
        dispatch = build_dispatch_context(
            session_id=session_id,
            target_dha_id=target_dha_id,
            goal=discussion_goal,
            k=mem["dispatch_top_k"],
            max_facts=mem["max_facts"],
        )
    except Exception:
        logger.warning("group memory read failed", exc_info=True)

    if dispatch.get("has_memory"):
        parts = [
            f"【群聊讨论目标】\n{discussion_goal}",
            "【任务要求】\n请先用 1-2 句复述当前你要完成的子任务，再输出可执行结果；若信息不足，先提出最小补充问题（最多 2 个）。",
            str(dispatch.get("rendered") or "").strip(),
        ]
        parts.append("【输出要求】\n聚焦执行，不复读整段历史；不要在正文中指定下一位角色。")
        return "\n\n".join([p for p in parts if p])

    return (decision_next_prompt or "").strip() or _build_next_prompt_fallback(discussion_goal, context)


def _shorten_text(text: str, max_chars: int = 1800) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rstrip() + "\n...[内容已截断]"


def _normalize_compare_text(text: str) -> str:
    s = (text or "").lower()
    s = re.sub(r"[\s\r\n\t]+", "", s)
    s = re.sub(r"[`~!@#$%^&*()_\-+=\[\]{}\\|;:'\",.<>/?，。！？；：、“”‘’（）《》【】…·]", "", s)
    return s


def _ensure_structured_next_prompt(
    prompt: str,
    discussion_goal: str,
    context: str,
    target_dha_id: str,
) -> str:
    """轻量校验 next_prompt 结构，不足时补齐关键段落，避免专家空转。"""
    p = (prompt or "").strip()
    context_excerpt = _shorten_text(context, max_chars=1600)
    has_goal = ("【群聊讨论目标】" in p) or ("讨论目标" in p)
    has_input = any(k in p for k in ("【最近讨论】", "【最近几轮讨论内容", "【输入依据】", "【上下文】", "【已知信息】"))
    has_output_format = any(k in p for k in ("【输出格式】", "【输出要求】", "格式要求", "请按以下格式"))
    has_boundary = any(k in p for k in ("【边界条件】", "若信息不足", "不要", "禁止", "最多"))
    has_delivery = any(k in p for k in ("【交付标准】", "【完成标准】", "验收标准", "达标"))
    compact_len = len(_normalize_compare_text(p))
    missing_core = sum([not has_goal, not has_input, not has_output_format])

    # 缺失较多或内容过短时，构建可执行的结构化模板（保留主持人原始补充）
    if (not p) or compact_len < 120 or missing_core >= 2:
        parts = [
            f"【群聊讨论目标】\n{discussion_goal}",
            f"【输入依据】\n{context_excerpt}",
            "【你本轮要完成的事情】\n"
            "1. 先用 1-2 句确认你理解的子任务；\n"
            "2. 直接输出可执行结果（不是泛泛解释）；\n"
            "3. 只交付本轮结果，不要在正文中指定下一位角色。",
        ]
        parts.extend([
            "【输出格式】\n- 使用分点输出；\n- 每点尽量包含“动作 + 结果”；\n- 涉及链接/参数请显式写出。",
            "【边界条件】\n- 信息不足时，仅提出最多 2 个最小补充问题；\n- 不要复读整段历史，不要偏离讨论目标。",
            "【交付标准】\n- 结论清晰、可执行。",
        ])
        return "\n\n".join(parts)

    parts = [p]
    if not has_goal:
        parts.append(f"【群聊讨论目标】\n{discussion_goal}")
    if not has_input:
        parts.append(f"【输入依据】\n{context_excerpt}")
    if not has_output_format:
        parts.append("【输出格式】\n请分点给出“动作 + 结果”，必要时给出链接/参数。")
    if not has_boundary:
        parts.append("【边界条件】\n若信息不足，仅提出最多 2 个最小补充问题；不要复读整段历史。")
    if not has_delivery:
        parts.append("【交付标准】\n输出应可直接执行，并能让下一位专家无歧义接力。")
    return "\n\n".join(parts)


def _build_checked_next_prompt(
    session_id: str,
    target_dha_id: str,
    discussion_goal: str,
    context: str,
    app_settings: Dict[str, Any],
    decision_next_prompt: Optional[str] = None,
) -> str:
    raw = _build_next_prompt_with_memory(
        session_id=session_id,
        target_dha_id=target_dha_id,
        discussion_goal=discussion_goal,
        context=context,
        app_settings=app_settings,
        decision_next_prompt=decision_next_prompt,
    )
    return _ensure_structured_next_prompt(
        prompt=raw,
        discussion_goal=discussion_goal,
        context=context,
        target_dha_id=target_dha_id,
    )


def _looks_like_conclusion_text(text: str) -> bool:
    s = (text or "").lower()
    keys = (
        "结论", "总结", "综上", "最终", "已完成", "完成了", "没有更多", "无法继续", "请用户补充", "建议用户",
    )
    return any(k in s for k in keys)


def _has_tool_failure(tool_raw_results: List[str], full_content: str) -> bool:
    blob = "\n".join([str(x or "") for x in (tool_raw_results or [])] + [str(full_content or "")]).lower()
    fail_keys = (
        "执行错误", "error", "failed", "exception", "traceback", "timeout", "超时", "not found", "调用异常", "无法",
    )
    return any(k in blob for k in fail_keys)


def _evaluate_soft_stop(
    state: Dict[str, Any],
    current_speaker: str,
    full_content: str,
    tool_raw_results: List[str],
) -> Optional[str]:
    """软判停：连续低增量/重复结论/工具连续失败时提前暂停。"""
    prev_content = str(state.get("prev_content") or "")
    prev_speaker = str(state.get("prev_speaker") or "")
    cur_norm = _normalize_compare_text(full_content)
    prev_norm = _normalize_compare_text(prev_content)
    same_speaker = bool(prev_speaker and prev_speaker == current_speaker)

    if not same_speaker:
        state["low_increment_streak"] = 0
        state["repeat_conclusion_streak"] = 0

    if same_speaker and cur_norm and prev_norm:
        sim = difflib.SequenceMatcher(a=prev_norm[:1600], b=cur_norm[:1600]).ratio()
        low_increment = sim >= 0.88
        repeat_conclusion = sim >= 0.82 and _looks_like_conclusion_text(prev_content) and _looks_like_conclusion_text(full_content)
        state["low_increment_streak"] = int(state.get("low_increment_streak", 0)) + 1 if low_increment else 0
        state["repeat_conclusion_streak"] = int(state.get("repeat_conclusion_streak", 0)) + 1 if repeat_conclusion else 0
    else:
        state["low_increment_streak"] = 0
        state["repeat_conclusion_streak"] = 0

    has_fail = _has_tool_failure(tool_raw_results, full_content)
    state["tool_failure_streak"] = int(state.get("tool_failure_streak", 0)) + 1 if has_fail else 0
    state["prev_content"] = full_content
    state["prev_speaker"] = current_speaker

    if int(state.get("tool_failure_streak", 0)) >= 2:
        return "连续两轮出现工具执行失败/异常，建议先由用户确认或调整任务。"
    if int(state.get("repeat_conclusion_streak", 0)) >= 2:
        return "连续两轮输出结论高度重复，继续自动运行收益较低。"
    if int(state.get("low_increment_streak", 0)) >= 2:
        return "连续两轮内容增量较低，建议暂停并由用户确认下一步。"
    return None


def _append_workspace_image_preview_markdown(content: str, tool_raw_results: List[str]) -> str:
    """若工具结果中包含工作区图片下载链接，则自动补一段 Markdown 图片预览。"""
    if not tool_raw_results:
        return content
    urls: List[str] = []
    for raw in tool_raw_results:
        if not raw:
            continue
        for u in re.findall(r"/api/workspaces/[^\s)]+/files/download\?path=[^\s)]+", raw):
            urls.append(u)
    if not urls:
        return content
    image_urls = []
    for u in urls:
        lu = u.lower()
        if any(ext in lu for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg")):
            image_urls.append(u)
    if not image_urls:
        return content
    seen = set()
    unique_urls = []
    for u in image_urls:
        if u in seen:
            continue
        seen.add(u)
        unique_urls.append(u)
    blocks = []
    for i, u in enumerate(unique_urls, start=1):
        blocks.append(f"![生成图片{i}]({u})\n\n[点击下载图片{i}]({u})")
    extra = "\n\n".join(blocks)
    if extra in (content or ""):
        return content
    base = (content or "").rstrip()
    return f"{base}\n\n---\n\n{extra}" if base else extra


def _get_llm_for_dha(dha: Optional[Dict[str, Any]], app_settings: Dict[str, Any]) -> Any:
    """按 DHA 的 llm_provider_id 或应用默认创建 LLM"""
    provider = (dha.get("llm_provider_id") or "").strip() if dha else ""
    if not provider:
        provider = app_settings.get("default_llm", "qwen")
    return get_llm_from_config(provider, app_settings.get("llm_providers"))


def _get_dha_skill_content(dha: Dict[str, Any]) -> str:
    """获取 DHA 的技能内容（按 skill_ids 取第一个或 default）"""
    sl = _request_skills_loader()
    skill_ids = dha.get("skill_ids") or []
    if skill_ids:
        for sid in skill_ids:
            content = sl.get_skill_full_content(sid)
            if content:
                return content
    return sl.get_skill_full_content("default") or "你是通用助手，直接回答用户问题。"


def _parse_host_response(content: str) -> Optional[Dict[str, Any]]:
    """解析主持人 DHA 的回复，提取主持词与 JSON。

    期望 JSON 字段（可选）：
    - task_done: bool
    - next_speaker: "user" 或某 dha_id
    - reason / announcement: str
    - suggested_add_dha_ids: [dha_id, ...] 或 suggested_add_dha_id: dha_id
    - suggested_order: [dha_id, ...]
    """
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
        # 主持人建议邀请的成员（可选）
        suggested_add_dha_ids = None
        ids_raw = data.get("suggested_add_expert_ids")
        if not isinstance(ids_raw, list) or not ids_raw:
            ids_raw = data.get("suggested_add_dha_ids")
        if isinstance(ids_raw, list) and ids_raw:
            cleaned = [str(x).strip() for x in ids_raw if str(x).strip()]
            if cleaned:
                suggested_add_dha_ids = list(dict.fromkeys(cleaned))
        if not suggested_add_dha_ids:
            sid = (data.get("suggested_add_expert_id") or data.get("suggested_add_dha_id") or "").strip()
            if sid:
                suggested_add_dha_ids = [sid]
        suggested_order = data.get("suggested_order")  # 首轮任务规划：建议的 DHA 运行顺序
        if isinstance(suggested_order, list):
            suggested_order = [str(x).strip().lower() for x in suggested_order if str(x).strip()]
        else:
            suggested_order = None
        phase = (data.get("phase") or "").strip().lower() or None
        owner_dha_id = (data.get("owner_dha_id") or "").strip() or None
        interrupt_reason = (data.get("interrupt_reason") or "").strip().lower() or None
        decision_source = (data.get("decision_source") or "").strip().lower() or "legacy"
        handoff_reason = (data.get("handoff_reason") or "").strip() or None
        required_user_fields = data.get("required_user_fields")
        if not isinstance(required_user_fields, list):
            required_user_fields = []
        if not announcement and reason:
            announcement = reason
        return {
            "task_done": task_done,
            "next_speaker": next_speaker,
            "reason": reason,
            "announcement": announcement or "请下一位发言。",
            "next_prompt": None,
            "suggested_order": suggested_order,
            "suggested_add_dha_ids": suggested_add_dha_ids,
            "suggested_add_expert_ids": suggested_add_dha_ids,
            "phase": phase,
            "owner_dha_id": owner_dha_id,
            "interrupt_reason": interrupt_reason,
            "decision_source": decision_source,
            "handoff_reason": handoff_reason,
            "required_user_fields": required_user_fields,
        }
    except Exception:
        return None


def _extract_valid_dha_ids_from_text(text: str, valid_ids: set[str], max_n: int = 3) -> List[str]:
    """从自由文本里兜底提取合法 dha_id。"""
    if not text or not valid_ids:
        return []
    found = re.findall(r"dha-[a-zA-Z0-9\-]+", str(text), flags=re.I)
    cleaned = [x for x in dict.fromkeys(found) if x in valid_ids]
    return cleaned[: max(0, int(max_n))]


def _extract_valid_dha_ids_from_text_or_names(
    text: str,
    valid_ids: set[str],
    all_instances: List[Dict[str, Any]],
    max_n: int = 3,
) -> List[str]:
    """从主持人自由文本中兜底提取合法专家 ID（支持 dha_id 或专家名字）。"""
    if not text:
        return []
    ids = _extract_valid_dha_ids_from_text(text, valid_ids, max_n=max_n)
    if ids:
        return ids[: max(0, int(max_n))]
    name_hits: List[str] = []
    low = str(text).lower()
    for d in all_instances or []:
        did = (d.get("dha_id") or "").strip()
        if not did or did not in valid_ids:
            continue
        name = str(d.get("name") or "").strip()
        if name and name.lower() in low and did not in name_hits:
            name_hits.append(did)
    return name_hits[: max(0, int(max_n))]


def _user_requests_host_takeover(
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
    # Natural-language takeover must include explicit summon intent, not mere mention.
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


def _select_next_speaker_without_host(
    *,
    dha_ids: List[str],
    last_speaker_dha_id: Optional[str],
    explicit_requested_dha_ids: List[str],
) -> Optional[str]:
    """Fallback progression when host takeover is disabled."""
    if last_speaker_dha_id and last_speaker_dha_id in dha_ids:
        return last_speaker_dha_id
    for did in explicit_requested_dha_ids or []:
        if did in dha_ids:
            return did
    if len(dha_ids) == 1:
        return dha_ids[0]
    return None


def _heuristic_recommend_dhas(
    discussion_goal: str, all_instances: List[Dict[str, Any]], max_n: Optional[int] = None
) -> List[str]:
    """0 成员时兜底推荐：用简单关键词匹配 name/role，返回 dha_id 列表（去重、保序）。

    max_n 为 None 时返回尽可能多的候选（按匹配度排序）。
    """
    goal = (discussion_goal or "").strip().lower()
    scored = []
    for d in all_instances or []:
        did = (d.get("dha_id") or "").strip()
        if not did:
            continue
        name = str(d.get("name") or "").lower()
        role = str(d.get("role") or "").lower()
        hay = f"{did} {name} {role}"
        score = 0
        # 朴素：目标词命中越多越靠前
        for token in (goal.replace("，", " ").replace("。", " ").replace(",", " ").split() if goal else []):
            if token and token in hay:
                score += 3
        # 常见意图兜底
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
        # 仍然没有命中：选前 max_n 个
        for d in all_instances or []:
            did = (d.get("dha_id") or "").strip()
            if did and did not in picked:
                picked.append(did)
            if max_n is not None and len(picked) >= max_n:
                break
    if max_n is not None:
        return picked[:max(0, int(max_n))]
    return picked


def _extract_explicit_requested_dha_ids(user_text: str, all_instances: List[Dict[str, Any]]) -> List[str]:
    """从用户文本中提取明确点名的专家（按 dha_id/name 精确包含匹配）。"""
    text = (user_text or "").strip().lower()
    if not text:
        return []
    out: List[str] = []
    for d in all_instances or []:
        did = (d.get("dha_id") or "").strip()
        if not did:
            continue
        name = str(d.get("name") or "").strip()
        did_hit = did.lower() in text
        name_hit = bool(name) and (name.lower() in text)
        if did_hit or name_hit:
            out.append(did)
    return list(dict.fromkeys(out))


def _skill_requires_confirmation_gate(skill_content: str) -> bool:
    """从 skill 文本中判断是否存在分阶段且需用户确认的流程门控。"""
    s = (skill_content or "").lower()
    if not s:
        return False
    has_stages = ("stage 1" in s and "stage 2" in s) or ("阶段" in s and ("步骤" in s or "流程" in s))
    requires_confirm = ("ask if" in s) or ("wait for user confirmation" in s) or ("用户确认" in s) or ("请确认" in s)
    return has_stages and requires_confirm


def _infer_required_user_fields_for_skill(skill_content: str, model_output: str) -> List[Dict[str, Any]]:
    """当 skill 流程需要用户确认且当前输出进入交互点时，产出统一 required_user_fields。"""
    if not _skill_requires_confirmation_gate(skill_content):
        return []
    text = (model_output or "").strip()
    if not text:
        return []
    has_question = ("?" in text) or ("？" in text) or ("请确认" in text) or ("是否" in text) or ("请补充" in text)
    if not has_question:
        return []
    return [
        {
            "key": "workflow_user_confirmation",
            "label": "请确认是否按当前流程继续，或补充缺失信息",
            "required": True,
        }
    ]


async def _host_decide_by_dha(
    llm,
    host_dha: Dict[str, Any],
    dha_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    last_speaker_dha_id: Optional[str],
    extra_system_prompt: str,
    available_to_add: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    由主持人 DHA 执行主持技能，返回 {task_done, next_speaker, reason, announcement}。
    失败时返回 None，调用方应回退到 leader_decide。
    """
    skill_content = _request_skills_loader().get_skill_full_content("group-host")
    if not skill_content:
        return None
    app_settings = load_app_settings()
    host_prompts = app_settings.get("host_prompts") or {}
    if not isinstance(host_prompts, dict):
        host_prompts = {}
    host_display_name = str(host_prompts.get("host_display_name") or "四九").strip() or "四九"
    name = host_dha.get("name") or host_dha.get("dha_id", host_display_name)
    role = host_dha.get("role") or "群聊主持人"
    skill_content = f"你是 {name}，担任本群主持人。你的角色：{role}。\n\n{skill_content}"
    host_system = (host_dha.get("system_prompt") or "").strip()
    if host_system:
        skill_content = f"{host_system}\n\n{skill_content}"

    dha_lines = []
    for d in dha_list:
        r = d.get("role") or "参与者"
        n = d.get("name") or d.get("dha_id", "")
        did = d.get("dha_id", "")
        dha_lines.append(f"- {n} ({did}): {r}")
    dha_text = "\n".join(dha_lines)

    # 可邀请的专家列表：主持人用它来输出 suggested_add_dha_ids
    add_lines = []
    for d in (available_to_add or []):
        did = (d.get("dha_id") or "").strip()
        if not did:
            continue
        n = (d.get("name") or did) if isinstance(d.get("name") or did, str) else did
        r = d.get("role") or "参与者"
        skills = d.get("skill_ids") or []
        skills_txt = ""
        if isinstance(skills, list) and skills:
            skills_txt = " skills=" + ",".join([str(x) for x in skills if str(x).strip()][:4])
        add_lines.append(f"- {n} ({did}): {r}{skills_txt}")
    available_text = "\n".join(add_lines) if add_lines else "（暂无可邀请专家）"
    host_master_prompt = str(host_prompts.get("host_master_prompt") or "")

    user_content = (
        f"【当前群聊参与者（next_speaker 必须使用以下 dha_id 之一）】\n{dha_text}\n\n"
        f"【讨论目标】\n{discussion_goal}\n\n"
        "【最近讨论内容（按时间顺序）】\n"
        f"{recent_messages}\n\n"
        f"【可邀请专家列表（需要补人时，从此列表选择 suggested_add_dha_ids）】\n{available_text}\n\n"
        "【建议策略】\n"
        "- 若建议补人，优先推荐 1~3 位最相关专家；\n"
        "- 推荐后请先交还给用户确认，不要假设会自动邀请。\n\n"
    )
    if last_speaker_dha_id:
        user_content += f"【刚发言的专家】{last_speaker_dha_id}\n\n"
    else:
        user_content += "【当前为首轮】尚无上一位专家发言。\n\n"

    try:
        # 将 host_master_prompt 作为额外 system prompt 注入
        agent = create_skill_execution_agent(llm, [], skill_content, (host_master_prompt + "\n\n" + (extra_system_prompt or "")).strip())
        initial_state = {"messages": [HumanMessage(content=user_content)], "tools": []}
        run_cfg = {"configurable": {"thread_id": f"host-decide:{uuid.uuid4().hex}"}}
        final_state = await agent.ainvoke(initial_state, config=run_cfg)
        out_msgs = final_state.get("messages", [])
        content_str = ""
        for m in reversed(out_msgs):
            if isinstance(m, AIMessage):
                content_str = str(m.content) if isinstance(m.content, str) else str(m.content or "")
                break
        return _parse_host_response(content_str)
    except Exception as e:
        logger.warning("主持人 DHA 调用失败，将回退到默认调度: %s", e)
        return None


async def _host_only_respond_and_recommend(
    discussion_goal: str,
    recent_messages: str,
    all_instances: List[Dict[str, Any]],
    extra_system_prompt: str,
) -> tuple[str, Optional[List[str]]]:
    """
    当前群聊 0 个成员时：主持人回复用户并推荐 1~3 位专家加入（等待用户确认）。
    返回 (主持人回复正文, suggested_add_dha_ids 或 None)。
    """
    skill_content = _request_skills_loader().get_skill_full_content("group-host")
    if not skill_content:
        skill_content = "你是群聊主持人，负责协调讨论并适时推荐合适的专家加入。"
    app_settings = load_app_settings()
    host_prompts = app_settings.get("host_prompts") or {}
    if not isinstance(host_prompts, dict):
        host_prompts = {}
    host_display_name = str(host_prompts.get("host_display_name") or "四九").strip() or "四九"
    host_zero_member_policy = str(host_prompts.get("host_zero_member_policy") or "")
    host_intro = f"你是 {host_display_name}，担任本群主持人。"
    system_content = (host_zero_member_policy + "\n\n" + host_intro + "\n\n" + str(skill_content or "")).strip()
    dha_lines = []
    for d in all_instances:
        did = d.get("dha_id", "")
        if did == CHAT_DHA_ID:
            continue
        name = d.get("name") or did
        role = d.get("role") or "参与者"
        dha_lines.append(f"- {name} ({did}): {role}")
    dha_text = "\n".join(dha_lines) if dha_lines else "（暂无可选专家）"
    llm = _get_llm_for_dha(None, app_settings)
    user_content = (
        f"【讨论目标/用户消息】\n{discussion_goal}\n\n"
        f"【最近对话】\n{recent_messages}\n\n"
        f"【可选专家列表】\n{dha_text}\n\n"
        "【建议策略】\n"
        "- 优先推荐 1~3 位最相关专家（按优先级排序）；\n"
        "- 推荐后先等待用户确认邀请。\n\n"
    )
    agent = create_skill_execution_agent(llm, [], system_content, extra_system_prompt or "")
    initial_state = {"messages": [HumanMessage(content=user_content)], "tools": []}
    try:
        run_cfg = {"configurable": {"thread_id": f"host-zero:{uuid.uuid4().hex}"}}
        final_state = await agent.ainvoke(initial_state, config=run_cfg)
        out_msgs = final_state.get("messages", [])
        content_str = ""
        for m in reversed(out_msgs):
            if isinstance(m, AIMessage):
                content_str = str(m.content) if isinstance(m.content, str) else str(m.content or "")
                break
        if not content_str or not content_str.strip():
            # LLM 没输出：直接兜底推荐
            fallback_ids = _heuristic_recommend_dhas(discussion_goal, all_instances, max_n=3)
            return "我已收到您的需求，建议先邀请以下专家加入讨论。", fallback_ids or None
        text = content_str.strip()
        announcement = text
        suggested_add_dha_ids: Optional[List[str]] = None
        valid_ids = {d.get("dha_id") for d in all_instances if d.get("dha_id")}
        for sep in ("\n{", "{"):
            if sep in text:
                idx = text.find(sep) if sep == "{" else text.find(sep) + 1
                announcement = text[:idx].strip()
                # 去掉正文末尾可能残留的 ```json 或 ``` 代码块标记，避免在前端展示出多余的 “```json”
                for fence in ("```json", "```"):
                    if announcement.endswith(fence):
                        announcement = announcement[: -len(fence)].rstrip()
                json_str = text[idx:].strip()
                try:
                    data = json.loads(json_str)
                    ids_raw = data.get("suggested_add_expert_ids")
                    if not isinstance(ids_raw, list) or not ids_raw:
                        ids_raw = data.get("suggested_add_dha_ids")
                    if isinstance(ids_raw, list) and ids_raw:
                        # 过滤合法 id，去重并限制最多 3 位（优先最相关）
                        cleaned = [str(x).strip() for x in ids_raw if str(x).strip() in valid_ids]
                        if cleaned:
                            # 保持顺序去重
                            suggested_add_dha_ids = list(dict.fromkeys(cleaned))[:3]
                    if not suggested_add_dha_ids:
                        sid = (data.get("suggested_add_expert_id") or data.get("suggested_add_dha_id") or "").strip()
                        if sid and sid in valid_ids:
                            suggested_add_dha_ids = [sid]
                except Exception:
                    pass
                break
        # 若 JSON 未解析出推荐列表，从正文中提取 dha-xxx 作为备用（主持人常在正文中写专家 id，如 dha-url-to-blog、dha-2be73edd）
        if not suggested_add_dha_ids and valid_ids:
            dha_id_pattern = re.compile(r"dha-[a-zA-Z0-9\-]+", re.I)
            found = list(dict.fromkeys(dha_id_pattern.findall(text)))
            suggested_add_dha_ids = [x for x in found if x in valid_ids][:3]
        return announcement or text, suggested_add_dha_ids
    except Exception as e:
        logger.warning("主持人 0 成员推荐调用失败: %s", e)
        fallback_ids = _heuristic_recommend_dhas(discussion_goal, all_instances, max_n=3)
        return "我已收到您的需求，建议先邀请以下专家加入讨论。", fallback_ids or None


class _NeedUserInputHeuristicHook:
    name = "need_user_input_heuristic"
    priority = HookPriority.ORCHESTRATOR_GUARD

    async def run(self, payload: Dict[str, Any]) -> HookResult:
        req = payload.get("required_user_fields")
        if isinstance(req, list) and req:
            return HookResult(
                allow=False,
                interrupt_reason=InterruptReason.NEED_USER_INPUT,
                message="expert_requires_user_confirmation",
                metadata={"required_user_fields": req},
            )
        text = str(payload.get("full_content") or "")
        if not text.strip():
            return HookResult(allow=True)
        markers = (
            "请提供",
            "请补充",
            "还需要你",
            "需要你提供",
            "请确认",
            "请上传",
            "请给我",
            "请告诉我",
        )
        if any(m in text for m in markers):
            fields = payload.get("required_user_fields")
            if not isinstance(fields, list):
                fields = [{"key": "user_input", "label": "请补充必要信息", "required": True}]
            return HookResult(
                allow=False,
                interrupt_reason=InterruptReason.NEED_USER_INPUT,
                message="expert_need_user_input",
                metadata={"required_user_fields": fields},
            )
        return HookResult(allow=True)


class _ToolFailureHeuristicHook:
    name = "tool_failure_heuristic"
    priority = HookPriority.POLICY_GUARD

    async def run(self, payload: Dict[str, Any]) -> HookResult:
        raw = payload.get("tool_raw_results") or []
        if not isinstance(raw, list):
            raw = [str(raw)]
        text = "\n".join([str(x or "") for x in raw])
        if ("执行错误" in text) or ("error" in text.lower() and "tool" in text.lower()):
            return HookResult(
                allow=False,
                interrupt_reason=InterruptReason.TOOL_UNAVAILABLE,
                message="tool_execution_failed",
                metadata={},
            )
        return HookResult(allow=True)


# ========== Pydantic 模型 ==========


class GroupSessionCreate(BaseModel):
    title: str = "新群聊"
    agent_ids: List[str] = Field(default_factory=list)
    dha_ids: List[str] = []  # 可为空，表示单聊；之后通过邀请追加 DHA 变为群聊
    expert_ids: List[str] = Field(default_factory=list)  # 兼容字段：expert_ids
    leader_dha_id: Optional[str] = ""  # 已废弃：主持人改为写死在代码流程中，不再由 DHA 担任
    speak_mode: Optional[str] = "auto"  # auto | manual


class GroupSessionUpdate(BaseModel):
    title: Optional[str] = None
    speak_mode: Optional[str] = None
    add_agent_ids: Optional[List[str]] = None  # 向已有群聊追加 Agent
    remove_agent_ids: Optional[List[str]] = None  # 从群聊中移除 Agent
    add_dha_ids: Optional[List[str]] = None  # 向已有群聊追加 DHA
    remove_dha_ids: Optional[List[str]] = None  # 从群聊中移除 DHA
    add_expert_ids: Optional[List[str]] = None  # 兼容字段：add_expert_ids
    remove_expert_ids: Optional[List[str]] = None  # 兼容字段：remove_expert_ids


class GroupChatRequest(BaseModel):
    message: Optional[str] = None
    override_next_speaker: Optional[str] = None  # dha_id | "user" | null
    action: Optional[str] = None  # "continue" 继续下一轮
    custom_prompt: Optional[str] = None  # 手动模式下，可由前端传入自定义给下一发言人的提示词（覆盖默认生成）
    host_takeover_requested: Optional[bool] = None  # 仅在用户明确提到主持人时才允许主持人调度


class GroupPromptPreviewRequest(BaseModel):
    """前端在 manual 模式下预览（并可编辑）某个 DHA 下一轮发言时将收到的提示词内容。"""

    agent_id: Optional[str] = None
    dha_id: Optional[str] = None
    expert_id: Optional[str] = None


# ========== 统一会话用内部接口（供 api/sessions 复用） ==========


def create_session_internal(
    title: str = "新对话",
    agent_ids: Optional[List[str]] = None,
    dha_ids: Optional[List[str]] = None,
    expert_ids: Optional[List[str]] = None,
    speak_mode: str = "auto",
) -> Dict[str, Any]:
    """创建一条会话（主持人必在，dha_ids 可为空）。返回 meta 条目（含 id）。"""
    instances = load_dha_instances()
    valid_ids = {d.get("dha_id") for d in instances}
    resolved_ids = _normalize_agent_ids(
        legacy_dha_ids=dha_ids,
        agent_ids=agent_ids,
        expert_ids=expert_ids,
    )
    for did in resolved_ids:
        if did not in valid_ids:
            raise HTTPException(status_code=400, detail=f"专家 {did} 不存在")
    gsid = f"group-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    meta = _load_group_meta()
    raw_title = (title or "").strip()
    placeholder_titles = {"新对话", "新群聊", ""}
    title_auto_generated = raw_title in placeholder_titles or raw_title.startswith("多Agent协作 ·")
    meta[gsid] = {
        "title": title or "新对话",
        "title_auto_generated": title_auto_generated,
        "dha_ids": resolved_ids,
        "leader_dha_id": "",
        "speak_mode": (speak_mode or "auto").strip().lower(),
        "created_at": now,
        "updated_at": now,
    }
    _save_group_meta(meta)
    _save_group_history(gsid, [])
    # 工作区目录延后创建：仅在用户首次使用工作区（列表/上传/导出等）时由 files API 或 export 创建
    return _build_session_payload(gsid, meta[gsid])


def export_session_to_markdown(session_id: str, filename: Optional[str] = None) -> tuple:
    """将会话历史导出为 Markdown 到该会话工作区。历史来自 group_history。返回 (rel_path, download_url)。"""
    from app.api.files import get_workspace_root

    messages = _load_group_history(session_id)
    if not messages:
        raise HTTPException(status_code=400, detail="会话无消息，无法导出")
    lines = ["# 对话导出\n", f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "---\n"]
    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        dha_id = msg.get("dha_id", "")
        if role == "user":
            lines.append("## 用户\n\n")
        elif role == "host":
            lines.append("## 主持人\n\n")
        else:
            label = dha_id or "助手"
            lines.append(f"## {label}\n\n")
        lines.append(content)
        lines.append("\n\n")
    md = "".join(lines)
    ws_root = get_workspace_root(session_id)
    fn = filename or f"session-{session_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    fn = fn.replace("..", "").replace("/", "")
    if not fn.endswith(".md"):
        fn += ".md"
    filepath = ws_root / fn
    filepath.write_text(md, encoding="utf-8")
    rel = str(filepath.relative_to(ws_root)).replace("\\", "/")
    return rel, f"/api/workspaces/{session_id}/files/download?path={rel}"


# ========== API 路由 ==========


@router.get("/group-sessions")
async def list_group_sessions(response: Response):
    """兼容别名：获取群聊会话列表（推荐迁移到 /sessions）。"""
    _set_group_alias_deprecated_header(response)
    meta = _load_group_meta()
    _cleanup_orphan_group_histories(meta)
    sessions = []
    for gsid, gm in meta.items():
        sessions.append(_build_session_payload(gsid, gm))
    sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"status": "ok", "data": {"sessions": sessions}}


@router.post("/group-sessions/{group_session_id}/prompt-preview")
async def preview_next_speaker_prompt(group_session_id: str, body: GroupPromptPreviewRequest):
    """
    预览指定 DHA 作为下一发言人时，将要收到的用户侧提示词（HumanMessage 内容）。

    仅用于前端 manual 模式下展示/编辑提示词，不实际触发 LLM 调用。
    """
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    m = meta[group_session_id]
    session_meta = m
    dha_ids = m.get("dha_ids", [])
    target_dha_id = (body.agent_id or body.expert_id or body.dha_id or "").strip()
    if target_dha_id not in dha_ids:
        raise HTTPException(status_code=400, detail="专家不在该群聊中")

    messages = _load_group_history(group_session_id)

    # 讨论目标：取首条用户消息（去掉前端已加的「【讨论目标】」前缀，避免重复）
    discussion_goal = ""
    for msg in messages:
        if msg.get("role") == "user":
            discussion_goal = _normalize_discussion_goal(msg.get("content") or "")
            break
    if not discussion_goal:
        discussion_goal = "待用户提出讨论主题"

    # 与实际调用时保持一致的上下文拼接逻辑
    context = _messages_to_context(messages)
    user_content = (
        f"【群聊讨论目标】\n{discussion_goal}\n\n"
        f"【最近讨论】\n{context}\n\n"
        "请紧扣讨论目标发言，不要偏离主题。"
    )

    return {"status": "ok", "data": {"prompt": user_content}}


@router.post("/group-sessions")
async def create_group_session(body: GroupSessionCreate, response: Response):
    """创建群聊会话。dha_ids 为空时表示「主持人为先」：用户先与主持人交流。"""
    _set_group_alias_deprecated_header(response)
    resolved_ids = _normalize_agent_ids(
        legacy_dha_ids=body.dha_ids,
        agent_ids=body.agent_ids,
        expert_ids=body.expert_ids,
    )
    if body.leader_dha_id and resolved_ids and body.leader_dha_id not in resolved_ids:
        raise HTTPException(status_code=400, detail="leader_dha_id 必须在专家列表中")
    data = create_session_internal(
        title=body.title or "新群聊",
        dha_ids=resolved_ids,
        speak_mode=body.speak_mode or "auto",
    )
    return {"status": "ok", "data": data}


@router.get("/group-sessions/{group_session_id}")
async def get_group_session(group_session_id: str):
    """获取群聊详情与消息。"""
    meta = _load_group_meta()
    # #region agent log
    _log_path = Path(__file__).resolve().parents[3] / ".cursor" / "debug-1338a6.log"
    _found = group_session_id in meta
    try:
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        _log_path.open("a").write(
            json.dumps({"sessionId": "1338a6", "location": "group_chat.get_group_session", "message": "get_group_session", "data": {"group_session_id": group_session_id, "found": _found}, "timestamp": int(time.time() * 1000), "hypothesisId": "H1"}) + "\n"
        )
    except Exception:
        pass
    # #endregion
    if not _found:
        raise HTTPException(status_code=404, detail="Group session not found")
    m = meta[group_session_id]
    messages = _load_group_history(group_session_id)
    instances = load_dha_instances()
    dha_map_raw = {d.get("dha_id"): d for d in instances if d.get("dha_id")}
    dha_ids_in_group = set(m.get("dha_ids", []))
    dha_ids_in_messages = {msg.get("dha_id") for msg in messages if msg.get("dha_id")}
    relevant_ids = dha_ids_in_group | dha_ids_in_messages
    dha_map = {
        k: {
            "name": v.get("name") or "",
            "role": v.get("role") or "",
            "is_leader": v.get("is_leader", False),
        }
        for k, v in dha_map_raw.items()
        if k in relevant_ids
    }
    return {
        "status": "ok",
        "data": {
            **_build_session_payload(group_session_id, m),
            "messages": messages,
            "dha_map": dha_map,
            "expert_map": dha_map,
        },
    }


@router.put("/group-sessions/{group_session_id}")
async def update_group_session(group_session_id: str, body: GroupSessionUpdate):
    """更新群聊：重命名、发言模式、追加 DHA 等。若会话不在 meta 中但请求为邀请（add_dha_ids），则自动创建该会话条目以避免 404。"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        if body.add_dha_ids:
            now = datetime.now(timezone.utc).isoformat()
            meta[group_session_id] = {
                "title": "新群聊",
                "title_auto_generated": True,
                "dha_ids": [],
                "leader_dha_id": "",
                "speak_mode": "auto",
                "created_at": now,
                "updated_at": now,
            }
            _save_group_meta(meta)
            path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
            if not path.exists():
                _save_group_history(group_session_id, [])
        else:
            raise HTTPException(status_code=404, detail="Group session not found")
    if body.title is not None and str(body.title).strip():
        next_title = body.title.strip()
        meta[group_session_id]["title"] = next_title
        # 兼容历史前端自动模板标题：仍视为“自动生成”，允许后续被主题标题覆盖
        if next_title.startswith("多Agent协作 ·") or next_title in {"新对话", "新群聊", ""}:
            meta[group_session_id]["title_auto_generated"] = True
        else:
            # 用户主动修改标题后，停止自动主题覆盖
            meta[group_session_id]["title_auto_generated"] = False
    if body.speak_mode is not None and body.speak_mode.strip().lower() in ("auto", "manual"):
        meta[group_session_id]["speak_mode"] = body.speak_mode.strip().lower()
    add_ids = (
        body.add_expert_ids
        if body.add_expert_ids is not None
        else (body.add_agent_ids if body.add_agent_ids is not None else body.add_dha_ids)
    )
    remove_ids = (
        body.remove_expert_ids
        if body.remove_expert_ids is not None
        else (body.remove_agent_ids if body.remove_agent_ids is not None else body.remove_dha_ids)
    )
    if add_ids or remove_ids:
        instances = load_dha_instances()
        id_to_name = {
            d.get("dha_id"): (d.get("name") or d.get("dha_id"))
            for d in instances
            if d.get("dha_id")
        }
        valid_ids = {d.get("dha_id") for d in instances if d.get("dha_id")}
        current = set(meta[group_session_id].get("dha_ids", []))
        before_ids = set(current)
        newly_added_ids: List[str] = []
        if add_ids:
            for did in add_ids:
                if did not in valid_ids:
                    raise HTTPException(status_code=400, detail=f"专家 {did} 不存在")
                if did not in current:
                    newly_added_ids.append(did)
                current.add(did)
            current.discard(CHAT_DHA_ID)
        if remove_ids:
            for did in remove_ids:
                current.discard(did)
        meta[group_session_id]["dha_ids"] = list(current)
        # 仅在确实新增成员时，写入主持人提示消息（一次一条）
        if newly_added_ids:
            unique_added = list(dict.fromkeys([x for x in newly_added_ids if x in current and x not in before_ids]))
            if unique_added:
                messages = _load_group_history(group_session_id)
                for did in unique_added:
                    display_name = id_to_name.get(did, did)
                    join_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host",
                        "content": f"已邀请“{display_name}”加入会话",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "event_type": "member_joined",
                        "joined_dha_ids": [did],
                    }
                    messages.append(join_msg)
                _save_group_history(group_session_id, messages)
    meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_group_meta(meta)
    return {"status": "ok", "data": _build_session_payload(group_session_id, meta[group_session_id])}


@router.delete("/group-sessions/{group_session_id}")
async def delete_group_session(group_session_id: str):
    """删除群聊会话：同时删除 meta、群聊历史文件与该会话的工作区目录。"""
    current_user = get_current_user()
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    del meta[group_session_id]
    _save_group_meta(meta)
    # 删除群聊历史
    path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    if path.exists():
        path.unlink()
    # 顺手清理孤儿历史（避免旧残留持续堆积）
    _cleanup_orphan_group_histories(meta)
    # 删除该会话对应的工作区目录（若存在）
    try:
        ws_root = get_workspace_root_path(group_session_id, user=current_user)
        if ws_root.exists() and ws_root.is_dir():
            shutil.rmtree(ws_root)
    except Exception:
        logger.warning("删除群聊 %s 的 workspace 目录失败，可手动清理。", group_session_id, exc_info=True)
    return {"status": "ok", "data": {"id": group_session_id, "deleted": True}}


@router.delete("/group-sessions/{group_session_id}/messages/{message_id}")
async def delete_group_message(group_session_id: str, message_id: str):
    """从会话列表和会话历史中彻底删除一条消息（含专家发言），避免污染下一轮 DHA 的上下文。"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    messages = _load_group_history(group_session_id)
    before = len(messages)
    messages = [m for m in messages if m.get("message_id") != message_id]
    if len(messages) == before:
        raise HTTPException(status_code=404, detail="Message not found")
    _save_group_history(group_session_id, messages)
    return {"status": "ok", "data": {"message_id": message_id, "deleted": True}}


@router.post("/group-sessions/{group_session_id}/chat/stream")
async def group_chat_stream(group_session_id: str, request: GroupChatRequest):
    """群聊流式对话：用户消息或继续下一轮，支持 override_next_speaker"""
    await _ensure_initialized()

    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    m = meta[group_session_id]
    session_meta = m
    dha_ids = m.get("dha_ids", [])
    leader_dha_id = m.get("leader_dha_id", "")
    instances = load_dha_instances()
    dha_map = {d.get("dha_id"): d for d in instances}
    dha_list = [d for d in instances if d.get("dha_id") in dha_ids]
    # 当前不在群内的专家，主持人可在「完成不了工作」时建议邀请
    available_to_add = [d for d in instances if d.get("dha_id") and d.get("dha_id") not in dha_ids and d.get("dha_id") != CHAT_DHA_ID]

    messages = _load_group_history(group_session_id)
    app_settings = load_app_settings()
    host_prompts = app_settings.get("host_prompts") or {}
    if not isinstance(host_prompts, dict):
        host_prompts = {}
    host_display_name = str(host_prompts.get("host_display_name") or "四九").strip() or "四九"
    pending_owner_dha_id = (m.get("pending_owner_dha_id") or "").strip().lower()
    pending_skill_id = (m.get("pending_skill_id") or "").strip()
    explicit_requested_dha_ids = _extract_explicit_requested_dha_ids(request.message or "", instances) if (request.message and request.message.strip()) else []
    auto_resume_owner: Optional[str] = None
    host_takeover_requested = _user_requests_host_takeover(
        request.message or "",
        explicit_flag=request.host_takeover_requested,
        host_display_name=host_display_name,
    )

    # 用户消息
    if request.message and request.message.strip():
        if pending_owner_dha_id and pending_owner_dha_id in dha_ids and request.override_next_speaker is None:
            auto_resume_owner = pending_owner_dha_id
        first_user_message = not any(m.get("role") == "user" for m in messages)
        messages.append({
            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
            "role": "user",
            "content": request.message.strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _save_group_history(group_session_id, messages)
        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

        current_title = (meta[group_session_id].get("title") or "").strip()
        placeholder_titles = ("新对话", "新群聊", "")
        is_template_title = current_title.startswith("多Agent协作 ·")
        title_auto_generated = meta[group_session_id].get("title_auto_generated")
        if title_auto_generated is None:
            # 兼容历史：若标题较短或仍是占位符，则视为“自动生成的标题”，允许覆盖更新
            title_auto_generated = current_title in placeholder_titles or is_template_title or len(current_title) <= 12

        if title_auto_generated or current_title in placeholder_titles or is_template_title:
            llm_provider_id = app_settings.get("default_llm", "qwen")
            llm = get_llm_from_config(llm_provider_id, app_settings.get("llm_providers"))
            # 基于最近用户发言生成“当前主题”，避免讨论发散后标题仍停留在旧主题
            ai_title = await _ai_title_from_recent_user_messages(llm, messages, max_chars=18, max_user_messages=6)
            if ai_title:
                meta[group_session_id]["title"] = ai_title
                meta[group_session_id]["title_auto_generated"] = True
            elif first_user_message and current_title in placeholder_titles:
                # AI 失败时的回退：截取首条用户消息（较短，保证可用）
                auto_title = _title_from_first_message(request.message.strip(), max_chars=10)
                if auto_title:
                    meta[group_session_id]["title"] = auto_title
                    meta[group_session_id]["title_auto_generated"] = True
        _save_group_meta(meta)

    # 上一发言人（用于主持人/领导人判断 task_done；排除主持人本人，只计参与讨论的 DHA）
    last_speaker_dha_id = None
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("dha_id") and msg.get("dha_id") != leader_dha_id:
            last_speaker_dha_id = msg.get("dha_id")
            break

    # 讨论目标：取首条用户消息（去掉前端已加的「【讨论目标】」前缀，避免重复）
    discussion_goal = ""
    for msg in messages:
        if msg.get("role") == "user":
            discussion_goal = _normalize_discussion_goal(msg.get("content") or "")
            break
    if not discussion_goal:
        discussion_goal = "待用户提出讨论主题"

    # 已废弃：不再提供全局 system_prompt；主持人提示词改为在主持人 DHA（is_leader）实例上维护
    extra_system_prompt = ""
    # speak_mode 从会话 meta 读取（m 为 meta[group_session_id]），manual 时仅主持人给建议并结束，等用户选人/改提示词后再发
    speak_mode = m.get("speak_mode", "auto")

    import json as json_module

    async def event_gen():
        nonlocal last_speaker_dha_id, dha_ids, dha_list, available_to_add, host_takeover_requested
        meta_item: Dict[str, Any] = meta.get(group_session_id, {})
        host_takeover_open = bool(host_takeover_requested)
        custom_prompt_used = False  # custom_prompt 仅对本次请求的首个 DHA 生效
        dha_turns = 0  # 本次流中 DHA 总发言轮次
        orch_ctx = OrchestrationContext(
            session_id=group_session_id,
            phase=OrchestrationPhase.PLANNING,
            owner_dha_id=last_speaker_dha_id,
            decision_source=DecisionSource.LEGACY,
        )
        start_turn(orch_ctx, phase=OrchestrationPhase.PLANNING, owner_dha_id=last_speaker_dha_id, source=DecisionSource.LEGACY)
        soft_stop_state: Dict[str, Any] = {
            "prev_content": "",
            "prev_speaker": "",
            "low_increment_streak": 0,
            "repeat_conclusion_streak": 0,
            "tool_failure_streak": 0,
        }
        try:
            required_user_fields: List[Dict[str, Any]] = []
            latest_handoff_reason: Optional[str] = None
            resume_target_dha_id: Optional[str] = last_speaker_dha_id
            current_skill_id_for_pending = pending_skill_id
            post_turn_hooks = HookPipeline([_ToolFailureHeuristicHook(), _NeedUserInputHeuristicHook()])

            def _audit(event_type: str, payload: Dict[str, Any]) -> None:
                try:
                    append_audit_event(group_session_id, event_type, payload, turn_id=orch_ctx.turn_id)
                except Exception:
                    logger.debug("audit append skipped", exc_info=True)

            def _apply_decision_to_ctx(decision: Dict[str, Any]) -> None:
                nonlocal latest_handoff_reason, resume_target_dha_id
                phase_val = str(decision.get("phase") or OrchestrationPhase.PLANNING.value)
                interrupt_val = str(decision.get("interrupt_reason") or InterruptReason.NONE.value)
                source_val = str(decision.get("decision_source") or DecisionSource.LEGACY.value)
                phase = OrchestrationPhase(phase_val) if phase_val in {p.value for p in OrchestrationPhase} else OrchestrationPhase.PLANNING
                interrupt = InterruptReason(interrupt_val) if interrupt_val in {r.value for r in InterruptReason} else InterruptReason.NONE
                source = DecisionSource(source_val) if source_val in {s.value for s in DecisionSource} else DecisionSource.LEGACY
                parsed = OrchestrationDecision(
                    task_done=bool(decision.get("task_done", True)),
                    next_speaker=(decision.get("next_speaker") or "user"),
                    reason=(decision.get("reason") or ""),
                    announcement=(decision.get("announcement") or ""),
                    next_prompt=decision.get("next_prompt"),
                    suggested_add_dha_ids=(decision.get("suggested_add_dha_ids") or []),
                    phase=phase,
                    owner_dha_id=decision.get("owner_dha_id"),
                    interrupt_reason=interrupt,
                    decision_source=source,
                    handoff_reason=decision.get("handoff_reason"),
                    required_user_fields=decision.get("required_user_fields") or [],
                )
                apply_decision(orch_ctx, parsed)
                required_user_fields[:] = list(parsed.required_user_fields or [])
                latest_handoff_reason = parsed.handoff_reason
                resume_target_dha_id = parsed.owner_dha_id
                _audit("scheduler_decision", {"decision": decision, "ctx": orch_ctx.to_dict()})

            def _persist_pending_state(end_payload: Dict[str, Any]) -> None:
                nonlocal current_skill_id_for_pending
                waiting = bool(end_payload.get("waiting_for_user"))
                interrupt = str(end_payload.get("interrupt_reason") or "")
                resume = str(end_payload.get("resume_target_dha_id") or "").strip().lower()
                required = end_payload.get("required_user_fields") or []
                should_keep_pending = (
                    waiting
                    and resume in dha_ids
                    and (
                        interrupt in (InterruptReason.NEED_USER_INPUT.value, InterruptReason.NEED_MORE_CONTEXT.value)
                        or bool(required)
                    )
                )
                if should_keep_pending:
                    meta_item["pending_owner_dha_id"] = resume
                    meta_item["pending_skill_id"] = current_skill_id_for_pending or ""
                    meta_item["pending_phase"] = str(end_payload.get("phase") or "")
                    meta_item["pending_required_user_fields"] = required if isinstance(required, list) else []
                    meta_item["pending_handoff_reason"] = str(end_payload.get("handoff_reason") or "")
                else:
                    meta_item.pop("pending_owner_dha_id", None)
                    meta_item.pop("pending_skill_id", None)
                    meta_item.pop("pending_phase", None)
                    meta_item.pop("pending_required_user_fields", None)
                    meta_item.pop("pending_handoff_reason", None)
                meta_item["updated_at"] = datetime.now(timezone.utc).isoformat()
                _save_group_meta(meta)

            yield f"event: start\ndata: {json_module.dumps({'type': 'start'})}\n\n"

            next_speaker = None

            # 0 个 DHA：主持人为先，主持人回复用户并推荐若干 DHA 加入（不再使用 Chat）
            if len(dha_ids) == 0:
                recent = _messages_to_context(messages)
                all_instances = [d for d in instances if d.get("dha_id") and d.get("dha_id") != CHAT_DHA_ID]
                picked: List[str] = []
                valid_ids = {d.get("dha_id") for d in instances if d.get("dha_id")}
                if explicit_requested_dha_ids:
                    picked = list(dict.fromkeys([x for x in explicit_requested_dha_ids if x in valid_ids]))[:3]
                else:
                    if host_takeover_requested:
                        host_content, suggested_add_dha_ids = await _host_only_respond_and_recommend(
                            discussion_goal, recent, all_instances, extra_system_prompt
                        )
                        suggested_add_dha_ids = suggested_add_dha_ids or []
                        picked = list(dict.fromkeys([x for x in suggested_add_dha_ids if x in valid_ids]))[:3]
                        host_msg = {
                            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                            "role": "host",
                            "content": host_content,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        if picked:
                            host_msg["suggested_add_dha_ids"] = picked
                            host_msg["suggested_add_expert_ids"] = picked
                        messages.append(host_msg)
                        _save_group_history(group_session_id, messages)
                        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                        _save_group_meta(meta)
                        yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                    else:
                        auto_picked = _heuristic_recommend_dhas(discussion_goal, all_instances, max_n=3)
                        picked = list(dict.fromkeys([x for x in auto_picked if x in valid_ids]))[:3]
                end_payload = build_end_payload(
                    waiting_for_user=True,
                    phase=OrchestrationPhase.AWAITING_USER,
                    interrupt_reason=InterruptReason.NONE,
                    resume_target_dha_id=resume_target_dha_id,
                    required_user_fields=required_user_fields,
                    turn_id=orch_ctx.turn_id,
                    token_version=orch_ctx.token_version,
                    handoff_reason=latest_handoff_reason,
                )
                if picked:
                    end_payload["suggested_add_dha_ids"] = picked
                    end_payload["suggested_add_expert_ids"] = picked
                _persist_pending_state(end_payload)
                yield f"event: end\ndata: {json_module.dumps(end_payload, ensure_ascii=False)}\n\n"
                return

            if auto_resume_owner and auto_resume_owner in dha_ids:
                next_speaker = auto_resume_owner
                orch_ctx.phase = OrchestrationPhase.EXECUTING
                orch_ctx.owner_dha_id = auto_resume_owner
                _audit(
                    "auto_resume_pending_owner",
                    {
                        "resume_owner": auto_resume_owner,
                        "pending_skill_id": pending_skill_id,
                        "ctx": orch_ctx.to_dict(),
                    },
                )
            elif request.override_next_speaker is not None:
                next_speaker = request.override_next_speaker.strip().lower()
                if next_speaker == "user":
                    orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                    payload = build_end_payload(
                        waiting_for_user=True,
                        phase=orch_ctx.phase,
                        interrupt_reason=InterruptReason.NONE,
                        resume_target_dha_id=resume_target_dha_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                    )
                    _persist_pending_state(payload)
                    yield f"event: end\ndata: {json_module.dumps(payload)}\n\n"
                    return
                if next_speaker == "end":
                    orch_ctx.phase = OrchestrationPhase.COMPLETED
                    payload = build_end_payload(
                        waiting_for_user=False,
                        discussion_ended=True,
                        phase=orch_ctx.phase,
                        interrupt_reason=InterruptReason.NONE,
                        resume_target_dha_id=resume_target_dha_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                    )
                    _persist_pending_state(payload)
                    yield f"event: end\ndata: {json_module.dumps(payload)}\n\n"
                    return
                if next_speaker and next_speaker not in dha_ids:
                    next_speaker = None
                if next_speaker in dha_ids:
                    orch_ctx.phase = OrchestrationPhase.EXECUTING
                    orch_ctx.owner_dha_id = next_speaker
            elif not host_takeover_open:
                next_speaker = _select_next_speaker_without_host(
                    dha_ids=dha_ids,
                    last_speaker_dha_id=last_speaker_dha_id,
                    explicit_requested_dha_ids=explicit_requested_dha_ids,
                )
                if next_speaker in dha_ids:
                    orch_ctx.phase = OrchestrationPhase.EXECUTING
                    orch_ctx.owner_dha_id = next_speaker
                else:
                    orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                    payload = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker=last_speaker_dha_id if last_speaker_dha_id in dha_ids else None,
                        phase=orch_ctx.phase,
                        interrupt_reason=InterruptReason.NONE,
                        resume_target_dha_id=resume_target_dha_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                    )
                    _persist_pending_state(payload)
                    yield f"event: end\ndata: {json_module.dumps(payload, ensure_ascii=False)}\n\n"
                    return
            elif speak_mode != "auto":
                host_takeover_open = False
                # 非自动（manual）模式：主持人先给出建议。
                # 如果已经明确推荐了下一位 DHA，则在同一条流中直接进入该 DHA 的发言；
                # 仅在主持人没有给出明确下一位时，才等待用户选择。
                recent = _messages_to_context(messages)
                decision = None
                host_dha = dha_map.get(leader_dha_id) if leader_dha_id in dha_ids else None
                if leader_dha_id and host_dha:
                    llm_host = _get_llm_for_dha(host_dha, app_settings)
                    decision = await _host_decide_by_dha(
                        llm_host, host_dha, dha_list, discussion_goal, recent, last_speaker_dha_id, extra_system_prompt, available_to_add
                    )
                if decision is None:
                    llm_default = _get_llm_for_dha(None, app_settings)
                    decision = await leader_decide(llm_default, dha_list, discussion_goal, recent, last_speaker_dha_id, available_to_add)
                decision = normalize_scheduler_decision(
                    decision,
                    dha_ids=dha_ids,
                    recruitable_ids=[str(d.get("dha_id") or "") for d in available_to_add if d.get("dha_id")],
                    last_speaker_dha_id=last_speaker_dha_id,
                    current_owner_dha_id=last_speaker_dha_id,
                )
                _apply_decision_to_ctx(decision)
                announcement = decision.get("announcement")
                suggested = (decision.get("next_speaker") or "").strip().lower()
                suggested_add = decision.get("suggested_add_expert_ids") or decision.get("suggested_add_dha_ids") or []
                recruitable_ids = {d.get("dha_id") for d in available_to_add if d.get("dha_id")}
                suggested_add = list(dict.fromkeys([x for x in suggested_add if x in recruitable_ids]))[:3]
                if not suggested_add and isinstance(announcement, str):
                    suggested_add = _extract_valid_dha_ids_from_text_or_names(announcement, recruitable_ids, available_to_add, max_n=3)
                if suggested in dha_ids and not suggested_add:
                    next_dha = dha_map.get(suggested)
                    next_name = (next_dha.get("name") or suggested) if next_dha else suggested
                    host_content = announcement or f"建议由 {next_name} 发言，请选择发言人并发送。"
                else:
                    host_content = announcement or "请选择下一发言人并发送。"
                host_msg = {
                    "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                    "role": "host" if not leader_dha_id else "assistant",
                    "content": host_content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                if leader_dha_id:
                    host_msg["dha_id"] = leader_dha_id
                messages.append(host_msg)
                # 保存并把主持人建议发给前端
                if suggested in dha_ids and not suggested_add:
                    next_dha = dha_map.get(suggested)
                    host_msg["next_dha_name"] = (next_dha.get("name") or suggested) if next_dha else suggested
                if decision.get("suggested_order"):
                    host_msg["suggested_order"] = decision["suggested_order"]
                _save_group_history(group_session_id, messages)
                yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                # 如果主持人已经明确推荐了下一位 DHA，则直接把该 DHA 作为下一发言人继续往下走，
                # 不再发 waiting_for_user，让前端自动看到该 DHA 的发言。
                if suggested in dha_ids and not suggested_add:
                    next_speaker = suggested
                    orch_ctx.phase = OrchestrationPhase.EXECUTING
                    orch_ctx.owner_dha_id = suggested
                else:
                    orch_ctx.phase = OrchestrationPhase.AWAITING_USER if not suggested_add else OrchestrationPhase.RECRUITING
                    # 否则等待用户选择；若建议补人，仅展示推荐列表，等待用户确认邀请
                    if suggested_add:
                        host_msg["suggested_add_dha_ids"] = suggested_add
                        host_msg["suggested_add_expert_ids"] = suggested_add
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        phase=orch_ctx.phase,
                        interrupt_reason=InterruptReason.NEED_RECRUIT_EXPERT if suggested_add else InterruptReason.NONE,
                        resume_target_dha_id=resume_target_dha_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                    )
                    if suggested_add:
                        end_data["suggested_add_dha_ids"] = suggested_add
                        end_data["suggested_add_expert_ids"] = suggested_add
                    _persist_pending_state(end_data)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return
            else:
                host_takeover_open = False
                # auto：由主持人 DHA 或默认调度决定下一发言人
                recent = _messages_to_context(messages)
                decision = None
                host_dha = dha_map.get(leader_dha_id) if leader_dha_id else None
                if leader_dha_id and leader_dha_id in dha_ids and host_dha:
                    llm_host = _get_llm_for_dha(host_dha, app_settings)
                    decision = await _host_decide_by_dha(
                        llm_host, host_dha, dha_list, discussion_goal, recent, last_speaker_dha_id, extra_system_prompt, available_to_add
                    )
                if decision is None:
                    llm_default = _get_llm_for_dha(None, app_settings)
                    decision = await leader_decide(llm_default, dha_list, discussion_goal, recent, last_speaker_dha_id, available_to_add)
                decision = normalize_scheduler_decision(
                    decision,
                    dha_ids=dha_ids,
                    recruitable_ids=[str(d.get("dha_id") or "") for d in available_to_add if d.get("dha_id")],
                    last_speaker_dha_id=last_speaker_dha_id,
                    current_owner_dha_id=last_speaker_dha_id,
                )
                _apply_decision_to_ctx(decision)
                announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                suggested_add = (decision.get("suggested_add_expert_ids") or decision.get("suggested_add_dha_ids") or [])
                recruitable_ids = {d.get("dha_id") for d in available_to_add if d.get("dha_id")}
                suggested_add = list(dict.fromkeys([x for x in suggested_add if x in recruitable_ids]))[:3]
                if not suggested_add and isinstance(announcement, str):
                    suggested_add = _extract_valid_dha_ids_from_text_or_names(announcement, recruitable_ids, available_to_add, max_n=3)
                # 由主持人/调度明确给出下一位发言人。
                # 不再根据 task_done 强制让上一位 DHA 连续发言，
                # 每一小轮都回到主持人决策，再由 decision["next_speaker"] 指定下一位。
                next_speaker = decision.get("next_speaker", "user")
                # 主持人建议新增成员时：仅给出推荐，等待用户确认邀请
                if suggested_add:
                    host_content = "当前成员无法完成该工作，建议先邀请更匹配的专家。"
                    next_speaker = "user"
                    orch_ctx.phase = OrchestrationPhase.RECRUITING
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host" if not leader_dha_id else "assistant",
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "suggested_add_dha_ids": suggested_add,
                        "suggested_add_expert_ids": suggested_add,
                    }
                    if leader_dha_id:
                        host_msg["dha_id"] = leader_dha_id
                    messages.append(host_msg)
                    _save_group_history(group_session_id, messages)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                # 主持人发言（单人会话时也由主持人先点名，再让该 DHA 发言）
                if next_speaker in dha_ids:
                    orch_ctx.phase = OrchestrationPhase.EXECUTING
                    orch_ctx.owner_dha_id = next_speaker
                    host_content = announcement if announcement else None
                    if not host_content:
                        next_dha = dha_map.get(next_speaker)
                        next_name = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                        host_content = f"下面由 {next_name} 发言。"
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host" if not leader_dha_id else "assistant",
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    if leader_dha_id:
                        host_msg["dha_id"] = leader_dha_id
                    messages.append(host_msg)
                    next_dha = dha_map.get(next_speaker)
                    host_msg["next_dha_name"] = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                    if decision.get("suggested_order"):
                        host_msg["suggested_order"] = decision["suggested_order"]
                    _save_group_history(group_session_id, messages)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                    # 这里不再发送 waiting_for_user 的 end 事件，而是直接在同一条流中继续执行
                    # 下方 while next_speaker 循环会立刻进入对应 DHA 的发言，实现“主持人点名后自动发言”。

            while orch_ctx.phase == OrchestrationPhase.EXECUTING and next_speaker and next_speaker in dha_ids:
                # 在自动或手动模式下，单次流中专家发言超过一定轮次（默认 32）时强制停下来，让用户确认是否继续，
                # 避免在服务器上长时间无限循环。
                if dha_turns >= 32:
                    move_to_interrupt(orch_ctx, InterruptReason.TIMEOUT_OR_BUDGET_EXCEEDED)
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker=next_speaker,
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=InterruptReason.TIMEOUT_OR_BUDGET_EXCEEDED,
                        resume_target_dha_id=resume_target_dha_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                        extra={"turns_limit_reached": True},
                    )
                    _persist_pending_state(end_data)
                    yield f"event: end\ndata: {json_module.dumps(end_data)}\n\n"
                    return
                dha_turns += 1
                start_turn(
                    orch_ctx,
                    phase=OrchestrationPhase.EXECUTING,
                    owner_dha_id=next_speaker,
                    source=DecisionSource.EXPERT,
                )
                resume_target_dha_id = next_speaker
                _audit("turn_started", {"speaker": next_speaker, "turn_index": dha_turns, "ctx": orch_ctx.to_dict()})
                dha = dha_map.get(next_speaker)
                if not dha:
                    move_to_interrupt(orch_ctx, InterruptReason.NEED_MORE_CONTEXT)
                    next_speaker = "user"
                    break

                tools = await build_tools_for_group_chat(dha, group_session_id)
                skill_content = _get_dha_skill_content(dha)
                role = dha.get("role") or ""
                dha_system = (dha.get("system_prompt") or "").strip()
                if dha_system:
                    skill_content = f"{dha_system}\n\n{skill_content}"
                if role:
                    skill_content = f"你的角色：{role}\n\n{skill_content}"

                llm_dha = _get_llm_for_dha(dha, app_settings)
                agent = create_skill_execution_agent(llm_dha, tools, skill_content, extra_system_prompt)
                context = _messages_to_context(messages)
                if not custom_prompt_used and request.custom_prompt:
                    user_content = (request.custom_prompt or "").strip()
                    custom_prompt_used = True
                else:
                    # 主持人不再生成 next_prompt；仅使用目标 + 最近讨论作为默认输入。
                    user_content = (
                        f"【群聊讨论目标】\n{discussion_goal}\n\n"
                        f"【最近讨论】\n{context}\n\n"
                        "请紧扣讨论目标发言，不要偏离主题。"
                    )
                # 避免重复拼接历史：如果默认输入中已包含“最近讨论/历史对话”，则不再追加。
                uc = (user_content or "").strip()
                if ("【历史对话（供参考）】" not in uc) and ("【最近几轮讨论内容" not in uc) and ("【最近讨论】" not in uc):
                    uc = uc + "\n\n【历史对话（供参考）】\n" + context
                user_content = uc
                initial_state = {"messages": [HumanMessage(content=user_content)], "tools": tools}
                run_cfg = {"configurable": {"thread_id": f"group:{group_session_id}:{next_speaker}:{uuid.uuid4().hex}"}}

                accumulated = []
                accumulated_raw_tool_results: List[str] = []
                try:
                    async for stream_item in agent.astream(
                        initial_state, config=run_cfg, stream_mode=["updates", "messages", "values"]
                    ):
                        if isinstance(stream_item, tuple) and len(stream_item) == 2:
                            mode, chunk = stream_item
                            if mode == "messages":
                                msg_chunk, meta_info = chunk if isinstance(chunk, tuple) and len(chunk) >= 2 else (chunk, {})
                                if meta_info.get("langgraph_node") == "agent" and hasattr(msg_chunk, "content") and msg_chunk.content:
                                    txt = msg_chunk.content if isinstance(msg_chunk.content, str) else str(msg_chunk.content or "")
                                    if txt:
                                        accumulated.append(txt)
                                        yield f"event: content\ndata: {json_module.dumps({'text': txt, 'dha_id': next_speaker, 'meta': {}}, ensure_ascii=False)}\n\n"
                            continue
                        event = stream_item if not isinstance(stream_item, tuple) else stream_item[1]
                        if isinstance(event, dict) and "tool" in event:
                            tool_msgs = event["tool"]
                            if isinstance(tool_msgs, dict) and "messages" in tool_msgs:
                                tool_msgs = tool_msgs["messages"] or []
                            if not isinstance(tool_msgs, list):
                                tool_msgs = [tool_msgs]
                            for tm in tool_msgs:
                                content = None
                                if isinstance(tm, dict) and "messages" in tm and isinstance(tm["messages"], list) and tm["messages"]:
                                    tm = tm["messages"][0]
                                if isinstance(tm, (HumanMessage, ToolMessage)):
                                    content = tm.content
                                elif isinstance(tm, dict) and tm.get("content"):
                                    content = tm["content"]
                                elif hasattr(tm, "content"):
                                    content = getattr(tm, "content", None)
                                if content is not None:
                                    raw_str = str(content) if not isinstance(content, str) else content
                                    if raw_str and raw_str not in accumulated_raw_tool_results:
                                        accumulated_raw_tool_results.append(raw_str)
                        if isinstance(event, dict) and "agent" in event:
                            agent_out = event["agent"]
                            aimsg = None
                            if isinstance(agent_out, dict) and "messages" in agent_out:
                                for m in reversed(agent_out["messages"]):
                                    if isinstance(m, AIMessage):
                                        aimsg = m
                                        break
                            elif isinstance(agent_out, list):
                                for m in reversed(agent_out):
                                    if isinstance(m, AIMessage):
                                        aimsg = m
                                        break
                            if aimsg:
                                has_tool_calls = hasattr(aimsg, "tool_calls") and aimsg.tool_calls
                                if has_tool_calls:
                                    for tco in aimsg.tool_calls:
                                        tool_name = tco.get("name") or tco.get("id", "")
                                        args = tco.get("args") or {}
                                        payload = {"action": "tool_call", "tool": tool_name, "arguments": args}
                                        tc_json = json_module.dumps(payload, ensure_ascii=False, indent=2)
                                        block = f"\n```json\n{tc_json}\n```\n"
                                        accumulated.append(block)
                                        yield f"event: content\ndata: {json_module.dumps({'text': block, 'dha_id': next_speaker, 'meta': {}}, ensure_ascii=False)}\n\n"
                                content_str = str(aimsg.content) if isinstance(aimsg.content, str) else str(aimsg.content or "")
                                if content_str.strip() and content_str not in accumulated:
                                    accumulated.append(content_str)
                                    yield f"event: content\ndata: {json_module.dumps({'text': content_str, 'dha_id': next_speaker, 'meta': {}}, ensure_ascii=False)}\n\n"
                except Exception as stream_err:
                    logger.warning("群聊 agent astream 失败，回退到 ainvoke: %s", stream_err)
                    try:
                        final_state = await agent.ainvoke(initial_state, config=run_cfg)
                        out_msgs = final_state.get("messages", [])
                        for m in out_msgs:
                            if isinstance(m, AIMessage):
                                if hasattr(m, "tool_calls") and m.tool_calls:
                                    for tco in m.tool_calls:
                                        tool_name = tco.get("name") or tco.get("id", "")
                                        args = tco.get("args") or {}
                                        payload = {"action": "tool_call", "tool": tool_name, "arguments": args}
                                        tc_json = json_module.dumps(payload, ensure_ascii=False, indent=2)
                                        accumulated.append(f"\n```json\n{tc_json}\n```\n")
                                content_str = str(m.content) if isinstance(m.content, str) else str(m.content or "")
                                if content_str.strip():
                                    accumulated.append(content_str)
                        if not accumulated_raw_tool_results:
                            for msg in out_msgs:
                                if isinstance(msg, (HumanMessage, ToolMessage)) and msg.content:
                                    raw_str = str(msg.content) if isinstance(msg.content, str) else str(msg.content or "")
                                    if raw_str and (
                                        ("工具 " in raw_str and " 的执行结果:" in raw_str)
                                        or "执行错误" in raw_str
                                        or raw_str.strip().startswith("{")
                                        or "Title:" in raw_str
                                        or "URL:" in raw_str
                                    ):
                                        if raw_str not in accumulated_raw_tool_results:
                                            accumulated_raw_tool_results.append(raw_str)
                    except Exception as invoke_err:
                        logger.exception("群聊 agent ainvoke 也失败: %s", invoke_err)
                        accumulated.append(f"(调用异常: {invoke_err})")

                full_content = "".join(accumulated) if accumulated else "(无文本输出)"
                full_content = _append_workspace_image_preview_markdown(full_content, accumulated_raw_tool_results)
                skill_id = (dha.get("skill_ids") or ["default"])[0] if dha else "default"
                current_skill_id_for_pending = skill_id
                assistant_msg = {
                    "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                    "role": "assistant",
                    "dha_id": next_speaker,
                    "content": full_content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "skill_id": skill_id,
                }
                inferred_required_fields = _infer_required_user_fields_for_skill(skill_content, full_content)
                if inferred_required_fields:
                    assistant_msg["required_user_fields"] = inferred_required_fields
                if accumulated_raw_tool_results:
                    assistant_msg["tool_raw_results"] = accumulated_raw_tool_results
                messages.append(assistant_msg)
                _save_group_history(group_session_id, messages)
                meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                _save_group_meta(meta)
                # 专家回合自动落盘：失败不影响主对话链路
                try:
                    mem = _get_group_memory_settings(app_settings)
                    if mem["enabled"]:
                        full_message_ref = append_expert_message_file(
                            session_id=group_session_id,
                            dha_id=next_speaker,
                            timestamp=assistant_msg.get("timestamp"),
                            content=full_content,
                            skill_id=skill_id,
                        )
                        input_summary = (user_content or "")[:800]
                        response_summary = (full_content or "")[:1400]
                        tool_summary = "\n".join((accumulated_raw_tool_results or [])[:2])[:1000]
                        append_turn_log(
                            session_id=group_session_id,
                            max_logs=mem["max_logs"],
                            turn_record={
                                "dha_id": next_speaker,
                                "timestamp": assistant_msg.get("timestamp"),
                                "skill_id": skill_id,
                                "full_message_ref": full_message_ref,
                                "discussion_goal": discussion_goal,
                                "input_prompt_summary": input_summary,
                                "response_summary": response_summary,
                                "tool_result_summary": tool_summary,
                            },
                        )
                        facts_delta = _extract_facts_from_response(full_content)
                        if facts_delta:
                            upsert_facts(
                                session_id=group_session_id,
                                facts_delta=facts_delta,
                                max_facts=mem["max_facts"],
                            )
                except Exception:
                    logger.warning("group memory write failed", exc_info=True)
                yield f"event: message\ndata: {json_module.dumps(assistant_msg, ensure_ascii=False)}\n\n"
                # skill 输出命中“需要用户补充/确认”时，立即中断并保持当前专家 owner；
                # 不再回到主持人二次分发，避免出现“skill 未结束却断链”。
                if inferred_required_fields:
                    move_to_interrupt(orch_ctx, InterruptReason.NEED_USER_INPUT)
                    required_user_fields = list(inferred_required_fields)
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker="user",
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=InterruptReason.NEED_USER_INPUT,
                        resume_target_dha_id=next_speaker,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                    )
                    _persist_pending_state(end_data)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return
                hook_output = await post_turn_hooks.run(
                    {
                        "session_id": group_session_id,
                        "dha_id": next_speaker,
                        "skill_id": skill_id,
                        "full_content": full_content,
                        "tool_raw_results": accumulated_raw_tool_results,
                        "required_user_fields": assistant_msg.get("required_user_fields") or [],
                    }
                )
                if not hook_output.allow:
                    move_to_interrupt(orch_ctx, hook_output.interrupt_reason)
                    required_user_fields = list(hook_output.merged_metadata.get("required_user_fields") or required_user_fields)
                    _audit(
                        "hook_interrupt",
                        {
                            "reason": hook_output.interrupt_reason.value,
                            "message": hook_output.message,
                            "trace": [x.__dict__ for x in hook_output.trace],
                            "ctx": orch_ctx.to_dict(),
                        },
                    )
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker="user",
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=hook_output.interrupt_reason,
                        resume_target_dha_id=resume_target_dha_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=hook_output.message or latest_handoff_reason,
                    )
                    _persist_pending_state(end_data)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return
                soft_stop_reason = _evaluate_soft_stop(
                    state=soft_stop_state,
                    current_speaker=next_speaker,
                    full_content=full_content,
                    tool_raw_results=accumulated_raw_tool_results,
                )
                if soft_stop_reason:
                    logger.info(
                        "群聊软判停触发: session=%s speaker=%s turns=%s reason=%s metrics=%s",
                        group_session_id,
                        next_speaker,
                        dha_turns,
                        soft_stop_reason,
                        {
                            "low_increment_streak": soft_stop_state.get("low_increment_streak", 0),
                            "repeat_conclusion_streak": soft_stop_state.get("repeat_conclusion_streak", 0),
                            "tool_failure_streak": soft_stop_state.get("tool_failure_streak", 0),
                        },
                    )
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker="user",
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=InterruptReason.NEED_USER_INPUT,
                        resume_target_dha_id=resume_target_dha_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                        extra={"soft_stop": True, "soft_stop_reason": soft_stop_reason},
                    )
                    _persist_pending_state(end_data)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return

                last_speaker_dha_id = next_speaker
                if not host_takeover_open:
                    if speak_mode != "auto":
                        orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                        end_data = build_end_payload(
                            waiting_for_user=True,
                            suggested_next_speaker=next_speaker,
                            phase=OrchestrationPhase.AWAITING_USER,
                            interrupt_reason=InterruptReason.NONE,
                            resume_target_dha_id=resume_target_dha_id,
                            required_user_fields=required_user_fields,
                            turn_id=orch_ctx.turn_id,
                            token_version=orch_ctx.token_version,
                            handoff_reason=latest_handoff_reason,
                        )
                        _persist_pending_state(end_data)
                        yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                        return
                    # auto 且未触发主持人接管：保持当前专家连续执行。
                    continue
                # 主持人接管后：manual/auto 均允许主持人决定下一步
                if speak_mode != "auto":
                    host_takeover_open = False
                    host_msg = {}
                    decision = None
                    host_dha = dha_map.get(leader_dha_id) if leader_dha_id else None
                    if leader_dha_id and leader_dha_id in dha_ids and host_dha:
                        llm_host = _get_llm_for_dha(host_dha, app_settings)
                        decision = await _host_decide_by_dha(
                            llm_host, host_dha, dha_list, discussion_goal, _messages_to_context(messages),
                            last_speaker_dha_id, extra_system_prompt, available_to_add
                        )
                    if decision is None:
                        llm_default = _get_llm_for_dha(None, app_settings)
                        decision = await leader_decide(llm_default, dha_list, discussion_goal, _messages_to_context(messages), last_speaker_dha_id, available_to_add)
                    decision = normalize_scheduler_decision(
                        decision,
                        dha_ids=dha_ids,
                        recruitable_ids=[str(d.get("dha_id") or "") for d in available_to_add if d.get("dha_id")],
                        last_speaker_dha_id=last_speaker_dha_id,
                        current_owner_dha_id=last_speaker_dha_id,
                    )
                    _apply_decision_to_ctx(decision)
                    next_speaker_manual = decision.get("next_speaker", "user")
                    suggested_add = (decision.get("suggested_add_expert_ids") or decision.get("suggested_add_dha_ids") or [])
                    recruitable_ids = {d.get("dha_id") for d in available_to_add if d.get("dha_id")}
                    suggested_add = list(dict.fromkeys([x for x in suggested_add if x in recruitable_ids]))[:3]
                    announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                    if not suggested_add and isinstance(announcement, str):
                        suggested_add = _extract_valid_dha_ids_from_text_or_names(announcement, recruitable_ids, available_to_add, max_n=3)
                    if suggested_add:
                        next_speaker_manual = "user"
                    if next_speaker_manual in dha_ids or next_speaker_manual in ("user", "end"):
                        host_content = announcement
                        if not host_content and next_speaker_manual in dha_ids:
                            next_dha = dha_map.get(next_speaker_manual)
                            host_content = f"下面由 {next_dha.get('name') or next_speaker_manual} 发言。" if next_dha else f"下面由 {next_speaker_manual} 发言。"
                        if not host_content:
                            host_content = "请用户补充或继续提问。" if next_speaker_manual == "user" else "讨论结束。"
                        if suggested_add:
                            host_content = "当前成员无法完成该工作，建议先邀请更匹配的专家。"
                        host_msg = {
                            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                            "role": "host" if not leader_dha_id else "assistant",
                            "content": host_content,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        if leader_dha_id:
                            host_msg["dha_id"] = leader_dha_id
                        if suggested_add:
                            host_msg["suggested_add_dha_ids"] = suggested_add
                            host_msg["suggested_add_expert_ids"] = suggested_add
                        messages.append(host_msg)
                        if next_speaker_manual in dha_ids:
                            next_dha = dha_map.get(next_speaker_manual)
                            host_msg["next_dha_name"] = (next_dha.get("name") or next_speaker_manual) if next_dha else next_speaker_manual
                        _save_group_history(group_session_id, messages)
                        yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                    end_data = build_end_payload(
                        waiting_for_user=True,
                        suggested_next_speaker=next_speaker_manual,
                        phase=OrchestrationPhase.AWAITING_USER,
                        interrupt_reason=InterruptReason.NONE,
                        resume_target_dha_id=resume_target_dha_id,
                        required_user_fields=required_user_fields,
                        turn_id=orch_ctx.turn_id,
                        token_version=orch_ctx.token_version,
                        handoff_reason=latest_handoff_reason,
                    )
                    if suggested_add:
                        end_data["suggested_add_dha_ids"] = suggested_add
                        end_data["suggested_add_expert_ids"] = suggested_add
                    _persist_pending_state(end_data)
                    yield f"event: end\ndata: {json_module.dumps(end_data, ensure_ascii=False)}\n\n"
                    return
                # auto 且多 DHA：主持人决定下一发言人
                host_takeover_open = False
                decision = None
                host_dha = dha_map.get(leader_dha_id) if leader_dha_id else None
                if leader_dha_id and leader_dha_id in dha_ids and host_dha:
                    llm_host = _get_llm_for_dha(host_dha, app_settings)
                    decision = await _host_decide_by_dha(
                        llm_host, host_dha, dha_list, discussion_goal, _messages_to_context(messages),
                        last_speaker_dha_id, extra_system_prompt, available_to_add
                    )
                if decision is None:
                    llm_default = _get_llm_for_dha(None, app_settings)
                    decision = await leader_decide(llm_default, dha_list, discussion_goal, _messages_to_context(messages), last_speaker_dha_id, available_to_add)
                decision = normalize_scheduler_decision(
                    decision,
                    dha_ids=dha_ids,
                    recruitable_ids=[str(d.get("dha_id") or "") for d in available_to_add if d.get("dha_id")],
                    last_speaker_dha_id=last_speaker_dha_id,
                    current_owner_dha_id=last_speaker_dha_id,
                )
                _apply_decision_to_ctx(decision)
                next_speaker = decision.get("next_speaker", "user")
                suggested_add = (decision.get("suggested_add_expert_ids") or decision.get("suggested_add_dha_ids") or [])
                recruitable_ids = {d.get("dha_id") for d in available_to_add if d.get("dha_id")}
                suggested_add = list(dict.fromkeys([x for x in suggested_add if x in recruitable_ids]))[:3]
                announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                if not suggested_add and isinstance(announcement, str):
                    suggested_add = _extract_valid_dha_ids_from_text_or_names(announcement, recruitable_ids, available_to_add, max_n=3)
                # 主持人建议新增成员时：仅给出推荐，等待用户确认邀请
                if suggested_add:
                    next_speaker = "user"
                    host_content = "当前成员无法完成该工作，建议先邀请更匹配的专家。"
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host" if not leader_dha_id else "assistant",
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "suggested_add_dha_ids": suggested_add,
                        "suggested_add_expert_ids": suggested_add,
                    }
                    if leader_dha_id:
                        host_msg["dha_id"] = leader_dha_id
                    messages.append(host_msg)
                    _save_group_history(group_session_id, messages)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                # 主持人发言：leader_dha_id 为空时用 role=host（固定逻辑）
                if next_speaker in dha_ids or (next_speaker in ("user", "end") and not suggested_add):
                    host_content = announcement
                    if not host_content and next_speaker in dha_ids:
                        next_dha = dha_map.get(next_speaker)
                        next_name = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                        host_content = f"下面由 {next_name} 发言。"
                    if not host_content:
                        host_content = "请用户补充或继续提问。" if next_speaker == "user" else "讨论结束。"
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host" if not leader_dha_id else "assistant",
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    if leader_dha_id:
                        host_msg["dha_id"] = leader_dha_id
                    messages.append(host_msg)
                    if next_speaker in dha_ids:
                        next_dha = dha_map.get(next_speaker)
                        host_msg["next_dha_name"] = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                    if decision.get("suggested_order"):
                        host_msg["suggested_order"] = decision["suggested_order"]
                    _save_group_history(group_session_id, messages)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                # auto 模式下：不再每轮暂停，直接继续 while 循环让下一 DHA 发言，直到任务完成（next_speaker 为 user/end）再结束

            if next_speaker == "end":
                orch_ctx.phase = OrchestrationPhase.COMPLETED
                payload = build_end_payload(
                    waiting_for_user=False,
                    discussion_ended=True,
                    phase=orch_ctx.phase,
                    interrupt_reason=InterruptReason.NONE,
                    resume_target_dha_id=resume_target_dha_id,
                    required_user_fields=required_user_fields,
                    turn_id=orch_ctx.turn_id,
                    token_version=orch_ctx.token_version,
                    handoff_reason=latest_handoff_reason,
                )
                _persist_pending_state(payload)
                yield f"event: end\ndata: {json_module.dumps(payload)}\n\n"
            else:
                if orch_ctx.phase == OrchestrationPhase.EXECUTING:
                    orch_ctx.phase = OrchestrationPhase.AWAITING_USER
                end_data = build_end_payload(
                    waiting_for_user=True,
                    suggested_next_speaker=next_speaker,
                    phase=orch_ctx.phase,
                    interrupt_reason=orch_ctx.interrupt_reason if orch_ctx.interrupt_reason != InterruptReason.NONE else InterruptReason.NONE,
                    resume_target_dha_id=resume_target_dha_id,
                    required_user_fields=required_user_fields,
                    turn_id=orch_ctx.turn_id,
                    token_version=orch_ctx.token_version,
                    handoff_reason=latest_handoff_reason,
                )
                _persist_pending_state(end_data)
                yield f"event: end\ndata: {json_module.dumps(end_data)}\n\n"

        except Exception as e:
            logger.exception("群聊流式输出异常")
            yield f"event: error\ndata: {json_module.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
