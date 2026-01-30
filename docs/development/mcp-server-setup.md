# MCP Server 配置指南

## 概述

本文档详细说明如何在 DHA 项目中配置和使用 MCP Server，包括创建自定义 MCP Server 和配置现有 MCP Server。

## 目录

1. [快速开始](#快速开始)
2. [创建简单的 MCP Server](#创建简单的-mcp-server)
3. [配置 MCP Server 到 DHA](#配置-mcp-server-到-dha)
4. [使用示例](#使用示例)
5. [常见问题](#常见问题)

## 快速开始

### 方式 1：使用现有的 MCP Server 示例

DHA 项目已经包含了 MCP SDK 的示例 Server，可以直接使用：

```bash
# 进入 MCP SDK 示例目录
cd MCP_Learn/python-sdk/examples/servers/simple-tool

# 安装依赖（如果需要）
pip install -e .

# 测试运行（stdio 模式）
python run_server.py
```

### 方式 2：配置到 DHA

编辑 `backend/config/mcp_servers.json`：

```json
[
  {
    "id": "simple-tool",
    "name": "简单工具 Server",
    "enabled": true,
    "transport": {
      "type": "stdio",
      "command": "python",
      "args": [
        "/Users/ggd/mycode/DHA/MCP_Learn/python-sdk/examples/servers/simple-tool/run_server.py"
      ]
    }
  }
]
```

**注意**：需要将路径替换为你的实际路径。

## 创建简单的 MCP Server

### 使用 FastMCP（推荐）

FastMCP 是最简单的方式创建 MCP Server。创建一个新的 MCP Server：

#### 1. 创建项目结构

```bash
mkdir my-mcp-server
cd my-mcp-server
```

#### 2. 创建 Server 文件

创建 `my_mcp_server.py`：

```python
"""我的 MCP Server"""
from mcp.server.fastmcp import FastMCP

# 创建 Server
mcp = FastMCP("My MCP Server")

@mcp.tool()
def calculate(operation: str, a: float, b: float) -> str:
    """执行数学计算
    
    Args:
        operation: 操作类型 (add, subtract, multiply, divide)
        a: 第一个数字
        b: 第二个数字
    
    Returns:
        计算结果
    """
    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    elif operation == "divide":
        if b == 0:
            return "Error: Division by zero"
        result = a / b
    else:
        return f"Error: Unknown operation {operation}"
    
    return f"Result: {result}"

@mcp.tool()
def get_weather(city: str) -> str:
    """获取城市天气（示例）
    
    Args:
        city: 城市名称
    
    Returns:
        天气信息
    """
    # 这里可以调用实际的天气 API
    return f"Weather in {city}: Sunny, 25°C"

if __name__ == "__main__":
    # 运行 Server（stdio 模式）
    mcp.run()
```

#### 3. 安装依赖

```bash
pip install mcp
```

#### 4. 测试运行

```bash
python my_mcp_server.py
```

Server 将在 stdio 模式下运行，可以通过 MCP Client 连接。

### 使用低级 API

如果需要更多控制，可以使用低级 API：

```python
from mcp.server.lowlevel import Server
import mcp.types as types

app = Server("my-server")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="my_tool",
            description="我的工具",
            input_schema={
                "type": "object",
                "properties": {
                    "param": {
                        "type": "string",
                        "description": "参数"
                    }
                }
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
    if name == "my_tool":
        param = arguments.get("param", "")
        return [types.TextContent(type="text", text=f"Result: {param}")]
    raise ValueError(f"Unknown tool: {name}")

# 运行 Server
from mcp.server.stdio import stdio_server
import anyio

async def run():
    async with stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())

anyio.run(run)
```

## 配置 MCP Server 到 DHA

### 步骤 1：准备 MCP Server

确保你的 MCP Server 可以正常运行：

```bash
# 测试运行
python your_mcp_server.py
```

### 步骤 2：编辑配置文件

编辑 `backend/config/mcp_servers.json`：

```json
[
  {
    "id": "my-calculator",
    "name": "计算器 Server",
    "enabled": true,
    "transport": {
      "type": "stdio",
      "command": "python",
      "args": [
        "/absolute/path/to/my_mcp_server.py"
      ],
      "env": {
        "PYTHONPATH": "/path/to/your/project"
      }
    },
    "metadata": {
      "description": "提供数学计算工具",
      "version": "1.0.0"
    }
  }
]
```

### 配置说明

#### stdio 传输配置

```json
{
  "type": "stdio",
  "command": "python",           // 命令（python, node, 等）
  "args": ["-m", "module"],      // 命令参数
  "env": {                       // 环境变量（可选）
    "API_KEY": "your-key"
  }
}
```

#### SSE 传输配置

```json
{
  "type": "sse",
  "url": "http://localhost:8000/sse",
  "headers": {                  // 请求头（可选）
    "Authorization": "Bearer token"
  }
}
```

**注意**：当前 DHA 实现主要支持 stdio 传输。

#### 添加远程 MCP Server（如 Linkup）

若你要接入 **远程 MCP 服务**（例如 [Linkup MCP](https://mcp.linkup.so)），只需在 `backend/config/mcp_servers.json` 里增加一条配置，**不需要**填写网页上的 DOM Path、Position、HTML 等界面元素信息；只需填写连接地址和传输方式。

**Linkup 远程 MCP 示例**（官方文档：<https://docs.linkup.so/pages/integrations/mcp/mcp>）：

```json
{
  "id": "linkup",
  "name": "Linkup MCP（远程）",
  "enabled": true,
  "transport": {
    "type": "http",
    "url": "https://mcp.linkup.so/mcp?apiKey=YOUR_LINKUP_API_KEY",
    "headers": {}
  },
  "metadata": {
    "description": "Linkup 远程 MCP：linkup-search 搜索、linkup-fetch 抓取网页",
    "version": "1.0.0"
  }
}
```

**操作步骤：**

1. 在 [Linkup](https://app.linkup.so) 注册并获取 API Key。
2. 把上例中的 `YOUR_LINKUP_API_KEY` 换成你的真实 API Key。
3. 将上述对象追加到 `backend/config/mcp_servers.json` 的数组中（或使用项目里已提供的 `linkup` 示例条，修改 `url` 中的 apiKey 并将 `enabled` 设为 `true`）。
4. **已支持远程**：DHA 的 MCP 管理器已支持 **Streamable HTTP**。`transport.type` 为 `http`、`streamable_http` 或 `sse` 时，会使用 MCP SDK 的 `streamable_http_client` 连接远程 URL；需已安装 `mcp` 与 `httpx`。

#### Exa / Fetch / Mem0（wechat-article-writer 等 skill 可选）

项目已在 `mcp_servers.json` 中预置以下三条，按需启用即可：

| Server | 用途 | 启用方式 |
|--------|------|----------|
| **exa** | 搜索（web_search_exa 等） | 在 [Exa Dashboard](https://dashboard.exa.ai/api-keys) 获取 API Key，将配置里 url 中的 `YOUR_EXA_API_KEY` 替换后，把 `enabled` 设为 `true`。 |
| **fetch** | 网页抓取（fetch_fetch，等价 web_fetch） | 执行 `pip install mcp-server-fetch`（或已写在 `requirements.txt`），保持 `enabled: true`。stdio 命令为 `python -m mcp_server_fetch`。 |
| **mem0** | 长期记忆（添加/搜索记忆） | 在 [Mem0](https://app.mem0.ai) 获取 API Key（格式 `sk_mem0_...`），将 transport.env 中的 `YOUR_MEM0_API_KEY` 替换后，把 `enabled` 设为 `true`。 |

- **Exa**：远程 HTTP，`url` 格式为 `https://mcp.exa.ai/mcp?exaApiKey=你的KEY`。
- **Fetch**：stdio，需已安装 `mcp-server-fetch`；工具在运行时名为 `fetch_fetch`。
- **Mem0**：stdio，需已安装 `mem0-mcp-server`；需设置环境变量 `MEM0_API_KEY` 和可选 `MEM0_DEFAULT_USER_ID`。

### 步骤 3：重启后端服务

```bash
# 重启后端
# 后端会在启动时自动加载配置的 MCP Server
```

### 步骤 4：验证连接

查看后端日志，确认 MCP Server 连接成功：

```
INFO: MCP Server 'my-calculator' connected successfully
INFO: Loaded 2 tools from 'my-calculator'
```

## 使用示例

### 示例 1：使用 simple-tool Server

#### 配置

```json
{
  "id": "website-fetcher",
  "name": "网站抓取工具",
  "enabled": true,
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": [
      "/Users/ggd/mycode/DHA/MCP_Learn/python-sdk/examples/servers/simple-tool/run_server.py"
    ]
  }
}
```

#### 使用

在聊天界面中，Agent 可以自动使用 `fetch` 工具：

```
用户: 帮我获取 https://example.com 的内容
Agent: [调用 fetch 工具] 正在获取网站内容...
```

### 示例 2：创建文件操作 Server

#### 创建 Server

```python
from mcp.server.fastmcp import FastMCP
from pathlib import Path

mcp = FastMCP("File Operations Server")

@mcp.tool()
def read_file(file_path: str) -> str:
    """读取文件内容
    
    Args:
        file_path: 文件路径
    
    Returns:
        文件内容
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def write_file(file_path: str, content: str) -> str:
    """写入文件
    
    Args:
        file_path: 文件路径
        content: 文件内容
    
    Returns:
        操作结果
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote to {file_path}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def list_directory(dir_path: str) -> str:
    """列出目录内容
    
    Args:
        dir_path: 目录路径
    
    Returns:
        目录内容列表
    """
    try:
        path = Path(dir_path)
        if not path.exists():
            return f"Error: Directory {dir_path} does not exist"
        
        items = []
        for item in path.iterdir():
            items.append(f"{'[DIR]' if item.is_dir() else '[FILE]'} {item.name}")
        
        return "\n".join(items)
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    mcp.run()
```

#### 配置

```json
{
  "id": "file-ops",
  "name": "文件操作 Server",
  "enabled": true,
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": ["/path/to/file_ops_server.py"]
  }
}
```

### 示例 3：使用环境变量

如果 MCP Server 需要 API Key 等配置：

```json
{
  "id": "api-server",
  "name": "API Server",
  "enabled": true,
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "my_api_server"],
    "env": {
      "API_KEY": "your-api-key-here",
      "API_URL": "https://api.example.com"
    }
  }
}
```

## 常见问题

### Q1: MCP Server 连接失败

**问题**：后端日志显示连接失败

**解决方案**：
1. 检查 MCP Server 路径是否正确（使用绝对路径）
2. 确保 MCP Server 可以独立运行
3. 检查 Python 环境和依赖是否安装
4. 查看后端日志获取详细错误信息

### Q2: 工具未显示

**问题**：配置了 MCP Server，但工具未出现在 Agent 中

**解决方案**：
1. 确认 MCP Server 的 `enabled` 字段为 `true`
2. 检查后端启动日志，确认工具已加载
3. 验证 MCP Server 的 `list_tools()` 方法是否正确实现

### Q3: 工具调用失败

**问题**：Agent 调用工具时出错

**解决方案**：
1. 检查工具参数是否正确
2. 查看 MCP Server 的错误日志
3. 验证工具的实现逻辑

### Q4: 多个 MCP Server 工具名称冲突

**问题**：不同 Server 有同名工具

**解决方案**：
当前实现会在工具名前添加 Server ID 前缀，例如：
- Server ID: `file-ops`
- 工具名: `read_file`
- 实际工具名: `file-ops_read_file`

### Q5: 如何调试 MCP Server

**调试步骤**：
1. 独立运行 MCP Server，测试是否正常
2. 使用 MCP Inspector 工具连接测试
3. 查看后端日志中的详细错误信息
4. 在 MCP Server 中添加日志输出

## 最佳实践

1. **使用绝对路径**：在配置中使用绝对路径，避免路径问题
2. **环境隔离**：为每个 MCP Server 配置独立的环境变量
3. **错误处理**：在 MCP Server 中实现完善的错误处理
4. **文档完善**：为每个工具提供清晰的描述和参数说明
5. **测试先行**：在集成到 DHA 前，先独立测试 MCP Server

## 参考资源

- [MCP 官方文档](https://modelcontextprotocol.io)
- [MCP Python SDK GitHub](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Python SDK 文档](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs)
- [FastMCP 示例](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples/fastmcp)
- [MCP Server 示例](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples/servers)

## 下一步

- 查看 [MCP 配置文档](../features/mcp-config.md) 了解完整的 MCP 功能
- 查看 [开发设置文档](./setup.md) 了解开发环境配置
- 查看 [API 设计文档](../architecture/api-design.md) 了解 API 接口
