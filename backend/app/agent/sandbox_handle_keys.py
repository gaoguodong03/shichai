"""Cache key and policy fingerprint helpers for sandbox handles."""
from __future__ import annotations

import hashlib

from app.agent.sandbox_adapter import SandboxPolicy


def policy_mount_fingerprint(policy: SandboxPolicy) -> str:
    parts = [policy.fs_root or ""]
    for m in sorted(policy.volume_mounts or [], key=lambda x: (x.target, x.source)):
        parts.append(f"{m.source}|{m.target}|{int(m.read_only)}|{m.mount_type}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def handle_cache_key(user_id: str, session_id: str = "") -> str:
    uid = (user_id or "").strip() or "anonymous"
    sid = (session_id or "").strip()
    return f"{uid}:{sid}" if sid else uid


def request_handle_cache_key(
    *,
    tool_name: str,
    user_id: str,
    session_id: str,
    session_isolation: bool,
) -> str:
    name = (tool_name or "").strip()
    if name == "__sandbox_workspace_fs__":
        return handle_cache_key(f"{user_id}:workspace", session_id)
    if name == "run_skill_script" or name.startswith("run_skill_script_"):
        return handle_cache_key(user_id, session_id)
    return handle_cache_key(user_id, session_id if session_isolation else "")


def request_needs_user_requirements(tool_name: str) -> bool:
    return (tool_name or "").strip() != "__sandbox_workspace_fs__"


def to_workspace_inner_path(rel: str) -> str:
    r = (rel or "").strip().lstrip("/").replace("..", "")
    return f"/workspace/{r}" if r else "/workspace"
