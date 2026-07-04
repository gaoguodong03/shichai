"""
MCP Server 管理器：规范、轻量的调用方式。

- stdio 类 MCP 的 Python 入口脚本位于同包下 `stdio/`（如 `stdio_json_filter.py`、`file_reader_mcp.py`），工具资源的 transport.args 中写相对 backend 的路径，例如 `app/mcp/stdio/file_reader_mcp.py`。
- 多用户：每个用户名对应独立的 MCPToolManager 实例与连接，配置来自 data/users/{user}/resources/tools/{tool}/tool.json。
- 生命周期：进程退出时在 lifespan 内 cleanup_all_mcp_runtimes；单用户配置变更时可 dispose 该用户实例。
- 调用方式：Tool.func 为异步函数，直接 session.call_tool；由 graph/agent 侧 await。
"""
import os
import re
import json
import logging
import asyncio
import hashlib
import threading
import time
from typing import List, Dict, Any, Optional
from contextlib import AsyncExitStack
from urllib.parse import urlsplit, urlunsplit

from app.agent.tool_spec import ToolSpec

logger = logging.getLogger(__name__)

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError as e:
    ClientSession = Any  # type: ignore
    StdioServerParameters = Any  # type: ignore
    stdio_client = None  # type: ignore
    logger.error(f"MCP SDK not found: {e}")
    print("Please install MCP SDK: pip install mcp")
    print("Or from GitHub: pip install git+https://github.com/modelcontextprotocol/python-sdk.git")

# HTTP/Streamable HTTP 为可选依赖，仅在配置了远程 Server 时使用
_streamable_http_available = False
try:
    from mcp.client.streamable_http import streamable_http_client
    import httpx
    _streamable_http_available = True
except ImportError:
    pass

_mcp_user_lock = threading.Lock()
_mcp_by_user: Dict[str, "MCPToolManager"] = {}
_mcp_call_locks_guard = threading.Lock()
_mcp_call_locks: Dict[int, asyncio.Lock] = {}
_MODEL_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _model_tool_slug(raw: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(raw or "")).strip("_-")


def _safe_mcp_model_tool_name(server_name: Optional[str], tool_name: str) -> str:
    """Return a model-safe function name while preserving original names in metadata."""
    raw_server = str(server_name or "").strip()
    raw_tool = str(tool_name or "").strip()
    server_slug = _model_tool_slug(raw_server)
    tool_slug = _model_tool_slug(raw_tool)
    readable = "_".join(part for part in (server_slug, tool_slug) if part) or "tool"
    suffix = hashlib.sha1(f"{raw_server}\0{raw_tool}".encode("utf-8")).hexdigest()[:8]
    max_readable = max(1, 64 - len("mcp__") - len(suffix))
    readable = readable[:max_readable].strip("_-") or "tool"
    alias = f"mcp_{readable}_{suffix}"
    if not _MODEL_TOOL_NAME_RE.fullmatch(alias):
        return f"mcp_tool_{suffix}"
    return alias


def _get_mcp_call_lock(session: ClientSession) -> asyncio.Lock:
    key = id(session)
    with _mcp_call_locks_guard:
        lock = _mcp_call_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _mcp_call_locks[key] = lock
        return lock


def _looks_like_closed_resource_error(err: str) -> bool:
    s = str(err or "").strip()
    if not s:
        return False
    low = s.lower()
    return ("closedresourceerror" in low) or ("resource closed" in low)


def _exception_detail(exc: BaseException) -> str:
    msg = str(exc)
    parts = [
        f"type={exc.__class__.__name__}",
        f"message={msg if msg.strip() else '<empty>'}",
        f"repr={repr(exc)}",
    ]
    cause = getattr(exc, "__cause__", None)
    context = getattr(exc, "__context__", None)
    if cause is not None:
        cause_msg = str(cause)
        parts.append(
            f"cause={cause.__class__.__name__}:{cause_msg if cause_msg.strip() else '<empty>'}"
        )
    elif context is not None:
        context_msg = str(context)
        parts.append(
            f"context={context.__class__.__name__}:{context_msg if context_msg.strip() else '<empty>'}"
        )
    return " ".join(parts)


def _looks_like_retryable_mcp_call_error(err: str) -> bool:
    s = str(err or "").strip()
    if not s:
        return False
    if _looks_like_closed_resource_error(s):
        return True
    low = s.lower()
    retry_markers = (
        "cancelled",
        "remote stream ended",
        "remoteprotocolerror",
        "incomplete chunked read",
        "peer closed connection",
        "connection reset",
        "connection aborted",
        "stream reset",
        "type=runtimeerror message=<empty>",
        "runtimeerror()",
    )
    return any(marker in low for marker in retry_markers)


