from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from app.agent.path_whitelist_guard import normalize_rel_path
from app.agent.sandbox_adapter import SandboxHandle
from app.agent.sandbox_policy_builder import workspace_only_policy
from app.agent.sandbox_workspace_fs import (
    exec_workspace_shell_on_host,
    list_workspace_files_on_host,
    mkdir_workspace_on_host,
    read_workspace_text_on_host,
    write_workspace_text_on_host,
)
from app.agent.session_workspace_policy import host_sessions_root_from_workspace, sandbox_session_dir

logger = logging.getLogger(__name__)


@dataclass
class _WorkspaceSandboxRequest:
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
    policy: Any
    cwd: str = ""
    runtime_backend: str = "docker"
    runtime_profile: str = "standard"
    skill_home: Path | None = None
    skill_scripts_path: Path | None = None
    skill_config_path: Path | None = None


class SandboxWorkspaceMixin:
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
        policy = workspace_only_policy(host_sessions_root, timeout_ms=timeout_ms)
        req = _WorkspaceSandboxRequest(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            tool_name="__sandbox_workspace_fs__",
            tool_kind="internal",
            payload={},
            timeout_ms=policy.timeout_ms,
            runner=lambda: None,
            workspace_path=workspace_path,
            policy=policy,
        )
        return await self._ensure_user_handle(req, policy)  # type: ignore[attr-defined]

    async def read_workspace_text(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
    ) -> str:
        started_at = time.perf_counter()
        session_rel = normalize_rel_path(rel_path)
        text = read_workspace_text_on_host(workspace_path=workspace_path, rel_path=session_rel)
        logger.info(
            "sandbox_workspace_read_host_done user_id=%s session_id=%s path=%s bytes=%s elapsed_ms=%s",
            user_id,
            session_id,
            session_rel,
            len(text.encode("utf-8")),
            int((time.perf_counter() - started_at) * 1000),
        )
        return text

    async def write_workspace_text(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
        content: str,
    ) -> None:
        started_at = time.perf_counter()
        session_rel = normalize_rel_path(rel_path)
        session_rel, byte_count = write_workspace_text_on_host(
            workspace_path=workspace_path,
            rel_path=session_rel,
            content=content,
        )
        logger.info(
            "sandbox_workspace_write_host_done user_id=%s session_id=%s path=%s bytes=%s elapsed_ms=%s",
            user_id,
            session_id,
            session_rel,
            byte_count,
            int((time.perf_counter() - started_at) * 1000),
        )

    async def mkdir_workspace(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_path: str,
    ) -> None:
        started_at = time.perf_counter()
        session_rel = normalize_rel_path(rel_path)
        session_rel = mkdir_workspace_on_host(workspace_path=workspace_path, rel_path=session_rel)
        logger.info(
            "sandbox_workspace_mkdir_host_done user_id=%s session_id=%s path=%s elapsed_ms=%s",
            user_id,
            session_id,
            session_rel,
            int((time.perf_counter() - started_at) * 1000),
        )

    async def list_workspace_files_flat(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_path: Path,
        rel_prefix: str = "",
    ) -> List[Dict[str, Any]]:
        started_at = time.perf_counter()
        root_rel = normalize_rel_path(rel_prefix)
        items = list_workspace_files_on_host(
            workspace_path=workspace_path,
            session_id=session_id,
            rel_prefix=root_rel,
        )
        logger.info(
            "sandbox_workspace_list_host_done user_id=%s session_id=%s path=%s count=%s elapsed_ms=%s",
            user_id,
            session_id,
            root_rel or ".",
            len(items or []),
            int((time.perf_counter() - started_at) * 1000),
        )
        return items

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
        started_at = time.perf_counter()
        host_result = exec_workspace_shell_on_host(
            session_id=session_id,
            workspace_path=workspace_path,
            argv=argv,
        )
        if host_result is not None:
            logger.info(
                "sandbox_workspace_exec_host_done user_id=%s session_id=%s argv0=%s argc=%s exit_code=%s elapsed_ms=%s",
                user_id,
                session_id,
                str(argv[0] if argv else ""),
                len(argv or []),
                host_result.get("exit_code"),
                int((time.perf_counter() - started_at) * 1000),
            )
            return host_result
        handle = await self._ensure_workspace_handle(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            timeout_ms=timeout_ms,
        )
        adapter = self._adapter  # type: ignore[attr-defined]
        if hasattr(adapter, "exec_command"):
            sandbox_id = str((handle.metadata or {}).get("sandbox_id") or "")
            try:
                result = await adapter.exec_command(
                    handle,
                    argv,
                    cwd=sandbox_session_dir(session_id),
                    timeout_ms=timeout_ms,
                )
                logger.info(
                    "sandbox_workspace_exec_done user_id=%s session_id=%s argv0=%s argc=%s exit_code=%s elapsed_ms=%s sandbox_id=%s",
                    user_id,
                    session_id,
                    str(argv[0] if argv else ""),
                    len(argv or []),
                    result.get("exit_code") if isinstance(result, dict) else "",
                    int((time.perf_counter() - started_at) * 1000),
                    sandbox_id,
                )
                return result
            except Exception as e:
                logger.warning(
                    "sandbox_workspace_exec_failed user_id=%s session_id=%s argv0=%s argc=%s elapsed_ms=%s sandbox_id=%s err=%s",
                    user_id,
                    session_id,
                    str(argv[0] if argv else ""),
                    len(argv or []),
                    int((time.perf_counter() - started_at) * 1000),
                    sandbox_id,
                    str(e)[:500],
                )
                raise
        raise RuntimeError("当前沙箱适配器不支持 exec_command，无法执行目录/重命名等 shell 操作。")
