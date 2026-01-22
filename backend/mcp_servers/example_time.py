from mcp.server.fastmcp import FastMCP

# 创建 MCP Server
mcp = FastMCP("Time Server")

@mcp.tool()
def get_time() -> str:
    """获取当前时间
    
    Returns:
        当前时间的字符串表示
    """
    from datetime import datetime
    now = datetime.now()
    return f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"

if __name__ == "__main__":
    # 运行 Server（stdio 模式）
    # 注意：在 stdio 模式下，mcp.run() 会阻塞等待 stdin 输入
    # 这是正常行为，不要手动运行此文件，应该通过 MCP 客户端启动
    mcp.run(transport="stdio")
