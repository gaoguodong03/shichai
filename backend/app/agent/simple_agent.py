from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, BaseMessage
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
    tool_runner: Any  # async (state, tools) -> dict
    timeout_s: float = 180.0
    max_steps: int = 12

    @staticmethod
    def _extract_tool_intent(content: str) -> dict[str, Any] | None:
        text = (content or "").strip()
        if not text:
            return None
        json_candidates: list[str] = []
        if "```json" in text:
            try:
                json_candidates.append(text.split("```json", 1)[1].split("```", 1)[0].strip())
            except Exception:
                pass
        elif "```" in text:
            try:
                json_candidates.append(text.split("```", 1)[1].split("```", 1)[0].strip())
            except Exception:
                pass
        json_candidates.append(text)
        for candidate in json_candidates:
            if not candidate:
                continue
            try:
                obj = json.loads(candidate)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if "tool" in obj:
                args = obj.get("arguments")
                if args is None:
                    args = obj.get("args")
                if args is None:
                    args = {}
                return {
                    "tool": str(obj.get("tool") or "").strip(),
                    "arguments": args if isinstance(args, dict) else {},
                    "action": str(obj.get("action") or "").strip().lower(),
                    "raw": obj,
                }
        return None

    async def _call_model(self, client: Any, messages: list[BaseMessage]) -> AIMessage:
        try:
            return await asyncio.wait_for(client.ainvoke(messages), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            logger.error("SimpleAgent: LLM 调用超时（%ss）", self.timeout_s)
            return AIMessage(content="抱歉，模型响应超时，请稍后重试。")

    async def astream(self, initial_state: dict[str, Any], stream_mode=None, config: dict | None = None):
        """统一事件协议：agent_step / tool_step / final_step。"""
        messages: list[BaseMessage] = list(initial_state.get("messages") or [])
        tools = self.tools

        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=self.system_prompt)] + messages

        client = self.llm.get_client()
        if tools:
            client = client.bind_tools(tools)

        tool_attempt_debug: list[dict[str, Any]] = []
        for step in range(self.max_steps):
            response = await self._call_model(client, messages)
            messages.append(response)
            yield {"type": "agent_step", "step": step + 1, "message": response}

            tool_calls = getattr(response, "tool_calls", None) or []
            if tool_calls:
                tool_attempt_debug.append(
                    {
                        "source": "structured_tool_calls",
                        "count": len(tool_calls),
                        "matched": True,
                    }
                )
                state = {"messages": messages, "tools": tools}
                tool_out = await self.tool_runner(state, tools)
                out_msgs = tool_out.get("messages") or []
                tad = tool_out.get("tool_attempt_debug")
                if isinstance(tad, list):
                    tool_attempt_debug.extend([x for x in tad if x not in tool_attempt_debug])
                tool_calls_trace = tool_out.get("tool_calls") if isinstance(tool_out.get("tool_calls"), list) else []
                tool_raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out.get("tool_raw_outputs"), list) else []
                if isinstance(out_msgs, list) and out_msgs:
                    messages.extend(out_msgs)
                yield {
                    "type": "tool_step",
                    "step": step + 1,
                    "tool_messages": out_msgs if isinstance(out_msgs, list) else [],
                    "tool_calls": tool_calls_trace,
                    "tool_raw_outputs": tool_raw_outputs,
                    "tool_attempt_debug": tool_attempt_debug,
                }
                continue

            content = response.content if isinstance(response.content, str) else str(response.content or "")
            intent = self._extract_tool_intent(content)
            if intent and intent.get("tool"):
                tool_attempt_debug.append(
                    {
                        "source": "content_json",
                        "requested_tool": intent.get("tool"),
                        "action": intent.get("action") or "",
                        "matched": False,
                    }
                )
                state = {"messages": messages, "tools": tools}
                tool_out = await self.tool_runner(state, tools)
                out_msgs = tool_out.get("messages") or []
                tad = tool_out.get("tool_attempt_debug")
                if isinstance(tad, list):
                    tool_attempt_debug.extend([x for x in tad if x not in tool_attempt_debug])
                tool_calls_trace = tool_out.get("tool_calls") if isinstance(tool_out.get("tool_calls"), list) else []
                tool_raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out.get("tool_raw_outputs"), list) else []
                if isinstance(out_msgs, list) and out_msgs:
                    messages.extend(out_msgs)
                yield {
                    "type": "tool_step",
                    "step": step + 1,
                    "tool_messages": out_msgs if isinstance(out_msgs, list) else [],
                    "tool_calls": tool_calls_trace,
                    "tool_raw_outputs": tool_raw_outputs,
                    "tool_attempt_debug": tool_attempt_debug,
                }
                continue

            if content.strip():
                tool_attempt_debug.append(
                    {
                        "source": "no_tool_detected",
                        "matched": False,
                        "content_preview": content.strip()[:240],
                    }
                )
                yield {
                    "type": "tool_step",
                    "step": step + 1,
                    "tool_messages": [],
                    "tool_calls": [],
                    "tool_raw_outputs": [],
                    "tool_attempt_debug": tool_attempt_debug,
                }

            break

        yield {"type": "final_step", "messages": messages, "tool_attempt_debug": tool_attempt_debug}

    async def ainvoke(self, initial_state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
        """单一主路径：同一套 tool-intent 判定与执行，不保留旧回退。"""
        messages: list[BaseMessage] = list(initial_state.get("messages") or [])
        tools = self.tools

        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=self.system_prompt)] + messages

        client = self.llm.get_client()
        if tools:
            client = client.bind_tools(tools)

        tool_attempt_debug: list[dict[str, Any]] = []
        tool_calls_trace: list[dict[str, Any]] = []
        tool_raw_outputs: list[str] = []
        for step in range(self.max_steps):
            t0 = time.perf_counter()
            response = await self._call_model(client, messages)

            messages.append(response)
            logger.info("SimpleAgent: step=%s LLM done in %.2fs", step + 1, time.perf_counter() - t0)

            # 1) 结构化 tool_calls
            tool_calls = getattr(response, "tool_calls", None) or []
            if tool_calls:
                tool_attempt_debug.append(
                    {
                        "source": "structured_tool_calls",
                        "count": len(tool_calls),
                        "matched": True,
                    }
                )
                state = {"messages": messages, "tools": tools}
                tool_out = await self.tool_runner(state, tools)
                out_msgs = tool_out.get("messages") or []
                tad = tool_out.get("tool_attempt_debug")
                if isinstance(tad, list):
                    tool_attempt_debug.extend([x for x in tad if x not in tool_attempt_debug])
                tc = tool_out.get("tool_calls")
                if isinstance(tc, list):
                    tool_calls_trace.extend(tc)
                tro = tool_out.get("tool_raw_outputs")
                if isinstance(tro, list):
                    tool_raw_outputs.extend([str(x) for x in tro])
                if isinstance(out_msgs, list) and out_msgs:
                    messages.extend(out_msgs)
                continue

            # 2) 回退：content 中的 tool_call JSON
            content = response.content if isinstance(response.content, str) else str(response.content or "")
            intent = self._extract_tool_intent(content)
            if intent and intent.get("tool"):
                tool_attempt_debug.append(
                    {
                        "source": "content_json",
                        "requested_tool": intent.get("tool"),
                        "action": intent.get("action") or "",
                        "matched": False,
                    }
                )
                state = {"messages": messages, "tools": tools}
                tool_out = await self.tool_runner(state, tools)
                out_msgs = tool_out.get("messages") or []
                tad = tool_out.get("tool_attempt_debug")
                if isinstance(tad, list):
                    tool_attempt_debug.extend([x for x in tad if x not in tool_attempt_debug])
                tc = tool_out.get("tool_calls")
                if isinstance(tc, list):
                    tool_calls_trace.extend(tc)
                tro = tool_out.get("tool_raw_outputs")
                if isinstance(tro, list):
                    tool_raw_outputs.extend([str(x) for x in tro])
                if isinstance(out_msgs, list) and out_msgs:
                    messages.extend(out_msgs)
                continue

            # no tool calls → finish
            if content.strip():
                tool_attempt_debug.append(
                    {
                        "source": "no_tool_detected",
                        "matched": False,
                        "content_preview": content.strip()[:240],
                    }
                )
            break

        return {
            "messages": messages,
            "tool_attempt_debug": tool_attempt_debug,
            "tool_calls": tool_calls_trace,
            "tool_raw_outputs": tool_raw_outputs,
        }

