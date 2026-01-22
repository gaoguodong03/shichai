# MCP 配置

## 概述

MCP (Model Context Protocol) 配置功能允许用户配置和管理 MCP Server，将 MCP Server 的工具、资源和提示转换为 Agent 可用的能力。本项目使用 Python MCP SDK 直接集成 MCP Server，无需额外的适配器。

## MCP 协议基础

### 核心概念

MCP 定义了三个核心原语：

1. **Tools（工具）**: 模型控制的函数，Agent 可以调用执行操作
2. **Resources（资源）**: 应用控制的数据，提供上下文信息
3. **Prompts（提示）**: 用户控制的模板，用于交互式输入

### 传输方式

MCP Server 支持多种传输方式：

- **stdio**: 标准输入输出（适合本地进程）
- **SSE**: Server-Sent Events（适合 HTTP 服务）
- **HTTP**: HTTP 请求/响应（适合 RESTful 服务）

## 功能特性

### MCP Server 管理

- **添加 MCP Server**: 支持配置新的 MCP Server
- **编辑配置**: 修改 Server 的连接参数和设置
- **删除 Server**: 移除不再需要的 MCP Server
- **启用/禁用**: 动态启用或禁用特定的 MCP Server
- **连接测试**: 测试 MCP Server 的连接状态

### 工具发现和注册

- **自动发现**: 自动发现 MCP Server 提供的工具
- **工具列表**: 显示所有可用工具的详细信息
- **工具注册**: 将 MCP 工具注册到 Agent 工具注册表
- **工具验证**: 验证工具的参数和返回值格式

### 多 Server 支持

- **并发运行**: 支持多个 MCP Server 同时运行
- **工具命名空间**: 避免不同 Server 的工具名称冲突
- **资源管理**: 管理多个 Server 的资源访问

## 配置格式

### MCP Server 配置

每个 MCP Server 的配置包含以下信息：

```json
{
  "id": "mcp-server-1",
  "name": "文件系统 MCP",
  "enabled": true,
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "mcp_server_fs"]
  },
  "metadata": {
    "description": "提供文件系统操作工具",
    "version": "1.0.0"
  }
}
```

### 传输配置示例

**stdio 传输**:
```json
{
  "type": "stdio",
  "command": "python",
  "args": ["-m", "mcp_server_fs"],
  "env": {
    "API_KEY": "your-api-key"
  }
}
```

**SSE 传输**:
```json
{
  "type": "sse",
  "url": "http://localhost:8000/sse",
  "headers": {
    "Authorization": "Bearer token"
  }
}
```

**HTTP 传输**:
```json
{
  "type": "http",
  "base_url": "http://localhost:8000/mcp",
  "headers": {
    "Authorization": "Bearer token"
  }
}
```

## 实现要点

### Python MCP SDK 集成

使用 `/Users/ggd/mycode/DHA/MCP_Learn/python-sdk` 中的 MCP SDK：

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 创建 MCP Client
server_params = StdioServerParameters(
    command="python",
    args=["-m", "mcp_server_fs"]
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        # 初始化连接
        await session.initialize()
        
        # 列出可用工具
        tools = await session.list_tools()
        
        # 调用工具
        result = await session.call_tool("read_file", {"path": "/tmp/test.txt"})
```

### 工具注册到 LangChain

将 MCP 工具转换为 LangChain 工具：

```python
from langchain.tools import Tool
from typing import Callable

def create_langchain_tool(mcp_tool, session: ClientSession) -> Tool:
    """将 MCP 工具转换为 LangChain 工具"""
    async def tool_func(**kwargs):
        result = await session.call_tool(mcp_tool.name, kwargs)
        return result.content[0].text if result.content else ""
    
    return Tool(
        name=mcp_tool.name,
        description=mcp_tool.description,
        func=tool_func
    )
```

### 工具注册表管理

```python
from app.tools.registry import ToolRegistry

class MCPToolManager:
    def __init__(self):
        self.registry = ToolRegistry()
        self.sessions: Dict[str, ClientSession] = {}
    
    async def register_mcp_server(self, config: MCPServerConfig):
        """注册 MCP Server 并加载其工具"""
        session = await self.connect_to_server(config)
        tools = await session.list_tools()
        
        for tool in tools:
            langchain_tool = create_langchain_tool(tool, session)
            self.registry.register_tool(langchain_tool)
        
        self.sessions[config.id] = session
    
    async def unregister_mcp_server(self, server_id: str):
        """注销 MCP Server"""
        if server_id in self.sessions:
            await self.sessions[server_id].close()
            del self.sessions[server_id]
```

## API 设计

### RESTful API 端点

- `GET /api/settings/mcp`: 获取所有 MCP Server 配置
- `POST /api/settings/mcp`: 添加新的 MCP Server
- `PUT /api/settings/mcp/{id}`: 更新 MCP Server 配置
- `DELETE /api/settings/mcp/{id}`: 删除 MCP Server
- `POST /api/settings/mcp/{id}/enable`: 启用 MCP Server
- `POST /api/settings/mcp/{id}/disable`: 禁用 MCP Server
- `GET /api/settings/mcp/{id}/tools`: 获取 MCP Server 的工具列表
- `POST /api/settings/mcp/{id}/test`: 测试 MCP Server 连接

### 请求/响应示例

**获取 MCP Server 列表**:
```json
GET /api/settings/mcp

Response:
{
  "servers": [
    {
      "id": "mcp-server-1",
      "name": "文件系统 MCP",
      "enabled": true,
      "tool_count": 5,
      "status": "connected"
    }
  ]
}
```

**添加 MCP Server**:
```json
POST /api/settings/mcp

Request:
{
  "name": "文件系统 MCP",
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "mcp_server_fs"]
  }
}

Response:
{
  "id": "mcp-server-1",
  "status": "connected",
  "tools": ["read_file", "write_file", "list_directory"]
}
```

## 最佳实践

1. **连接管理**: 使用连接池管理多个 MCP Server 连接
2. **错误处理**: 实现重试机制和错误恢复
3. **工具命名**: 使用命名空间避免工具名称冲突
4. **资源清理**: 确保在 Server 禁用时正确清理资源
5. **配置验证**: 在添加 Server 前验证配置的有效性
6. **性能监控**: 监控工具调用的性能和错误率

## 安全考虑

1. **权限控制**: 限制 MCP Server 可以访问的资源
2. **输入验证**: 验证工具参数，防止注入攻击
3. **沙箱隔离**: 考虑在沙箱环境中运行 MCP Server
4. **审计日志**: 记录所有工具调用，便于审计

## 参考资源

- [MCP 官方文档](https://modelcontextprotocol.io)
- [MCP Python SDK 文档](/Users/ggd/mycode/DHA/MCP_Learn/python-sdk/docs)
- [LangChain Tools 文档](https://python.langchain.com/docs/modules/tools)
