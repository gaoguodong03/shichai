"""Sandbox policy construction helpers."""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional

from app.agent.sandbox_adapter import SandboxHandle, SandboxPolicy
from app.agent.sandbox_handle_keys import policy_mount_fingerprint
from app.agent.sandbox_mount_policy import SANDBOX_WORKSPACE_ROOT, SandboxMountPolicy
from app.agent.sandbox_policy_runtime import env_csv, sandbox_default_environment, sandbox_image_for_user
from app.agent.session_workspace_policy import host_sessions_root_from_workspace, sandbox_session_dir, sandbox_sessions_root
from app.core.user_context import get_user_context_for


def apply_fixed_resource_policy(
    policy: SandboxPolicy,
    *,
    fixed_cpu: Optional[float],
    fixed_memory_mb: Optional[int],
    default_env: Dict[str, str] | None = None,
) -> SandboxPolicy:
    updates: Dict[str, Any] = {}
    if fixed_cpu is not None and float(policy.cpu_limit) != float(fixed_cpu):
        updates["cpu_limit"] = fixed_cpu
    if fixed_memory_mb is not None and int(policy.memory_limit_mb) != int(fixed_memory_mb):
        updates["memory_limit_mb"] = fixed_memory_mb
    merged_env = {**dict(default_env or sandbox_default_environment()), **dict(policy.environment or {})}
    if merged_env != dict(policy.environment or {}):
        updates["environment"] = merged_env
    if updates:
        return replace(policy, **updates)
    return policy


def apply_user_image_policy(policy: SandboxPolicy, user_id: str) -> SandboxPolicy:
    variant, image_ref = sandbox_image_for_user(user_id)
    if policy.image_ref == image_ref:
        return policy
    env = {**dict(policy.environment or {}), "SANDBOX_IMAGE_VARIANT": variant}
    return replace(policy, image_ref=image_ref, environment=env)


def ensure_mount_source_ready(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    sentinel = path / ".st49-mount-ready"
    if not sentinel.exists():
        sentinel.write_text("ready\n", encoding="utf-8")


def build_mounts_for_request(
    *,
    user_id: str,
    workspace_path: Path,
) -> tuple[Path, Optional[Path], list]:
    host_sessions_root = host_sessions_root_from_workspace(workspace_path)
    ensure_mount_source_ready(host_sessions_root)
    skills_root: Optional[Path] = None
    uid = (user_id or "").strip()
    if uid:
        try:
            skills_root = get_user_context_for(uid).skills_dir.resolve()
        except Exception:
            skills_root = None
    if skills_root is not None:
        mounts = SandboxMountPolicy.workspace_with_all_skills(
            workspace_sessions_host_path=host_sessions_root,
            skills_root_host_path=skills_root,
            workspace_target=sandbox_sessions_root(),
        )
    else:
        mounts = SandboxMountPolicy.workspace_sessions_root_only(
            workspace_sessions_host_path=host_sessions_root
        )
    return host_sessions_root, skills_root, mounts


def resolve_cwd(policy: SandboxPolicy, *, session_id: str, cwd: str = "") -> str:
    desired = (cwd or "").strip() or sandbox_session_dir(session_id)
    targets = {str(m.target or "").strip() for m in (policy.volume_mounts or []) if str(m.target or "").strip()}
    if desired == "/":
        return desired
    if desired.startswith("/workspace"):
        if "/workspace" in targets:
            return desired
        return "/"
    return desired


def workspace_only_policy(sessions_root_path: Path, *, timeout_ms: int = 60_000) -> SandboxPolicy:
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
        allowed_hosts=env_csv("SANDBOX_ALLOWED_HOSTS"),
    )


def workspace_with_skills_policy(
    sessions_root_path: Path,
    *,
    skills_root_path: Path,
    timeout_ms: int = 60_000,
) -> SandboxPolicy:
    mounts = SandboxMountPolicy.workspace_with_all_skills(
        workspace_sessions_host_path=sessions_root_path,
        skills_root_host_path=skills_root_path,
        workspace_target=SANDBOX_WORKSPACE_ROOT,
    )
    return SandboxPolicy(
        fs_root=str(sessions_root_path.resolve()),
        workspace_host_path=str(sessions_root_path.resolve()),
        skill_scripts_host_path=str(skills_root_path.resolve()),
        timeout_ms=max(1000, int(timeout_ms)),
        tool_allowlist=[],
        runtime_backend=os.getenv("SANDBOX_RUNTIME_BACKEND", "docker"),
        runtime_profile=os.getenv("SANDBOX_RUNTIME_PROFILE", "standard"),
        allow_network=False,
        allowed_hosts=env_csv("SANDBOX_ALLOWED_HOSTS"),
        volume_mounts=mounts,
    )


def cached_handle_still_valid(handle: SandboxHandle, policy: SandboxPolicy, tool_name: str) -> bool:
    meta = handle.metadata if isinstance(handle.metadata, dict) else {}
    old_fp = str(meta.get("mount_fingerprint") or "").strip()
    new_fp = policy_mount_fingerprint(policy)
    if not old_fp or old_fp != new_fp:
        return False
    old_image_ref = str(meta.get("image_ref") or "").strip()
    new_image_ref = str(policy.image_ref or "").strip()
    if old_image_ref != new_image_ref:
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
