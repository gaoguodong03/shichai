"""Platform-side sandbox service over OpenSandbox adapter."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.agent.dep_image_registry import DepImageRegistry
from app.agent.dependency_resolver import DependencyResolver
from app.agent.sandbox_adapter import OpenSandboxAdapter, SandboxAdapter, SandboxHandle, SandboxPolicy
from app.agent.sandbox_audit import append_sandbox_event
from app.agent.sandbox_mount_policy import SandboxMountPolicy

logger = logging.getLogger(__name__)


@dataclass
class SandboxExecutionRequest:
    session_id: str
    turn_id: str
    tool_call_id: str
    tool_name: str
    tool_kind: str
    payload: Dict[str, Any]
    timeout_ms: int
    runner: Any
    workspace_path: Path
    skill_home: Optional[Path] = None
    skill_scripts_path: Optional[Path] = None
    skill_config_path: Optional[Path] = None
    runtime_backend: str = "docker"
    runtime_profile: str = "standard"
    policy: Optional[SandboxPolicy] = None
    user_id: str = ""


def policy_mount_fingerprint(policy: SandboxPolicy) -> str:
    parts = [policy.dep_hash or "", policy.base_image_ref or "", policy.fs_root or ""]
    for m in sorted(policy.volume_mounts or [], key=lambda x: (x.target, x.source)):
        parts.append(f"{m.source}|{m.target}|{int(m.read_only)}|{m.mount_type}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def handle_cache_key(session_id: str, policy: SandboxPolicy) -> str:
    return f"{session_id}:{policy_mount_fingerprint(policy)}"


def to_workspace_inner_path(rel: str) -> str:
    r = (rel or "").strip().lstrip("/").replace("..", "")
    return f"/workspace/{r}" if r else "/workspace"


class SandboxService:
    """Manage session sandbox lifecycle and OpenSandbox request mapping."""

    def __init__(
        self,
        sandbox_adapter: Optional[SandboxAdapter] = None,
        dependency_resolver: Optional[DependencyResolver] = None,
        dep_registry: Optional[DepImageRegistry] = None,
        session_ttl_sec: int = 1800,
    ):
        self._adapter = sandbox_adapter or OpenSandboxAdapter()
        logger.info("sandbox_backend_selected backend=%s", self._describe_adapter(self._adapter))
        self._dependency_resolver = dependency_resolver or DependencyResolver()
        self._dep_registry = dep_registry or DepImageRegistry()
        self._session_ttl_sec = max(60, int(session_ttl_sec))
        self._lock = asyncio.Lock()
        self._session_handles: Dict[str, Tuple[SandboxHandle, float]] = {}

    @staticmethod
    def _describe_adapter(adapter: SandboxAdapter) -> str:
        if isinstance(adapter, OpenSandboxAdapter):
            return "opensandbox"
        return adapter.__class__.__name__

    def backend_label(self) -> str:
        return self._describe_adapter(self._adapter)

    def _workspace_only_policy(self, workspace_path: Path, *, timeout_ms: int = 60_000) -> SandboxPolicy:
        mounts = SandboxMountPolicy.workspace_only(workspace_host_path=workspace_path)
        return SandboxPolicy(
            fs_root=str(workspace_path.resolve()),
            workspace_host_path=str(workspace_path.resolve()),
            volume_mounts=mounts,
            timeout_ms=max(1000, int(timeout_ms)),
            tool_allowlist=[],
            runtime_backend=os.getenv("SANDBOX_RUNTIME_BACKEND", "docker"),
            runtime_profile=os.getenv("SANDBOX_RUNTIME_PROFILE", "standard"),
        )

    async def _build_policy(self, req: SandboxExecutionRequest) -> SandboxPolicy:
        if req.policy is not None:
            return req.policy
        mounts: list = []
        dep_hash = ""
        base_image_ref = ""
        scripts_path = req.skill_scripts_path
        if scripts_path is None and req.skill_home is not None:
            scripts_path = req.skill_home / "scripts"
        if req.skill_home is not None and scripts_path is not None:
            runtime_name, os_arch = self._dependency_resolver.parse_runtime("python3.11", req.runtime_profile)
            fp = self._dependency_resolver.resolve_for_skill(req.skill_home, runtime=runtime_name, os_arch=os_arch)
            dep_hash = fp.dep_hash
            rec = self._dep_registry.ensure(
                dep_hash=dep_hash,
                runtime_backend=req.runtime_backend,
                runtime_profile=req.runtime_profile,
            )
            base_image_ref = rec.image_ref
            mounts = SandboxMountPolicy.build_mounts(
                workspace_host_path=req.workspace_path,
                skill_scripts_host_path=scripts_path,
                skill_config_host_path=req.skill_config_path,
                config_writable=False,
            )
        else:
            mounts = SandboxMountPolicy.workspace_only(workspace_host_path=req.workspace_path)
        return SandboxPolicy(
            fs_root=str(req.workspace_path.resolve()),
            workspace_host_path=str(req.workspace_path.resolve()),
            skill_scripts_host_path=str(scripts_path.resolve()) if scripts_path else "",
            skill_config_host_path=str(req.skill_config_path.resolve()) if req.skill_config_path else "",
            runtime_backend=req.runtime_backend,
            runtime_profile=req.runtime_profile,
            timeout_ms=max(1000, int(req.timeout_ms)),
            tool_allowlist=[req.tool_name],
            dep_hash=dep_hash,
            base_image_ref=base_image_ref,
            volume_mounts=mounts,
        )

    async def _ensure_session_handle(self, req: SandboxExecutionRequest, policy: SandboxPolicy) -> SandboxHandle:
        now = time.time()
        key = handle_cache_key(req.session_id, policy)
        logical_sid = key
        async with self._lock:
            existing = self._session_handles.get(key)
            if existing is not None:
                handle, touched = existing
                if now - touched <= self._session_ttl_sec:
                    self._session_handles[key] = (handle, now)
                    return handle
                await self._adapter.dispose_sandbox(handle)
                self._session_handles.pop(key, None)

            handle = await self._adapter.create_session_sandbox(logical_sid, policy)
            self._session_handles[key] = (handle, now)
            logger.info(
                "sandbox_session_bound session_id=%s mount_fp=%s backend=%s sandbox_id=%s",
                req.session_id,
                policy_mount_fingerprint(policy),
                self._describe_adapter(self._adapter),
                handle.metadata.get("sandbox_id", ""),
            )
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_session_created",
                turn_id=req.turn_id,
                payload={
                    "tool_call_id": req.tool_call_id,
                    "sandbox_id": handle.metadata.get("sandbox_id", ""),
                    "mount_fingerprint": policy_mount_fingerprint(policy),
                    "runtime": handle.runtime,
                    "runtime_backend": policy.runtime_backend,
                    "runtime_profile": policy.runtime_profile,
                    "dep_hash": policy.dep_hash,
                },
            )
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_mount_applied",
                turn_id=req.turn_id,
                payload={
                    "mount_fingerprint": policy_mount_fingerprint(policy),
                    "mounts": [
                        {"source": m.source, "target": m.target, "read_only": m.read_only, "type": m.mount_type}
                        for m in (policy.volume_mounts or [])
                    ],
                },
            )
            return handle

    async def _ensure_workspace_handle(
        self,
        *,
        session_id: str,
        workspace_path: Path,
        turn_id: str,
        tool_call_id: str,
        timeout_ms: int,
    ) -> SandboxHandle:
        policy = self._workspace_only_policy(workspace_path, timeout_ms=timeout_ms)
        req = SandboxExecutionRequest(
            session_id=session_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            tool_name="__sandbox_workspace_fs__",
            tool_kind="internal",
            payload={},
            timeout_ms=policy.timeout_ms,
            runner=lambda: asyncio.sleep(0),
            workspace_path=workspace_path,
            policy=policy,
        )
        return await self._ensure_session_handle(req, policy)

    async def read_workspace_text(
        self,
        *,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
        turn_id: str = "workspace-fs",
        tool_call_id: str = "read",
    ) -> str:
        handle = await self._ensure_workspace_handle(
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            timeout_ms=60_000,
        )
        inner = to_workspace_inner_path(rel_path)
        data = await self._adapter.read_file(handle, inner)
        return data.decode("utf-8")

    async def write_workspace_text(
        self,
        *,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
        content: str,
        turn_id: str = "workspace-fs",
        tool_call_id: str = "write",
    ) -> None:
        handle = await self._ensure_workspace_handle(
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            timeout_ms=60_000,
        )
        inner = to_workspace_inner_path(rel_path)
        await self._adapter.write_file(handle, inner, content.encode("utf-8"))

    async def mkdir_workspace(
        self,
        *,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
        turn_id: str = "workspace-fs",
    ) -> None:
        handle = await self._ensure_workspace_handle(
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id="mkdir",
            timeout_ms=60_000,
        )
        inner = to_workspace_inner_path(rel_path).rstrip("/")
        if hasattr(self._adapter, "exec_command"):
            await self._adapter.exec_command(handle, ["mkdir", "-p", inner])  # type: ignore[attr-defined]
            return
        # Tests / minimal fakes: create on host workspace root (same bind mount as /workspace)
        p = (workspace_path / rel_path.strip("/").replace("..", "")).resolve()
        if not str(p).startswith(str(workspace_path.resolve())):
            raise ValueError("path out of workspace")
        p.mkdir(parents=True, exist_ok=True)

    async def list_workspace_files_flat(
        self,
        *,
        session_id: str,
        workspace_path: Path,
        rel_prefix: str = "",
        turn_id: str = "workspace-fs",
    ) -> List[Dict[str, Any]]:
        handle = await self._ensure_workspace_handle(
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id="list",
            timeout_ms=120_000,
        )
        root = to_workspace_inner_path(rel_prefix)
        return await self._adapter.list_artifacts(handle, task_id=root)

    async def exec_workspace_shell(
        self,
        *,
        session_id: str,
        workspace_path: Path,
        argv: List[str],
        turn_id: str = "workspace-fs",
        tool_call_id: str = "exec",
        timeout_ms: int = 120_000,
    ) -> Dict[str, Any]:
        handle = await self._ensure_workspace_handle(
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            timeout_ms=timeout_ms,
        )
        if hasattr(self._adapter, "exec_command"):
            return await self._adapter.exec_command(handle, argv, cwd="/workspace", timeout_ms=timeout_ms)  # type: ignore[attr-defined]
        raise RuntimeError("当前沙箱适配器不支持 exec_command，无法执行目录/重命名等 shell 操作。")

    async def execute(self, req: SandboxExecutionRequest) -> Dict[str, Any]:
        policy = await self._build_policy(req)
        handle = await self._ensure_session_handle(req, policy)
        started = time.time()
        append_sandbox_event(
            session_id=req.session_id,
            event_type="sandbox_command_started",
            turn_id=req.turn_id,
            payload={
                "tool_name": req.tool_name,
                "tool_kind": req.tool_kind,
                "tool_call_id": req.tool_call_id,
                "sandbox_id": handle.metadata.get("sandbox_id", ""),
            },
        )
        try:
            result = await self._adapter.run_tool_in_sandbox(
                handle,
                {
                    "tool_name": req.tool_name,
                    "tool_kind": req.tool_kind,
                    "payload": req.payload,
                    "timeout_ms": req.timeout_ms,
                    "runner": req.runner,
                    "cwd": "/workspace",
                },
            )
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_command_finished",
                turn_id=req.turn_id,
                payload={
                    "tool_name": req.tool_name,
                    "tool_call_id": req.tool_call_id,
                    "sandbox_id": handle.metadata.get("sandbox_id", ""),
                    "elapsed_ms": int((time.time() - started) * 1000),
                },
            )
            return result
        except TimeoutError:
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_command_timeout",
                turn_id=req.turn_id,
                payload={"tool_name": req.tool_name, "tool_call_id": req.tool_call_id},
            )
            raise
        except Exception as exc:  # noqa: BLE001
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_command_failed",
                turn_id=req.turn_id,
                payload={
                    "tool_name": req.tool_name,
                    "tool_call_id": req.tool_call_id,
                    "error": str(exc),
                },
            )
            raise

    async def dispose_session(self, session_id: str, *, turn_id: str = "") -> None:
        async with self._lock:
            keys = [k for k in list(self._session_handles.keys()) if k == session_id or k.startswith(f"{session_id}:")]
            handles = [(k, self._session_handles.pop(k)) for k in keys]
        for _k, (_handle, _) in handles:
            await self._adapter.dispose_sandbox(_handle)
            append_sandbox_event(
                session_id=session_id,
                event_type="sandbox_session_disposed",
                turn_id=turn_id,
                payload={"sandbox_id": _handle.metadata.get("sandbox_id", "")},
            )
