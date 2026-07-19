from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.agent.messages import AIMessage, BaseMessage
from app.agent.simple_agent_messages import _extract_text_content
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
    synthesize_after_read_file_paths: tuple[str, ...] = ()
    final_output_model: Any = None

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
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("SimpleAgent: LLM 调用失败: %s", exc)
            raise

    async def astream(self, initial_state: dict[str, Any], stream_mode=None, config: dict | None = None):
        """统一事件协议：agent_step / tool_step / final_step。"""
        async for event in stream_simple_agent(self, initial_state, stream_mode=stream_mode, config=config):
            yield event

    async def ainvoke(self, initial_state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
        """单一主路径：复用流式工具循环并收集非流式结果。"""
        return await invoke_simple_agent(self, initial_state, config=config)
