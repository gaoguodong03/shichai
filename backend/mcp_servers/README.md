# MCP Servers 示例

这个目录包含可以直接使用的 MCP Server 示例。

## 示例列表

### example_calculator.py

一个简单的计算器 Server，提供数学计算工具。

**功能**：
- `calculate`: 执行数学计算（加法、减法、乘法、除法）
- `get_time`: 获取当前时间

**使用方法**：

1. 测试运行：
```bash
python example_calculator.py
```

2. 配置到 DHA：

编辑 `backend/config/mcp_servers.json`：

```json
[
  {
    "id": "calculator",
    "name": "计算器 Server",
    "enabled": true,
    "transport": {
      "type": "stdio",
      "command": "python",
      "args": [
        "/absolute/path/to/backend/mcp_servers/example_calculator.py"
      ]
    }
  }
]
```

**注意**：将路径替换为你的实际绝对路径。

## 创建自定义 MCP Server

参考 [MCP Server 配置指南](../../docs/development/mcp-server-setup.md) 了解如何创建自己的 MCP Server。

## 更多示例

查看 `MCP_Learn/python-sdk/examples/servers/` 目录获取更多 MCP Server 示例。
