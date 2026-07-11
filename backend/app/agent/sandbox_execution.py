"""Sandbox command execution orchestration for SandboxService."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from app.agent.sandbox_adapter import SandboxHandle
from app.agent.sandbox_audit import append_sandbox_event
from app.agent.sandbox_lifecycle_errors import (
    SandboxEnvironmentError,
    is_lifecycle_connect_error as _is_lifecycle_connect_error,
    lifecycle_connect_error_message as _lifecycle_connect_error_message,
)
from app.agent.sandbox_mount_policy import SANDBOX_WORKSPACE_ROOT
from app.agent.sandbox_policy_builder import resolve_cwd


async def execute_sandbox_request(service: Any, req: Any) -> Dict[str, Any]:
    """Execute one sandbox request using SandboxService lifecycle and cache hooks."""
    policy = await service._build_policy(req)
    cwd = resolve_cwd(policy, session_id=req.session_id, cwd=req.cwd)
    mount_targets = [str(m.target or "") for m in (policy.volume_mounts or []) if str(m.target or "")]
    payload = req.payload if isinstance(req.payload, dict) else {}
    command = payload.get("__sandbox_command")
    env = service._prepare_command_env(req, payload.get("__sandbox_env"))
    started = time.time()
    user_id = (req.user_id or "").strip() or f"session:{req.session_id}"
    for attempt in range(2):
        handle: Optional[SandboxHandle] = None
        try:
            handle = await service._ensure_user_handle(req, policy)
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
            result = await service._adapter.run_tool_in_sandbox(
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
        except Exception as exc:
            if attempt == 0 and service._is_sandbox_not_found_error(exc):
                await service._invalidate_user_handle(user_id, expected_handle=handle)
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
                await service._invalidate_user_handle(user_id, expected_handle=handle)
                raise SandboxEnvironmentError(_lifecycle_connect_error_message(exc)) from exc
            if attempt == 0 and "tool not allowed by sandbox policy" in str(exc).lower():
                await service._invalidate_user_handle(user_id, expected_handle=handle)
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
