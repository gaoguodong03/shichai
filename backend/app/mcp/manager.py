"""
MCP Server 管理器：规范、轻量的调用方式。

- 生命周期：在 FastAPI lifespan 中 initialize_all / cleanup，保证与 anyio 同任务，避免跨任务 exit 报错。
- 调用方式：Tool.func 为异步函数，直接 session.call_tool；不在外层包 sync（asyncio.run/run_until_complete 会拖慢且易出错），由 graph/agent 侧 await。
- 参数：LLM 可能传 __arg1 等；normalize_mcp_kwargs_for_call（含 tool_arg_normalizers）在调用前统一映射到 MCP schema 参数名。
"""
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
    规范化 MCP 工具调用参数。委托给 tool_arg_normalizers，便于 manager/chat 复用同一逻辑。
    """
    from app.mcp.tool_arg_normalizers import normalize_mcp_tool_kwargs
    return normalize_mcp_tool_kwargs(server_id, original_tool_name, kwargs, input_schema)


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
        else:
            logger.warning(f"MCP 配置文件不存在: {config_path}")
            # 默认配置示例
            self.server_configs = []
    
    async def connect_server(self, server_id: str, config: Dict[str, Any]) -> bool:
        """连接 MCP Server"""
        try:
            transport = config.get("transport", {})
            transport_type = transport.get("type", "stdio")

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
            """异步执行 MCP 工具。直接使用 session.call_tool，与主事件循环同任务，避免 sync 包装带来的额外开销与 anyio 跨任务错误。"""
            try:
                call_kwargs = normalize_mcp_kwargs_for_call(
                    server_id, original_tool_name, dict(kwargs or {}), input_schema=_input_schema
                )
                logger.debug("MCP call_tool: %s %s", original_tool_name, list(call_kwargs.keys()))
                result = await asyncio.wait_for(
                    session.call_tool(original_tool_name, call_kwargs), timeout=60.0
                )
                if result.content:
                    block = result.content[0]
                    return block.text if hasattr(block, "text") else str(block)
                return str(result)
            except asyncio.TimeoutError:
                logger.error("MCP 工具 %s 调用超时（60s）", original_tool_name)
                return f"Error: MCP 工具 {original_tool_name} 调用超时（60s），请稍后重试。"
            except Exception as e:
                logger.error("MCP 工具执行错误: %s", e, exc_info=True)
                return f"Error: {e}"

        description = mcp_tool.description or f"MCP tool: {mcp_tool.name}"
        if getattr(mcp_tool, "inputSchema", None) and isinstance(mcp_tool.inputSchema, dict):
            props = (mcp_tool.inputSchema or {}).get("properties") or {}
            if props:
                parts = [f"{k} ({v.get('type', 'string')})" for k, v in props.items()]
                description = f"{description} 参数: {', '.join(parts)}。"
        # 使用异步 func：graph/agent 侧已按 iscoroutinefunction 做 await，无需 sync 包装，避免 asyncio.run/run_until_complete 带来的新循环或跨任务问题
        langchain_tool = Tool(
            name=tool_name,
            description=description,
            func=tool_func,
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