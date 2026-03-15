"""MCP Server 管理器"""
import os
import re
import logging
import asyncio
from typing import List, Dict, Any, Optional
from contextlib import AsyncExitStack

logger = logging.getLogger(__name__)

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from langchain.tools import Tool
except ImportError as e:
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

_mcp_manager_singleton: Optional["MCPToolManager"] = None


def normalize_mcp_kwargs_for_call(
    server_id: Optional[str],
    original_tool_name: str,
    kwargs: Dict[str, Any],
    input_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    规范化 MCP 工具调用参数。

    仅做纯函数转换（不写日志），便于：
    - manager 内部在真正调用 MCP 前统一规整参数
    - chat 层在展示「实际调用参数」时复用相同逻辑，保证前后端一致

    input_schema: 工具的 JSON Schema（含 properties/required），用于将 __arg1 等通用占位符
                  映射到实际参数名（如 query、address），解决 LLM 常输出 __arg1 的问题。
    """
    call_kwargs: Dict[str, Any] = dict(kwargs or {})

    # volces-icon generate_app_icon:
    # 1) 优先从 prompt / input / text / content 映射到 description（LLM 常传这些别名而非 description）
    if (
        server_id == "volces-icon"
        and original_tool_name == "generate_app_icon"
        and "description" not in call_kwargs
    ):
        desc_candidate = (
            call_kwargs.pop("prompt", None)
            or call_kwargs.pop("input", None)
            or call_kwargs.pop("text", None)
            or call_kwargs.pop("content", None)
        )
        if desc_candidate is not None:
            call_kwargs["description"] = str(desc_candidate).strip() or ""

    # 2) 兼容 __arg1 + pic_size / 纯字符串 / JSON，统一映射为 description/pic_size
    if (
        server_id == "volces-icon"
        and original_tool_name == "generate_app_icon"
        and "__arg1" in call_kwargs
        and "description" not in call_kwargs
    ):
        import json as _json

        arg1 = call_kwargs.pop("__arg1")
        _mapped = False
        # 如果 __arg1 是 JSON 字符串，优先按 {description, pic_size} 解析
        if isinstance(arg1, str):
            try:
                _parsed = _json.loads(arg1)
            except (ValueError, TypeError):
                _parsed = None
            if isinstance(_parsed, dict) and "description" in _parsed:
                call_kwargs["description"] = _parsed["description"]
                if "pic_size" in _parsed and "pic_size" not in call_kwargs:
                    call_kwargs["pic_size"] = _parsed["pic_size"]
                _mapped = True
        # 否则，直接把 __arg1 当成 description 文本
        if not _mapped:
            call_kwargs["description"] = str(arg1) if arg1 is not None else ""

    # 3) 确保 volces-icon generate_app_icon 必有 description，避免 MCP 报「缺少必填项」
    if (
        server_id == "volces-icon"
        and original_tool_name == "generate_app_icon"
        and "description" not in call_kwargs
    ):
        call_kwargs["description"] = ""

    # amap-maps maps_geo:
    # 若仍然收到 __arg1，则兼容以下几种常见写法，归一化为 address/city
    # - "__arg1": "天安门,北京"        → address="天安门", city="北京"
    # - "__arg1": "{\"address\":\"天安门\",\"city\":\"北京\"}" → 按 JSON 解析
    # - "__arg1": "天安门"             → address="天安门"（city 由 Skill 控制）
    if server_id == "amap-maps" and original_tool_name == "maps_geo" and "__arg1" in call_kwargs:
        import json as _json_amap_arg1

        arg1 = call_kwargs.pop("__arg1", "")
        # 1) "地址,城市" 形式
        if isinstance(arg1, str) and "," in arg1 and "city" not in call_kwargs:
            parts = arg1.split(",", 1)
            if len(parts) == 2:
                call_kwargs.setdefault("address", parts[0].strip())
                call_kwargs.setdefault("city", parts[1].strip())
                arg1 = None
        # 2) JSON 字符串或 dict，优先解析 address/city
        if arg1 is not None:
            try:
                _parsed = _json_amap_arg1.loads(arg1) if isinstance(arg1, str) else arg1
                if isinstance(_parsed, dict) and "address" in _parsed:
                    call_kwargs.setdefault("address", _parsed["address"])
                    if "city" in _parsed and "city" not in call_kwargs:
                        call_kwargs["city"] = _parsed["city"]
                else:
                    # 3) 其余情况，直接视为 address 字符串
                    if "address" not in call_kwargs:
                        call_kwargs["address"] = str(arg1) if arg1 else ""
            except (ValueError, TypeError):
                if "address" not in call_kwargs:
                    call_kwargs["address"] = str(arg1) if arg1 else ""

    # amap-maps 路线/距离相关工具：
    # 若仍然收到 __arg1，且 origin/destination 等核心字段缺失，
    # 兼容以下写法：{"__arg1": "{\"origin\": \"...\", \"destination\": \"...\", ... }"}
    if (
        server_id == "amap-maps"
        and original_tool_name
        in (
            "maps_direction_driving",
            "maps_direction_walking",
            "maps_bicycling",
            "maps_direction_transit",
            "maps_direction_transit_integrated",
            "maps_distance",
        )
        and "__arg1" in call_kwargs
    ):
        import json as _json_amap_route

        arg1 = call_kwargs.pop("__arg1", "")
        try:
            _parsed = _json_amap_route.loads(arg1) if isinstance(arg1, str) else arg1
        except (ValueError, TypeError):
            _parsed = None
        if isinstance(_parsed, dict):
            # 仅在目标字段缺失时，从 __arg1 补充 origin/destination/city/cityd/type 等
            for _k in ("origin", "destination", "city", "cityd", "type"):
                if _k in _parsed and _k not in call_kwargs:
                    call_kwargs[_k] = _parsed[_k]

    # file-reader / filesystem 系列: 若仍收到 __arg1，则将其视为 path（统一兼容老模板）
    if server_id in ("file-reader", "filesystem") and "__arg1" in call_kwargs:
        if "path" not in call_kwargs:
            call_kwargs["path"] = str(call_kwargs["__arg1"]) if call_kwargs["__arg1"] is not None else ""

    # 通用：若存在 __arg1 且尚未被上述规则映射，且能拿到工具的 inputSchema，
    # 则映射到 schema 中第一个必需参数或第一个属性（解决 zhipu-web-search、exa 等 query 参数问题）
    if "__arg1" in call_kwargs and input_schema:
        schema = input_schema if isinstance(input_schema, dict) else {}
        first_param = None
        required = schema.get("required") or []
        if required:
            first_param = required[0]
        else:
            props = schema.get("properties") or {}
            if props:
                first_param = next(iter(props.keys()), None)
        if first_param and first_param not in call_kwargs:
            call_kwargs[first_param] = call_kwargs.pop("__arg1")

    # amap-maps maps_geo:
    # 无 city 或 city 为区名时，若地址含北京相关关键词则自动补 city=北京，避免全国检索误匹配
    if server_id == "amap-maps" and original_tool_name == "maps_geo":
        addr = (call_kwargs.get("address") or "").strip()
        city = (call_kwargs.get("city") or "").strip()
        _beijing_keywords = ("北邮", "海淀", "天安门", "故宫", "北京", "西单", "东单", "国贸", "中关村")
        _district_not_city = ("海淀", "朝阳", "东城", "西城", "丰台", "石景山", "通州", "顺义")  # 区名不能当 city
        needs_fix = (not city) or (
            city in _district_not_city and any(kw in addr for kw in _beijing_keywords)
        )
        if needs_fix and any(kw in addr for kw in _beijing_keywords):
            call_kwargs["city"] = "北京"

    # 最后一步：清理所有残留的 "__argX" 占位字段，避免传递到实际 MCP 调用
    _keys_to_delete = [k for k in list(call_kwargs.keys()) if k.startswith("__arg")]
    for _k in _keys_to_delete:
        call_kwargs.pop(_k, None)

    return call_kwargs


def _subst_env(val: str) -> str:
    """将字符串中的 ${VAR} 替换为环境变量"""
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), str(val))


def get_mcp_manager() -> "MCPToolManager":
    """获取全局 MCP 管理器单例（chat、settings 共用，保证状态一致）"""
    global _mcp_manager_singleton
    if _mcp_manager_singleton is None:
        _mcp_manager_singleton = MCPToolManager()
    return _mcp_manager_singleton


class MCPToolManager:
    """MCP 工具管理器"""
    
    def __init__(self):
        self.sessions: Dict[str, ClientSession] = {}
        self.tools: Dict[str, Tool] = {}
        self.server_configs: List[Dict[str, Any]] = []
        self.exit_stack = AsyncExitStack()  # 用于管理异步上下文管理器
    
    async def load_config(self, config_path: str = None):
        """加载 MCP Server 配置"""
        import json
        config_path = config_path or os.getenv("MCP_CONFIG_PATH", "./config/mcp_servers.json")
        logger.info(f"加载 MCP 配置: {config_path}")
        
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                self.server_configs = json.load(f)
            logger.info(f"成功加载 {len(self.server_configs)} 个 MCP Server 配置")
            for config in self.server_configs:
                logger.info(f"  - {config.get('id')}: {config.get('name')}, enabled: {config.get('enabled')}")
            # #region agent log
            # 调试：记录当前加载到的 MCP Server 基本信息（不包含任何敏感字段）
            try:
                import json as _json_cfg, time as _time_cfg
                summary = []
                for _cfg in self.server_configs:
                    _transport = _cfg.get("transport") or {}
                    summary.append(
                        {
                            "id": _cfg.get("id"),
                            "enabled": bool(_cfg.get("enabled", True)),
                            "transport_type": _transport.get("type", ""),
                        }
                    )
                with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                    _f.write(
                        _json_cfg.dumps(
                            {
                                "id": f"log_mcp_load_config_{int(_time_cfg.time() * 1000)}",
                                "timestamp": int(_time_cfg.time() * 1000),
                                "location": "backend/app/mcp/manager.py:205",
                                "message": "MCP load_config summary",
                                "data": {"config_path": config_path, "servers": summary},
                                "runId": "mcp-config",
                                "hypothesisId": "H-config",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except Exception:
                # 日志失败不影响正常逻辑
                pass
            # #endregion
        else:
            logger.warning(f"MCP 配置文件不存在: {config_path}")
            # 默认配置示例
            self.server_configs = []
    
    async def connect_server(self, server_id: str, config: Dict[str, Any]) -> bool:
        """连接 MCP Server"""
        try:
            transport = config.get("transport", {})
            transport_type = transport.get("type", "stdio")
            # #region agent log
            # 调试：记录连接前的关键信息，用于排查 Docker 环境下某些 MCP 未能成功连接的问题
            try:
                import json as _json_conn, time as _time_conn
                env_keys = sorted(list((transport.get("env") or {}).keys()))
                url_or_base = (transport.get("url") or transport.get("base_url") or "").strip()
                _payload = {
                    "id": f"log_mcp_connect_try_{server_id}_{int(_time_conn.time() * 1000)}",
                    "timestamp": int(_time_conn.time() * 1000),
                    "location": "backend/app/mcp/manager.py:222",
                    "message": "MCP connect attempt",
                    "data": {
                        "server_id": server_id,
                        "transport_type": transport_type,
                        "has_command": bool(transport.get("command")),
                        "has_args": bool(transport.get("args")),
                        "env_keys": env_keys,
                        "has_url_or_base": bool(url_or_base),
                    },
                    "runId": "mcp-connect",
                    "hypothesisId": "H-connect",
                }
                with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                    _f.write(_json_conn.dumps(_payload, ensure_ascii=False) + "\n")
            except Exception:
                # 日志失败不影响正常逻辑
                pass
            # #endregion
            
            if transport_type == "stdio":
                command = transport.get("command", "python")
                args = transport.get("args", [])
                
                # 如果命令是 "python"，使用当前 Python 解释器
                if command == "python" or command == "python3":
                    import sys
                    command = sys.executable
                
                raw_env = transport.get("env")
                env = None
                if isinstance(raw_env, dict) and raw_env:
                    env = {k: _subst_env(v) for k, v in raw_env.items()}
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
                    logger.error(f"创建 stdio 客户端失败（: {e}", exc_info=True)
                    raise
                
                # 根据 MCP 官方文档，ClientSession 应该作为异步上下文管理器使用
                # 使用 exit_stack 来管理，保持连接打开
                try:
                    session = await self.exit_stack.enter_async_context(
                        ClientSession(read, write)
                    )
                    # 添加超时保护（30秒），asyncio 在文件顶部已导入
                    await asyncio.wait_for(session.initialize(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.error("MCP Session 初始化超时（30秒），可能的原因：")
                    raise
                except Exception as e:
                    logger.error(f"MCP Session 初始化失败: {e}", exc_info=True)
                    raise
                
                self.sessions[server_id] = session
                await self._load_tools_from_server(server_id, session)
                # #region agent log
                # 调试：记录成功连接的 MCP Server 及加载到的工具数量
                try:
                    import json as _json_conn_ok, time as _time_conn_ok
                    tool_count = len(
                        [t for name, t in self.tools.items() if isinstance(name, str) and name.startswith(f"{server_id}_")]
                    )
                    with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                        _f.write(
                            _json_conn_ok.dumps(
                                {
                                    "id": f"log_mcp_connect_ok_{server_id}_{int(_time_conn_ok.time() * 1000)}",
                                    "timestamp": int(_time_conn_ok.time() * 1000),
                                    "location": "backend/app/mcp/manager.py:275",
                                    "message": "MCP connect success",
                                    "data": {
                                        "server_id": server_id,
                                        "transport_type": transport_type,
                                        "tool_count": tool_count,
                                    },
                                    "runId": "mcp-connect",
                                    "hypothesisId": "H-connect-ok",
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                except Exception:
                    # 日志失败不影响正常逻辑
                    pass
                # #endregion
                return True

            elif transport_type in ("http", "streamable_http", "sse") and _streamable_http_available:
                # 远程 HTTP / Streamable HTTP：使用 MCP SDK 的 streamable_http_client
                url = (transport.get("url") or transport.get("base_url") or "").strip()
                url = _subst_env(url)  # 支持 ${VAR} 环境变量（如 Exa API Key）
                if not url:
                    logger.error(f"MCP Server {server_id}: HTTP 传输缺少 url 或 base_url")
                    return False
                raw_headers = dict(transport.get("headers") or {})
                # 支持 ${VAR} 环境变量替换，便于安全配置 API Key（如 "Bearer ${SMITHERY_API_KEY}"）
                headers = {k: _subst_env(str(v)) for k, v in raw_headers.items()}
                http_client = None
                if headers:
                    http_client = httpx.AsyncClient(headers=headers, timeout=60.0)
                    await self.exit_stack.enter_async_context(http_client)
                try:
                    streamable_transport = streamable_http_client(url, http_client=http_client, terminate_on_close=True)
                    read_write_getid = await self.exit_stack.enter_async_context(streamable_transport)
                    read_stream, write_stream, _ = read_write_getid
                    session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
                    await asyncio.wait_for(session.initialize(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.error(f"MCP Server {server_id} Streamable HTTP 初始化超时（30秒）")
                    raise
                except Exception as e:
                    logger.error(f"MCP Server {server_id} Streamable HTTP 连接失败: {e}", exc_info=True)
                    raise
                self.sessions[server_id] = session
                await self._load_tools_from_server(server_id, session)
                return True

            else:
                if transport_type in ("http", "streamable_http", "sse") and not _streamable_http_available:
                    logger.error(f"传输类型 {transport_type} 需要安装 mcp 与 httpx，且 mcp 需包含 streamable_http 客户端")
                else:
                    logger.error(f"不支持的传输类型: {transport_type}")
                return False
        except Exception as e:
            logger.error(f"Failed to connect MCP server {server_id}: {e}", exc_info=True)
            # #region agent log
            # 调试：记录连接失败的原因（不包含任何敏感字段）
            try:
                import json as _json_conn_err, time as _time_conn_err
                with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                    _f.write(
                        _json_conn_err.dumps(
                            {
                                "id": f"log_mcp_connect_error_{server_id}_{int(_time_conn_err.time() * 1000)}",
                                "timestamp": int(_time_conn_err.time() * 1000),
                                "location": "backend/app/mcp/manager.py:318",
                                "message": "MCP connect failed",
                                "data": {
                                    "server_id": server_id,
                                    "transport_type": locals().get("transport_type", ""),
                                    "error": str(e),
                                },
                                "runId": "mcp-connect",
                                "hypothesisId": "H-connect-error",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except Exception:
                # 日志失败不影响正常逻辑
                pass
            # #endregion
            return False
    
    async def _load_tools_from_server(self, server_id: str, session: ClientSession):
        """从 MCP Server 加载工具"""
        try:
            tools_result = await session.list_tools()
            for mcp_tool in tools_result.tools:
                # 创建 LangChain Tool（传入 server_id 用于生成唯一名称）
                langchain_tool = self._create_langchain_tool(mcp_tool, session, server_id)
                tool_name = f"{server_id}_{mcp_tool.name}" if server_id else mcp_tool.name
                self.tools[tool_name] = langchain_tool
        except Exception as e:
            logger.error(f"Failed to load tools from server {server_id}: {e}", exc_info=True)
    
    def _create_langchain_tool(self, mcp_tool, session: ClientSession, server_id: Optional[str] = None) -> Tool:
        """将 MCP 工具转换为 LangChain Tool"""
        # 保存原始工具名和 session 引用
        original_tool_name = mcp_tool.name
        tool_name = f"{server_id}_{mcp_tool.name}" if server_id else mcp_tool.name
        # 将 inputSchema 转为 dict 并保存，供 normalize_mcp_kwargs_for_call 做 __arg1 等通用映射
        _input_schema = getattr(mcp_tool, "inputSchema", None)
        if hasattr(_input_schema, "model_dump"):
            _input_schema = _input_schema.model_dump()
        if not isinstance(_input_schema, dict):
            _input_schema = None

        async def tool_func(**kwargs):
            logger.info(f"执行工具: {original_tool_name}, 参数: {kwargs}")
            try:
                call_Kwargs = dict(kwargs)
                # #region agent log
                try:
                    if server_id == "volces-icon" and original_tool_name == "generate_app_icon":
                        import json as _json
                        import time as _time
                        with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                            _f.write(
                                _json.dumps(
                                    {
                                        "id": "log_volces_icon_pre",
                                        "timestamp": int(_time.time() * 1000),
                                        "location": "backend/app/mcp/manager.py:201",
                                        "message": "volces-icon_generate_app_icon raw kwargs",
                                        "data": {
                                            "server_id": server_id,
                                            "original_tool_name": original_tool_name,
                                            "kwargs": call_Kwargs,
                                        },
                                        "runId": "pre-fix",
                                        "hypothesisId": "A",
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                except Exception:
                    # 日志失败不影响正常逻辑
                    pass
                # #endregion
                # 若工具参数中仍然出现 __arg1，记录调试信息，便于排查提示词/技能是否仍在使用旧示例
                if "__arg1" in call_Kwargs:
                    try:
                        import json as _json3, time as _time3
                        with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                            _f.write(
                                _json3.dumps(
                                    {
                                        "id": f"log_mcp_arg1_{int(_time3.time() * 1000)}",
                                        "timestamp": int(_time3.time() * 1000),
                                        "location": "backend/app/mcp/manager.py:231",
                                        "message": "__arg1 still present in MCP tool kwargs",
                                        "data": {
                                            "server_id": server_id,
                                            "original_tool_name": original_tool_name,
                                            "keys": list(call_Kwargs.keys()),
                                        },
                                        "runId": "mcp-arg1",
                                        "hypothesisId": "cleanup",
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                    except Exception:
                        pass
                # 归一化 MCP 调用参数（纯函数逻辑提取到 normalize_mcp_kwargs_for_call，便于前端展示复用）
                call_Kwargs = normalize_mcp_kwargs_for_call(
                    server_id, original_tool_name, call_Kwargs, input_schema=_input_schema
                )
                if server_id == "volces-icon" and original_tool_name == "generate_app_icon":
                    logger.info(f"generate_app_icon: 归一化参数为 {call_Kwargs}")
                    # #region agent log
                    try:
                        import json as _json2, time as _time2
                        with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                            _f.write(
                                _json2.dumps(
                                    {
                                        "id": "log_volces_icon_mapped",
                                        "timestamp": int(_time2.time() * 1000),
                                        "location": "backend/app/mcp/manager.py:236",
                                        "message": "volces-icon_generate_app_icon mapped kwargs",
                                        "data": {
                                            "server_id": server_id,
                                            "original_tool_name": original_tool_name,
                                            "kwargs": call_Kwargs,
                                        },
                                        "runId": "fix-mapped",
                                        "hypothesisId": "B",
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                    except Exception:
                        # 日志失败不影响正常逻辑
                        pass
                # amap-maps: 调用前记录参数，便于排查「返回参数不对/INVALID_PARAMS」类问题
                if server_id == "amap-maps":
                    try:
                        import json as _json_amap, time as _time_amap
                        with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                            _f.write(
                                _json_amap.dumps(
                                    {
                                        "id": f"log_amap_kwargs_{int(_time_amap.time() * 1000)}",
                                        "timestamp": int(_time_amap.time() * 1000),
                                        "location": "backend/app/mcp/manager.py:309",
                                        "message": "amap-maps tool kwargs before call",
                                        "data": {
                                            "original_tool_name": original_tool_name,
                                            "kwargs": call_Kwargs,
                                        },
                                        "runId": "amap-maps",
                                        "hypothesisId": "amap-params",
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                    except Exception:
                        pass
                # 使用原始工具名调用 MCP Server
                logger.info(f"调用 MCP Session: call_tool({original_tool_name}, {call_Kwargs})")
                # 额外写入 debug 日志，便于排查「卡在 call_tool」的问题
                try:
                    import json as _json_call, time as _time_call
                    with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                        _f.write(
                            _json_call.dumps(
                                {
                                    "id": f"log_mcp_call_start_{server_id or 'unknown'}_{original_tool_name}_{int(_time_call.time() * 1000)}",
                                    "timestamp": int(_time_call.time() * 1000),
                                    "location": "backend/app/mcp/manager.py:call_tool_start",
                                    "message": "MCP call_tool start",
                                    "data": {"server_id": server_id, "tool": original_tool_name, "kwargs": call_Kwargs},
                                    "runId": "mcp-call",
                                    "hypothesisId": "H-call-start",
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                except Exception:
                    pass

                # 为 MCP 调用增加超时，防止长时间无响应导致前端感觉「卡死」
                try:
                    result = await asyncio.wait_for(session.call_tool(original_tool_name, call_Kwargs), timeout=60.0)
                except asyncio.TimeoutError:
                    timeout_msg = f"MCP 工具 {original_tool_name} 调用超时（60s）"
                    logger.error(timeout_msg)
                    try:
                        import json as _json_call_to, time as _time_call_to
                        with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                            _f.write(
                                _json_call_to.dumps(
                                    {
                                        "id": f"log_mcp_call_timeout_{server_id or 'unknown'}_{original_tool_name}_{int(_time_call_to.time() * 1000)}",
                                        "timestamp": int(_time_call_to.time() * 1000),
                                        "location": "backend/app/mcp/manager.py:call_tool_timeout",
                                        "message": "MCP call_tool timeout",
                                        "data": {"server_id": server_id, "tool": original_tool_name},
                                        "runId": "mcp-call",
                                        "hypothesisId": "H-call-timeout",
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                    except Exception:
                        pass
                    return f"Error: MCP 工具 {original_tool_name} 调用超时（60s），请稍后重试。"

                logger.info(f"MCP 调用返回结果类型: {type(result)}")
                
                if result.content:
                    text_result = result.content[0].text if hasattr(result.content[0], 'text') else str(result.content[0])
                    logger.info(f"工具执行结果: {text_result}")
                    # amap-maps: 记录返回内容（截断），用于分析参数是否正确
                    if server_id == "amap-maps":
                        try:
                            import json as _json_amap2, time as _time_amap2
                            preview = text_result[:300]
                            with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                                _f.write(
                                    _json_amap2.dumps(
                                        {
                                            "id": f"log_amap_result_{int(_time_amap2.time() * 1000)}",
                                            "timestamp": int(_time_amap2.time() * 1000),
                                            "location": "backend/app/mcp/manager.py:327",
                                            "message": "amap-maps tool result",
                                            "data": {
                                                "original_tool_name": original_tool_name,
                                                "result_preview": preview,
                                            },
                                            "runId": "amap-maps",
                                            "hypothesisId": "amap-params",
                                        },
                                        ensure_ascii=False,
                                    )
                                    + "\n"
                                )
                        except Exception:
                            pass
                    return text_result
                logger.info(f"工具执行结果（无 content）: {str(result)}")
                return str(result)
            except Exception as e:
                error_msg = f"Error: {str(e)}"
                logger.error(f"工具执行错误: {error_msg}", exc_info=True)
                # amap-maps: 记录异常信息
                try:
                    import json as _json_amap3, time as _time_amap3
                    with open("/Users/ggd/mycode/DHA/.cursor/debug.log", "a", encoding="utf-8") as _f:
                        _f.write(
                            _json_amap3.dumps(
                                {
                                    "id": f"log_amap_error_{int(_time_amap3.time() * 1000)}",
                                    "timestamp": int(_time_amap3.time() * 1000),
                                    "location": "backend/app/mcp/manager.py:333",
                                    "message": "amap-maps tool exception",
                                    "data": {
                                        "original_tool_name": original_tool_name,
                                        "error": error_msg,
                                    },
                                    "runId": "amap-maps",
                                    "hypothesisId": "amap-params",
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                except Exception:
                    pass
                return error_msg
        
        # 若有 inputSchema，把参数说明拼进 description，避免 LLM 误以为只接受一个参数
        description = mcp_tool.description or f"MCP tool: {mcp_tool.name}"
        if getattr(mcp_tool, "inputSchema", None) and isinstance(mcp_tool.inputSchema, dict):
            props = mcp_tool.inputSchema.get("properties") or {}
            if props:
                parts = [f"{k} ({v.get('type', 'string')})" for k, v in props.items()]
                description = f"{description} 参数: {', '.join(parts)}。"
        # LangChain 的 Tool 默认期望同步函数；若直接把 async 函数赋给 func，
        # 上游不会 await，而是把协程对象当结果用，用户就会看到
        # "<coroutine object MCPToolManager._create_langchain_tool.<locals>.tool_func at 0x...>"。
        # 这里包一层同步函数，在内部显式跑异步逻辑，保证返回的是实际字符串结果。
        def sync_tool_func(*args, **kwargs):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # 当前线程没有事件循环：直接新建一个跑完
                return asyncio.run(tool_func(**kwargs))
            else:
                # 已有事件循环（例如在某些异步环境下被调用）：同步等待该协程完成
                return loop.run_until_complete(tool_func(**kwargs))

        langchain_tool = Tool(
            name=tool_name,
            description=description,
            func=sync_tool_func,
        )
        # 供 chat 层展示时复用同一套归一化逻辑（含 __arg1 -> 首参 映射）
        # LangChain Tool 为 Pydantic 模型，不能直接赋未声明属性，用 object.__setattr__ 绕过
        object.__setattr__(langchain_tool, "_mcp_input_schema", _input_schema)
        return langchain_tool
    
    def get_tools(self) -> List[Tool]:
        """获取所有工具"""
        return list(self.tools.values())
    
    async def initialize_all(self):
        """初始化所有配置的 MCP Server"""
        await self.load_config()
        
        for config in self.server_configs:
            server_id = config.get("id", f"server_{len(self.sessions)}")
            if config.get("enabled", True):
                try:
                    success = await self.connect_server(server_id, config)
                    if not success:
                        logger.error(f"MCP Server {server_id} 初始化失败")
                except asyncio.CancelledError:
                    raise  # 请求被取消时继续向上抛出
                except Exception as e:
                    logger.error(f"MCP Server {server_id} 初始化异常，跳过: {e}", exc_info=True)
        
        logger.info("加载 mcp 工具完成")
    
    async def cleanup(self):
        """清理所有连接"""
        logger.info("清理 MCP 连接...")
        # 使用 exit_stack 自动清理所有异步上下文管理器
        try:
            await self.exit_stack.aclose()
        except Exception as e:
            logger.error(f"清理 exit_stack 时出错: {e}", exc_info=True)
        
        self.sessions.clear()
        self.tools.clear()
        logger.info("MCP 连接清理完成")