"""Sandbox adapter abstraction with OpenSandbox-first runtime integration."""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
from datetime import timedelta
from dataclasses import dataclass, field
from urllib.parse import urlparse
logger = logging.getLogger(__name__)

from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class SandboxVolumeMount:
    source: str
    target: str
    read_only: bool = False
    mount_type: str = "host_path"


@dataclass
class SandboxPolicy:
    fs_root: str
    workspace_host_path: str = ""
    skill_scripts_host_path: str = ""
    skill_config_host_path: str = ""
    runtime_backend: str = "docker"
    runtime_profile: str = "standard"
    allow_network: bool = False
    allowed_hosts: List[str] = field(default_factory=list)
    cpu_limit: float = 1.0
    memory_limit_mb: int = 512
    timeout_ms: int = 30000
    tool_allowlist: List[str] = field(default_factory=list)
    max_artifact_size_mb: int = 50
    dep_hash: str = ""
    base_image_ref: str = ""
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
            int(tool_request.get("timeout_ms") or (policy or {}).get("timeout_ms") or 30000),
            allowlist_hit,
        )
        raise PermissionError(f"tool not allowed by sandbox policy: {req_name}")

    timeout_ms = int(tool_request.get("timeout_ms") or (policy or {}).get("timeout_ms") or 30000)
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
        # 强制接入 OpenSandbox：始终尝试初始化客户端；失败则启动失败并退出（不降级到其它底座）。
        try:
            from opensandbox.adapters.command_adapter import CommandsAdapter
            from opensandbox.adapters.filesystem_adapter import FilesystemAdapter
            from opensandbox.adapters.sandboxes_adapter import SandboxesAdapter
            from opensandbox.config.connection import ConnectionConfig
            from opensandbox.constants import DEFAULT_EXECD_PORT
            from opensandbox.models.execd import RunCommandOpts
            from opensandbox.models.sandboxes import Host, SandboxEndpoint, SandboxImageSpec, Volume

            class _SDKClient:
                @staticmethod
                def _normalize_domain(raw_domain: str) -> str:
                    d = (raw_domain or "").strip().strip('"').strip("'")
                    if not d:
                        return ""
                    # 用户常把完整 URL 填到 domain（如 http://127.0.0.1:8091/）
                    # ConnectionConfig.domain 期望 host[:port]，这里做容错归一化。
                    if "://" in d:
                        p = urlparse(d)
                        d = p.netloc or p.path
                    d = d.strip().strip("/")
                    if "/" in d:
                        d = d.split("/", 1)[0]
                    return d

                def __init__(self):
                    raw_domain = (os.getenv("OPENSANDBOX_DOMAIN") or os.getenv("OPEN_SANDBOX_DOMAIN") or "").strip()
                    domain = self._normalize_domain(raw_domain)
                    api_key = (os.getenv("OPENSANDBOX_API_KEY") or os.getenv("OPEN_SANDBOX_API_KEY") or "").strip() or None
                    protocol = (os.getenv("OPENSANDBOX_PROTOCOL") or os.getenv("OPEN_SANDBOX_PROTOCOL") or "http").strip()
                    if not domain:
                        raise RuntimeError(
                            "缺少 OpenSandbox domain：请设置 OPENSANDBOX_DOMAIN（或 OPEN_SANDBOX_DOMAIN）。"
                        )
                    if protocol not in {"http", "https"}:
                        protocol = "http"
                    # 关键：本地/compose 场景下，execd endpoint 可能返回容器内不可解析主机名。
                    # 统一走 server proxy 可避免 host 解析失败（nodename nor servname provided）。
                    self._conn = ConnectionConfig(
                        api_key=api_key,
                        domain=domain,
                        protocol=protocol,
                        use_server_proxy=True,
                    )
                    logger.info("opensandbox_connection_target=%s://%s proxy=%s", protocol, domain, True)
                    self._sandboxes = SandboxesAdapter(self._conn)
                    self._execd_port = int(DEFAULT_EXECD_PORT)
                    self._RunCommandOpts = RunCommandOpts
                    self._SandboxImageSpec = SandboxImageSpec
                    self._Volume = Volume
                    self._Host = Host
                    self._SandboxEndpoint = SandboxEndpoint
                    self._commands: Dict[str, CommandsAdapter] = {}
                    self._fs: Dict[str, FilesystemAdapter] = {}

                async def _ensure_execd(self, sandbox_id: str) -> tuple[CommandsAdapter, FilesystemAdapter]:
                    if sandbox_id in self._commands and sandbox_id in self._fs:
                        return self._commands[sandbox_id], self._fs[sandbox_id]
                    endpoint = await self._sandboxes.get_sandbox_endpoint(
                        sandbox_id=sandbox_id, port=self._execd_port, use_server_proxy=self._conn.use_server_proxy
                    )
                    logger.info(
                        "opensandbox_execd_endpoint sandbox_id=%s endpoint=%s:%s proxy=%s",
                        sandbox_id,
                        getattr(endpoint, "host", ""),
                        getattr(endpoint, "port", ""),
                        self._conn.use_server_proxy,
                    )
                    cmd = CommandsAdapter(self._conn, endpoint)
                    fs = FilesystemAdapter(self._conn, endpoint)
                    self._commands[sandbox_id] = cmd
                    self._fs[sandbox_id] = fs
                    return cmd, fs

                async def create_sandbox(self, spec: Dict[str, Any]) -> Dict[str, Any]:
                    image_ref = (spec.get("base_image_ref") or "").strip() or "ubuntu:22.04"
                    mounts = list(spec.get("mounts") or [])
                    volumes = []
                    for i, m in enumerate(mounts):
                        if str(m.get("type") or "") not in {"host_path", "hostpath", "host"}:
                            continue
                        src = str(m.get("source") or "").strip()
                        tgt = str(m.get("target") or "").strip()
                        if not src or not tgt:
                            continue
                        ro = bool(m.get("read_only"))
                        volumes.append(
                            self._Volume(
                                name=f"v{i}",
                                host=self._Host(path=src),
                                mountPath=tgt,
                                readOnly=ro,
                            )
                        )
                    # OpenSandbox lifecycle API 对 entrypoint 有校验，不能为空；
                    # 这里使用稳定的长驻命令，后续命令执行通过 execd 完成。
                    entrypoint = ["/bin/sh", "-lc", "while true; do sleep 3600; done"]
                    timeout_s = int(spec.get("timeout_s") or 3600)
                    created = await self._sandboxes.create_sandbox(
                        spec=self._SandboxImageSpec(image=image_ref),
                        entrypoint=entrypoint,
                        env=dict(spec.get("env") or {}),
                        metadata={},
                        timeout=timedelta(seconds=max(60, timeout_s)),
                        resource={"cpu": str(spec.get("resource_limit", {}).get("cpu") or "1000m"),
                                  "memory": str(spec.get("resource_limit", {}).get("memory_mb") or "1024") + "Mi"},
                        network_policy=None,
                        extensions={},
                        volumes=volumes or None,
                    )
                    return {"id": getattr(created, "id", None) or str(created)}

                async def execute_command(self, sandbox_id: str, req: Dict[str, Any]) -> Dict[str, Any]:
                    cmd, _fs = await self._ensure_execd(sandbox_id)
                    argv = req.get("command")
                    if not isinstance(argv, list):
                        raise ValueError("command must be argv list")
                    command = " ".join(shlex.quote(str(x)) for x in argv)
                    opts = self._RunCommandOpts(
                        background=False,
                        working_directory=str(req.get("cwd") or "/workspace"),
                        timeout=timedelta(milliseconds=int(req.get("timeout_ms") or 120_000)),
                        envs=dict(req.get("env") or {}),
                    )
                    exe = await cmd.run(command, opts=opts)
                    stdout = "\n".join([m.text for m in (getattr(getattr(exe, "logs", None), "stdout", None) or [])])
                    stderr = "\n".join([m.text for m in (getattr(getattr(exe, "logs", None), "stderr", None) or [])])
                    return {
                        "exit_code": getattr(exe, "exit_code", None),
                        "stdout": stdout,
                        "stderr": stderr,
                        "id": getattr(exe, "id", None),
                        "complete": bool(getattr(exe, "complete", None)),
                    }

                async def read_file(self, sandbox_id: str, path: str) -> bytes:
                    _cmd, fs = await self._ensure_execd(sandbox_id)
                    return await fs.read_bytes(path)

                async def write_file(self, sandbox_id: str, path: str, data: bytes) -> Dict[str, Any]:
                    _cmd, fs = await self._ensure_execd(sandbox_id)
                    await fs.write_file(path, data)
                    return {"status": "ok", "path": path, "bytes": len(data)}

                async def list_files(self, sandbox_id: str, root: str) -> List[Dict[str, Any]]:
                    _cmd, fs = await self._ensure_execd(sandbox_id)
                    # Execd 文件系统 API 没有“递归 list”统一接口；这里用 search('*') 近似实现。
                    try:
                        from opensandbox.models.filesystem import SearchEntry

                        items = await fs.search(SearchEntry(path=root, pattern="*", recursive=True))
                        out: List[Dict[str, Any]] = []
                        for it in items or []:
                            out.append(
                                {
                                    "path": str(getattr(it, "path", "")).replace("\\", "/"),
                                    "size": getattr(it, "size", None),
                                    "is_dir": getattr(it, "is_dir", False),
                                }
                            )
                        return out
                    except Exception:
                        return []

                async def dispose_sandbox(self, sandbox_id: str) -> None:
                    try:
                        await self._sandboxes.kill_sandbox(sandbox_id)
                    finally:
                        self._commands.pop(sandbox_id, None)
                        self._fs.pop(sandbox_id, None)

            return _SDKClient()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "无法初始化 OpenSandbox 客户端：请安装/配置 OpenSandbox。\n"
                "- 需安装 opensandbox Python SDK（你已安装）。\n"
                "- 需配置 OPENSANDBOX_DOMAIN（或 OPEN_SANDBOX_DOMAIN），以及可选 OPENSANDBOX_API_KEY。\n"
                f"原始错误: {e}"
            ) from e

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
            "base_image_ref": policy.base_image_ref,
            "dep_hash": policy.dep_hash,
            "env": dict(policy.environment or {}),
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
                "dep_hash": policy.dep_hash,
            },
        )

    async def run_tool_in_sandbox(self, handle: SandboxHandle, tool_request: Dict[str, Any]) -> Dict[str, Any]:
        policy = handle.metadata.get("policy") if isinstance(handle.metadata, dict) else None
        req_name = str(tool_request.get("tool_name") or "").strip()
        allowlist = list((policy or {}).get("tool_allowlist") or [])
        if allowlist and req_name and req_name not in allowlist:
            raise PermissionError(f"tool not allowed by sandbox policy: {req_name}")
        timeout_ms = int(tool_request.get("timeout_ms") or (policy or {}).get("timeout_ms") or 30000)
        cmd = tool_request.get("command")
        if cmd is not None:
            payload = tool_request.get("payload") or {}
            req = {
                "tool_name": req_name or "unknown_tool",
                "tool_kind": str(tool_request.get("tool_kind") or "tool"),
                "payload": payload if isinstance(payload, dict) else {"value": payload},
                "timeout_ms": timeout_ms,
                "cwd": str(tool_request.get("cwd") or "/workspace"),
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
        cwd: str = "/workspace",
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
