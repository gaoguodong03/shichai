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

from app.agent.path_whitelist_guard import ensure_within_root, normalize_rel_path
from app.agent.sandbox_adapter import OpenSandboxAdapter, SandboxAdapter, SandboxHandle, SandboxPolicy
from app.agent.sandbox_audit import append_sandbox_event
from app.agent.sandbox_mount_policy import SandboxMountPolicy
from app.agent.session_workspace_policy import host_sessions_root_from_workspace, sandbox_session_dir, sandbox_sessions_root

logger = logging.getLogger(__name__)

def _env_truthy(name: str, default: str = "0") -> bool:
    val = (os.getenv(name) or default).strip().lower()
    return val in {"1", "true", "yes", "on", "enabled"}


def _env_csv(name: str) -> List[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return []
    parts = []
    for x in raw.split(","):
        s = x.strip()
        if s:
            parts.append(s)
    # de-dup preserve order
    return list(dict.fromkeys(parts))


@dataclass
class SandboxExecutionRequest:
    user_id: str
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
    cwd: str = ""


def policy_mount_fingerprint(policy: SandboxPolicy) -> str:
    parts = [policy.fs_root or ""]
    for m in sorted(policy.volume_mounts or [], key=lambda x: (x.target, x.source)):
        parts.append(f"{m.source}|{m.target}|{int(m.read_only)}|{m.mount_type}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def handle_cache_key(user_id: str) -> str:
    return (user_id or "").strip() or "anonymous"


def to_workspace_inner_path(rel: str) -> str:
    r = (rel or "").strip().lstrip("/").replace("..", "")
    return f"/workspace/{r}" if r else "/workspace"


class SandboxService:
    """Manage user sandbox lifecycle and OpenSandbox request mapping."""

    def __init__(
        self,
        sandbox_adapter: Optional[SandboxAdapter] = None,
        session_ttl_sec: int = 1800,
    ):
        self._adapter = sandbox_adapter or OpenSandboxAdapter()
        logger.info("sandbox_backend_selected backend=%s", self._describe_adapter(self._adapter))
        self._session_ttl_sec = max(60, int(session_ttl_sec))
        self._lock = asyncio.Lock()
        self._user_handles: Dict[str, Tuple[SandboxHandle, float]] = {}

    @staticmethod
    def _describe_adapter(adapter: SandboxAdapter) -> str:
        if isinstance(adapter, OpenSandboxAdapter):
            return "opensandbox"
        return adapter.__class__.__name__

    def backend_label(self) -> str:
        return self._describe_adapter(self._adapter)

    def _workspace_only_policy(self, sessions_root_path: Path, *, timeout_ms: int = 60_000) -> SandboxPolicy:
        mounts = SandboxMountPolicy.workspace_sessions_root_only(workspace_sessions_host_path=sessions_root_path)
        return SandboxPolicy(
            fs_root=str(sessions_root_path.resolve()),
            workspace_host_path=str(sessions_root_path.resolve()),
            volume_mounts=mounts,
            timeout_ms=max(1000, int(timeout_ms)),
            tool_allowlist=[],
            runtime_backend=os.getenv("SANDBOX_RUNTIME_BACKEND", "docker"),
            runtime_profile=os.getenv("SANDBOX_RUNTIME_PROFILE", "standard"),
            allow_network=_env_truthy("SANDBOX_ALLOW_NETWORK", default="0"),
            allowed_hosts=_env_csv("SANDBOX_ALLOWED_HOSTS"),
        )

    async def _build_policy(self, req: SandboxExecutionRequest) -> SandboxPolicy:
        if req.policy is not None:
            return req.policy
        mounts: list = []
        host_sessions_root = host_sessions_root_from_workspace(req.workspace_path)
        scripts_path = req.skill_scripts_path
        if scripts_path is None and req.skill_home is not None:
            scripts_path = req.skill_home / "scripts"
        if req.skill_home is not None and scripts_path is not None:
            mounts = SandboxMountPolicy.build_mounts(
                workspace_host_path=host_sessions_root,
                skill_scripts_host_path=scripts_path,
                skill_config_host_path=req.skill_config_path,
                config_writable=False,
                workspace_target=sandbox_sessions_root(),
            )
        else:
            mounts = SandboxMountPolicy.workspace_sessions_root_only(workspace_sessions_host_path=host_sessions_root)
        return SandboxPolicy(
            fs_root=str(host_sessions_root.resolve()),
            workspace_host_path=str(host_sessions_root.resolve()),
            skill_scripts_host_path=str(scripts_path.resolve()) if scripts_path else "",
            skill_config_host_path=str(req.skill_config_path.resolve()) if req.skill_config_path else "",
            runtime_backend=req.runtime_backend,
            runtime_profile=req.runtime_profile,
            timeout_ms=max(1000, int(req.timeout_ms)),
            tool_allowlist=[req.tool_name],
            volume_mounts=mounts,
            allow_network=_env_truthy("SANDBOX_ALLOW_NETWORK", default="0"),
            allowed_hosts=_env_csv("SANDBOX_ALLOWED_HOSTS"),
        )

    async def _ensure_user_handle(self, req: SandboxExecutionRequest, policy: SandboxPolicy) -> SandboxHandle:
        now = time.time()
        user_id = (req.user_id or "").strip() or f"session:{req.session_id}"
        key = handle_cache_key(user_id)
        logical_sid = user_id
        async with self._lock:
            existing = self._user_handles.get(key)
            if existing is not None:
                handle, touched = existing
                if now - touched <= self._session_ttl_sec:
                    self._user_handles[key] = (handle, now)
                    return handle
                await self._adapter.dispose_sandbox(handle)
                self._user_handles.pop(key, None)

            handle = await self._adapter.create_session_sandbox(logical_sid, policy)
            self._user_handles[key] = (handle, now)
            logger.info(
                "sandbox_user_bound user_id=%s session_id=%s cache_key=%s mount_fp=%s backend=%s sandbox_id=%s",
                user_id,
                req.session_id,
                key,
                policy_mount_fingerprint(policy),
                self._describe_adapter(self._adapter),
                handle.metadata.get("sandbox_id", ""),
            )
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_session_created",
                turn_id=req.turn_id,
                payload={
                    "user_id": user_id,
                    "tool_call_id": req.tool_call_id,
                    "sandbox_id": handle.metadata.get("sandbox_id", ""),
                    "sandbox_mode": "user_single_sandbox",
                    "mount_fingerprint": policy_mount_fingerprint(policy),
                    "runtime": handle.runtime,
                    "runtime_backend": policy.runtime_backend,
                    "runtime_profile": policy.runtime_profile,
                },
            )
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_mount_applied",
                turn_id=req.turn_id,
                payload={
                    "user_id": user_id,
                    "sandbox_mode": "user_single_sandbox",
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
        user_id: str,
        session_id: str,
        workspace_path: Path,
        turn_id: str,
        tool_call_id: str,
        timeout_ms: int,
    ) -> SandboxHandle:
        host_sessions_root = host_sessions_root_from_workspace(workspace_path)
        policy = self._workspace_only_policy(host_sessions_root, timeout_ms=timeout_ms)
        req = SandboxExecutionRequest(
            user_id=user_id,
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
        return await self._ensure_user_handle(req, policy)

    async def read_workspace_text(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
        turn_id: str = "workspace-fs",
        tool_call_id: str = "read",
    ) -> str:
        handle = await self._ensure_workspace_handle(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            timeout_ms=60_000,
        )
        session_rel = normalize_rel_path(rel_path)
        inner = f"{sandbox_session_dir(session_id)}/{session_rel}".rstrip("/")
        data = await self._adapter.read_file(handle, inner)
        return data.decode("utf-8")

    async def write_workspace_text(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
        content: str,
        turn_id: str = "workspace-fs",
        tool_call_id: str = "write",
    ) -> None:
        handle = await self._ensure_workspace_handle(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            timeout_ms=60_000,
        )
        session_rel = normalize_rel_path(rel_path)
        inner = f"{sandbox_session_dir(session_id)}/{session_rel}".rstrip("/")
        await self._adapter.write_file(handle, inner, content.encode("utf-8"))

    async def mkdir_workspace(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
        turn_id: str = "workspace-fs",
    ) -> None:
        handle = await self._ensure_workspace_handle(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id="mkdir",
            timeout_ms=60_000,
        )
        session_rel = normalize_rel_path(rel_path)
        inner = f"{sandbox_session_dir(session_id)}/{session_rel}".rstrip("/")
        if hasattr(self._adapter, "exec_command"):
            await self._adapter.exec_command(handle, ["mkdir", "-p", inner])  # type: ignore[attr-defined]
            return
        # Tests / minimal fakes: create on host workspace root (same bind mount as /workspace)
        p = ensure_within_root(workspace_path / session_rel, workspace_path)
        p.mkdir(parents=True, exist_ok=True)

    async def list_workspace_files_flat(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_prefix: str = "",
        turn_id: str = "workspace-fs",
    ) -> List[Dict[str, Any]]:
        handle = await self._ensure_workspace_handle(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id="list",
            timeout_ms=120_000,
        )
        root_rel = normalize_rel_path(rel_prefix)
        root = f"{sandbox_session_dir(session_id)}/{root_rel}".rstrip("/")
        return await self._adapter.list_artifacts(handle, task_id=root)

    async def exec_workspace_shell(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        argv: List[str],
        turn_id: str = "workspace-fs",
        tool_call_id: str = "exec",
        timeout_ms: int = 120_000,
    ) -> Dict[str, Any]:
        handle = await self._ensure_workspace_handle(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            timeout_ms=timeout_ms,
        )
        if hasattr(self._adapter, "exec_command"):
            return await self._adapter.exec_command(
                handle,
                argv,
                cwd=sandbox_session_dir(session_id),
                timeout_ms=timeout_ms,
            )  # type: ignore[attr-defined]
        raise RuntimeError("当前沙箱适配器不支持 exec_command，无法执行目录/重命名等 shell 操作。")

    async def execute(self, req: SandboxExecutionRequest) -> Dict[str, Any]:
        policy = await self._build_policy(req)
        handle = await self._ensure_user_handle(req, policy)
        cwd = req.cwd or sandbox_session_dir(req.session_id)
        payload = req.payload if isinstance(req.payload, dict) else {}
        command = payload.get("__sandbox_command")
        env = payload.get("__sandbox_env")
        started = time.time()
        append_sandbox_event(
            session_id=req.session_id,
            event_type="sandbox_command_started",
            turn_id=req.turn_id,
            payload={
                "tool_name": req.tool_name,
                "tool_kind": req.tool_kind,
                "tool_call_id": req.tool_call_id,
                "user_id": req.user_id,
                "sandbox_id": handle.metadata.get("sandbox_id", ""),
                "cwd": cwd,
            },
        )
        try:
            result = await self._adapter.run_tool_in_sandbox(
                handle,
                {
                    "tool_name": req.tool_name,
                    "tool_kind": req.tool_kind,
                    "payload": payload,
                    "timeout_ms": req.timeout_ms,
                    "runner": req.runner,
                    "cwd": cwd,
                    "command": command if isinstance(command, list) else None,
                    "env": env if isinstance(env, dict) else {},
                },
            )
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_command_finished",
                turn_id=req.turn_id,
                payload={
                    "tool_name": req.tool_name,
                    "tool_call_id": req.tool_call_id,
                    "user_id": req.user_id,
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
                    "user_id": req.user_id,
                    "error": str(exc),
                },
            )
            raise

    async def dispose_user(self, user_id: str, *, turn_id: str = "") -> None:
        async with self._lock:
            keys = [k for k in list(self._user_handles.keys()) if k == user_id or k.startswith(f"{user_id}:")]
            handles = [(k, self._user_handles.pop(k)) for k in keys]
        for _k, (_handle, _) in handles:
            await self._adapter.dispose_sandbox(_handle)
            append_sandbox_event(
                session_id=user_id,
                event_type="sandbox_session_disposed",
                turn_id=turn_id,
                payload={"sandbox_id": _handle.metadata.get("sandbox_id", ""), "user_id": user_id},
            )

    async def dispose_session(self, session_id: str, *, turn_id: str = "") -> None:
        # Backward-compatible API: session-level dispose is no-op in user-level sandbox mode.
        append_sandbox_event(
            session_id=session_id,
            event_type="sandbox_session_disposed",
            turn_id=turn_id,
            payload={"session_id": session_id, "mode": "user_single_sandbox"},
        )
