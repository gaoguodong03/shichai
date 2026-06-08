"""Platform-side sandbox service over OpenSandbox adapter."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.agent.sandbox_adapter import OpenSandboxAdapter, SandboxAdapter, SandboxHandle, SandboxPolicy
from app.agent.sandbox_audit import append_sandbox_event
from app.agent.sandbox_handle_keys import (
    handle_cache_key,
    policy_mount_fingerprint,
    request_handle_cache_key,
    request_needs_user_requirements,
)
from app.agent.sandbox_lifecycle_errors import (
    SandboxEnvironmentError,
    is_host_path_mount_source_error as _is_host_path_mount_source_error,
    is_lifecycle_connect_error as _is_lifecycle_connect_error,
    lifecycle_connect_error_message as _lifecycle_connect_error_message,
    opensandbox_lifecycle_reachable as _opensandbox_lifecycle_reachable,
)
from app.agent.sandbox_mount_policy import SANDBOX_WORKSPACE_ROOT
from app.agent.sandbox_policy_builder import (
    apply_fixed_resource_policy,
    apply_user_image_policy,
    build_mounts_for_request,
    resolve_cwd,
)
from app.agent.sandbox_policy_runtime import (
    env_csv as _env_csv,
    env_float as _env_float,
    env_int as _env_int,
    env_truthy as _env_truthy,
    network_allowed_for_tool as _network_allowed_for_tool,
    sandbox_default_environment as _sandbox_default_environment,
)
from app.agent.sandbox_prewarm import SandboxPrewarmMixin
from app.agent.sandbox_requirements import REQUIREMENTS_VERIFIER_VERSION, SandboxRequirementsMixin
from app.agent.sandbox_requirements_verifier import (
    REQUIREMENTS_REAL_VERIFIED_AT_KEY as _REQUIREMENTS_REAL_VERIFIED_AT_KEY,
    verify_installed_user_requirements,
)
from app.agent.sandbox_workspace_ops import SandboxWorkspaceMixin

logger = logging.getLogger(__name__)


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


class SandboxService(SandboxRequirementsMixin, SandboxPrewarmMixin, SandboxWorkspaceMixin):
    """Manage user sandbox lifecycle and OpenSandbox request mapping."""

    def __init__(
        self,
        sandbox_adapter: Optional[SandboxAdapter] = None,
    ):
        self._adapter = sandbox_adapter or OpenSandboxAdapter()
        logger.info("sandbox_backend_selected backend=%s", self._describe_adapter(self._adapter))
        try:
            self._requirements_real_verify_ttl_sec = max(
                0,
                int(os.getenv("SANDBOX_REQUIREMENTS_REAL_VERIFY_TTL_SEC", "300") or "300"),
            )
        except ValueError:
            logger.warning(
                "sandbox_env_invalid_int name=%s value=%s",
                "SANDBOX_REQUIREMENTS_REAL_VERIFY_TTL_SEC",
                os.getenv("SANDBOX_REQUIREMENTS_REAL_VERIFY_TTL_SEC"),
            )
            self._requirements_real_verify_ttl_sec = 300
        self._fixed_cpu = _env_float("SANDBOX_FIXED_CPU")
        self._fixed_memory_mb = _env_int("SANDBOX_FIXED_MEMORY_MB")
        self._session_isolation = _env_truthy("SANDBOX_SESSION_ISOLATION", default="0")
        self._lock = asyncio.Lock()
        self._user_handles: Dict[str, Tuple[SandboxHandle, float]] = {}
        self._user_ensure_locks: Dict[str, asyncio.Lock] = {}

    async def _ensure_lock_for_key(self, key: str) -> asyncio.Lock:
        async with self._lock:
            lock = self._user_ensure_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._user_ensure_locks[key] = lock
            return lock

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
        return ("not found" in msg) or ("no such" in msg) or ("invalid sandbox" in msg)

    def _prepare_command_env(self, req: SandboxExecutionRequest, raw_env: Any) -> Dict[str, str]:
        env: Dict[str, str] = {}
        if isinstance(raw_env, dict):
            env.update({str(k): str(v) for k, v in raw_env.items() if v is not None})
        user_id = (req.user_id or "").strip() or f"session:{req.session_id}"
        req_b64 = self._requirements_b64_for_user(user_id)
        current_b64 = (env.get("SKILL_REQUIREMENTS_B64") or "").strip()
        if req_b64 and not current_b64:
            env["SKILL_REQUIREMENTS_B64"] = req_b64
            logger.debug(
                "st49_sandbox_command_env_injected code=requirements_env_injected user_id=%s session_id=%s tool_name=%s requirements_hash=%s",
                user_id,
                req.session_id,
                req.tool_name,
                self._requirements_hash_for_user(user_id),
            )
        elif req_b64 and current_b64:
            logger.debug(
                "st49_sandbox_command_env_present code=requirements_env_present user_id=%s session_id=%s tool_name=%s requirements_hash=%s",
                user_id,
                req.session_id,
                req.tool_name,
                self._requirements_hash_for_user(user_id),
            )
        else:
            logger.debug(
                "st49_sandbox_command_env_empty code=requirements_env_empty user_id=%s session_id=%s tool_name=%s requirements_hash=%s",
                user_id,
                req.session_id,
                req.tool_name,
                self._requirements_hash_for_user(user_id),
            )
        return env

    @staticmethod
    def _installed_requirements_hash(handle: SandboxHandle) -> str:
        if not isinstance(handle.metadata, dict):
            return ""
        return str(handle.metadata.get("installed_requirements_hash") or "").strip()

    async def _build_policy(self, req: SandboxExecutionRequest) -> SandboxPolicy:
        if req.policy is not None:
            env_net = _network_allowed_for_tool(req.tool_name)
            final_net = bool(env_net or req.policy.allow_network)
            policy = req.policy
            if final_net != bool(req.policy.allow_network):
                policy = replace(req.policy, allow_network=final_net)
            host_sessions_root, skills_root, mounts = build_mounts_for_request(
                user_id=req.user_id,
                workspace_path=req.workspace_path,
            )
            updates: Dict[str, Any] = {}
            # 用户级单沙箱复用模式：不按工具名做 allowlist 限制，避免跨工具调用被旧策略误拦截。
            if list(policy.tool_allowlist or []):
                updates["tool_allowlist"] = []
            if not list(policy.volume_mounts or []):
                updates["fs_root"] = str(host_sessions_root.resolve())
                updates["volume_mounts"] = mounts
            if not (policy.workspace_host_path or "").strip():
                updates["workspace_host_path"] = str(host_sessions_root.resolve())
            if skills_root is not None and not (policy.skill_scripts_host_path or "").strip():
                updates["skill_scripts_host_path"] = str(skills_root.resolve())
            if updates:
                policy = replace(policy, **updates)
            policy = apply_fixed_resource_policy(
                policy,
                fixed_cpu=self._fixed_cpu,
                fixed_memory_mb=self._fixed_memory_mb,
                default_env=_sandbox_default_environment(),
            )
            return apply_user_image_policy(policy, req.user_id)
        host_sessions_root, skills_root, mounts = build_mounts_for_request(
            user_id=req.user_id,
            workspace_path=req.workspace_path,
        )
        policy = SandboxPolicy(
            fs_root=str(host_sessions_root.resolve()),
            workspace_host_path=str(host_sessions_root.resolve()),
            skill_scripts_host_path=str(skills_root) if skills_root else "",
            skill_config_host_path="",
            runtime_backend=req.runtime_backend,
            runtime_profile=req.runtime_profile,
            timeout_ms=max(1000, int(req.timeout_ms)),
            # 全量挂载模式下，用户级沙箱在同一挂载策略下复用，不按工具名触发重建。
            tool_allowlist=[],
            volume_mounts=mounts,
            allow_network=_network_allowed_for_tool(req.tool_name),
            allowed_hosts=_env_csv("SANDBOX_ALLOWED_HOSTS"),
        )
        policy = apply_fixed_resource_policy(
            policy,
            fixed_cpu=self._fixed_cpu,
            fixed_memory_mb=self._fixed_memory_mb,
            default_env=_sandbox_default_environment(),
        )
        return apply_user_image_policy(policy, req.user_id)

    async def _ensure_user_handle(self, req: SandboxExecutionRequest, policy: SandboxPolicy) -> SandboxHandle:
        user_id = (req.user_id or "").strip() or f"session:{req.session_id}"
        key = request_handle_cache_key(
            tool_name=req.tool_name,
            user_id=user_id,
            session_id=req.session_id,
            session_isolation=self._session_isolation,
        )
        user_lock = await self._ensure_lock_for_key(key)
        async with user_lock:
            return await self._ensure_user_handle_locked(req, policy, user_id=user_id, key=key)

    async def _ensure_user_handle_locked(
        self,
        req: SandboxExecutionRequest,
        policy: SandboxPolicy,
        *,
        user_id: str,
        key: str,
    ) -> SandboxHandle:
        now = time.time()
        ensure_started_at = time.perf_counter()
        logical_sid = key
        needs_requirements = request_needs_user_requirements(req.tool_name)
        async with self._lock:
            existing = self._user_handles.get(key)
            if existing is not None:
                handle, _touched = existing
                current_req_hash = self._requirements_hash_for_user(user_id)
                installed_req_hash = self._installed_requirements_hash(handle)
                verified_req_hash = str((handle.metadata or {}).get("verified_requirements_hash") or "").strip()
                verifier_version = str((handle.metadata or {}).get("requirements_verifier_version") or "").strip()
                old_mount_fp = str((handle.metadata or {}).get("mount_fingerprint") or "").strip()
                new_mount_fp = policy_mount_fingerprint(policy)
                old_image_ref = str((handle.metadata or {}).get("image_ref") or "").strip()
                new_image_ref = str(policy.image_ref or "").strip()
                stored_net = (handle.metadata or {}).get("policy_allow_network")
                network_policy_matches = stored_net is None or bool(stored_net) == bool(policy.allow_network)
                logger.info(
                    "st49_sandbox_cache_check code=user_handle_cache_check user_id=%s session_id=%s cache_key=%s sandbox_id=%s current_hash=%s installed_hash=%s verified_hash=%s verifier=%s old_image=%s new_image=%s old_mount_fp=%s new_mount_fp=%s old_allow_network=%s new_allow_network=%s",
                    user_id,
                    req.session_id,
                    key,
                    str((handle.metadata or {}).get("sandbox_id") or ""),
                    current_req_hash,
                    installed_req_hash,
                    verified_req_hash,
                    verifier_version,
                    old_image_ref,
                    new_image_ref,
                    old_mount_fp,
                    new_mount_fp,
                    bool(stored_net) if stored_net is not None else "",
                    bool(policy.allow_network),
                )
                if (
                    current_req_hash == installed_req_hash
                    and current_req_hash == verified_req_hash
                    and verifier_version == REQUIREMENTS_VERIFIER_VERSION
                    and old_image_ref == new_image_ref
                    and old_mount_fp == new_mount_fp
                    and network_policy_matches
                ):
                    self._user_handles[key] = (handle, now)
                    if not needs_requirements:
                        logger.info(
                            "st49_sandbox_requirements_skip code=requirements_not_needed user_id=%s session_id=%s cache_key=%s tool_name=%s sandbox_id=%s",
                            user_id,
                            req.session_id,
                            key,
                            req.tool_name,
                            str((handle.metadata or {}).get("sandbox_id") or ""),
                        )
                        return handle
                    if self._requirements_real_verify_is_fresh(handle, dep_hash=current_req_hash, now=now):
                        logger.info(
                            "st49_sandbox_requirements_skip code=requirements_real_verify_ttl_hit user_id=%s session_id=%s dep_hash=%s sandbox_id=%s ttl_sec=%s",
                            user_id,
                            req.session_id,
                            current_req_hash,
                            str((handle.metadata or {}).get("sandbox_id") or ""),
                            self._requirements_real_verify_ttl_sec,
                        )
                        return handle
                    real_verified = await verify_installed_user_requirements(
                        self._adapter,
                        handle,
                        user_id=user_id,
                        policy=policy,
                        normalized_requirements=self._read_user_sandbox_requirements(user_id),
                        dep_hash=current_req_hash,
                    )
                    if real_verified:
                        return handle
                    if isinstance(handle.metadata, dict):
                        handle.metadata.pop("installed_requirements_hash", None)
                        handle.metadata.pop("verified_requirements_hash", None)
                        handle.metadata.pop("requirements_verifier_version", None)
                        handle.metadata.pop(_REQUIREMENTS_REAL_VERIFIED_AT_KEY, None)
                    logger.info(
                        "st49_sandbox_reinstall code=user_requirements_real_verify_failed user_id=%s session_id=%s dep_hash=%s sandbox_id=%s",
                        user_id,
                        req.session_id,
                        current_req_hash,
                        str((handle.metadata or {}).get("sandbox_id") or ""),
                    )
                    await self._maybe_install_user_requirements(handle, user_id=user_id, policy=policy)
                    self._user_handles[key] = (handle, now)
                    return handle
                if old_image_ref != new_image_ref:
                    logger.info(
                        "st49_sandbox_recreate code=user_image_updated user_id=%s session_id=%s old_image=%s new_image=%s",
                        user_id,
                        req.session_id,
                        old_image_ref,
                        new_image_ref,
                    )
                elif old_mount_fp != new_mount_fp:
                    logger.info(
                        "st49_sandbox_recreate code=user_mount_policy_updated user_id=%s session_id=%s old_mount_fp=%s new_mount_fp=%s",
                        user_id,
                        req.session_id,
                        old_mount_fp,
                        new_mount_fp,
                    )
                elif not network_policy_matches:
                    logger.info(
                        "st49_sandbox_recreate code=user_network_policy_updated user_id=%s session_id=%s old_allow_network=%s new_allow_network=%s",
                        user_id,
                        req.session_id,
                        bool(stored_net),
                        bool(policy.allow_network),
                    )
                else:
                    logger.info(
                        "st49_sandbox_recreate code=user_requirements_updated user_id=%s session_id=%s old_hash=%s new_hash=%s",
                        user_id,
                        req.session_id,
                        installed_req_hash,
                        current_req_hash,
                    )
                try:
                    await self._adapter.dispose_sandbox(handle)
                except Exception as e:  # noqa: BLE001
                    if not self._is_sandbox_not_found_error(e):
                        logger.warning("sandbox_dispose_stale_failed user_id=%s err=%s", user_id, e)
                self._user_handles.pop(key, None)

            logger.info(
                "st49_sandbox_create_prepare code=user_handle_create_prepare user_id=%s session_id=%s cache_key=%s logical_sid=%s image_ref=%s variant=%s mount_fp=%s allow_network=%s timeout_ms=%s skills_root=%s workspace_root=%s workspace_root_exists=%s workspace_mount_ready=%s",
                user_id,
                req.session_id,
                key,
                logical_sid,
                str(policy.image_ref or ""),
                str((policy.environment or {}).get("SANDBOX_IMAGE_VARIANT") or ""),
                policy_mount_fingerprint(policy),
                bool(policy.allow_network),
                int(policy.timeout_ms or 0),
                str(policy.skill_scripts_host_path or ""),
                str(policy.workspace_host_path or policy.fs_root or ""),
                Path(str(policy.workspace_host_path or policy.fs_root or "")).exists(),
                (Path(str(policy.workspace_host_path or policy.fs_root or "")) / ".st49-mount-ready").exists(),
            )
            try:
                handle = await self._adapter.create_session_sandbox(logical_sid, policy)
            except Exception as e:  # noqa: BLE001
                if _is_lifecycle_connect_error(e):
                    raise SandboxEnvironmentError(_lifecycle_connect_error_message(e)) from e
                if _is_host_path_mount_source_error(e):
                    workspace_root = Path(str(policy.workspace_host_path or policy.fs_root or ""))
                    ready = workspace_root / ".st49-mount-ready"
                    raise SandboxEnvironmentError(
                        "OpenSandbox host_path 挂载失败：应用侧工作区目录已经传给 Docker，但 Docker daemon 无法访问该宿主路径。"
                        f" workspace_root={workspace_root}"
                        f" workspace_root_exists={workspace_root.exists()}"
                        f" workspace_mount_ready={ready.exists()}"
                        "。本地 Docker Desktop 场景请检查 Docker Desktop File Sharing"
                        "（Settings → Resources → File Sharing）是否包含项目目录"
                        "（例如 /Users/ggd/project/shichai），必要时重启 Docker Desktop；"
                        "1Panel/容器部署场景请确认 SANDBOX_HOST_PATH_MAP 将 /app/backend/data 映射到"
                        " Docker daemon 可见路径（例如 /var/lib/docker/volumes/st49/_data）。"
                        f" 原始错误: {e}"
                    ) from e
                raise
            if isinstance(handle.metadata, dict):
                handle.metadata["mount_fingerprint"] = policy_mount_fingerprint(policy)
                handle.metadata["policy_allow_network"] = bool(policy.allow_network)
                handle.metadata["image_ref"] = policy.image_ref
                handle.metadata["user_id"] = user_id
                handle.metadata["app_session_id"] = req.session_id
            self._user_handles[key] = (handle, now)
            logger.info(
                "st49_sandbox_create_done code=user_handle_create_done user_id=%s session_id=%s cache_key=%s sandbox_id=%s image_ref=%s mount_fp=%s",
                user_id,
                req.session_id,
                key,
                str((handle.metadata or {}).get("sandbox_id") or handle.session_id or ""),
                str((handle.metadata or {}).get("image_ref") or ""),
                str((handle.metadata or {}).get("mount_fingerprint") or ""),
            )
        # 出锁后做安装：避免长时间持锁阻塞其他请求
        if needs_requirements:
            await self._maybe_install_user_requirements(handle, user_id=user_id, policy=policy)
        else:
            logger.info(
                "st49_sandbox_requirements_skip code=requirements_not_needed user_id=%s session_id=%s cache_key=%s tool_name=%s sandbox_id=%s",
                user_id,
                req.session_id,
                key,
                req.tool_name,
                str((handle.metadata or {}).get("sandbox_id") or ""),
            )
        ensure_elapsed_ms = int((time.perf_counter() - ensure_started_at) * 1000)
        async with self._lock:
            logger.info(
                "st49_sandbox_user_bound code=user_sandbox_bound user_id=%s session_id=%s cache_key=%s mount_fp=%s backend=%s sandbox_id=%s image_ref=%s elapsed_ms=%s",
                user_id,
                req.session_id,
                key,
                policy_mount_fingerprint(policy),
                self._describe_adapter(self._adapter),
                handle.metadata.get("sandbox_id", ""),
                str((handle.metadata or {}).get("image_ref") or ""),
                ensure_elapsed_ms,
            )
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_session_created",
                turn_id=req.turn_id,
                payload={
                    "user_id": user_id,
                    "tool_call_id": req.tool_call_id,
                    "sandbox_id": handle.metadata.get("sandbox_id", ""),
                    "sandbox_mode": "user_session_sandbox",
                    "mount_fingerprint": policy_mount_fingerprint(policy),
                    "runtime": handle.runtime,
                    "runtime_backend": policy.runtime_backend,
                    "runtime_profile": policy.runtime_profile,
                    "image_ref": policy.image_ref,
                    "mount_count": len(policy.volume_mounts or []),
                    "workspace_root_in_sandbox": SANDBOX_WORKSPACE_ROOT,
                    "resource_limit": {
                        "cpu": policy.cpu_limit,
                        "memory_mb": policy.memory_limit_mb,
                    },
                },
            )
            mounts_payload = [
                {"source": m.source, "target": m.target, "read_only": m.read_only, "type": m.mount_type}
                for m in (policy.volume_mounts or [])
            ]
            append_sandbox_event(
                session_id=req.session_id,
                event_type="sandbox_mount_applied",
                turn_id=req.turn_id,
                payload={
                    "user_id": user_id,
                    "sandbox_mode": "user_session_sandbox",
                    "mount_fingerprint": policy_mount_fingerprint(policy),
                    "mounts": mounts_payload,
                    "mount_targets": [str(m.get("target") or "") for m in mounts_payload],
                    "mounts_empty": len(mounts_payload) == 0,
                },
            )
            return handle

    async def _invalidate_user_handle(self, user_id: str, *, expected_handle: Optional[SandboxHandle] = None) -> None:
        target: Optional[SandboxHandle] = None
        async with self._lock:
            target_key = ""
            if expected_handle is not None:
                for k, (handle, _touched) in self._user_handles.items():
                    if handle is expected_handle:
                        target_key = k
                        target = handle
                        break
            else:
                key_prefix = handle_cache_key(user_id)
                existing = self._user_handles.get(key_prefix)
                if existing is not None:
                    target_key = key_prefix
                    target = existing[0]
            if not target_key or target is None:
                return
            self._user_handles.pop(target_key, None)
        if target is None:
            return
        try:
            await self._adapter.dispose_sandbox(target)
        except Exception as e:  # noqa: BLE001
            if not self._is_sandbox_not_found_error(e):
                logger.warning("sandbox_invalidate_dispose_failed user_id=%s err=%s", user_id, e)

    async def execute(self, req: SandboxExecutionRequest) -> Dict[str, Any]:
        policy = await self._build_policy(req)
        cwd = resolve_cwd(policy, session_id=req.session_id, cwd=req.cwd)
        mount_targets = [str(m.target or "") for m in (policy.volume_mounts or []) if str(m.target or "")]
        payload = req.payload if isinstance(req.payload, dict) else {}
        command = payload.get("__sandbox_command")
        env = self._prepare_command_env(req, payload.get("__sandbox_env"))
        started = time.time()
        user_id = (req.user_id or "").strip() or f"session:{req.session_id}"
        for attempt in range(2):
            handle: Optional[SandboxHandle] = None
            try:
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
                        "mount_count": len(policy.volume_mounts or []),
                        "mount_targets": mount_targets,
                        "attempt": attempt + 1,
                    },
                )
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
                        "env": env,
                    },
                )
                if isinstance(result, dict):
                    trace = result.get("_sandbox_trace")
                    if not isinstance(trace, dict):
                        trace = {}
                    trace.setdefault("sandbox_id", str((handle.metadata or {}).get("sandbox_id") or ""))
                    trace.setdefault("image_ref", str((handle.metadata or {}).get("image_ref") or ""))
                    trace.setdefault(
                        "installed_requirements_hash",
                        str((handle.metadata or {}).get("installed_requirements_hash") or ""),
                    )
                    trace.setdefault(
                        "verified_requirements_hash",
                        str((handle.metadata or {}).get("verified_requirements_hash") or ""),
                    )
                    trace.setdefault(
                        "requirements_verifier_version",
                        str((handle.metadata or {}).get("requirements_verifier_version") or ""),
                    )
                    result["_sandbox_trace"] = trace
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
            except SandboxEnvironmentError:
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
                if _is_lifecycle_connect_error(exc):
                    await self._invalidate_user_handle(user_id, expected_handle=handle)
                    raise SandboxEnvironmentError(_lifecycle_connect_error_message(exc)) from exc
                if attempt == 0 and "tool not allowed by sandbox policy" in str(exc).lower():
                    await self._invalidate_user_handle(user_id, expected_handle=handle)
                    append_sandbox_event(
                        session_id=req.session_id,
                        event_type="sandbox_session_recreated",
                        turn_id=req.turn_id,
                        payload={
                            "tool_name": req.tool_name,
                            "tool_call_id": req.tool_call_id,
                            "user_id": req.user_id,
                            "reason": "sandbox_tool_policy_mismatch",
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
                        "cwd": cwd,
                        "mount_count": len(policy.volume_mounts or []),
                        "mount_targets": mount_targets,
                        "attempt": attempt + 1,
                    },
                )
                diag = {
                    "sandbox_id": str(((handle.metadata if handle is not None else {}) or {}).get("sandbox_id") or ""),
                    "sandbox_cwd": cwd,
                    "mount_count": len(policy.volume_mounts or []),
                    "mount_targets": mount_targets,
                    "resource_limit": {
                        "cpu": policy.cpu_limit,
                        "memory_mb": policy.memory_limit_mb,
                    },
                    "last_sandbox_error_code": "INVALID_REQUEST_BODY"
                    if "INVALID_REQUEST_BODY" in str(exc)
                    else ("HTTP_400" if "Status code: 400" in str(exc) else ""),
                }
                raise RuntimeError(f"{exc} | sandbox_diag={json.dumps(diag, ensure_ascii=False)}") from exc
        raise RuntimeError("sandbox execution failed without terminal error")

    async def dispose_session(self, session_id: str, *, turn_id: str = "") -> None:
        if not self._session_isolation:
            append_sandbox_event(
                session_id=session_id,
                event_type="sandbox_session_disposed",
                turn_id=turn_id,
                payload={"session_id": session_id, "mode": "user_single_sandbox"},
            )
            return
        sid = (session_id or "").strip()
        async with self._lock:
            keys = [
                k
                for k, (handle, _touched) in list(self._user_handles.items())
                if str((handle.metadata or {}).get("app_session_id") or "").strip() == sid
            ]
            handles = [(k, self._user_handles.pop(k)) for k in keys]
        for _k, (_handle, _) in handles:
            await self._adapter.dispose_sandbox(_handle)
            append_sandbox_event(
                session_id=session_id,
                event_type="sandbox_session_disposed",
                turn_id=turn_id,
                payload={
                    "sandbox_id": _handle.metadata.get("sandbox_id", ""),
                    "session_id": session_id,
                    "mode": "user_session_sandbox",
                },
            )
