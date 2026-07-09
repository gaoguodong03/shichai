"""Hook pipeline for orchestrator/tool execution lifecycle."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Protocol

from app.agent.runtime_status import InterruptReason


class HookPriority(IntEnum):
    QUALITY_GUARD = 10
    ORCHESTRATOR_GUARD = 20
    POLICY_GUARD = 30
    SECURITY_GUARD = 40


@dataclass
class HookResult:
    allow: bool = True
    interrupt_reason: InterruptReason = InterruptReason.NONE
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class Hook(Protocol):
    name: str
    priority: HookPriority

    async def run(self, payload: Dict[str, Any]) -> HookResult:
        ...


@dataclass
class HookExecution:
    hook_name: str
    priority: int
    allow: bool
    interrupt_reason: str
    message: str


@dataclass
class HookPipelineOutput:
    allow: bool
    interrupt_reason: InterruptReason
    message: str
    trace: List[HookExecution]
    merged_metadata: Dict[str, Any]


class HookPipeline:
    """Execute hooks by priority and short-circuit on deny."""

    def __init__(self, hooks: List[Hook] | None = None):
        self._hooks = sorted(list(hooks or []), key=lambda h: int(h.priority), reverse=True)

    def register(self, hook: Hook) -> None:
        self._hooks.append(hook)
        self._hooks.sort(key=lambda h: int(h.priority), reverse=True)

    async def run(self, payload: Dict[str, Any]) -> HookPipelineOutput:
        trace: List[HookExecution] = []
        merged: Dict[str, Any] = {}
        for hook in self._hooks:
            result = await hook.run(payload)
            if result.metadata:
                merged.update(result.metadata)
            trace.append(
                HookExecution(
                    hook_name=hook.name,
                    priority=int(hook.priority),
                    allow=bool(result.allow),
                    interrupt_reason=result.interrupt_reason.value,
                    message=result.message or "",
                )
            )
            if not result.allow:
                return HookPipelineOutput(
                    allow=False,
                    interrupt_reason=result.interrupt_reason,
                    message=result.message or f"Hook denied: {hook.name}",
                    trace=trace,
                    merged_metadata=merged,
                )
        return HookPipelineOutput(
            allow=True,
            interrupt_reason=InterruptReason.NONE,
            message="",
            trace=trace,
            merged_metadata=merged,
        )
