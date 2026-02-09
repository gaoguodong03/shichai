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
        logger.info(f"连接 MCP Server: {server_id}")
        try:
            transport = config.get("transport", {})
            transport_type = transport.get("type", "stdio")
            logger.info(f"传输类型: {transport_type}")
            
            if transport_type == "stdio":
                command = transport.get("command", "python")
                args = transport.get("args", [])
                
                # 如果命令是 "python"，使用当前 Python 解释器
                if command == "python" or command == "python3":
                    import sys
                    command = sys.executable
                
                env = transport.get("env")
                params = StdioServerParameters(
                    command=command,
                    args=args,
                    env=env if isinstance(env, dict) else None,
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
                
                logger.info("创建 ClientSession（使用异步上下文管理器）...")
                # 根据 MCP 官方文档，ClientSession 应该作为异步上下文管理器使用
                # 使用 exit_stack 来管理，保持连接打开
                try:
                    session = await self.exit_stack.enter_async_context(
                        ClientSession(read, write)
                    )
                    # 添加超时保护（30秒），asyncio 在文件顶部已导入
                    await asyncio.wait_for(session.initialize(), timeout=30.0)
                    logger.info("MCP Session 初始化成功")
                except asyncio.TimeoutError:
                    logger.error("MCP Session 初始化超时（30秒），可能的原因：")
                    raise
                except Exception as e:
                    logger.error(f"MCP Session 初始化失败: {e}", exc_info=True)
                    raise
                
                self.sessions[server_id] = session
                logger.info(f"MCP Server {server_id} 连接成功")
                await self._load_tools_from_server(server_id, session)
                return True

            elif transport_type in ("http", "streamable_http", "sse") and _streamable_http_available:
                # 远程 HTTP / Streamable HTTP：使用 MCP SDK 的 streamable_http_client
                url = (transport.get("url") or transport.get("base_url") or "").strip()
                if not url:
                    logger.error(f"MCP Server {server_id}: HTTP 传输缺少 url 或 base_url")
                    return False
                raw_headers = dict(transport.get("headers") or {})
                # 支持 ${VAR} 环境变量替换，便于安全配置 API Key（如 "Bearer ${SMITHERY_API_KEY}"）
                def _subst_env(s: str) -> str:
                    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), s)
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
                    logger.info("MCP Session (Streamable HTTP) 初始化成功")
                except asyncio.TimeoutError:
                    logger.error(f"MCP Server {server_id} Streamable HTTP 初始化超时（30秒）")
                    raise
                except Exception as e:
                    logger.error(f"MCP Server {server_id} Streamable HTTP 连接失败: {e}", exc_info=True)
                    raise
                self.sessions[server_id] = session
                logger.info(f"MCP Server {server_id} 连接成功 (Streamable HTTP)")
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
        logger.info(f"从 MCP Server {server_id} 加载工具...")
        try:
            tools_result = await session.list_tools()
            logger.info(f"MCP Server {server_id} 返回 {len(tools_result.tools)} 个工具")
            
            for mcp_tool in tools_result.tools:
                logger.info(f"处理工具: {mcp_tool.name}, 描述: {mcp_tool.description}")
                # 创建 LangChain Tool（传入 server_id 用于生成唯一名称）
                langchain_tool = self._create_langchain_tool(mcp_tool, session, server_id)
                tool_name = f"{server_id}_{mcp_tool.name}" if server_id else mcp_tool.name
                self.tools[tool_name] = langchain_tool
                logger.info(f"成功加载工具: {tool_name} (原始名称: {mcp_tool.name})")
        except Exception as e:
            logger.error(f"Failed to load tools from server {server_id}: {e}", exc_info=True)
    
    def _create_langchain_tool(self, mcp_tool, session: ClientSession, server_id: Optional[str] = None) -> Tool:
        """将 MCP 工具转换为 LangChain Tool"""
        # 保存原始工具名和 session 引用
        original_tool_name = mcp_tool.name
        tool_name = f"{server_id}_{mcp_tool.name}" if server_id else mcp_tool.name
        
        async def tool_func(**kwargs):
            logger.info(f"执行工具: {original_tool_name}, 参数: {kwargs}")
            try:
                # 使用原始工具名调用 MCP Server
                logger.info(f"调用 MCP Session: call_tool({original_tool_name}, {kwargs})")
                result = await session.call_tool(original_tool_name, kwargs)
                logger.info(f"MCP 调用返回结果类型: {type(result)}")
                
                if result.content:
                    text_result = result.content[0].text if hasattr(result.content[0], 'text') else str(result.content[0])
                    logger.info(f"工具执行结果: {text_result}")
                    return text_result
                logger.info(f"工具执行结果（无 content）: {str(result)}")
                return str(result)
            except Exception as e:
                error_msg = f"Error: {str(e)}"
                logger.error(f"工具执行错误: {error_msg}", exc_info=True)
                return error_msg
        
        # 若有 inputSchema，把参数说明拼进 description，避免 LLM 误以为只接受一个参数
        description = mcp_tool.description or f"MCP tool: {mcp_tool.name}"
        if getattr(mcp_tool, "inputSchema", None) and isinstance(mcp_tool.inputSchema, dict):
            props = mcp_tool.inputSchema.get("properties") or {}
            if props:
                parts = [f"{k} ({v.get('type', 'string')})" for k, v in props.items()]
                description = f"{description} 参数: {', '.join(parts)}。"
        return Tool(
            name=tool_name,
            description=description,
            func=tool_func,
        )
    
    def get_tools(self) -> List[Tool]:
        """获取所有工具"""
        return list(self.tools.values())
    
    async def initialize_all(self):
        """初始化所有配置的 MCP Server"""
        logger.info("开始初始化所有 MCP Servers")
        await self.load_config()
        
        enabled_count = 0
        for config in self.server_configs:
            server_id = config.get("id", f"server_{len(self.sessions)}")
            if config.get("enabled", True):
                enabled_count += 1
                try:
                    success = await self.connect_server(server_id, config)
                    if success:
                        logger.info(f"MCP Server {server_id} 初始化成功")
                    else:
                        logger.error(f"MCP Server {server_id} 初始化失败")
                except asyncio.CancelledError:
                    raise  # 请求被取消时继续向上抛出
                except Exception as e:
                    logger.error(f"MCP Server {server_id} 初始化异常，跳过: {e}", exc_info=True)
        
        logger.info(f"MCP 初始化完成: 共 {len(self.server_configs)} 个配置，{enabled_count} 个启用，{len(self.sessions)} 个连接成功，{len(self.tools)} 个工具加载")
    
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