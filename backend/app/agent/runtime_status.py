"""Small runtime status enums shared by tools, hooks, and scheduler guards."""
from __future__ import annotations

from enum import Enum


class RuntimePhase(str, Enum):
    """Public runtime phases allowed by the current SSE/session contract."""

    ROUTING = "routing"
    PLANNING = "planning"
    EXECUTING = "executing"
    FILE_RESOLVING = "file_resolving"
    FILE_RESOLVED = "file_resolved"
    SKILL_SELECTING = "skill_selecting"
    AGENT_ROUTED = "agent_routed"
    TOOL_RUNNING = "tool_running"
    ASSISTANT_GENERATING = "assistant_generating"
    FINALIZING = "finalizing"
    AWAITING_USER = "awaiting_user"
    RECRUITING = "recruiting"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class InterruptReason(str, Enum):
    """Internal interruption reasons that can be logged or mapped to end/error events."""

    NONE = "none"
    NEED_USER_INPUT = "need_user_input"
    NEED_MORE_CONTEXT = "need_more_context"
    NEED_RECRUIT_EXPERT = "need_recruit_expert"
    POLICY_OR_SECURITY = "policy_or_security"
    TOOL_UNAVAILABLE = "tool_unavailable"
    TIMEOUT_OR_BUDGET_EXCEEDED = "timeout_or_budget_exceeded"
    CONFLICT_DETECTED = "conflict_detected"
    PROTOCOL_ERROR = "protocol_error"
