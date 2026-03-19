from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


@dataclass
class SimpleAgent:
    """
    一个不依赖 langgraph 的极简 agent：
    - 使用 LLM 的 tool_calls（优先）或 content 中的 tool_call JSON（回退）进行工具调用
    - 直到模型不再请求工具，返回累计 messages
    """

    llm: Any
    tools: list[BaseTool]
    system_prompt: str
    tool_runner: Any  # async (state, tools) -> {"messages": [HumanMessage(...)]}
    timeout_s: float = 180.0
    max_steps: int = 12

    async def astream(self, initial_state: dict[str, Any], stream_mode=None, config: dict | None = None):
        """
        兼容 group_chat.py 里对 agent.astream 的使用。
        这里不做 token 级流式，只在每一步产出一条 messages 事件与必要的 tool/update 事件。
        """
        messages: list[BaseMessage] = list(initial_state.get("messages") or [])
        tools = self.tools

        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=self.system_prompt)] + messages

        client = self.llm.get_client()
        if tools:
            client = client.bind_tools(tools)

        for _ in range(self.max_steps):
            response: AIMessage = await asyncio.wait_for(client.ainvoke(messages), timeout=self.timeout_s)
            messages.append(response)
            yield ("messages", (response, {"langgraph_node": "agent"}))

            tool_calls = getattr(response, "tool_calls", None) or []
            if tool_calls:
                state = {"messages": messages, "tools": tools}
                tool_out = await self.tool_runner(state, tools)
                out_msgs = tool_out.get("messages") or []
                if isinstance(out_msgs, list) and out_msgs:
                    messages.extend(out_msgs)
                    yield ("updates", {"tool": {"messages": out_msgs}})
                continue

            content = response.content if isinstance(response.content, str) else str(response.content or "")
            if isinstance(content, str) and "tool_call" in content.lower():
                try:
                    if "```json" in content:
                        json_str = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        json_str = content.split("```")[1].split("```")[0].strip()
                    else:
                        json_str = content.strip()
                    obj = json.loads(json_str)
                    if isinstance(obj, dict) and obj.get("action") == "tool_call":
                        state = {"messages": messages, "tools": tools}
                        tool_out = await self.tool_runner(state, tools)
                        out_msgs = tool_out.get("messages") or []
                        if isinstance(out_msgs, list) and out_msgs:
                            messages.extend(out_msgs)
                            yield ("updates", {"tool": {"messages": out_msgs}})
                        continue
                except Exception:
                    pass

            break

        yield ("values", {"messages": messages})

    async def ainvoke(self, initial_state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
        messages: list[BaseMessage] = list(initial_state.get("messages") or [])
        tools = self.tools

        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=self.system_prompt)] + messages

        client = self.llm.get_client()
        if tools:
            client = client.bind_tools(tools)

        for step in range(self.max_steps):
            t0 = time.perf_counter()
            try:
                response: AIMessage = await asyncio.wait_for(client.ainvoke(messages), timeout=self.timeout_s)
            except asyncio.TimeoutError:
                logger.error("SimpleAgent: LLM 调用超时（%ss）", self.timeout_s)
                response = AIMessage(content="抱歉，模型响应超时，请稍后重试。")

            messages.append(response)
            logger.info("SimpleAgent: step=%s LLM done in %.2fs", step + 1, time.perf_counter() - t0)

            # 1) 结构化 tool_calls
            tool_calls = getattr(response, "tool_calls", None) or []
            if tool_calls:
                state = {"messages": messages, "tools": tools}
                tool_out = await self.tool_runner(state, tools)
                out_msgs = tool_out.get("messages") or []
                if isinstance(out_msgs, list) and out_msgs:
                    messages.extend(out_msgs)
                continue

            # 2) 回退：content 中的 tool_call JSON
            content = response.content if isinstance(response.content, str) else str(response.content or "")
            if isinstance(content, str) and "tool_call" in content.lower():
                # 尝试解析一个 tool_call JSON；解析失败则视为终止
                try:
                    if "```json" in content:
                        json_str = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        json_str = content.split("```")[1].split("```")[0].strip()
                    else:
                        json_str = content.strip()
                    obj = json.loads(json_str)
                    if isinstance(obj, dict) and obj.get("action") == "tool_call":
                        state = {"messages": messages, "tools": tools}
                        tool_out = await self.tool_runner(state, tools)
                        out_msgs = tool_out.get("messages") or []
                        if isinstance(out_msgs, list) and out_msgs:
                            messages.extend(out_msgs)
                        continue
                except Exception:
                    pass

            # no tool calls → finish
            break

        return {"messages": messages}

