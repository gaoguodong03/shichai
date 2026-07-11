from __future__ import annotations

from typing import Any

from app.agent.simple_agent_streaming import stream_simple_agent


async def invoke_simple_agent(agent: Any, initial_state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
    """Collect the canonical streaming loop into the non-streaming SimpleAgent result contract."""
    final_messages = []
    final_tool_attempt_debug: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    tool_raw_outputs: list[str] = []

    async for event in stream_simple_agent(agent, initial_state, config=config):
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "tool_step":
            tc = event.get("tool_calls")
            if isinstance(tc, list):
                tool_calls.extend([x for x in tc if isinstance(x, dict)])
            trs = event.get("tool_results")
            if isinstance(trs, list):
                tool_results.extend([x for x in trs if isinstance(x, dict)])
            tro = event.get("tool_raw_outputs")
            if isinstance(tro, list):
                tool_raw_outputs.extend([str(x) for x in tro])
        elif event_type == "final_step":
            messages = event.get("messages")
            if isinstance(messages, list):
                final_messages = messages
            debug = event.get("tool_attempt_debug")
            if isinstance(debug, list):
                final_tool_attempt_debug = [x for x in debug if isinstance(x, dict)]

    return {
        "messages": final_messages,
        "tool_attempt_debug": final_tool_attempt_debug,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "tool_raw_outputs": tool_raw_outputs,
    }
