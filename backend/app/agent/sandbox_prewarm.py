"""Prewarm and startup cleanup helpers for sandbox service."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any, Dict, List

from app.agent.sandbox_adapter import OpenSandboxAdapter
from app.agent.sandbox_policy_builder import (
    apply_fixed_resource_policy,
    apply_user_image_policy,
    workspace_with_skills_policy,
)
from app.agent.sandbox_policy_runtime import (
    env_int,
    env_truthy,
    sandbox_default_environment,
)
from app.agent.sandbox_requirements_verifier import REQUIREMENTS_REAL_VERIFIED_AT_KEY
from app.core.user_context import get_user_context_for, users_data_root

logger = logging.getLogger(__name__)


class SandboxPrewarmMixin:
    _adapter: Any
    _lock: Any
    _fixed_cpu: float | None
    _fixed_memory_mb: int | None

    async def prewarm_user_sandbox(
        self,
        user_id: str,
        *,
        reason: str = "manual",
        timeout_ms: int = 60_000,
    ) -> Dict[str, Any]:
        uid = (user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        user_ctx = get_user_context_for(uid)
        workspaces_root = (user_ctx.base_dir / "settings" / "sandbox" / "prewarm-workspace").resolve()
        workspaces_root.mkdir(parents=True, exist_ok=True)
        policy = workspace_with_skills_policy(
            workspaces_root,
            skills_root_path=user_ctx.skills_dir.resolve(),
            timeout_ms=timeout_ms,
        )
        policy = apply_fixed_resource_policy(
            policy,
            fixed_cpu=self._fixed_cpu,
            fixed_memory_mb=self._fixed_memory_mb,
            default_env=sandbox_default_environment(),
        )
        policy = apply_user_image_policy(policy, uid)
        if (self._read_user_sandbox_requirements(uid) or "").strip() and not policy.allow_network:
            policy = replace(policy, allow_network=True)
        req = self._build_prewarm_request(
            user_id=uid,
            reason=reason,
            timeout_ms=policy.timeout_ms,
            workspace_path=workspaces_root,
            policy=policy,
        )
        handle = await self._ensure_user_handle(req, policy)
        if hasattr(self._adapter, "exec_command"):
            try:
                await self._adapter.exec_command(
                    handle,
                    ["sh", "-lc", "true"],
                    cwd="/",
                    timeout_ms=min(10_000, int(policy.timeout_ms)),
                )
            except Exception as e:
                if self._is_sandbox_not_found_error(e):
                    await self._invalidate_user_handle(uid, expected_handle=handle)
                    handle = await self._ensure_user_handle(req, policy)
                else:
                    raise
        return {
            "status": "ok",
            "user_id": uid,
            "sandbox_id": str((handle.metadata or {}).get("sandbox_id") or ""),
            "image_ref": str((handle.metadata or {}).get("image_ref") or ""),
            "requirements_hash": self._requirements_hash_for_user(uid),
            "installed_requirements_hash": str((handle.metadata or {}).get("installed_requirements_hash") or ""),
            "verified_requirements_hash": str((handle.metadata or {}).get("verified_requirements_hash") or ""),
            "requirements_verifier_version": str((handle.metadata or {}).get("requirements_verifier_version") or ""),
            "requirements_real_verified_at": float((handle.metadata or {}).get(REQUIREMENTS_REAL_VERIFIED_AT_KEY) or 0),
            "backend": self.backend_label(),
            "reason": reason,
        }

    async def prewarm_all_known_users(
        self,
        *,
        reason: str = "startup",
        timeout_ms: int = 60_000,
    ) -> Dict[str, Any]:
        root = users_data_root()
        if not root.exists():
            return {"status": "ok", "users_total": 0, "ok": 0, "failed": 0, "errors": []}
        users = sorted([p.name for p in root.iterdir() if p.is_dir() and p.name.strip()])
        ok_count = 0
        errors: List[Dict[str, str]] = []
        for uid in users:
            try:
                await self.prewarm_user_sandbox(uid, reason=reason, timeout_ms=timeout_ms)
                ok_count += 1
            except Exception as exc:
                logger.warning("sandbox_prewarm_known_user_failed user=%s err=%s", uid, exc)
                errors.append({"user_id": uid, "error": str(exc)})
        return {
            "status": "ok",
            "users_total": len(users),
            "ok": ok_count,
            "failed": len(errors),
            "errors": errors,
        }

    async def cleanup_orphan_sandboxes_on_startup(self) -> Dict[str, Any]:
        if not env_truthy("SANDBOX_CLEANUP_ORPHANS_ON_START", default="1"):
            logger.info("sandbox_orphan_cleanup_disabled")
            return {"enabled": False, "deleted": [], "failed": []}
        if not hasattr(self._adapter, "cleanup_orphan_sandboxes"):
            logger.info("sandbox_orphan_cleanup_skipped reason=adapter_unsupported backend=%s", self.backend_label())
            return {"enabled": True, "skipped": "adapter_unsupported", "deleted": [], "failed": []}
        if isinstance(self._adapter, OpenSandboxAdapter):
            from app.agent import sandbox_service as sandbox_service_module

            reachable, target = sandbox_service_module._opensandbox_lifecycle_reachable()
            if not reachable:
                logger.warning("sandbox_orphan_cleanup_skipped reason=opensandbox_unreachable target=%s", target)
                return {
                    "enabled": True,
                    "skipped": "opensandbox_unreachable",
                    "target": target,
                    "deleted": [],
                    "failed": [],
                }
        min_age_sec = env_int("SANDBOX_ORPHAN_CLEANUP_MIN_AGE_SEC") or 60
        async with self._lock:
            active_ids = {
                str((handle.metadata or {}).get("sandbox_id") or "").strip()
                for handle, _touched in self._user_handles.values()
                if isinstance(handle.metadata, dict)
            }
        active_ids.discard("")
        logger.info(
            "sandbox_orphan_cleanup_start backend=%s active_count=%s min_age_sec=%s",
            self.backend_label(),
            len(active_ids),
            min_age_sec,
        )
        result = await self._adapter.cleanup_orphan_sandboxes(
            active_sandbox_ids=active_ids,
            min_age_sec=min_age_sec,
        )
        deleted = list((result or {}).get("deleted") or [])
        failed = list((result or {}).get("failed") or [])
        logger.info(
            "sandbox_orphan_cleanup_done scanned=%s deleted=%s failed=%s skipped_active=%s skipped_young=%s skipped_unmanaged=%s",
            int((result or {}).get("scanned") or 0),
            len(deleted),
            len(failed),
            int((result or {}).get("skipped_active") or 0),
            int((result or {}).get("skipped_young") or 0),
            int((result or {}).get("skipped_unmanaged") or 0),
        )
        return {"enabled": True, **dict(result or {})}

    def _build_prewarm_request(self, **kwargs: Any) -> Any:
        from app.agent.sandbox_service import SandboxExecutionRequest

        reason = str(kwargs["reason"])
        uid = str(kwargs["user_id"])
        return SandboxExecutionRequest(
            user_id=uid,
            session_id=f"prewarm:{uid}",
            turn_id=f"prewarm:{reason}",
            tool_call_id=f"prewarm:{reason}",
            tool_name="__sandbox_prewarm__",
            tool_kind="internal",
            payload={},
            timeout_ms=int(kwargs["timeout_ms"]),
            runner=lambda: asyncio.sleep(0),
            workspace_path=kwargs["workspace_path"],
            policy=kwargs["policy"],
        )