def _looks_like_protocol_mismatch_error(err: str) -> bool:
    s = str(err or "").strip().lower()
    if not s:
        return False
    return ("invalid response format" in s) or ("parse error" in s) or ("invalid json-rpc" in s)


def _redact_mcp_url(raw_url: Any) -> str:
    raw = str(raw_url or "").strip()
    if not raw:
        return "<empty>"
    try:
        parts = urlsplit(raw)
    except Exception:
        return raw.split("?", 1)[0].split("#", 1)[0] or "<invalid>"
    if not parts.scheme or not parts.netloc:
        return raw.split("?", 1)[0].split("#", 1)[0] or "<invalid>"
    host = parts.hostname or ""
    if not host:
        return "<invalid>"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "", "", ""))


def _mcp_connection_log_context(
    server_name: str,
    config: Dict[str, Any],
    *,
    transport: Optional[Dict[str, Any]] = None,
    url: Optional[str] = None,
    headers: Optional[Dict[str, Any]] = None,
) -> str:
    transport_cfg = transport if isinstance(transport, dict) else config.get("transport", {})
    if not isinstance(transport_cfg, dict):
        transport_cfg = {}
    raw_headers = headers if isinstance(headers, dict) else transport_cfg.get("headers")
    header_names = sorted(str(k) for k in (raw_headers or {}).keys())
    raw_url = url if url is not None else (transport_cfg.get("url") or transport_cfg.get("base_url") or "")
    parts = [
        f"server_name={server_name}",
        f"name={str(config.get('name') or '').strip() or '<unnamed>'}",
        f"transport={str(transport_cfg.get('type') or 'stdio').strip() or 'stdio'}",
    ]
    if raw_url:
        parts.append(f"url={_redact_mcp_url(raw_url)}")
    if header_names:
        parts.append(f"headers={','.join(header_names)}")
    return " ".join(parts)


def _server_key(config: Dict[str, Any]) -> str:
    return str((config or {}).get("name") or "").strip()


