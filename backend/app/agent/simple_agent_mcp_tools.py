from __future__ import annotations

from app.agent.messages import AIMessage


def _mcp_tool_result_direct_final_message(tool_out: dict[str, Any]) -> AIMessage | None:
    """MCP success output is tool evidence; the expert finalizer must write the reply."""
    _ = tool_out
    return None
