from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.agent.messages import AIMessage, BaseMessage
from app.agent.platform_prompts import render_platform_prompt
from app.agent.simple_agent_messages import _extract_text_content
from app.agent.simple_agent_tool_flow import (
    has_successful_workspace_write_output as _has_successful_workspace_write_output,
    has_workspace_mutating_tool_call as _has_workspace_mutating_tool_call,
    remember_successful_workspace_writes as _remember_successful_workspace_writes,
)
from app.agent.simple_agent_tool_ids import (
    _missing_tool_response_messages,
    _normalize_ai_tool_call_ids,
    _normalize_tool_message_ids,
)
from app.agent.tool_spec import ToolSpec
from app.agent.simple_agent_streaming import stream_simple_agent
from app.agent.simple_agent_invocation import invoke_simple_agent

logger = logging.getLogger(__name__)


@dataclass
class SimpleAgent:
    """
    一个不依赖外部编排框架的极简 agent：
    - 仅使用 LLM 的结构化 tool_calls 进行工具调用
    - 直到模型不再请求工具，返回累计 messages
    """

    llm: Any
    tools: list[ToolSpec]
    system_prompt: str
    tool_runner: Any  # async (state, tools) -> dict
    timeout_s: float = 180.0
    max_steps: int = 12
    max_repeated_tool_rounds: int = 3
    stop_after_tool_names: tuple[str, ...] = ()
    synthesize_after_tools: bool = True
    synthesize_after_read_file_paths: tuple[str, ...] = ()

    async def _execute_tool_response(
        self,
        response: BaseMessage,
        *,
        messages: list[BaseMessage],
        tools: list[ToolSpec],
        tool_result_cache: dict[str, dict[str, Any]],
        tool_attempt_debug: list[dict[str, Any]],
        tool_raw_outputs: list[str],
        initial_state: dict[str, Any],
        tool_calls_trace: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        tool_call_id_map = _normalize_ai_tool_call_ids(response)
        state = {
            "messages": messages,
            "tools": tools,
            "tool_result_cache": tool_result_cache,
            "workspace_id": initial_state.get("workspace_id", ""),
        }
        tool_out = await self.tool_runner(state, tools)
        out_msgs = tool_out.get("messages") or []
        tad = tool_out.get("tool_attempt_debug")
        if isinstance(tad, list):
            tool_attempt_debug.extend([x for x in tad if x not in tool_attempt_debug])
        tc = tool_out.get("tool_calls")
        if isinstance(tc, list) and tool_calls_trace is not None:
            tool_calls_trace.extend(tc)
        tro = tool_out.get("tool_raw_outputs")
        if isinstance(tro, list):
            tool_raw_outputs.extend([str(x) for x in tro])
        if isinstance(out_msgs, list) and out_msgs:
            _normalize_tool_message_ids(out_msgs, tool_call_id_map)
            messages.extend(out_msgs)
        missing_tool_msgs = _missing_tool_response_messages(
            getattr(response, "tool_calls", None) or [],
            out_msgs if isinstance(out_msgs, list) else [],
            render_platform_prompt("agent.tool_call.missing_response.default_reason.v1", {}),
        )
        if missing_tool_msgs:
            logger.warning(
                "SimpleAgent: tool_runner returned incomplete synthesized tool messages; filled_missing=%s",
                len(missing_tool_msgs),
            )
            messages.extend(missing_tool_msgs)
        return tool_out

    async def _coerce_and_execute_synthesis_tool_calls(
        self,
        synthesis_response: BaseMessage,
        *,
        messages: list[BaseMessage],
        tools: list[ToolSpec],
        tool_result_cache: dict[str, dict[str, Any]],
        tool_attempt_debug: list[dict[str, Any]],
        tool_raw_outputs: list[str],
        initial_state: dict[str, Any],
        step: int,
        tool_calls_trace: list[dict[str, Any]] | None = None,
        previous_tool_signature: str = "",
        successful_workspace_write_keys: set[str] | None = None,
    ) -> tuple[BaseMessage | None, dict[str, Any] | None]:
        tool_calls = getattr(synthesis_response, "tool_calls", None) or []
        if not tool_calls:
            return None, None
        synthesis_signature = " | ".join(
            f"{str(tc.get('name') or '')}:{tc.get('args')}"
            for tc in tool_calls
            if isinstance(tc, dict)
        )
        if previous_tool_signature and synthesis_signature == previous_tool_signature:
            tool_attempt_debug.append(
                {
                    "source": "post_tool_synthesis_repeated_tool_calls_ignored",
                    "matched": True,
                    "signature_preview": synthesis_signature[:240],
                }
            )
            return None, None
        if _has_successful_workspace_write_output(tool_raw_outputs) and _has_workspace_mutating_tool_call(tool_calls):
            tool_attempt_debug.append(
                {
                    "source": "post_tool_synthesis_repeated_write_ignored",
                    "matched": True,
                    "signature_preview": synthesis_signature[:240],
                }
            )
            return None, None
        debug = {
            "source": "post_tool_synthesis_tool_calls",
            "matched": True,
            "count": len(tool_calls),
            "content_preview": _extract_text_content(synthesis_response)[:240],
        }
        tool_attempt_debug.append(debug)
        messages.append(synthesis_response)
        tool_out = await self._execute_tool_response(
            synthesis_response,
            messages=messages,
            tools=tools,
            tool_result_cache=tool_result_cache,
            tool_attempt_debug=tool_attempt_debug,
            tool_raw_outputs=tool_raw_outputs,
            initial_state=initial_state,
            tool_calls_trace=tool_calls_trace,
        )
        if successful_workspace_write_keys is not None:
            _remember_successful_workspace_writes(tool_out, successful_workspace_write_keys)
        logger.info(
            "SimpleAgent: executed synthesized tool calls step=%s count=%s",
            step,
            len(tool_calls),
        )
        return synthesis_response, tool_out

    async def _call_model(self, client: Any, messages: list[BaseMessage], *, step: int | None = None) -> AIMessage:
        chars = sum(len(_extract_text_content(msg)) for msg in messages)
        logger.info(
            "SimpleAgent: LLM call start step=%s messages=%s chars=%s timeout_s=%s",
            step if step is not None else "",
            len(messages),
            chars,
            self.timeout_s,
        )
        try:
            started = time.perf_counter()
            response = await asyncio.wait_for(client.ainvoke(messages), timeout=self.timeout_s)
            logger.info(
                "SimpleAgent: LLM call done step=%s elapsed=%.2fs",
                step if step is not None else "",
                time.perf_counter() - started,
            )
            return response
        except asyncio.TimeoutError:
            logger.error("SimpleAgent: LLM 调用超时（%ss）", self.timeout_s)
            return AIMessage(content="抱歉，模型响应超时，请稍后重试。")
        except Exception as exc:  # noqa: BLE001
            logger.exception("SimpleAgent: LLM 调用失败: %s", exc)
            return AIMessage(content=f"抱歉，模型响应失败：{exc}")

    async def astream(self, initial_state: dict[str, Any], stream_mode=None, config: dict | None = None):
        """统一事件协议：agent_step / tool_step / final_step。"""
        async for event in stream_simple_agent(self, initial_state, stream_mode=stream_mode, config=config):
            yield event

    async def ainvoke(self, initial_state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
        """单一主路径：复用流式工具循环并收集非流式结果。"""
        return await invoke_simple_agent(self, initial_state, config=config)
