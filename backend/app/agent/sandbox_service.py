"""Platform-side sandbox service over OpenSandbox adapter."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import base64
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.agent.path_whitelist_guard import ensure_within_root, normalize_rel_path
from app.agent.sandbox_adapter import OpenSandboxAdapter, SandboxAdapter, SandboxHandle, SandboxPolicy
from app.agent.sandbox_audit import append_sandbox_event
from app.agent.sandbox_mount_policy import SandboxMountPolicy
from app.agent.session_workspace_policy import host_sessions_root_from_workspace, sandbox_session_dir, sandbox_sessions_root
from app.core.user_context import get_user_context_for

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

def _network_allowed_for_tool(tool_name: str) -> bool:
    """
    Decide whether sandbox may access network for a given tool.

    - SANDBOX_ALLOW_NETWORK=1 and SANDBOX_NETWORK_TOOL_ALLOWLIST empty => allow for all tools (legacy behavior)
    - SANDBOX_NETWORK_TOOL_ALLOWLIST non-empty => only allow if tool_name in allowlist (or '*')
    - 配置里常写 run_skill_script，实际工具名为 run_skill_script_<skill_id>，二者等价放行
    - SANDBOX_ALLOW_NETWORK=0 => deny unless allowlist is explicitly configured (opt-in)
    """
    name = (tool_name or "").strip()
    allowlist = _env_csv("SANDBOX_NETWORK_TOOL_ALLOWLIST")
    allow_global = _env_truthy("SANDBOX_ALLOW_NETWORK", default="0")
    if allowlist:
        if "*" in allowlist:
            return True
        if name in allowlist:
            return True
        if name.startswith("run_skill_script_") and "run_skill_script" in allowlist:
            return True
        return False
    return bool(allow_global)


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

    @staticmethod
    def _is_sandbox_not_found_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        if "sandbox" not in msg:
            return False
        return "not found" in msg or "no such" in msg

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
            allow_network=False,
            allowed_hosts=_env_csv("SANDBOX_ALLOWED_HOSTS"),
        )

    @staticmethod
    def _cached_handle_still_valid(handle: SandboxHandle, policy: SandboxPolicy, tool_name: str) -> bool:
        """
        单用户沙箱会复用同一 OpenSandbox 会话。创建时写入的 policy.tool_allowlist 与挂载指纹若与当前请求不一致，
        必须丢弃缓存，否则会误拦后续工具（例如先跑 A 技能再跑 sandbox-dep-check）。
        """
        meta = handle.metadata if isinstance(handle.metadata, dict) else {}
        old_fp = str(meta.get("mount_fingerprint") or "").strip()
        new_fp = policy_mount_fingerprint(policy)
        if not old_fp or old_fp != new_fp:
            return False
        old_policy = meta.get("policy")
        old_allow: list[str] = []
        if isinstance(old_policy, dict):
            old_allow = list(old_policy.get("tool_allowlist") or [])
        tn = (tool_name or "").strip()
        if old_allow and tn and tn not in old_allow:
            return False
        stored_net = meta.get("policy_allow_network")
        if stored_net is not None and bool(stored_net) != bool(policy.allow_network):
            return False
        return True

    async def _build_policy(self, req: SandboxExecutionRequest) -> SandboxPolicy:
        if req.policy is not None:
            env_net = _network_allowed_for_tool(req.tool_name)
            final_net = bool(env_net or req.policy.allow_network)
            if final_net != bool(req.policy.allow_network):
                return replace(req.policy, allow_network=final_net)
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
                skill_home_host_path=req.skill_home,
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
            allow_network=_network_allowed_for_tool(req.tool_name),
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
                if now - touched <= self._session_ttl_sec and self._cached_handle_still_valid(
                    handle, policy, req.tool_name
                ):
                    self._user_handles[key] = (handle, now)
                    await self._maybe_install_user_requirements(handle, user_id=user_id, policy=policy)
                    return handle
                try:
                    await self._adapter.dispose_sandbox(handle)
                except Exception as e:  # noqa: BLE001
                    if not self._is_sandbox_not_found_error(e):
                        logger.warning("sandbox_dispose_stale_failed user_id=%s err=%s", user_id, e)
                self._user_handles.pop(key, None)

            handle = await self._adapter.create_session_sandbox(logical_sid, policy)
            if isinstance(handle.metadata, dict):
                handle.metadata["mount_fingerprint"] = policy_mount_fingerprint(policy)
                handle.metadata["policy_allow_network"] = bool(policy.allow_network)
            self._user_handles[key] = (handle, now)
        # 出锁后做安装：避免长时间持锁阻塞其他请求
        await self._maybe_install_user_requirements(handle, user_id=user_id, policy=policy)
        async with self._lock:
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

    async def _invalidate_user_handle(self, user_id: str, *, expected_handle: Optional[SandboxHandle] = None) -> None:
        key = handle_cache_key(user_id)
        target: Optional[SandboxHandle] = None
        async with self._lock:
            existing = self._user_handles.get(key)
            if existing is None:
                return
            handle, _ = existing
            if expected_handle is not None and handle is not expected_handle:
                return
            self._user_handles.pop(key, None)
            target = handle
        if target is None:
            return
        try:
            await self._adapter.dispose_sandbox(target)
        except Exception as e:  # noqa: BLE001
            if not self._is_sandbox_not_found_error(e):
                logger.warning("sandbox_invalidate_dispose_failed user_id=%s err=%s", user_id, e)

    def _read_user_sandbox_requirements(self, user_id: str) -> str:
        """读取当前用户的沙箱 requirements.txt 内容（允许为空）。"""
        try:
            ctx = get_user_context_for(user_id)
        except Exception:
            return ""
        path = (ctx.config_dir / "sandbox" / "requirements.txt").resolve()
        try:
            if not path.exists():
                return ""
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    async def _maybe_install_user_requirements(
        self,
        handle: SandboxHandle,
        *,
        user_id: str,
        policy: SandboxPolicy,
    ) -> None:
        """按内容 hash 在沙箱内安装 requirements（变更时才执行一次）。"""
        if not isinstance(handle.metadata, dict):
            return
        content = self._read_user_sandbox_requirements(user_id)
        normalized = (content or "").strip()
        dep_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        last = str(handle.metadata.get("installed_requirements_hash") or "")
        if dep_hash == last:
            return
        # 空清单：只更新 hash，不执行 pip
        if not normalized:
            handle.metadata["installed_requirements_hash"] = dep_hash
            return
        # 若禁网，很可能装不成；仍尝试一次并把错误抛出（方便测试验证）。
        b64 = base64.b64encode(normalized.encode("utf-8")).decode("ascii")
        cmd = [
            "sh",
            "-lc",
            (
                "set -euo pipefail; "
                'REQ_B64="${SANDBOX_REQUIREMENTS_B64:-}"; '
                'python3 - <<\'PY\'\n'
                "import base64,os,sys\n"
                "b=os.environ.get('SANDBOX_REQUIREMENTS_B64','')\n"
                "data=base64.b64decode(b.encode('ascii')) if b else b''\n"
                "open('/tmp/requirements.txt','wb').write(data)\n"
                "print('wrote_requirements_bytes', len(data))\n"
                "PY\n"
                "python3 -m pip install --disable-pip-version-check --no-input -r /tmp/requirements.txt"
            ),
        ]
        env = {"SANDBOX_REQUIREMENTS_B64": b64}
        try:
            if hasattr(self._adapter, "exec_command"):
                await self._adapter.exec_command(handle, cmd, cwd="/workspace", timeout_ms=max(120_000, int(policy.timeout_ms or 120_000)), env=env)  # type: ignore[attr-defined]
                handle.metadata["installed_requirements_hash"] = dep_hash
        except Exception as e:
            # 不更新 hash：下次仍会重试，便于用户修复 requirements 后再次验证
            logger.warning("sandbox_requirements_install_failed user_id=%s err=%s", user_id, str(e))
            raise

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
        cwd = req.cwd or sandbox_session_dir(req.session_id)
        payload = req.payload if isinstance(req.payload, dict) else {}
        command = payload.get("__sandbox_command")
        env = payload.get("__sandbox_env")
        started = time.time()
        user_id = (req.user_id or "").strip() or f"session:{req.session_id}"
        for attempt in range(2):
            handle = await self._ensure_user_handle(req, policy)
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
                    "attempt": attempt + 1,
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
                        "attempt": attempt + 1,
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
                if attempt == 0 and self._is_sandbox_not_found_error(exc):
                    await self._invalidate_user_handle(user_id, expected_handle=handle)
                    append_sandbox_event(
                        session_id=req.session_id,
                        event_type="sandbox_session_recreated",
                        turn_id=req.turn_id,
                        payload={
                            "tool_name": req.tool_name,
                            "tool_call_id": req.tool_call_id,
                            "user_id": req.user_id,
                            "reason": "sandbox_not_found",
                        },
                    )
                    continue
                append_sandbox_event(
                    session_id=req.session_id,
                    event_type="sandbox_command_failed",
                    turn_id=req.turn_id,
                    payload={
                        "tool_name": req.tool_name,
                        "tool_call_id": req.tool_call_id,
                        "user_id": req.user_id,
                        "error": str(exc),
                        "attempt": attempt + 1,
                    },
                )
                raise
        raise RuntimeError("sandbox execution failed without terminal error")

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

    async def prewarm_user_sandbox(
        self,
        user_id: str,
        *,
        reason: str = "manual",
        timeout_ms: int = 60_000,
    ) -> Dict[str, Any]:
        """提前创建并缓存用户级沙箱，减少首次工具调用冷启动延迟。"""
        uid = (user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        user_ctx = get_user_context_for(uid)
        workspaces_subdir = (os.getenv("WORKSPACES_SUBDIR") or "workspaces").strip() or "workspaces"
        workspaces_root = (user_ctx.agent_outputs_dir / workspaces_subdir).resolve()
        workspaces_root.mkdir(parents=True, exist_ok=True)
        policy = self._workspace_only_policy(workspaces_root, timeout_ms=timeout_ms)
        req = SandboxExecutionRequest(
            user_id=uid,
            session_id=f"prewarm:{uid}",
            turn_id=f"prewarm:{reason}",
            tool_call_id=f"prewarm:{reason}",
            tool_name="__sandbox_prewarm__",
            tool_kind="internal",
            payload={},
            timeout_ms=policy.timeout_ms,
            runner=lambda: asyncio.sleep(0),
            workspace_path=workspaces_root,
            policy=policy,
        )
        handle = await self._ensure_user_handle(req, policy)
        if hasattr(self._adapter, "exec_command"):
            try:
                await self._adapter.exec_command(  # type: ignore[attr-defined]
                    handle,
                    ["sh", "-lc", "true"],
                    cwd="/workspace",
                    timeout_ms=min(10_000, int(policy.timeout_ms)),
                )
            except Exception as e:  # noqa: BLE001
                if self._is_sandbox_not_found_error(e):
                    await self._invalidate_user_handle(uid, expected_handle=handle)
                    handle = await self._ensure_user_handle(req, policy)
                else:
                    raise
        return {
            "status": "ok",
            "user_id": uid,
            "sandbox_id": str((handle.metadata or {}).get("sandbox_id") or ""),
            "backend": self.backend_label(),
            "reason": reason,
        }
