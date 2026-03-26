"""Unified gateway for tool/MCP calls with guards and idempotency."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from app.agent.orchestrator_state import InterruptReason


ToolExecutor = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass
class ToolRequest:
    tool_name: str
    payload: Dict[str, Any]
    session_id: str
    task_id: str
    turn_id: str
    tool_call_id: str
    dha_id: str
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
