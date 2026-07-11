"""Soft-stop heuristics for group-chat auto runs."""
from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

from app.agent.group_context import (
    has_tool_failure as _has_tool_failure,
    looks_like_conclusion_text as _looks_like_conclusion_text,
    normalize_compare_text as _normalize_compare_text,
)


MAX_EXPERT_TURNS_PER_STREAM = 32


def expert_turn_budget_exceeded(turns: int, max_turns: int = MAX_EXPERT_TURNS_PER_STREAM) -> bool:
    """Return whether an expert auto-run turn count exceeds the contract budget."""
    return int(turns or 0) > int(max_turns)


def _evaluate_soft_stop(
    state: Dict[str, Any],
    current_speaker: str,
    full_content: str,
    tool_results: List[Dict[str, Any]],
) -> Optional[str]:
    """Pause auto-run when repeated failures or low-increment content make continuation wasteful."""
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

    has_fail = _has_unresolved_tool_failure(tool_results, full_content)
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


def _looks_like_terminal_tool_failure(content: str) -> bool:
    text = str(content or "").strip().lower()
    if not text:
        return True
    first = text[:500]
    terminal_markers = (
        "当前步骤失败",
        "工具执行失败",
        "执行错误",
        "工具已执行完成，但模型没有返回可展示的文字总结",
        "模型没有返回可展示的文字内容",
        "无法继续",
        "请用户确认或调整任务",
    )
    return any(marker.lower() in first for marker in terminal_markers)


def _has_substantive_recovered_content(content: str) -> bool:
    if _looks_like_terminal_tool_failure(content):
        return False
    return len(_normalize_compare_text(content)) >= 80


def _has_unresolved_tool_failure(tool_results: List[Dict[str, Any]], full_content: str) -> bool:
    if not _has_tool_failure(tool_results, full_content):
        return False
    # Some tools may fail while the expert still completes the turn from available
    # context, for example a material packet assembled after web requests returned
    # 404/DNS errors. Do not pause the scene if the visible expert answer recovered.
    if _has_substantive_recovered_content(full_content):
        return False
    return True
