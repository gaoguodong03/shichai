"""OpenSandbox SDK runtime client used by SandboxAdapter."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shlex
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


logger = logging.getLogger("app.agent.sandbox_adapter")
_OPENSANDBOX_METADATA_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def opensandbox_metadata_value(value: Any) -> str:
    raw = str(value or "").strip()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    cleaned = _OPENSANDBOX_METADATA_INVALID_CHARS.sub("_", raw).strip("._-")
    if not cleaned:
        return f"v{digest}"
    if len(cleaned) > 63:
        suffix = f"-{digest}"
        cleaned = cleaned[: 63 - len(suffix)].rstrip("._-")
        if not cleaned:
            return f"v{digest}"
        cleaned = f"{cleaned}{suffix}"
    return cleaned


def opensandbox_metadata(metadata: Dict[str, Any]) -> Dict[str, str]:
    return {
        str(k): opensandbox_metadata_value(v)
        for k, v in dict(metadata or {}).items()
    }


class OpenSandboxRuntimeClient:
    """Thin wrapper over the OpenSandbox Python SDK and its connection retry rules."""

    @staticmethod
    def _normalize_domain(raw_domain: str) -> str:
        d = (raw_domain or "").strip().strip('"').strip("'")
        if not d:
            return ""
        if "://" in d:
            p = urlparse(d)
            d = p.netloc or p.path
        d = d.strip().strip("/")
        if "/" in d:
            d = d.split("/", 1)[0]
        return d

    def __init__(self):
        from opensandbox.adapters.command_adapter import CommandsAdapter
        from opensandbox.adapters.filesystem_adapter import FilesystemAdapter
        from opensandbox.adapters.sandboxes_adapter import SandboxesAdapter
        from opensandbox.config.connection import ConnectionConfig
        from opensandbox.constants import DEFAULT_EXECD_PORT
        from opensandbox.models.execd import RunCommandOpts
        from opensandbox.models.sandboxes import Host, SandboxEndpoint, SandboxImageSpec, Volume

        raw_domain = (os.getenv("OPENSANDBOX_DOMAIN") or os.getenv("OPEN_SANDBOX_DOMAIN") or "").strip()
        domain = self._normalize_domain(raw_domain)
        api_key = (os.getenv("OPENSANDBOX_API_KEY") or os.getenv("OPEN_SANDBOX_API_KEY") or "").strip() or None
        protocol = (os.getenv("OPENSANDBOX_PROTOCOL") or os.getenv("OPEN_SANDBOX_PROTOCOL") or "http").strip()
        request_timeout_sec = int((os.getenv("OPENSANDBOX_REQUEST_TIMEOUT_SEC") or "900").strip() or "900")
        if not domain:
            raise RuntimeError("缺少 OpenSandbox domain：请设置 OPENSANDBOX_DOMAIN（或 OPEN_SANDBOX_DOMAIN）。")
        if protocol not in {"http", "https"}:
            protocol = "http"
        proxy_raw = (
            os.getenv("OPENSANDBOX_USE_SERVER_PROXY")
            or os.getenv("OPEN_SANDBOX_USE_SERVER_PROXY")
            or "1"
        ).strip().lower()
        use_server_proxy = proxy_raw in {"1", "true", "yes", "on", "enabled"}
        self._conn = ConnectionConfig(
            api_key=api_key,
            domain=domain,
            protocol=protocol,
            request_timeout=timedelta(seconds=max(30, request_timeout_sec)),
            use_server_proxy=use_server_proxy,
        )
        self._api_key = api_key
        self._domain = domain
        self._protocol = protocol
        self._request_timeout_sec = max(30, request_timeout_sec)
        logger.info("opensandbox_connection_target=%s://%s proxy=%s", protocol, domain, use_server_proxy)
        self._sandboxes = SandboxesAdapter(self._conn)
        self._execd_port = int(DEFAULT_EXECD_PORT)
        self._RunCommandOpts = RunCommandOpts
        self._SandboxImageSpec = SandboxImageSpec
        self._Volume = Volume
        self._Host = Host
        self._SandboxEndpoint = SandboxEndpoint
        self._CommandsAdapter = CommandsAdapter
        self._FilesystemAdapter = FilesystemAdapter
        self._SandboxesAdapter = SandboxesAdapter
        self._ConnectionConfig = ConnectionConfig
        self._commands: Dict[str, Any] = {}
        self._fs: Dict[str, Optional[Any]] = {}

    def _lifecycle_fallback_domains(self) -> list[str]:
        raw = (os.getenv("OPENSANDBOX_FALLBACK_DOMAINS") or "").strip()
        out = [self._normalize_domain(x) for x in raw.split(",") if self._normalize_domain(x)]
        domain = self._normalize_domain(str(getattr(self, "_domain", "") or ""))
        fallback_port = domain.rsplit(":", 1)[-1] if ":" in domain else (os.getenv("OPENSANDBOX_HOST_PORT") or "8091")
        in_container = Path("/.dockerenv").exists()
        if domain.startswith("host.docker.internal:") and not Path("/.dockerenv").exists():
            out.append("127.0.0.1:" + fallback_port)
        if in_container and (domain.startswith("127.0.0.1:") or domain.startswith("localhost:")):
            out.append("host.docker.internal:" + fallback_port)
        if not domain.startswith(("127.0.0.1:", "localhost:", "host.docker.internal:")):
            out.append("127.0.0.1:" + fallback_port)
            if in_container:
                out.append("host.docker.internal:" + fallback_port)
        if not in_container:
            out = [d for d in out if not d.startswith("host.docker.internal:")]
        return list(dict.fromkeys([d for d in out if d and d != domain]))

    @staticmethod
    def _is_lifecycle_connect_error(err: Exception) -> bool:
        msg = str(err or "").lower()
        return (
            "connecterror" in msg
            or "all connection attempts failed" in msg
            or "connection refused" in msg
            or "nodename nor servname provided" in msg
            or "name or service not known" in msg
            or "temporary failure in name resolution" in msg
            or "no address associated with hostname" in msg
        )

    def _switch_lifecycle_domain(self, domain: str) -> None:
        domain = self._normalize_domain(domain)
        self._conn = self._ConnectionConfig(
            api_key=getattr(self, "_api_key", None),
            domain=domain,
            protocol=getattr(self, "_protocol", "http") or "http",
            request_timeout=timedelta(seconds=int(getattr(self, "_request_timeout_sec", 900) or 900)),
            use_server_proxy=bool(self._conn.use_server_proxy),
        )
        self._domain = domain
        self._sandboxes = self._SandboxesAdapter(self._conn)
        self._commands.clear()
        self._fs.clear()
        logger.warning(
            "opensandbox_lifecycle_domain_switched target=%s://%s proxy=%s",
            getattr(self, "_protocol", "http") or "http",
            domain,
            bool(self._conn.use_server_proxy),
        )

    @staticmethod
    def _is_endpoint_valid(ep: Any) -> bool:
        endpoint_str = str(getattr(ep, "endpoint", "") or "").strip()
        if endpoint_str:
            return True
        h = str(getattr(ep, "host", "") or "").strip()
        p = getattr(ep, "port", None)
        return bool(h and h != ":" and p)

    @staticmethod
    def _endpoint_str(ep: Any) -> str:
        return str(getattr(ep, "endpoint", "") or "").strip()

    @staticmethod
    def _rewrite_endpoint_for_local_host(ep: Any) -> Any:
        if Path("/.dockerenv").exists():
            return ep
        enabled = (os.getenv("OPENSANDBOX_REWRITE_HOST_DOCKER_INTERNAL") or "1").strip().lower()
        if enabled not in {"1", "true", "yes", "on", "enabled"}:
            return ep
        replacement = (os.getenv("OPENSANDBOX_LOCAL_ENDPOINT_HOST") or "127.0.0.1").strip() or "127.0.0.1"
        endpoint_str = str(getattr(ep, "endpoint", "") or "").strip()
        if endpoint_str.startswith("host.docker.internal:"):
            rewritten = replacement + ":" + endpoint_str.rsplit(":", 1)[-1]
            try:
                setattr(ep, "endpoint", rewritten)
            except Exception:
                try:
                    object.__setattr__(ep, "endpoint", rewritten)
                except Exception:
                    pass
        host = str(getattr(ep, "host", "") or "").strip()
        if host == "host.docker.internal":
            try:
                setattr(ep, "host", replacement)
            except Exception:
                try:
                    object.__setattr__(ep, "host", replacement)
                except Exception:
                    pass
        return ep

    @staticmethod
    def _is_retryable_stream_error(err: Exception) -> bool:
        s = str(err or "").lower()
        return (
            "remoteprotocolerror" in s
            or "incomplete chunked read" in s
            or "peer closed connection without sending complete message body" in s
        )

    @staticmethod
    def _is_retryable_connect_error(err: Exception) -> bool:
        s = str(err or "").lower()
        return (
            "connecterror" in s
            or "all connection attempts failed" in s
            or "connection refused" in s
            or "could not connect to the backend sandbox endpoint" in s
            or "nodename nor servname provided" in s
            or "temporary failure in name resolution" in s
        )

    def _switch_command_proxy_mode(self, sandbox_id: str) -> bool:
        try:
            current = bool(self._conn.use_server_proxy)
            self._conn.use_server_proxy = not current
        except Exception:
            return False
        self._commands.pop(sandbox_id, None)
        self._fs.pop(sandbox_id, None)
        logger.warning("opensandbox_command_proxy_switched sandbox_id=%s proxy=%s", sandbox_id, bool(self._conn.use_server_proxy))
        return True

    async def _ensure_cmd_and_fs(self, sandbox_id: str) -> tuple[Any, Optional[Any], bool]:
        if sandbox_id in self._commands and sandbox_id in self._fs:
            fs = self._fs.get(sandbox_id)
            return self._commands[sandbox_id], fs, bool(fs)

        async def _get_endpoint(use_proxy: bool):
            return await self._sandboxes.get_sandbox_endpoint(
                sandbox_id=sandbox_id,
                port=self._execd_port,
                use_server_proxy=use_proxy,
            )

        endpoint = await _get_endpoint(bool(self._conn.use_server_proxy))
        proxy_used = bool(self._conn.use_server_proxy)
        if not self._is_endpoint_valid(endpoint):
            logger.warning(
                "opensandbox_execd_endpoint_empty sandbox_id=%s proxy=%s; retry_with_proxy=%s",
                sandbox_id,
                bool(self._conn.use_server_proxy),
                (not bool(self._conn.use_server_proxy)),
            )
            proxy_used = not bool(self._conn.use_server_proxy)
            endpoint = await _get_endpoint(proxy_used)
            if self._is_endpoint_valid(endpoint):
                try:
                    self._conn.use_server_proxy = proxy_used
                except Exception:
                    pass

        endpoint = self._rewrite_endpoint_for_local_host(endpoint)
        endpoint_ok = self._is_endpoint_valid(endpoint)
        logger.info(
            "opensandbox_execd_endpoint sandbox_id=%s endpoint=%s proxy=%s endpoint_ok=%s",
            sandbox_id,
            self._endpoint_str(endpoint),
            proxy_used,
            endpoint_ok,
        )
        cmd = self._CommandsAdapter(self._conn, endpoint)
        fs = self._FilesystemAdapter(self._conn, endpoint) if endpoint_ok else None
        self._commands[sandbox_id] = cmd
        self._fs[sandbox_id] = fs
        return cmd, fs, endpoint_ok

    async def _ensure_execd(self, sandbox_id: str) -> tuple[Any, Any]:
        cmd, fs, ok = await self._ensure_cmd_and_fs(sandbox_id)
        if fs is None or not ok:
            raise RuntimeError(
                "OpenSandbox execd endpoint 为空（host/port 缺失），FilesystemAdapter 不可用。\n"
                "排查建议：\n"
                "- 若用 docker compose 启动 opensandbox-server：确保容器能解析 host.docker.internal（Linux 常需 extra_hosts: host.docker.internal:host-gateway）。\n"
                "- 检查 OpenSandbox 配置 docker.host_ip 是否设置为 host.docker.internal。\n"
                "- 如曾设置 OPENSANDBOX_USE_SERVER_PROXY=1，可尝试改为 0。\n"
            )
        return cmd, fs

    async def create_sandbox(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        image_ref = (
            str(spec.get("image_ref") or "").strip()
            or (os.getenv("SANDBOX_BASE_IMAGE") or "").strip()
            or "crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.11.1"
        )
        mounts = list(spec.get("mounts") or [])
        volumes = []
        for i, m in enumerate(mounts):
            if str(m.get("type") or "") not in {"host_path", "hostpath", "host"}:
                continue
            src = str(m.get("source") or "").strip()
            tgt = str(m.get("target") or "").strip()
            if not src or not tgt:
                continue
            volumes.append(
                self._Volume(
                    name=f"v{i}",
                    host=self._Host(path=src),
                    mountPath=tgt,
                    readOnly=bool(m.get("read_only")),
                )
            )
        entrypoint = ["/bin/sh", "-lc", "while true; do sleep 3600; done"]
        timeout_s = int(spec.get("timeout_s") or 3600)

        async def _do_create():
            return await self._sandboxes.create_sandbox(
                spec=self._SandboxImageSpec(image=image_ref),
                entrypoint=entrypoint,
                env=dict(spec.get("env") or {}),
                metadata=opensandbox_metadata(spec.get("metadata") or {}),
                timeout=timedelta(seconds=max(60, timeout_s)),
                resource={
                    "cpu": str(spec.get("resource_limit", {}).get("cpu") or "1000m"),
                    "memory": str(spec.get("resource_limit", {}).get("memory_mb") or "1024") + "Mi",
                },
                network_policy=None,
                extensions={},
                volumes=volumes or None,
            )

        try:
            created = await _do_create()
        except Exception as e:
            if not self._is_lifecycle_connect_error(e):
                raise
            fallback_domains = self._lifecycle_fallback_domains()
            logger.warning(
                "opensandbox_lifecycle_connect_failed target=%s://%s fallbacks=%s err=%s",
                getattr(self, "_protocol", "http") or "http",
                getattr(self, "_domain", ""),
                fallback_domains,
                str(e)[:500],
            )
            last_exc: Exception = e
            for fallback_domain in fallback_domains:
                try:
                    self._switch_lifecycle_domain(fallback_domain)
                    created = await _do_create()
                    break
                except Exception as retry_exc:
                    last_exc = retry_exc
                    logger.warning(
                        "opensandbox_lifecycle_fallback_failed target=%s://%s err=%s",
                        getattr(self, "_protocol", "http") or "http",
                        fallback_domain,
                        str(retry_exc)[:500],
                    )
            else:
                raise RuntimeError(
                    "OpenSandbox lifecycle API 连接失败；请检查 OPENSANDBOX_DOMAIN/OPENSANDBOX_HOST_PORT、"
                    "opensandbox-server 是否启动，以及当前进程是在宿主机还是容器内。"
                ) from last_exc
        return {"id": getattr(created, "id", None) or str(created)}

    @staticmethod
    def _sandbox_info_to_dict(info: Any) -> Dict[str, Any]:
        image = getattr(info, "image", None)
        status = getattr(info, "status", None)
        created_at = getattr(info, "created_at", None)
        return {
            "id": str(getattr(info, "id", "") or ""),
            "status": str(getattr(status, "value", status) or ""),
            "image_ref": str(getattr(image, "image", "") or ""),
            "metadata": dict(getattr(info, "metadata", None) or {}),
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or ""),
        }

    async def list_sandboxes(self, *, page: int = 1, page_size: int = 100) -> Dict[str, Any]:
        from opensandbox.models.sandboxes import SandboxFilter

        paged = await self._sandboxes.list_sandboxes(
            SandboxFilter(page=max(1, int(page)), page_size=max(1, min(500, int(page_size))))
        )
        pagination = getattr(paged, "pagination", None)
        return {
            "items": [
                self._sandbox_info_to_dict(info)
                for info in list(getattr(paged, "sandbox_infos", None) or [])
            ],
            "has_next_page": bool(getattr(pagination, "has_next_page", False)),
            "page": int(getattr(pagination, "page", page) or page),
            "total_items": int(getattr(pagination, "total_items", 0) or 0),
        }

    async def execute_command(self, sandbox_id: str, req: Dict[str, Any]) -> Dict[str, Any]:
        argv = req.get("command")
        if not isinstance(argv, list):
            raise ValueError("command must be argv list")
        command = " ".join(shlex.quote(str(x)) for x in argv)
        opts = self._RunCommandOpts(
            background=False,
            working_directory=str(req.get("cwd") or "/"),
            timeout=timedelta(milliseconds=int(req.get("timeout_ms") or 120_000)),
            envs=dict(req.get("env") or {}),
        )
        last_error: Exception | None = None
        switched_proxy = False
        for attempt in (1, 2, 3):
            try:
                cmd, _fs, _ok = await self._ensure_cmd_and_fs(sandbox_id)
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
            except Exception as e:
                last_error = e
                if not switched_proxy and self._is_retryable_connect_error(e) and self._switch_command_proxy_mode(sandbox_id):
                    switched_proxy = True
                    logger.warning("opensandbox_command_connect_failed_retry_with_proxy_toggle sandbox_id=%s err=%s", sandbox_id, str(e)[:500])
                    await asyncio.sleep(0.2)
                    continue
                if attempt < 3 and self._is_retryable_stream_error(e):
                    logger.warning("opensandbox_command_stream_interrupted sandbox_id=%s; retry_once=true err=%s", sandbox_id, e)
                    self._commands.pop(sandbox_id, None)
                    self._fs.pop(sandbox_id, None)
                    await asyncio.sleep(0.2)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("execute_command failed with unknown error")

    async def read_file(self, sandbox_id: str, path: str) -> bytes:
        _cmd, fs = await self._ensure_execd(sandbox_id)
        return await fs.read_bytes(path)

    async def write_file(self, sandbox_id: str, path: str, data: bytes) -> Dict[str, Any]:
        _cmd, fs = await self._ensure_execd(sandbox_id)
        await fs.write_file(path, data)
        return {"status": "ok", "path": path, "bytes": len(data)}

    async def list_files(self, sandbox_id: str, root: str) -> List[Dict[str, Any]]:
        _cmd, fs = await self._ensure_execd(sandbox_id)
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
        except Exception as e:
            msg = str(e).lower()
            if "not found" not in msg:
                raise
        finally:
            self._commands.pop(sandbox_id, None)
            self._fs.pop(sandbox_id, None)
