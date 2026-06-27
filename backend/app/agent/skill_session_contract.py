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
场景协作中，普通专家本轮发言完成后默认交回主持人调度。

脚本型 Skill 必须在 stdout JSON 中输出固定字段：
`execution_status`、`result_code`、`message`、`artifacts`、`next_action`。
`next_action.skill_session` 只允许 `keep` 或 `release`：
`keep` 表示保留 Skill 会话锁，`release` 表示释放。
"""

SCRIPT_SKILL_SESSION_OVER_KEYS = ("skill_session_over", "over")
SCRIPT_NEXT_ACTION_SESSION_VALUES = {
    "keep": False,
    "release": True,
}


@dataclass(frozen=True)
class SkillSessionStateResolution:
    """Normalized result of resolving a Skill session finish state."""

    over: Optional[bool]
    display_content: str
    source: str
    signals: Optional["SkillSessionSignals"] = None


@dataclass(frozen=True)
class SkillSessionSignals:
    """Explicit finish-state signals collected from one expert turn."""

    assistant_state_block: Optional[bool]
    script_stdout: Optional[bool]
    legacy_end_marker: bool


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
    """Remove state blocks and return the last explicit Skill-session value."""
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
            next_action = obj.get("next_action")
            if isinstance(next_action, dict):
                parsed_action = SCRIPT_NEXT_ACTION_SESSION_VALUES.get(
                    str(next_action.get("skill_session") or "").strip().lower()
                )
                if parsed_action is not None:
                    last_over = parsed_action
                    continue
            for key in SCRIPT_SKILL_SESSION_OVER_KEYS:
                if key not in obj:
                    continue
                parsed = _boolish(obj.get(key))
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
    last_next_action: Optional[bool] = None
    last_legacy_over: Optional[bool] = None
    for payload in _iter_tool_payloads(raw_outputs, tool_names):
        next_action = payload.get("next_action")
        if isinstance(next_action, dict):
            parsed_action = SCRIPT_NEXT_ACTION_SESSION_VALUES.get(
                str(next_action.get("skill_session") or "").strip().lower()
            )
            if parsed_action is not None:
                last_next_action = parsed_action
        for key in SCRIPT_SKILL_SESSION_OVER_KEYS:
            if key not in payload:
                continue
            parsed = _boolish(payload.get(key))
            if parsed is not None:
                last_legacy_over = parsed
    return last_next_action if last_next_action is not None else last_legacy_over


def _choose_skill_session_state(signals: SkillSessionSignals) -> tuple[Optional[bool], str]:
    """Apply the product rule: continuing the Skill session beats ending it."""
    if signals.assistant_state_block is False:
        return False, "assistant_state_block"
    if signals.script_stdout is False:
        return False, "script_stdout"
    if signals.assistant_state_block is True:
        return True, "assistant_state_block"
    if signals.script_stdout is True:
        return True, "script_stdout"
    if signals.legacy_end_marker:
        return True, "legacy_end_marker"
    return None, "none"


def resolve_skill_session_state(
    raw_content: str,
    tool_raw_outputs: Iterable[str] | None = None,
    tool_names: Iterable[str] | None = None,
) -> SkillSessionStateResolution:
    """Resolve the Skill-session finish state conservatively.

    Precedence:
    1. Any explicit keep from expert state block or script stdout keeps the lock.
    2. Any explicit release from expert state block or script stdout releases it.
    3. Legacy expert final-answer end markers release it.
    4. No explicit state: ordinary one-turn expert speech; do not create a
       cross-request lock.
    """
    over_from_content, content_without_state = strip_skill_session_state_blocks_and_get_over(raw_content)
    display_content = strip_skill_session_end_markers_for_display(content_without_state)
    over_from_script = skill_session_over_from_tool_outputs(tool_raw_outputs, tool_names)
    signals = SkillSessionSignals(
        assistant_state_block=over_from_content,
        script_stdout=over_from_script,
        legacy_end_marker=skill_session_ended_by_expert_output(content_without_state),
    )
    over, source = _choose_skill_session_state(signals)
    return SkillSessionStateResolution(over, display_content, source, signals)
