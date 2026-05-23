"""Unified gateway for tool/MCP calls with guards and idempotency."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from app.agent.orchestrator_state import InterruptReason
from app.agent.sandbox_adapter import (
    SandboxAdapter,
    SandboxPolicy,
)
from app.agent.sandbox_service import SandboxEnvironmentError, SandboxExecutionRequest, SandboxService
from app.agent.sandbox_workspace_access import get_shared_sandbox_service


ToolExecutor = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


def _sandbox_base_timeout_ms(context: "ToolExecutionContext", policy: Optional[SandboxPolicy]) -> int:
    """单次沙箱命令（脚本本体 / OpenSandbox execute）应遵守的上限：取 context 与 policy 较大值。"""
    ct = int(context.timeout_ms or 0)
    pt = int(policy.timeout_ms or 0) if policy is not None else 0
    return max(ct, pt, 60_000)


def _sandbox_outer_wait_timeout_ms(
    context: "ToolExecutionContext", policy: Optional[SandboxPolicy], tool_kind: str
) -> int:
    """asyncio.wait_for 包住整段 sandbox_service.execute：含建沙箱、首次 pip、再执行命令；需比单次脚本更长。"""
    base = _sandbox_base_timeout_ms(context, policy)
    if (tool_kind or "").strip() != "script":
        return base
    raw = (os.getenv("SANDBOX_SCRIPT_GATEWAY_SLACK_MS") or "600000").strip()
    try:
        slack = int(raw)
    except ValueError:
        slack = 600_000
    return base + max(0, slack)


@dataclass
class ToolExecutionContext:
    session_id: str
    workspace_id: str
    agent_id: str
    user_id: str = ""
    skill_id: str = ""
    task_id: str = ""
    turn_id: str = ""
    tool_call_id: str = ""
    timeout_ms: int = 60_000
    retry_count: int = 1
    policy: Optional[SandboxPolicy] = None
    sandbox_cwd: str = ""


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
    timeout_ms: int = 60_000
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
                last_err = (
                    "gateway timeout: "
                    f"tool={req.tool_name} timeout_ms={int(req.timeout_ms)} "
                    f"attempt={i + 1}/{retries + 1}"
                )
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
            except asyncio.CancelledError as e:
                # 远端 MCP/streamable-http SDK 可能把上游流中断表现为 CancelledError。
                # 若当前请求本身没有被 ASGI/客户端取消，则降级为工具不可用，避免整条 SSE 响应未完成。
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    raise
                last_err = (
                    "gateway executor cancelled: "
                    f"tool={req.tool_name} type={e.__class__.__name__} message={str(e)}"
                )
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
            except Exception as e:  # noqa: BLE001
                if isinstance(e, SandboxEnvironmentError):
                    result = ToolResult(
                        ok=False,
                        error=str(e),
                        interrupt_reason=InterruptReason.TOOL_UNAVAILABLE,
                        elapsed_ms=int((time.time() - started) * 1000),
                        retries_used=i,
                    )
                    self._idem.set(key, result)
                    return result
                last_err = (
                    "gateway executor error: "
                    f"tool={req.tool_name} type={e.__class__.__name__} message={str(e)}"
                )
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
        self._user_semaphore_lock = asyncio.Lock()
        self._user_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._max_concurrent_tasks_per_user = max(
            1, int(os.getenv("SANDBOX_MAX_CONCURRENT_TASKS_PER_USER", "4"))
        )

    async def _get_user_semaphore(self, user_id: str) -> asyncio.Semaphore:
        key = (user_id or "").strip() or "anonymous"
        async with self._user_semaphore_lock:
            sem = self._user_semaphores.get(key)
            if sem is None:
                sem = asyncio.Semaphore(self._max_concurrent_tasks_per_user)
                self._user_semaphores[key] = sem
            return sem

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
            timeout_ms=max(100, int(context.timeout_ms or 60_000)),
            tool_allowlist=[tool_name],
        )
        inner_timeout_ms = _sandbox_base_timeout_ms(context, policy)
        outer_timeout_ms = _sandbox_outer_wait_timeout_ms(context, policy, tool_kind)

        async def _sandboxed_executor(inner_payload: Dict[str, Any]) -> Dict[str, Any]:
            resolved_user_id = (context.user_id or "").strip() or f"session:{context.session_id or 'session'}"
            return await self._sandbox_service.execute(
                SandboxExecutionRequest(
                    user_id=resolved_user_id,
                    session_id=context.session_id or "session",
                    turn_id=context.turn_id or "turn",
                    tool_call_id=context.tool_call_id or f"{tool_kind}:{tool_name}",
                    tool_name=tool_name,
                    tool_kind=tool_kind,
                    payload=inner_payload,
                    timeout_ms=inner_timeout_ms,
                    runner=runner,
                    workspace_path=Path(context.workspace_id or context.session_id or "."),
                    runtime_backend=policy.runtime_backend,
                    runtime_profile=policy.runtime_profile,
                    policy=policy,
                    cwd=context.sandbox_cwd or "",
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
            timeout_ms=outer_timeout_ms,
            retry_count=int(context.retry_count if context.retry_count is not None else 1),
        )
        user_sem = await self._get_user_semaphore(context.user_id or context.session_id)
        async with user_sem:
            return await gateway.execute(req)
