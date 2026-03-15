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

## 如何添加新 Server

1. **配置文件位置**：`backend/config/mcp_servers.json`（或在环境变量 `MCP_CONFIG_PATH` 指定的路径）。
2. **本地 stdio**：在数组里新增一条，`transport.type` 为 `stdio`，填写 `command` 和 `args`（如 `"command": "python"`, `"args": ["/绝对路径/your_server.py"]`）。
3. **远程 HTTP（如 Linkup）**：在数组里新增一条，`transport.type` 为 `http`，`transport.url` 填完整地址（如 Linkup：`https://mcp.linkup.so/mcp?apiKey=你的API_KEY`）。**不需要**从网页上复制 DOM Path、Position、HTML 等界面元素，只需 URL 和传输类型。
4. **当前实现**：后端 MCP 管理器支持 **stdio**（本地）与 **HTTP/Streamable HTTP**（远程）。`transport.type` 为 `http`、`streamable_http` 或 `sse` 时使用远程连接。详细步骤见 [MCP Server 配置指南](../development/mcp-server-setup.md#添加远程-mcp-server如-linkup)。

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

### 生命周期与连接

- **初始化时机**：在 FastAPI **lifespan 启动阶段**执行 `ensure_mcp_and_skills_initialized()`，建立所有已启用 MCP Server 的连接（stdio 或 Streamable HTTP）。与 anyio/MCP SDK 要求一致：同一 asyncio 任务内 enter/exit，避免关闭时报「跨任务 cancel scope」错误。
- **清理时机**：在 lifespan **关闭阶段**于同一任务中调用 `get_mcp_manager().cleanup()`，关闭所有 session 与传输。

### 调用方式（规范、异步）

- **Tool 形态**：每个 MCP 工具被封装为一个 LangChain `Tool`，**`func` 为异步函数**，直接在该函数内调用 `session.call_tool(tool_name, arguments)`，不包同步壳（不使用 `asyncio.run` / `run_until_complete`）。
- **执行路径**：技能执行 Agent（ReAct）在需要调用工具时，通过 `await tool.func(**arguments)` 执行，与主事件循环同任务，无额外线程或新事件循环。
- **参数规范**：LLM 可能输出通用占位参数（如 `__arg1`）；在调用 MCP 前由 `normalize_mcp_kwargs_for_call`（及 `tool_arg_normalizers`）按工具 `inputSchema` 做映射（如 `__arg1` → schema 首参），并去除占位键，保证传给 MCP 的是 schema 要求的参数名。

### Python MCP SDK 使用示例

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(command="python", args=["-m", "mcp_server_fs"])
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        # 调用时使用 MCP 工具原始名 + schema 参数名
        result = await session.call_tool("read_pdf", {"path": "/tmp/test.pdf"})
```

### 工具名与参数

- **系统内工具名**：`{server_id}_{tool_name}`，例如 `file-reader_read_pdf`、`filesystem_read_text_file`。Agent 与前端使用该名称；底层调用 MCP 时使用 `tool_name`（如 `read_pdf`）和规范化后的参数字典。
- **推荐**：在 SKILL 中写明「使用参数名 `description` / `path` / `query` 等」，与 MCP 的 inputSchema 一致；系统会对 `__arg1` 等做自动映射，但直接使用 schema 参数名兼容性最佳。

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
  "tools": ["file-reader_read_pdf", "filesystem_read_text_file", "filesystem_list_dir"]
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

- [MCP 操作指南](../development/mcp-operation-guide.md) - 从 MCP.so 搜选、远程接入与本地编写 MCP 的操作步骤
- [MCP 官方文档](https://modelcontextprotocol.io)
- [MCP Python SDK GitHub](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Python SDK 文档](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs)
- [LangChain Tools 文档](https://python.langchain.com/docs/modules/tools)