def _transport_from_server_config(config: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(config.get("transport"), dict):
        return dict(config.get("transport") or {})
    raw = str(config.get("server_config") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    servers = parsed.get("mcpServers") if isinstance(parsed, dict) else None
    if not isinstance(servers, dict) or not servers:
        return {}
    name = _server_key(config)
    selected = servers.get(name) if name else None
    if not isinstance(selected, dict):
        selected = next((item for item in servers.values() if isinstance(item, dict)), {})
    transport = dict(selected or {})
    if "type" not in transport:
        if transport.get("command"):
            transport["type"] = "stdio"
        elif transport.get("url"):
            transport["type"] = "sse"
        elif transport.get("base_url"):
            transport["type"] = "streamable_http"
    return transport


def normalize_mcp_kwargs_for_call(
    server_name: Optional[str],
    original_tool_name: str,
    kwargs: Dict[str, Any],
    input_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    规范化 MCP 工具调用参数。委托给 tool_arg_normalizers，便于 manager/chat 复用同一逻辑。
    """
    from app.mcp.tool_arg_normalizers import normalize_mcp_tool_kwargs
    return normalize_mcp_tool_kwargs(server_name, original_tool_name, kwargs, input_schema)


async def execute_mcp_call(
    *,
    server_name: str,
    tool_name: str,
    kwargs: Dict[str, Any],
    session: ClientSession,
    timeout_sec: Optional[float] = None,
) -> tuple[bool, Any, str]:
    """Execute a single MCP tool call directly through the MCP session.

    MCP calls are not sandbox commands. They may talk to remote Streamable HTTP
    servers or stdio subprocesses owned by the MCP manager, so keep timeout,
    serialization, and error formatting in this layer instead of routing them
    through the OpenSandbox tool gateway.
    """
    def _resolve_timeout_sec(raw: Optional[float]) -> Optional[float]:
        """
        MCP 工具超时：
        - raw 显式传入时优先
        - 否则读取环境变量 MCP_TOOL_TIMEOUT_SEC
        - 未设置时沿用 MCP_TOOL_TIMEOUT_FALLBACK_MS，避免远端 MCP 永久挂起
        """
        if raw is not None:
            try:
                v = float(raw)
            except Exception:
                return None
            return None if v <= 0 else v
        env = (os.getenv("MCP_TOOL_TIMEOUT_SEC") or "").strip()
        if env:
            try:
                v = float(env)
            except Exception:
                v = 0.0
            if v > 0:
                return v
        fallback_ms = (os.getenv("MCP_TOOL_TIMEOUT_FALLBACK_MS") or "3600000").strip()
        try:
            fallback = int(fallback_ms)
        except Exception:
            fallback = 3_600_000
        return None if fallback <= 0 else max(1.0, fallback / 1000.0)

    resolved_timeout_sec = _resolve_timeout_sec(timeout_sec)
    try:
        lock = _get_mcp_call_lock(session)
        async with lock:
            if resolved_timeout_sec is None:
                result = await session.call_tool(tool_name, kwargs)
            else:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, kwargs), timeout=resolved_timeout_sec
                )
        return True, result, ""
    except asyncio.TimeoutError:
        timeout_label = resolved_timeout_sec if resolved_timeout_sec is not None else "none"
        return (
            False,
            None,
            f"MCP tool timeout: server={server_name} tool={tool_name} timeout_sec={timeout_label}",
        )
    except asyncio.CancelledError as e:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise
        detail = _exception_detail(e)
        logger.warning("MCP tool call cancelled server=%s tool=%s %s", server_name, tool_name, detail)
        return False, None, f"MCP tool cancelled: server={server_name} tool={tool_name} {detail}"
    except Exception as e:  # noqa: BLE001
        detail = _exception_detail(e)
        logger.warning("MCP tool call failed server=%s tool=%s %s", server_name, tool_name, detail, exc_info=True)
        return False, None, f"MCP tool call failed: server={server_name} tool={tool_name} {detail}"


def _subst_mcp_placeholders(val: str, secrets: Optional[Dict[str, str]] = None) -> str:
    """${vault:标识} 显式引用密钥库；${VAR} 优先环境变量，未设置时再尝试同标识的密钥库条目（与 .env 中 EXA_API_KEY 等写法兼容）。"""
    secrets = secrets or {}
    s = str(val)

    def repl_vault(m: re.Match) -> str:
        return secrets.get(m.group(1), "")

    def repl_env(m: re.Match) -> str:
        name = m.group(1)
        v = os.environ.get(name, "")
        if v:
            return v
        return secrets.get(name, "")

    s = re.sub(r"\$\{vault:([A-Za-z0-9_-]+)\}", repl_vault, s)
    s = re.sub(r"\$\{(\w+)\}", repl_env, s)
    return s


def _missing_mcp_placeholders(val: Any, secrets: Optional[Dict[str, str]] = None) -> List[str]:
    """Return unresolved placeholder names before substituting them into transport config."""
    secrets = secrets or {}
    s = str(val or "")
    missing: List[str] = []

    for match in re.finditer(r"\$\{vault:([A-Za-z0-9_-]+)\}", s):
        name = match.group(1)
        if not secrets.get(name):
            missing.append(f"vault:{name}")

    for match in re.finditer(r"\$\{(\w+)\}", s):
        name = match.group(1)
        if not os.environ.get(name) and not secrets.get(name):
            missing.append(name)

    return missing


def _build_stdio_child_env(
    *,
    username: Optional[str],
    raw_env: Optional[Dict[str, Any]],
    secrets: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, str]]:
    """Build stdio MCP child env, including the stable user identity.

    Stdio MCP servers run in a separate process, so request ContextVars are not
    available there. Pass the resolved stable user id explicitly so tools that
    write workspace files do not fall back to the anonymous ``free4inno`` root.
    """
    should_create = bool(raw_env) or bool((username or "").strip())
    if not should_create:
        return None

    env: Dict[str, str] = {k: str(v) for k, v in os.environ.items()}
    if isinstance(raw_env, dict):
        env.update({str(k): _subst_mcp_placeholders(str(v), secrets) for k, v in raw_env.items()})

    uname = (username or "").strip()
    if uname:
        try:
            from app.core.user_context import get_user_context_for

            ctx = get_user_context_for(uname)
            env["ST49_MCP_USER_ID"] = ctx.user_id or uname
            env["ST49_MCP_USERNAME"] = ctx.username or uname
        except Exception:
            logger.warning("mcp_stdio_user_env_resolve_failed username=%s", uname, exc_info=True)
            env["ST49_MCP_USER_ID"] = uname
            env["ST49_MCP_USERNAME"] = uname

    return env


def _load_user_mcp_resource_configs(username: str) -> List[Dict[str, Any]]:
    from app.core.user_context import get_user_context_for
    from app.core.name_based_resources import normalize_tool_row

    uname = (username or "").strip()
    if not uname:
        raise ValueError("username required for MCP resources")
    root = get_user_context_for(uname).tools_dir.resolve()
    rows: List[Dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        body = child / "tool.json"
        if not body.is_file():
            continue
        try:
            parsed = json.loads(body.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                rows.append(normalize_tool_row(parsed))
        except Exception:
            logger.warning("load mcp tool resource failed: %s", body, exc_info=True)
    return rows


def get_mcp_manager_for_user(username: str) -> "MCPToolManager":
    """按用户名返回独立的 MCP 管理器（尚未加载配置时 server_configs 可能为空）。"""
    uname = (username or "").strip()
    if not uname:
        raise ValueError("username required for MCP runtime")
    with _mcp_user_lock:
        mgr = _mcp_by_user.get(uname)
        if mgr is None:
            mgr = MCPToolManager(username=uname)
            _mcp_by_user[uname] = mgr
        return mgr


async def ensure_user_mcp_bootstrapped(username: str) -> "MCPToolManager":
    """加载该用户 resources/tools，并对非 lazy 的 Server 建立连接（幂等）。"""
    mgr = get_mcp_manager_for_user(username)
    if getattr(mgr, "_mcp_boot_done", False):
        return mgr
    async with mgr._bootstrap_lock:
        if getattr(mgr, "_mcp_boot_done", False):
            return mgr
        await mgr.initialize_all()
        setattr(mgr, "_mcp_boot_done", True)
        setattr(mgr, "_mcp_config_loaded", True)
        return mgr


async def ensure_user_mcp_config_loaded(username: str) -> "MCPToolManager":
    """仅加载该用户 resources/tools，不主动连接任何 MCP Server（幂等）。"""
    mgr = get_mcp_manager_for_user(username)
    if getattr(mgr, "_mcp_boot_done", False) or getattr(mgr, "_mcp_config_loaded", False):
        return mgr
    async with mgr._bootstrap_lock:
        if getattr(mgr, "_mcp_boot_done", False) or getattr(mgr, "_mcp_config_loaded", False):
            return mgr
        await mgr.load_config()
        setattr(mgr, "_mcp_config_loaded", True)
        return mgr


async def dispose_mcp_runtime_for_user(username: str) -> None:
    """关闭并移除某用户的 MCP 运行时（配置更新后调用）。"""
    uname = (username or "").strip()
    if not uname:
        return
    with _mcp_user_lock:
        mgr = _mcp_by_user.pop(uname, None)
    if mgr is not None:
        try:
            await mgr.cleanup()
        except Exception:
            logger.exception("dispose_mcp_runtime_for_user: cleanup failed for %s", uname)


async def cleanup_all_mcp_runtimes() -> None:
    """关闭所有用户的 MCP 连接（进程退出时）。"""
    with _mcp_user_lock:
        items = list(_mcp_by_user.items())
        _mcp_by_user.clear()
    for uname, mgr in items:
        try:
            await mgr.cleanup()
        except Exception:
            logger.exception("cleanup_all_mcp_runtimes: failed for %s", uname)


def get_mcp_manager() -> "MCPToolManager":
    """兼容旧调用：返回当前登录用户的 MCP 管理器（不自动 bootstrap，请用 ensure_user_mcp_bootstrapped）。"""
    from app.core.security import get_current_user

    return get_mcp_manager_for_user(get_current_user().username)


class MCPToolManager:
    """MCP 工具管理器"""
    
    def __init__(self, username: Optional[str] = None):
        self._username = (username or "").strip() or None
        self.sessions: Dict[str, ClientSession] = {}
        self.tools: Dict[str, ToolSpec] = {}
        self.server_configs: List[Dict[str, Any]] = []
        self.exit_stack = AsyncExitStack()  # 用于管理异步上下文管理器
        self._bootstrap_lock = asyncio.Lock()
        self._server_retry_not_before: Dict[str, float] = {}
    
    async def load_config(self, config_path: str = None):
        """加载 MCP Server 配置"""
        if config_path:
            logger.info(f"加载 MCP 配置: {config_path}")
            with open(config_path, 'r', encoding='utf-8') as f:
                self.server_configs = json.load(f)
        elif self._username:
            logger.info("从 resources/tools 加载 MCP 配置: %s", self._username)
            self.server_configs = _load_user_mcp_resource_configs(self._username)
        else:
            config_path = os.getenv("MCP_CONFIG_PATH", "")
            if config_path and os.path.exists(config_path):
                logger.info(f"加载 MCP 配置: {config_path}")
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.server_configs = json.load(f)
            else:
                logger.warning("MCP 配置不存在：缺少用户上下文且未设置 MCP_CONFIG_PATH")
                self.server_configs = []
        self.server_configs = [
            c for c in self.server_configs
            if isinstance(c, dict) and str(c.get("type") or "mcp") == "mcp" and _server_key(c)
        ]
        logger.info(f"成功加载 {len(self.server_configs)} 个 MCP Server 配置")
        for config in self.server_configs:
            logger.info(f"  - {config.get('name')}")
    
    async def connect_server(self, server_name: str, config: Dict[str, Any]) -> bool:
        """连接 MCP Server"""
        now = time.time()
        blocked_until = float(self._server_retry_not_before.get(server_name, 0.0) or 0.0)
        if blocked_until > now:
            remain = blocked_until - now
            logger.warning(
                "MCP Server 处于失败冷却期，跳过重连（剩余 %.1fs） context=%s",
                remain,
                _mcp_connection_log_context(server_name, config),
            )
            return False
        try:
            transport = _transport_from_server_config(config)
            transport_type = transport.get("type", "stdio")
            failure_log_context = _mcp_connection_log_context(server_name, config, transport=transport)
            session_init_timeout = float((config.get("metadata") or {}).get("session_init_timeout_sec", 15.0))

            secrets: Dict[str, str] = {}
            if self._username:
                try:
                    from app.api.settings_secrets import load_api_secret_values_for_user

                    secrets = load_api_secret_values_for_user(self._username)
                except Exception:
                    secrets = {}

            if transport_type == "stdio":
                if stdio_client is None:
                    logger.error("stdio transport unavailable: MCP SDK not installed")
                    return False
                command = transport.get("command", "python")
                args = transport.get("args", [])
                
                # 如果命令是 "python"，使用当前 Python 解释器
                if command == "python" or command == "python3":
                    import sys
                    command = sys.executable
                
                raw_env = transport.get("env")
                # 重要：在 stdio 子进程中保留 PATH 等基础环境变量，否则 npx/python 等可能不可用。
                # 同时注入稳定用户身份；stdio 子进程没有请求 ContextVar。
                env = _build_stdio_child_env(username=self._username, raw_env=raw_env, secrets=secrets)
                params = StdioServerParameters(
                    command=command,
                    args=args,
                    env=env or None,
                )
                
                # stdio_client 是异步上下文管理器，返回 (read, write) 元组
                # 使用 exit_stack 来管理，保持连接打开
                # 注意：stdio_client 会自动将进程的 stderr 输出到当前进程的 stderr
                try:
                    import sys
                    stdio_transport = await self.exit_stack.enter_async_context(
                        stdio_client(params, errlog=sys.stderr)  # 直接输出到 stderr，便于查看
                    )
                    read, write = stdio_transport
                except Exception as e:
                    logger.error(f"新建 stdio 客户端失败（: {e}", exc_info=True)
                    raise
                
                # 根据 MCP 官方文档，ClientSession 应该作为异步上下文管理器使用
                # 使用 exit_stack 来管理，保持连接打开
                try:
                    session = await self.exit_stack.enter_async_context(
                        ClientSession(read, write)
                    )
                    # 添加超时保护（可配置），asyncio 在文件顶部已导入
                    await asyncio.wait_for(session.initialize(), timeout=session_init_timeout)
                except asyncio.TimeoutError:
                    logger.error("MCP Session 初始化超时（%.1fs）", session_init_timeout)
                    raise
                except asyncio.CancelledError as e:
                    logger.error("MCP Session 初始化被取消: %s", e, exc_info=True)
                    raise
                except Exception as e:
                    logger.error(f"MCP Session 初始化失败: {e}", exc_info=True)
                    raise
                
                self.sessions[server_name] = session
                await self._load_tools_from_server(server_name, session)
                self._server_retry_not_before.pop(server_name, None)
                return True

            elif transport_type in ("http", "streamable_http", "sse") and _streamable_http_available:
                # 远程 HTTP / Streamable HTTP：使用 MCP SDK 的 streamable_http_client
                raw_url = (transport.get("url") or transport.get("base_url") or "").strip()
                raw_headers = dict(transport.get("headers") or {})
                missing_placeholders: List[str] = []
                missing_placeholders.extend(_missing_mcp_placeholders(raw_url, secrets))
                for header_value in raw_headers.values():
                    missing_placeholders.extend(_missing_mcp_placeholders(header_value, secrets))
                if missing_placeholders:
                    missing_label = ",".join(sorted(set(missing_placeholders)))
                    logger.error(
                        "MCP Server HTTP 传输缺少必需变量: %s context=%s",
                        missing_label,
                        _mcp_connection_log_context(server_name, config, transport=transport, url=raw_url),
                    )
                    return False

                url = raw_url
                url = _subst_mcp_placeholders(url, secrets)  # ${vault:...} 密钥库；${VAR} 环境变量
                if not url:
                    logger.error(f"MCP Server {server_name}: HTTP 传输缺少 url 或 base_url")
                    return False
                headers = {k: _subst_mcp_placeholders(str(v), secrets) for k, v in raw_headers.items()}
                auth = headers.get("Authorization")
                if isinstance(auth, str) and auth.startswith("Bearer") and not auth.startswith("Bearer "):
                    token = auth[len("Bearer"):].strip()
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                failure_log_context = _mcp_connection_log_context(
                    server_name,
                    config,
                    transport=transport,
                    url=url,
                    headers=headers,
                )
                http_client = None
                if headers:
                    # 不要在这里硬编码 60s；默认不设置 timeout（由底层/调用侧控制），也可用 MCP_HTTP_TIMEOUT_SEC 覆盖。
                    _http_t = (os.getenv("MCP_HTTP_TIMEOUT_SEC") or "").strip()
                    if _http_t:
                        try:
                            http_timeout = float(_http_t)
                        except Exception:
                            http_timeout = None
                    else:
                        http_timeout = None
                    http_client = httpx.AsyncClient(headers=headers, timeout=http_timeout)
                    await self.exit_stack.enter_async_context(http_client)
                try:
                    streamable_transport = streamable_http_client(url, http_client=http_client, terminate_on_close=True)
                    read_write_getid = await self.exit_stack.enter_async_context(streamable_transport)
                    read_stream, write_stream, _ = read_write_getid
                    session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
                    await asyncio.wait_for(session.initialize(), timeout=session_init_timeout)
                except asyncio.TimeoutError:
                    logger.error(
                        "MCP Server Streamable HTTP 初始化超时（%.1fs） context=%s",
                        session_init_timeout,
                        _mcp_connection_log_context(server_name, config, transport=transport, url=url, headers=headers),
                    )
                    raise
                except Exception as e:
                    logger.error(
                        "MCP Server Streamable HTTP 连接失败: %s context=%s",
                        _exception_detail(e),
                        _mcp_connection_log_context(server_name, config, transport=transport, url=url, headers=headers),
                        exc_info=True,
                    )
                    raise
                self.sessions[server_name] = session
                await self._load_tools_from_server(server_name, session)
                self._server_retry_not_before.pop(server_name, None)
                return True

            else:
                if transport_type in ("http", "streamable_http", "sse") and not _streamable_http_available:
                    logger.error(f"传输类型 {transport_type} 需要安装 mcp 与 httpx，且 mcp 需包含 streamable_http 客户端")
                else:
                    logger.error(f"不支持的传输类型: {transport_type}")
                return False
        except Exception as e:
            # 遇到远端协议/返回格式不兼容时，短暂熔断，避免每次请求都重复打满错误日志并拖慢路径
            cooldown_sec = int(os.getenv("MCP_CONNECT_RETRY_COOLDOWN_SEC", "300"))
            error_detail = _exception_detail(e)
            if cooldown_sec > 0 and _looks_like_protocol_mismatch_error(error_detail):
                self._server_retry_not_before[server_name] = time.time() + cooldown_sec
                logger.warning(
                    "MCP Server 连接出现协议不兼容，进入冷却 %ss（可用 MCP_CONNECT_RETRY_COOLDOWN_SEC 调整） context=%s",
                    cooldown_sec,
                    failure_log_context,
                )
            logger.error(
                "Failed to connect MCP server: %s context=%s",
                error_detail,
                failure_log_context,
                exc_info=True,
            )
            return False
    
    async def _load_tools_from_server(self, server_name: str, session: ClientSession):
        """从 MCP Server 加载工具"""
        try:
            tools_result = await session.list_tools()
            for mcp_tool in tools_result.tools:
                # 新建项目内 ToolSpec（传入 server_name 用于生成唯一名称）
                tool_spec = self._create_tool_spec(mcp_tool, session, server_name)
                self.tools[tool_spec.name] = tool_spec
        except Exception as e:
            logger.error(f"Failed to load tools from server {server_name}: {e}", exc_info=True)

    async def _reconnect_server(self, server_name: str) -> bool:
        """Best-effort reconnect for a specific server when session is closed."""
        cfg = next((c for c in self.server_configs if _server_key(c) == server_name), None)
        if not cfg:
            return False
        old = self.sessions.pop(server_name, None)
        if old is not None:
            try:
                await old.__aexit__(None, None, None)
            except Exception:
                # best effort; manager-level cleanup still handles leftovers
                pass
        # 清理该 server 的工具，避免 stale session 继续被调用
        stale_prefix = f"{server_name}_"
        for name in [
            n
            for n, tool in list(self.tools.items())
            if n.startswith(stale_prefix) or getattr(tool, "metadata", {}).get("mcp_server_name") == server_name
        ]:
            self.tools.pop(name, None)
        return await self.connect_server(server_name, cfg)
    
    def _create_tool_spec(self, mcp_tool, session: ClientSession, server_name: Optional[str] = None) -> ToolSpec:
        """将 MCP 工具转换为项目内 ToolSpec。"""
        # 保存原始工具名和 session 引用
        original_tool_name = mcp_tool.name
        tool_name = _safe_mcp_model_tool_name(server_name, mcp_tool.name)
        # 将 inputSchema 转为 dict 并保存，供 normalize_mcp_kwargs_for_call 做 __arg1 等通用映射
        _input_schema = getattr(mcp_tool, "inputSchema", None)
        if hasattr(_input_schema, "model_dump"):
            _input_schema = _input_schema.model_dump()
        if not isinstance(_input_schema, dict):
            _input_schema = None

        async def tool_func(**kwargs):
            """异步执行 MCP 工具。直接使用 session.call_tool，与主事件循环同任务，避免 sync 包装带来的额外开销与 anyio 跨任务错误。"""
            try:
                try:
                    call_kwargs = normalize_mcp_kwargs_for_call(
                        server_name, original_tool_name, dict(kwargs or {}), input_schema=_input_schema
                    )
                except Exception as e:
                    detail = _exception_detail(e)
                    sid = server_name or ""
                    logger.warning(
                        "MCP tool argument normalization failed server=%s tool=%s %s",
                        sid,
                        original_tool_name,
                        detail,
                        exc_info=True,
                    )
                    return (
                        "Error: MCP tool argument normalization failed: "
                        f"server={sid} tool={original_tool_name} {detail}"
                    )
                logger.debug("MCP call_tool: %s %s", original_tool_name, list(call_kwargs.keys()))
                active_session = self.sessions.get(server_name or "", session)
                call_started = time.perf_counter()
                ok, result, err = await execute_mcp_call(
                    server_name=server_name or "",
                    tool_name=original_tool_name,
                    kwargs=call_kwargs,
                    session=active_session,
                    timeout_sec=None,
                )
                # 远端 streamable_http 连接被回收或异常中断时，首次调用可能只返回很弱的 SDK 错误；
                # 这里在 MCP 层重连一次，不把问题包装成 sandbox 失败。
                if (not ok) and _looks_like_retryable_mcp_call_error(err):
                    sid = server_name or ""
                    if sid:
                        logger.warning(
                            "MCP 调用疑似会话失效，尝试重连后重试: server=%s tool=%s err=%s",
                            sid,
                            original_tool_name,
                            str(err or "")[:500],
                        )
                        reconnected = await self._reconnect_server(sid)
                        if reconnected:
                            retry_session = self.sessions.get(sid)
                            if retry_session is not None:
                                ok, result, err = await execute_mcp_call(
                                    server_name=sid,
                                    tool_name=original_tool_name,
                                    kwargs=call_kwargs,
                                    session=retry_session,
                                    timeout_sec=None,
                                )
                elapsed_ms = int((time.perf_counter() - call_started) * 1000)
                if not ok:
                    logger.warning(
                        "mcp_tool_call_done server=%s tool=%s ok=false elapsed_ms=%s arg_keys=%s err=%s",
                        server_name or "",
                        original_tool_name,
                        elapsed_ms,
                        sorted(call_kwargs.keys()),
                        str(err or "")[:500],
                    )
                    if _looks_like_closed_resource_error(err):
                        return (
                            "Error: MCP session closed by remote server "
                            f"(server={server_name or ''}, tool={original_tool_name}). "
                            "Please retry once; if it persists, check upstream MCP service health."
                        )
                    return f"Error: {err or 'MCP tool call failed'}"
                if result.content:
                    block = result.content[0]
                    text = block.text if hasattr(block, "text") else str(block)
                else:
                    text = str(result)
                logger.info(
                    "mcp_tool_call_done server=%s tool=%s ok=true elapsed_ms=%s arg_keys=%s result_len=%s",
                    server_name or "",
                    original_tool_name,
                    elapsed_ms,
                    sorted(call_kwargs.keys()),
                    len(str(text or "")),
                )
                return text
            except Exception as e:
                logger.error("MCP 工具执行错误: %s", e, exc_info=True)
                return f"Error: {e}"

        description = mcp_tool.description or f"MCP tool: {mcp_tool.name}"
        if getattr(mcp_tool, "inputSchema", None) and isinstance(mcp_tool.inputSchema, dict):
            props = (mcp_tool.inputSchema or {}).get("properties") or {}
            if props:
                parts = [f"{k} ({v.get('type', 'string')})" for k, v in props.items()]
                description = f"{description} 参数: {', '.join(parts)}。"
        # 使用异步 func：graph/agent 侧会 await，避免 asyncio.run/run_until_complete 带来的新循环或跨任务问题
        tool_spec = ToolSpec.from_function(
            name=tool_name,
            description=description,
            func=tool_func,
            args_schema=_input_schema,
        )
        tool_spec.metadata.update(
            {
                "mcp_server_name": server_name or "",
                "mcp_tool_name": original_tool_name,
            }
        )
        # 供 chat 层展示时复用同一套归一化逻辑（含 __arg1 -> 首参 映射）
        tool_spec._mcp_input_schema = _input_schema
        return tool_spec
    
    def get_tools(self) -> List[ToolSpec]:
        """获取所有工具"""
        return list(self.tools.values())
    
    async def initialize_all(self, config_path: Optional[str] = None):
        """加载配置并初始化所有非 lazy 的 MCP Server。config_path 默认使用环境变量 MCP_CONFIG_PATH。"""
        await self.load_config(config_path)

        for config in self.server_configs:
            server_name = _server_key(config)
            if not server_name:
                continue
            # lazy server: 不在启动期建立连接，首次需要时再连接
            if config.get("lazy", False):
                logger.info("MCP Server %s 标记为 lazy，跳过启动初始化", server_name)
                continue
            try:
                # 单个 server 失败不应影响其它 server 与主服务启动
                tmo = float(config.get("metadata", {}).get("init_timeout_sec", 15.0))
                logger.info("初始化 MCP Server: %s (timeout=%.1fs)", server_name, tmo)
                success = await asyncio.wait_for(self.connect_server(server_name, config), timeout=tmo)
                if not success:
                    logger.error("MCP Server %s 初始化失败（已跳过）", server_name)
            except asyncio.TimeoutError:
                logger.error("MCP Server %s 初始化超时（已跳过）", server_name, exc_info=True)
            except asyncio.CancelledError as e:
                # 某些 stdio/http 初始化会触发 anyio cancel scope；这里降级处理，避免阻塞整个系统
                logger.error("MCP Server %s 初始化被取消（已跳过）: %s", server_name, e, exc_info=True)
            except BaseException as e:
                logger.error("MCP Server %s 初始化异常（已跳过）: %s", server_name, e, exc_info=True)
        
        logger.info("加载 mcp 工具完成")

    async def ensure_servers_loaded(self, server_names: List[str]) -> None:
        """确保给定 server_names 的 MCP 工具已加载（lazy 服务器也会在首次需要时加载）。"""
        if not server_names:
            return
        now = time.time()
        for sid in server_names:
            if not sid:
                continue
            if sid in self.sessions:
                # connect_server 成功后会同时 load tools
                continue
            blocked_until = float(self._server_retry_not_before.get(sid, 0.0) or 0.0)
            if blocked_until > now:
                logger.info("ensure_servers_loaded: MCP server %s 在冷却期内，跳过连接", sid)
                continue
            cfg = next((c for c in self.server_configs if _server_key(c) == sid), None)
            if not cfg:
                logger.warning("ensure_servers_loaded: 未找到 MCP server 配置: %s", sid)
                continue
            await self.connect_server(sid, cfg)
    
    async def cleanup(self):
        """清理所有连接"""
        logger.info("清理 MCP 连接...")
        # 使用 exit_stack 自动清理所有异步上下文管理器
        try:
            await self.exit_stack.aclose()
        except RuntimeError as e:
            # 某些第三方 MCP 客户端在不同 task 做 __aexit__ 会抛 anyio cancel-scope 错误。
            # 进程关停场景下允许降级为警告并继续清理内存引用，避免重复报错阻塞退出。
            if "cancel scope in a different task" in str(e):
                logger.warning("MCP 清理降级：%s", e)
            else:
                logger.error("清理 exit_stack 时出错: %s", e, exc_info=True)
        except Exception as e:
            logger.error("清理 exit_stack 时出错: %s", e, exc_info=True)

        self.sessions.clear()
        self.tools.clear()
        self.server_configs = []
        setattr(self, "_mcp_boot_done", False)
        setattr(self, "_mcp_config_loaded", False)
        self._server_retry_not_before = {}
        self.exit_stack = AsyncExitStack()
        self._bootstrap_lock = asyncio.Lock()
        logger.info("MCP 连接清理完成")
