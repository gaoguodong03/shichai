"""Sandbox adapter abstraction with local runtime fallback."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
logger = logging.getLogger(__name__)

from pathlib import Path
from typing import Any, Dict, List, Protocol


@dataclass
class SandboxPolicy:
    fs_root: str
    allow_network: bool = False
    allowed_hosts: List[str] = field(default_factory=list)
    cpu_limit: float = 1.0
    memory_limit_mb: int = 512
    timeout_ms: int = 30000
    tool_allowlist: List[str] = field(default_factory=list)
    max_artifact_size_mb: int = 50


@dataclass
class SandboxHandle:
    runtime: str
    session_id: str
    root: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class SandboxAdapter(Protocol):
    async def create_session_sandbox(self, session_id: str, policy: SandboxPolicy) -> SandboxHandle:
        ...

    async def run_tool_in_sandbox(self, handle: SandboxHandle, tool_request: Dict[str, Any]) -> Dict[str, Any]:
        ...

    async def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        ...

    async def write_file(self, handle: SandboxHandle, path: str, data: bytes, token_version: int = 0) -> Dict[str, Any]:
        ...

    async def list_artifacts(self, handle: SandboxHandle, task_id: str = "") -> List[Dict[str, Any]]:
        ...

    async def dispose_sandbox(self, handle: SandboxHandle) -> None:
        ...


class LocalRuntimeSandboxAdapter:
    """Initial adapter: use local file system under session root."""

    async def create_session_sandbox(self, session_id: str, policy: SandboxPolicy) -> SandboxHandle:
        root = Path(policy.fs_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return SandboxHandle(
            runtime="local_runtime",
            session_id=session_id,
            root=str(root),
            metadata={"policy": {"tool_allowlist": list(policy.tool_allowlist), "timeout_ms": int(policy.timeout_ms)}},
        )

    async def run_tool_in_sandbox(self, handle: SandboxHandle, tool_request: Dict[str, Any]) -> Dict[str, Any]:
        policy = handle.metadata.get("policy") if isinstance(handle.metadata, dict) else None
        req_name = str(tool_request.get("tool_name") or "").strip()
        allowlist = list((policy or {}).get("tool_allowlist") or [])
        allowlist_hit = bool(req_name and (not allowlist or req_name in allowlist))
        if allowlist and req_name and req_name not in allowlist:
            logger.warning(
                "sandbox_tool_blocked runtime=%s session=%s tool=%s timeout_ms=%s allowlist_hit=%s",
                handle.runtime,
                handle.session_id,
                req_name,
                int(tool_request.get("timeout_ms") or (policy or {}).get("timeout_ms") or 30000),
                allowlist_hit,
            )
            raise PermissionError(f"tool not allowed by sandbox policy: {req_name}")

        timeout_ms = int(tool_request.get("timeout_ms") or (policy or {}).get("timeout_ms") or 30000)
        logger.info(
            "sandbox_tool_enter runtime=%s session=%s tool=%s timeout_ms=%s allowlist_hit=%s",
            handle.runtime,
            handle.session_id,
            req_name or "unknown_tool",
            timeout_ms,
            allowlist_hit,
        )
        runner = tool_request.get("runner")
        if not callable(runner):
            raise ValueError("tool_request.runner callable is required")

        result_or_coro = runner()
        if asyncio.iscoroutine(result_or_coro):
            result = await asyncio.wait_for(result_or_coro, timeout=max(0.1, timeout_ms / 1000.0))
        else:
            result = result_or_coro
        sandbox_trace = {
            "runtime": handle.runtime,
            "session_id": handle.session_id,
            "tool_name": req_name or "unknown_tool",
            "timeout_ms": timeout_ms,
            "allowlist_hit": allowlist_hit,
        }
        if isinstance(result, dict):
            if "_sandbox_trace" not in result:
                result["_sandbox_trace"] = sandbox_trace
            return result
        return {"result": result, "_sandbox_trace": sandbox_trace}

    async def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        p = (Path(handle.root) / path).resolve()
        if not str(p).startswith(str(Path(handle.root).resolve())):
            raise ValueError("path out of sandbox root")
        return p.read_bytes()

    async def write_file(self, handle: SandboxHandle, path: str, data: bytes, token_version: int = 0) -> Dict[str, Any]:
        p = (Path(handle.root) / path).resolve()
        if not str(p).startswith(str(Path(handle.root).resolve())):
            raise ValueError("path out of sandbox root")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return {"status": "ok", "path": str(p), "bytes": len(data), "token_version": int(token_version)}

    async def list_artifacts(self, handle: SandboxHandle, task_id: str = "") -> List[Dict[str, Any]]:
        root = Path(handle.root).resolve()
        out: List[Dict[str, Any]] = []
        for p in root.rglob("*"):
            if p.is_file():
                out.append({"path": str(p.relative_to(root)).replace("\\", "/"), "size": p.stat().st_size, "task_id": task_id})
        return out

    async def dispose_sandbox(self, handle: SandboxHandle) -> None:
        # local runtime does not auto-delete artifacts.
        return None
