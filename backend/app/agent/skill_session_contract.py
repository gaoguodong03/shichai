"""Skill session finish-state contract shared by group orchestration."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Tuple


SKILL_SESSION_END_MARKERS = ("[[SKILL_SESSION_END]]", "【技能会话结束】")
SKILL_SESSION_STATE_START = "[[SKILL_SESSION_STATE]]"
SKILL_SESSION_STATE_END = "[[/SKILL_SESSION_STATE]]"

GROUP_EXPERT_SKILL_SESSION_STATE_INSTRUCTION = """

## Skill 会话状态
本轮回复末尾追加：
[[SKILL_SESSION_STATE]]
{"over": true}
[[/SKILL_SESSION_STATE]]
`over=true` 表示任务已完成并交回主持人；仍需用户补充或继续处理时用 `false`。

脚本型 Skill 若能确定当前 Skill 会话是否结束，可在 stdout JSON 中输出
`skill_session_over: true|false`；专家最终回复中的状态块优先级更高。
"""

SCRIPT_SKILL_SESSION_OVER_KEYS = ("skill_session_over", "over")


@dataclass(frozen=True)
class SkillSessionStateResolution:
    """Normalized result of resolving a Skill session finish state."""

    over: Optional[bool]
    display_content: str
    source: str


def _json_loads_maybe(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _boolish(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(int(value))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes", "on"):
            return True
        if normalized in ("false", "0", "no", "off"):
            return False
    return None


def skill_session_ended_by_expert_output(content: str) -> bool:
    """Return true when legacy expert-output markers end the current Skill session."""
    t = str(content or "")
    return any(m in t for m in SKILL_SESSION_END_MARKERS)


def strip_skill_session_state_blocks_and_get_over(raw: str) -> Tuple[Optional[bool], str]:
    """Remove state blocks and return the last explicit over / skill_session_over value."""
    s = str(raw or "")
    last_over: Optional[bool] = None
    start, end = SKILL_SESSION_STATE_START, SKILL_SESSION_STATE_END
    while True:
        lo = s.find(start)
        if lo < 0:
            break
        hi = s.find(end, lo)
        if hi < 0:
            break
        inner = s[lo + len(start) : hi].strip()
        s = (s[:lo] + s[hi + len(end) :]).rstrip()
        obj = _json_loads_maybe(inner)
        if isinstance(obj, dict):
            value = obj.get("over")
            if value is None:
                value = obj.get("skill_session_over")
            parsed = _boolish(value)
            if parsed is not None:
                last_over = parsed
    return last_over, s


def strip_skill_session_end_markers_for_display(text: str) -> str:
    """Remove legacy end markers from user-visible expert content."""
    t = str(text or "")
    for marker in SKILL_SESSION_END_MARKERS:
        t = t.replace(marker, "")
    return t.strip()


def _iter_tool_payloads(
    raw_outputs: Iterable[str] | None,
    tool_names: Iterable[str] | None = None,
) -> Iterable[dict[str, Any]]:
    names = [str(name or "") for name in tool_names] if tool_names is not None else None
    for idx, raw in enumerate(raw_outputs or []):
        if names is not None:
            tool_name = names[idx] if idx < len(names) else ""
            if not tool_name.startswith("run_skill_script_"):
                continue
        outer = _json_loads_maybe(raw)
        if isinstance(outer, dict):
            yield outer
            stdout_payload = _json_loads_maybe(outer.get("stdout"))
            if isinstance(stdout_payload, dict):
                yield stdout_payload


def skill_session_over_from_tool_outputs(
    raw_outputs: Iterable[str] | None,
    tool_names: Iterable[str] | None = None,
) -> Optional[bool]:
    """Read the explicit script-controlled Skill-session state from tool outputs.

    Only dedicated session fields are accepted here. When tool names are
    supplied, only `run_skill_script_*` outputs are considered. Generic
    `done` / `final` markers are intentionally ignored because they mean
    "stop this tool loop", not "release the group Skill session lock".
    """
    last_over: Optional[bool] = None
    for payload in _iter_tool_payloads(raw_outputs, tool_names):
        for key in SCRIPT_SKILL_SESSION_OVER_KEYS:
            if key not in payload:
                continue
            parsed = _boolish(payload.get(key))
            if parsed is not None:
                last_over = parsed
    return last_over


def audio_transcription_success_from_tool_outputs(
    raw_outputs: Iterable[str] | None,
    tool_names: Iterable[str] | None = None,
) -> bool:
    names = [str(name or "") for name in tool_names] if tool_names is not None else None
    if names is None or not any(name.startswith("run_skill_script_audio-transcription") for name in names):
        return False
    for payload in _iter_tool_payloads(raw_outputs, tool_names):
        if payload.get("ok") is not True:
            continue
        code = str(payload.get("code") or "").strip()
        text = str(payload.get("text") or "").strip()
        if code == "transcribed" and text:
            return True
    return False


def resolve_skill_session_state(
    raw_content: str,
    tool_raw_outputs: Iterable[str] | None = None,
    tool_names: Iterable[str] | None = None,
) -> SkillSessionStateResolution:
    """Resolve the Skill-session finish state with one explicit precedence order.

    Precedence:
    1. Expert final-answer state block.
    2. Legacy expert final-answer end markers.
    3. Script stdout JSON field `skill_session_over` / `over`.
    4. No explicit state.
    """
    over_from_content, content_without_state = strip_skill_session_state_blocks_and_get_over(raw_content)
    display_content = strip_skill_session_end_markers_for_display(content_without_state)
    if over_from_content is not None:
        return SkillSessionStateResolution(over_from_content, display_content, "assistant_state_block")
    if skill_session_ended_by_expert_output(content_without_state):
        return SkillSessionStateResolution(True, display_content, "legacy_end_marker")
    over_from_script = skill_session_over_from_tool_outputs(tool_raw_outputs, tool_names)
    if over_from_script is not None:
        return SkillSessionStateResolution(over_from_script, display_content, "script_stdout")
    if audio_transcription_success_from_tool_outputs(tool_raw_outputs, tool_names):
        return SkillSessionStateResolution(True, display_content, "audio_transcription_success")
    return SkillSessionStateResolution(None, display_content, "none")
