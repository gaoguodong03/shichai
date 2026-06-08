"""Soft-stop heuristics for group-chat auto runs."""
from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

from app.agent.group_context import (
    has_tool_failure as _has_tool_failure,
    looks_like_conclusion_text as _looks_like_conclusion_text,
    normalize_compare_text as _normalize_compare_text,
)


def _evaluate_soft_stop(
    state: Dict[str, Any],
    current_speaker: str,
    full_content: str,
    tool_raw_results: List[str],
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
