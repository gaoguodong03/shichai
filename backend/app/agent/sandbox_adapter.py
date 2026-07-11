"""Sandbox adapter abstraction with OpenSandbox-first runtime integration."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass
class SandboxVolumeMount:
    source: str
    target: str
    read_only: bool = False
    mount_type: str = "host_path"


@dataclass
class SandboxPolicy:
    fs_root: str
    image_ref: str = ""
    workspace_host_path: str = ""
    skill_scripts_host_path: str = ""
    skill_config_host_path: str = ""
    runtime_backend: str = "docker"
    runtime_profile: str = "standard"
    allow_network: bool = False
    allowed_hosts: List[str] = field(default_factory=list)
    cpu_limit: float = 1.0
    memory_limit_mb: int = 512
    timeout_ms: int = 60000
    tool_allowlist: List[str] = field(default_factory=list)
    max_artifact_size_mb: int = 50
    environment: Dict[str, str] = field(default_factory=dict)
    volume_mounts: List[SandboxVolumeMount] = field(default_factory=list)


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


class _OpenSandboxRuntimeClient(Protocol):
    async def create_sandbox(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        ...

    async def execute_command(self, sandbox_id: str, req: Dict[str, Any]) -> Dict[str, Any]:
        ...

    async def read_file(self, sandbox_id: str, path: str) -> bytes:
        ...

    async def write_file(self, sandbox_id: str, path: str, data: bytes) -> Dict[str, Any]:
        ...

    async def list_files(self, sandbox_id: str, root: str) -> List[Dict[str, Any]]:
        ...

    async def dispose_sandbox(self, sandbox_id: str) -> None:
        ...

    async def list_sandboxes(self, *, page: int = 1, page_size: int = 100) -> Dict[str, Any]:
        ...


async def execute_tool_runner_transport(handle: SandboxHandle, tool_request: Dict[str, Any]) -> Dict[str, Any]:
    """在宿主进程内执行可调用 runner（MCP / subprocess 等），不经由 OpenSandbox execute_command。

    与「经 OpenSandbox 挂载的工作区文件读写」分离：文件读写请使用 OpenSandboxAdapter.read_file/write_file。
    """
    policy = handle.metadata.get("policy") if isinstance(handle.metadata, dict) else None
    req_name = str(tool_request.get("tool_name") or "").strip()
    allowlist = list((policy or {}).get("tool_allowlist") or [])
    allowlist_hit = bool(req_name and (not allowlist or req_name in allowlist))
    if allowlist and req_name and req_name not in allowlist:
        logger.warning(
            "sandbox_tool_blocked runtime=%s session=%s tool=%s timeout_ms=%s allowlist_hit=%s",
            handle.runtime,
            handle.session_id,
            req_name,
            int(tool_request.get("timeout_ms") or (policy or {}).get("timeout_ms") or 60000),
            allowlist_hit,
        )
        raise PermissionError(f"tool not allowed by sandbox policy: {req_name}")

    timeout_ms = int(tool_request.get("timeout_ms") or (policy or {}).get("timeout_ms") or 60000)
    logger.info(
        "sandbox_tool_enter transport=host_runner runtime=%s session=%s tool=%s timeout_ms=%s allowlist_hit=%s",
        handle.runtime,
        handle.session_id,
        req_name or "unknown_tool",
        timeout_ms,
        allowlist_hit,
    )
    runner = tool_request.get("runner")
    if not callable(runner):
        raise ValueError("tool_request.runner callable is required")

    result_or_coro = runner()
    if asyncio.iscoroutine(result_or_coro):
        result = await asyncio.wait_for(result_or_coro, timeout=max(0.1, timeout_ms / 1000.0))
    else:
        result = result_or_coro
    sandbox_trace = {
        "runtime": handle.runtime,
        "transport": "host_runner",
        "session_id": handle.session_id,
        "tool_name": req_name or "unknown_tool",
        "timeout_ms": timeout_ms,
        "allowlist_hit": allowlist_hit,
    }
    if isinstance(result, dict):
        if "_sandbox_trace" not in result:
            result["_sandbox_trace"] = sandbox_trace
        return result
    return {"result": result, "_sandbox_trace": sandbox_trace}


class OpenSandboxAdapter:
    """OpenSandbox adapter: maps platform policy to OpenSandbox primitives."""

    def __init__(self, client: Optional[_OpenSandboxRuntimeClient] = None):
        self._client = client or self._build_default_client()

    def _build_default_client(self) -> _OpenSandboxRuntimeClient:
        try:
            from app.agent.opensandbox_runtime_client import OpenSandboxRuntimeClient

            return OpenSandboxRuntimeClient()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "无法初始化 OpenSandbox 客户端：请安装/配置 OpenSandbox。\n"
                "- 需安装 opensandbox Python SDK（你已安装）。\n"
                "- 需配置 OPENSANDBOX_DOMAIN（或 OPEN_SANDBOX_DOMAIN），以及可选 OPENSANDBOX_API_KEY。\n"
                f"原始错误: {e}"
            ) from e

    @staticmethod
    def _opensandbox_metadata_value(value: Any) -> str:
        from app.agent.opensandbox_runtime_client import opensandbox_metadata_value

        return opensandbox_metadata_value(value)

    @staticmethod
    def _opensandbox_metadata(metadata: Dict[str, Any]) -> Dict[str, str]:
        from app.agent.opensandbox_runtime_client import opensandbox_metadata

        return opensandbox_metadata(metadata)

    @staticmethod
    def _spec_from_policy(session_id: str, policy: SandboxPolicy) -> Dict[str, Any]:
        mounts = [
            {
                "type": vm.mount_type,
                "source": vm.source,
                "target": vm.target,
                "read_only": bool(vm.read_only),
            }
            for vm in list(policy.volume_mounts or [])
            if vm.source and vm.target
        ]
        return {
            "session_id": session_id,
            "runtime_backend": policy.runtime_backend,
            "runtime_profile": policy.runtime_profile,
            "resource_limit": {
                "cpu": policy.cpu_limit,
                "memory_mb": policy.memory_limit_mb,
            },
            "network": {
                "allow_network": policy.allow_network,
                "allowed_hosts": list(policy.allowed_hosts or []),
            },
            "env": dict(policy.environment or {}),
            "image_ref": policy.image_ref,
            "metadata": {
                "managed_by": "st49",
                "app": "shichai",
                "session_id": OpenSandboxAdapter._opensandbox_metadata_value(session_id),
            },
            "mounts": mounts,
            "workspace_root": policy.fs_root,
        }

    async def create_session_sandbox(self, session_id: str, policy: SandboxPolicy) -> SandboxHandle:
        spec = self._spec_from_policy(session_id=session_id, policy=policy)
        created = await self._client.create_sandbox(spec)
        sandbox_id = str(created.get("sandbox_id") or created.get("id") or session_id)
        return SandboxHandle(
            runtime="opensandbox",
            session_id=session_id,
            root=policy.fs_root,
            metadata={
                "sandbox_id": sandbox_id,
                "policy": {"tool_allowlist": list(policy.tool_allowlist), "timeout_ms": int(policy.timeout_ms)},
                "runtime_backend": policy.runtime_backend,
                "runtime_profile": policy.runtime_profile,
                "image_ref": policy.image_ref,
            },
        )

    async def run_tool_in_sandbox(self, handle: SandboxHandle, tool_request: Dict[str, Any]) -> Dict[str, Any]:
        policy = handle.metadata.get("policy") if isinstance(handle.metadata, dict) else None
        req_name = str(tool_request.get("tool_name") or "").strip()
        allowlist = list((policy or {}).get("tool_allowlist") or [])
        if allowlist and req_name and req_name not in allowlist:
            raise PermissionError(f"tool not allowed by sandbox policy: {req_name}")
        timeout_ms = int(tool_request.get("timeout_ms") or (policy or {}).get("timeout_ms") or 60000)
        cmd = tool_request.get("command")
        if cmd is not None:
            payload = tool_request.get("payload") or {}
            req = {
                "tool_name": req_name or "unknown_tool",
                "tool_kind": str(tool_request.get("tool_kind") or "tool"),
                "payload": payload if isinstance(payload, dict) else {"value": payload},
                "timeout_ms": timeout_ms,
                "cwd": str(tool_request.get("cwd") or "/"),
                "command": cmd,
                "env": tool_request.get("env") or {},
            }
            sandbox_id = str(handle.metadata.get("sandbox_id") or handle.session_id)
            result = await self._client.execute_command(sandbox_id, req)
            if isinstance(result, dict):
                result.setdefault(
                    "_sandbox_trace",
                    {
                        "runtime": "opensandbox",
                        "transport": "opensandbox_execute",
                        "session_id": handle.session_id,
                        "sandbox_id": sandbox_id,
                        "tool_name": req_name or "unknown_tool",
                        "timeout_ms": timeout_ms,
                    },
                )
                return result
            return {"result": result}
        return await execute_tool_runner_transport(handle, tool_request)

    async def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        sandbox_id = str(handle.metadata.get("sandbox_id") or handle.session_id)
        return await self._client.read_file(sandbox_id, path)

    async def write_file(self, handle: SandboxHandle, path: str, data: bytes, token_version: int = 0) -> Dict[str, Any]:
        sandbox_id = str(handle.metadata.get("sandbox_id") or handle.session_id)
        result = await self._client.write_file(sandbox_id, path, data)
        if isinstance(result, dict):
            result.setdefault("token_version", int(token_version))
            return result
        return {"status": "ok", "token_version": int(token_version)}

    async def exec_command(
        self,
        handle: SandboxHandle,
        argv: List[str],
        *,
        cwd: str = "/",
        timeout_ms: int = 120_000,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        sandbox_id = str(handle.metadata.get("sandbox_id") or handle.session_id)
        return await self._client.execute_command(
            sandbox_id,
            {
                "tool_name": "__exec__",
                "tool_kind": "internal",
                "timeout_ms": int(timeout_ms),
                "cwd": cwd,
                "command": argv,
                "env": dict(env or {}),
            },
        )

    async def list_artifacts(self, handle: SandboxHandle, task_id: str = "") -> List[Dict[str, Any]]:
        sandbox_id = str(handle.metadata.get("sandbox_id") or handle.session_id)
        root = (task_id or "").strip() or "/workspace"
        if not root.startswith("/"):
            root = "/workspace/" + root.lstrip("/")
        files = await self._client.list_files(sandbox_id, root)
        out: List[Dict[str, Any]] = []
        for item in files or []:
            if isinstance(item, dict):
                one = dict(item)
                one.setdefault("task_id", task_id)
                out.append(one)
        return out

    async def dispose_sandbox(self, handle: SandboxHandle) -> None:
        sandbox_id = str(handle.metadata.get("sandbox_id") or handle.session_id)
        await self._client.dispose_sandbox(sandbox_id)

    @staticmethod
    def _created_at_epoch(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value or "").strip()
        if not raw:
            return 0.0
        try:
            normalized = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return 0.0

    @staticmethod
    def _is_managed_sandbox(item: Dict[str, Any]) -> bool:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        return str(metadata.get("managed_by") or "") == "st49" or str(metadata.get("app") or "") == "shichai"

    async def cleanup_orphan_sandboxes(
        self,
        *,
        active_sandbox_ids: set[str] | None = None,
        min_age_sec: int = 60,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        active_ids = {str(x).strip() for x in (active_sandbox_ids or set()) if str(x).strip()}
        now = time.time()
        scanned = 0
        skipped_active = 0
        skipped_young = 0
        skipped_unmanaged = 0
        candidates: List[str] = []
        deleted: List[str] = []
        failed: List[Dict[str, str]] = []
        page = 1
        while True:
            listing = await self._client.list_sandboxes(page=page, page_size=page_size)
            items = list((listing or {}).get("items") or [])
            scanned += len(items)
            for item in items:
                if not isinstance(item, dict):
                    continue
                sandbox_id = str(item.get("id") or "").strip()
                if not sandbox_id:
                    continue
                if sandbox_id in active_ids:
                    skipped_active += 1
                    continue
                if not self._is_managed_sandbox(item):
                    skipped_unmanaged += 1
                    continue
                created_at = self._created_at_epoch(item.get("created_at"))
                if created_at and now - created_at < max(0, int(min_age_sec)):
                    skipped_young += 1
                    continue
                candidates.append(sandbox_id)
            if not bool((listing or {}).get("has_next_page")):
                break
            page += 1
        for sandbox_id in candidates:
            try:
                await self._client.dispose_sandbox(sandbox_id)
                deleted.append(sandbox_id)
            except Exception as exc:  # noqa: BLE001
                failed.append({"sandbox_id": sandbox_id, "error": str(exc)[:500]})
        return {
            "scanned": scanned,
            "candidates": candidates,
            "deleted": deleted,
            "failed": failed,
            "skipped_active": skipped_active,
            "skipped_young": skipped_young,
            "skipped_unmanaged": skipped_unmanaged,
        }
