"""Sandbox adapter abstraction with local runtime fallback."""
from __future__ import annotations

from dataclasses import dataclass, field
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
        return SandboxHandle(runtime="local_runtime", session_id=session_id, root=str(root))

    async def run_tool_in_sandbox(self, handle: SandboxHandle, tool_request: Dict[str, Any]) -> Dict[str, Any]:
        # Local runtime only returns passthrough metadata by design.
        return {"status": "ok", "runtime": handle.runtime, "tool_request": tool_request}

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
