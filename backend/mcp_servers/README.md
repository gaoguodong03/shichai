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

### file_reader_mcp.py

文件读取 MCP，从 `data/agent-outputs` 提取 PDF/DOC/Excel 文本供 LLM 使用。

**功能**：
- `read_file`: 读取纯文本（txt、md、json 等）
- `read_pdf`: 从 PDF 提取文本
- `read_docx`: 从 DOCX 提取文本
- `read_xlsx`: 从 Excel 提取文本

**依赖**：`pip install pypdf python-docx openpyxl`

**配置**：已在 `config/mcp_servers.json` 中默认添加，id 为 `file-reader`。

## 更多示例

查看 `MCP_Learn/python-sdk/examples/servers/` 目录获取更多 MCP Server 示例。
