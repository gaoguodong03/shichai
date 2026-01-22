#!/usr/bin/env python3
"""示例计算器 MCP Server

这是一个简单的 MCP Server 示例，提供数学计算工具。

使用方法：
    python example_calculator.py

配置到 DHA：
    在 backend/config/mcp_servers.json 中添加：
    {
      "id": "calculator",
      "name": "计算器 Server",
      "enabled": true,
      "transport": {
        "type": "stdio",
        "command": "python",
        "args": ["/absolute/path/to/example_calculator.py"]
      }
    }
"""
from mcp.server.fastmcp import FastMCP

# 创建 MCP Server
mcp = FastMCP("Calculator Server")

@mcp.tool()
def calculate(operation: str, a: float, b: float) -> str:
    """执行数学计算
    
    Args:
        operation: 操作类型，可选值: add (加法), subtract (减法), multiply (乘法), divide (除法)
        a: 第一个数字
        b: 第二个数字
    
    Returns:
        计算结果字符串
    """
    try:
        if operation == "add":
            result = a + b
            return f"{a} + {b} = {result}"
        elif operation == "subtract":
            result = a - b
            return f"{a} - {b} = {result}"
        elif operation == "multiply":
            result = a * b
            return f"{a} × {b} = {result}"
        elif operation == "divide":
            if b == 0:
                return "错误：除数不能为零"
            result = a / b
            return f"{a} ÷ {b} = {result}"
        else:
            return f"错误：不支持的操作 '{operation}'。支持的操作: add, subtract, multiply, divide"
    except Exception as e:
        return f"错误：{str(e)}"


if __name__ == "__main__":
    # 运行 Server（stdio 模式）
    # 注意：在 stdio 模式下，mcp.run() 会阻塞等待 stdin 输入
    # 这是正常行为，不要手动运行此文件，应该通过 MCP 客户端启动
    mcp.run(transport="stdio")
