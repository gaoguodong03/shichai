"""Unified gateway for tool/MCP calls with guards and idempotency."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from app.agent.orchestrator_state import InterruptReason
from app.agent.sandbox_adapter import (
    SandboxAdapter,
    SandboxPolicy,
)
from app.agent.sandbox_service import SandboxExecutionRequest, SandboxService
from app.agent.sandbox_workspace_access import get_shared_sandbox_service


ToolExecutor = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass
class ToolExecutionContext:
    session_id: str
    workspace_id: str
    agent_id: str
    skill_id: str = ""
    task_id: str = ""
    turn_id: str = ""
    tool_call_id: str = ""
    timeout_ms: int = 30_000
    retry_count: int = 1
    policy: Optional[SandboxPolicy] = None


@dataclass
class ToolRequest:
    tool_name: str
    payload: Dict[str, Any]
    session_id: str
    task_id: str
    turn_id: str
    tool_call_id: str
    agent_id: str
    skill_id: str
    idempotency_key: Optional[str] = None
    timeout_ms: int = 30_000
    retry_count: int = 2
    risk_level: str = "normal"

    def resolved_idempotency_key(self) -> str:
        if self.idempotency_key:
            return self.idempotency_key
        return f"{self.session_id}:{self.turn_id}:{self.tool_call_id}"


@dataclass
class ToolResult:
    ok: bool
    output: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    interrupt_reason: InterruptReason = InterruptReason.NONE
    elapsed_ms: int = 0
    retries_used: int = 0


class InMemoryIdempotencyStore:
    """Simple in-process idempotency cache for initial rollout."""

    def __init__(self):
        self._store: Dict[str, ToolResult] = {}

    def get(self, key: str) -> Optional[ToolResult]:
        return self._store.get(key)

    def set(self, key: str, value: ToolResult) -> None:
        self._store[key] = value


class ToolGateway:
    def __init__(self, executor: ToolExecutor, idempotency_store: Optional[InMemoryIdempotencyStore] = None):
        self._executor = executor
        self._idem = idempotency_store or InMemoryIdempotencyStore()

    async def execute(self, req: ToolRequest) -> ToolResult:
        key = req.resolved_idempotency_key()
        cached = self._idem.get(key)
        if cached is not None:
            return cached

        retries = max(0, int(req.retry_count))
        timeout_s = max(0.1, req.timeout_ms / 1000.0)
        last_err = ""
        started = time.time()
        for i in range(retries + 1):
            try:
                out = await asyncio.wait_for(self._executor(req.payload), timeout=timeout_s)
                result = ToolResult(ok=True, output=out or {}, elapsed_ms=int((time.time() - started) * 1000), retries_used=i)
                self._idem.set(key, result)
                return result
            except asyncio.TimeoutError:
                last_err = "tool timeout"
                if i >= retries:
                    result = ToolResult(
                        ok=False,
                        error=last_err,
                        interrupt_reason=InterruptReason.TIMEOUT_OR_BUDGET_EXCEEDED,
                        elapsed_ms=int((time.time() - started) * 1000),
                        retries_used=i,
                    )
                    self._idem.set(key, result)
                    return result
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                if i >= retries:
                    result = ToolResult(
                        ok=False,
                        error=last_err,
                        interrupt_reason=InterruptReason.TOOL_UNAVAILABLE,
                        elapsed_ms=int((time.time() - started) * 1000),
                        retries_used=i,
                    )
                    self._idem.set(key, result)
                    return result
                await asyncio.sleep(0.3 * (2**i))

        # logically unreachable
        return ToolResult(ok=False, error=last_err or "unknown error")


class UnifiedToolGateway:
    """Route side-effect calls into sandbox runtime then ToolGateway."""

    def __init__(
        self,
        sandbox_adapter: Optional[SandboxAdapter] = None,
        idempotency_store: Optional[InMemoryIdempotencyStore] = None,
        sandbox_service: Optional[SandboxService] = None,
    ):
        if sandbox_service is not None:
            self._sandbox_service = sandbox_service
        elif sandbox_adapter is not None:
            self._sandbox_service = SandboxService(sandbox_adapter=sandbox_adapter)
        else:
            self._sandbox_service = get_shared_sandbox_service()
        self._idem = idempotency_store or InMemoryIdempotencyStore()

    async def execute(
        self,
        *,
        tool_name: str,
        tool_kind: str,
        payload: Dict[str, Any],
        context: ToolExecutionContext,
        runner: Callable[[], Awaitable[Dict[str, Any]]],
    ) -> ToolResult:
        policy = context.policy or SandboxPolicy(
            fs_root=context.workspace_id or context.session_id or ".",
            timeout_ms=max(100, int(context.timeout_ms or 30_000)),
            tool_allowlist=[tool_name],
        )

        async def _sandboxed_executor(inner_payload: Dict[str, Any]) -> Dict[str, Any]:
            return await self._sandbox_service.execute(
                SandboxExecutionRequest(
                    session_id=context.session_id or "session",
                    turn_id=context.turn_id or "turn",
                    tool_call_id=context.tool_call_id or f"{tool_kind}:{tool_name}",
                    tool_name=tool_name,
                    tool_kind=tool_kind,
                    payload=inner_payload,
                    timeout_ms=int(context.timeout_ms or policy.timeout_ms or 30_000),
                    runner=runner,
                    workspace_path=Path(context.workspace_id or context.session_id or "."),
                    runtime_backend=policy.runtime_backend,
                    runtime_profile=policy.runtime_profile,
                    policy=policy,
                )
            )

        gateway = ToolGateway(executor=_sandboxed_executor, idempotency_store=self._idem)
        req = ToolRequest(
            tool_name=tool_name,
            payload=payload,
            session_id=context.session_id or "session",
            task_id=context.task_id or "task",
            turn_id=context.turn_id or "turn",
            tool_call_id=context.tool_call_id or f"{tool_kind}:{tool_name}",
            agent_id=context.agent_id or "agent",
            skill_id=context.skill_id or "",
            timeout_ms=int(context.timeout_ms or 30_000),
            retry_count=int(context.retry_count if context.retry_count is not None else 1),
        )
        return await gateway.execute(req)
