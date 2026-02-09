# MCP 操作指南：从 MCP.so 搜选到接入

本指南说明如何从 [MCP.so](https://mcp.so) 搜选 MCP，并完成**远程接入**或**本地编写**两种方式的配置。

---

## 一、在 MCP.so 中搜选 MCP

### 1.1 访问平台

打开 [MCP.so](https://mcp.so)，可浏览并搜索 MCP 服务器。

### 1.2 搜索与筛选

- **首页**：展示 Featured MCP Servers、Hosted、Official 等
- **Servers**：按类别、标签筛选
- **Categories**：如 developer-tools、productivity、search 等
- **Tags**：如 #time、#search、#official 等
- **搜索**：通过关键词查找（如 web search、fetch、calendar）

### 1.3 识别接入方式

每个 MCP 详情页通常包含：

| 信息 | 说明 |
|------|------|
| **Server Config** | 配置示例（Claude / Cursor 格式），可参考转换为 DHA 格式 |
| **Hosted** 标签 | 提供远程 HTTP URL，可直接远程接入 |
| **Visit Server** | 指向 GitHub 源码，本地编写时参考 |
| **Tools** Tab | 工具列表，便于了解能力 |

**判断接入方式**：

- 有 **Hosted** 且提供 HTTP URL → 适合**远程接入**
- 有 `pip install` / `uvx` / `npx` 等安装说明 → 适合**本地 stdio 接入**
- 有 GitHub 源码 → 可**本地编写**自定义 MCP

---

## 二、远程接入 MCP

适用于提供 HTTP/Streamable HTTP 的 MCP（如 Linkup、Exa、部分 Hosted 服务）。

### 2.1 在 MCP.so 获取配置信息

1. 进入目标 MCP 详情页（如 [Time](https://mcp.so/server/time/modelcontextprotocol)）
2. 查看 **Server Config** 或 **Hosted** 说明
3. 记录：
   - 远程 URL（含 API Key 参数格式）
   - 所需 API Key 获取地址（若有）

### 2.2 获取 API Key（若需要）

很多远程 MCP 需要 API Key，例如：

| MCP | API Key 获取 |
|-----|--------------|
| Linkup | [app.linkup.so](https://app.linkup.so) 注册获取 |
| Exa | [dashboard.exa.ai/api-keys](https://dashboard.exa.ai/api-keys) |
| Brave Search | [brave.com/search/api](https://brave.com/search/api) |

### 2.3 配置到 DHA

编辑 `backend/config/mcp_servers.json`，在数组中新增一条：

```json
{
  "id": "唯一标识",
  "name": "显示名称",
  "enabled": true,
  "transport": {
    "type": "http",
    "url": "https://服务商域名/mcp?apiKey=你的API_KEY",
    "headers": {}
  },
  "metadata": {
    "description": "功能描述",
    "version": "1.0.0"
  }
}
```

**注意**：

- `url` 中可直接写 API Key，或使用 `${VAR}` 从环境变量读取（见下方）
- 若服务商要求 Header 认证，可在 `headers` 中配置，支持 `${VAR}` 替换

**环境变量方式**（推荐，便于保密）：

```json
{
  "transport": {
    "type": "http",
    "url": "https://mcp.example.com/mcp",
    "headers": {
      "Authorization": "Bearer ${MY_MCP_API_KEY}"
    }
  }
}
```

在 `backend/.env` 中设置：

```
MY_MCP_API_KEY=你的密钥
```

### 2.4 示例：Linkup 远程接入

```json
{
  "id": "linkup",
  "name": "Linkup MCP（远程）",
  "enabled": true,
  "transport": {
    "type": "http",
    "url": "https://mcp.linkup.so/mcp?apiKey=你的Linkup_API_KEY",
    "headers": {}
  },
  "metadata": {
    "description": "Linkup 远程 MCP：linkup-search 搜索、linkup-fetch 抓取网页",
    "version": "1.0.0"
  }
}
```

### 2.5 重启并验证

```bash
# 重启后端
cd backend && python -m uvicorn app.main:app --reload
```

查看启动日志，确认出现类似：

```
INFO: MCP Server 'linkup' 连接成功 (Streamable HTTP)
INFO: 成功加载工具: linkup_linkup-search ...
```

---

## 三、本地编写 MCP

适用于需要自定义逻辑、或 MCP.so 上仅有源码无 Hosted 服务的情况。

### 3.1 创建 MCP 文件

在 `backend/mcp_servers/` 下新建 Python 文件，例如 `my_custom.py`：

```python
"""自定义 MCP Server"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("我的自定义 MCP")

@mcp.tool()
def my_tool(param: str) -> str:
    """工具描述，供 LLM 理解用途
    
    Args:
        param: 参数说明
    
    Returns:
        返回值说明
    """
    return f"处理结果: {param}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

### 3.2 安装依赖

```bash
pip install mcp
```

若使用 FastMCP：

```bash
pip install mcp[fastmcp]
# 或
pip install mcp
```

### 3.3 测试运行

```bash
cd backend/mcp_servers
python my_custom.py
```

在 stdio 模式下会等待 stdin，属正常现象。用 Ctrl+C 退出即可。

### 3.4 配置到 DHA

编辑 `backend/config/mcp_servers.json`，新增：

```json
{
  "id": "my-custom",
  "name": "我的自定义 MCP",
  "enabled": true,
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": ["/Users/ggd/mycode/DHA/backend/mcp_servers/my_custom.py"],
    "env": {}
  },
  "metadata": {
    "description": "自定义工具描述",
    "version": "1.0.0"
  }
}
```

**路径说明**：

- 建议使用**绝对路径**，避免工作目录影响
- `command` 为 `python` 时，后端会使用当前 Python 解释器

**环境变量**（如需要 API Key）：

```json
"transport": {
  "type": "stdio",
  "command": "python",
  "args": ["/path/to/my_custom.py"],
  "env": {
    "MY_API_KEY": "密钥",
    "OTHER_VAR": "值"
  }
}
```

### 3.5 使用 pip 安装的 MCP 包

若 MCP 通过 `pip install` 安装（如 `mcp-server-fetch`、`mcp-server-time`），可用 `-m` 方式：

```json
{
  "id": "fetch",
  "name": "Fetch 网页抓取 MCP",
  "enabled": true,
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "mcp_server_fetch"]
  },
  "metadata": {
    "description": "抓取 URL 内容并转为 Markdown",
    "version": "1.0.0"
  }
}
```

**操作步骤**：

1. 在 MCP.so 找到对应 MCP 的 `pip install` 命令
2. 执行安装：`pip install mcp-server-fetch`
3. 在配置中使用 `args: ["-m", "模块名"]`

### 3.6 示例：参考 MCP.so 的 Server Config 转换

MCP.so 常见格式（Claude/Cursor）：

```json
{
  "mcpServers": {
    "time": {
      "command": "uvx",
      "args": ["mcp-server-time", "--local-timezone=America/New_York"]
    }
  }
}
```

转换为 DHA 格式：

```json
{
  "id": "time",
  "name": "时间 MCP",
  "enabled": true,
  "transport": {
    "type": "stdio",
    "command": "uvx",
    "args": ["mcp-server-time", "--local-timezone=Asia/Shanghai"]
  },
  "metadata": {
    "description": "获取当前时间、时区转换",
    "version": "1.0.0"
  }
}
```

若使用 `python -m`：

```json
{
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "mcp_server_time"]
  }
}
```

（具体模块名以 MCP 官方文档为准）

---

## 四、配置格式速查

### 4.1 远程 HTTP

```json
{
  "id": "唯一id",
  "name": "名称",
  "enabled": true,
  "transport": {
    "type": "http",
    "url": "https://...",
    "headers": {}
  },
  "metadata": { "description": "...", "version": "1.0.0" }
}
```

### 4.2 本地 stdio（脚本文件）

```json
{
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": ["/绝对路径/script.py"],
    "env": {}
  }
}
```

### 4.3 本地 stdio（pip 模块）

```json
{
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "module_name"],
    "env": {}
  }
}
```

---

## 五、常见问题

### Q1: 远程 MCP 连接超时

- 检查 `url` 是否正确、API Key 是否有效
- 确认已安装 `mcp` 与 `httpx`：`pip install mcp httpx`

### Q2: 本地 MCP 启动失败

- 用绝对路径
- 单独运行脚本确认无报错
- 检查 `pip` 包是否已安装（`-m` 方式）

### Q3: 工具未出现在 Agent 中

- 确认 `enabled: true`
- 查看后端日志是否加载成功
- 工具名会带前缀，如 `linkup_linkup-search`

### Q4: API Key 如何安全配置

- 使用 `transport.headers` 的 `"Bearer ${VAR}"` 形式
- 在 `backend/.env` 中设置变量，勿提交到 Git

---

## 六、相关文档

- [MCP Server 配置指南](./mcp-server-setup.md) - 创建自定义 MCP、详细配置说明
- [MCP 配置功能](../features/mcp-config.md) - API 与功能概览
- [MCP.so 平台](https://mcp.so) - 搜索与发现 MCP
