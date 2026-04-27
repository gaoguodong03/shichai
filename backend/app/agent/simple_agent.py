from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, BaseMessage, ToolMessage, HumanMessage
from langchain_core.tools import BaseTool
from app.agent.llm_client import bind_tools_compat

logger = logging.getLogger(__name__)


def _extract_text_content(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return str(content or "")


def _has_visible_ai_text(messages: list[BaseMessage]) -> bool:
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        text = _extract_text_content(msg).strip()
        if text and not (getattr(msg, "tool_calls", None) or []):
            return True
    return False


def _tool_call_id(tool_call: Any, idx: int) -> str:
    if isinstance(tool_call, dict):
        return str(tool_call.get("id") or tool_call.get("tool_call_id") or f"tool-{idx}")
    return str(getattr(tool_call, "id", None) or getattr(tool_call, "tool_call_id", None) or f"tool-{idx}")


def _tool_call_name(tool_call: Any) -> str:
    if isinstance(tool_call, dict):
        return str(tool_call.get("name") or "tool")
    return str(getattr(tool_call, "name", None) or "tool")


def _missing_tool_response_messages(tool_calls: list[Any], existing_messages: list[Any], reason: str) -> list[ToolMessage]:
    seen_ids = {
        str(getattr(msg, "tool_call_id", "") or "")
        for msg in existing_messages
        if isinstance(msg, ToolMessage) and str(getattr(msg, "tool_call_id", "") or "")
    }
    missing: list[ToolMessage] = []
    for idx, tool_call in enumerate(tool_calls):
        tcid = _tool_call_id(tool_call, idx)
        if tcid in seen_ids:
            continue
        missing.append(
            ToolMessage(
                content=f"工具 {_tool_call_name(tool_call)} 未继续执行：{reason}",
                tool_call_id=tcid,
            )
        )
    return missing


def _env_truthy(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _json_loads_maybe(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _successful_tool_payload(tool_out: dict[str, Any]) -> dict[str, Any] | None:
    raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out, dict) else None
    if not isinstance(raw_outputs, list):
        return None
    for raw in reversed(raw_outputs):
        payload = _json_loads_maybe(raw)
        if not isinstance(payload, dict):
            continue
        ok = payload.get("ok")
        returncode = payload.get("returncode", payload.get("exit_code"))
        if ok is True or returncode == 0:
            return payload
    return None


def _payload_requests_final(payload: dict[str, Any]) -> bool:
    for key in ("final", "done", "skill_session_end", "session_end"):
        value = payload.get(key)
        if value is True:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on", "done", "final"}:
            return True
    return False


def _has_run_skill_script_call(tool_out: dict[str, Any]) -> bool:
    calls = tool_out.get("tool_calls") if isinstance(tool_out, dict) else None
    if not isinstance(calls, list):
        return False
    for call in calls:
        if isinstance(call, dict) and str(call.get("tool") or call.get("name") or "").startswith("run_skill_script_"):
            return True
    return False


def _should_force_final_after_tool_success(system_prompt: str, tool_out: dict[str, Any]) -> bool:
    if not _env_truthy("SKILL_AGENT_FORCE_FINAL_ON_SUCCESS", "1"):
        return False
    payload = _successful_tool_payload(tool_out)
    if payload is None:
        return False
    if "[[SKILL_SESSION_END]]" in (system_prompt or ""):
        return True
    if _payload_requests_final(payload):
        return True
    return _env_truthy("SKILL_AGENT_FORCE_FINAL_ON_ANY_SCRIPT_SUCCESS", "0") and _has_run_skill_script_call(tool_out)


def _final_synthesis_instruction(system_prompt: str, tool_out: dict[str, Any]) -> HumanMessage:
    payload = _successful_tool_payload(tool_out) or {}
    stdout = str(payload.get("stdout") or "").strip()
    stderr = str(payload.get("stderr") or "").strip()
    message = str(payload.get("message") or "工具执行成功。").strip() or "工具执行成功。"
    parts = [
        "工具已经执行成功。请严格遵循上方专家与技能系统提示词，基于工具结果输出最终自然语言答复。",
        "不要再次调用任何工具；不要说还需要执行脚本；stdout/stderr 是工具返回字段，不是文件路径。",
        f"工具状态：{message}",
    ]
    if stdout:
        parsed_stdout = _json_loads_maybe(stdout)
        if isinstance(parsed_stdout, (dict, list)):
            stdout = json.dumps(parsed_stdout, ensure_ascii=False, indent=2)
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    if "[[SKILL_SESSION_END]]" in (system_prompt or ""):
        parts.append("最终答复末尾必须包含 [[SKILL_SESSION_END]]。")
    return HumanMessage(content="\n\n".join(parts))


@dataclass
class SimpleAgent:
    """
    一个不依赖 langgraph 的极简 agent：
    - 仅使用 LLM 的结构化 tool_calls 进行工具调用（删除历史 content-json 回退）
    - 直到模型不再请求工具，返回累计 messages
    """

    llm: Any
    tools: list[BaseTool]
    system_prompt: str
    tool_runner: Any  # async (state, tools) -> dict
    timeout_s: float = 180.0
    max_steps: int = 12
    max_repeated_tool_rounds: int = 3

    async def _call_model(self, client: Any, messages: list[BaseMessage]) -> AIMessage:
        try:
            return await asyncio.wait_for(client.ainvoke(messages), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            logger.error("SimpleAgent: LLM 调用超时（%ss）", self.timeout_s)
            return AIMessage(content="抱歉，模型响应超时，请稍后重试。")
        except Exception as exc:  # noqa: BLE001
            logger.exception("SimpleAgent: LLM 调用失败: %s", exc)
            return AIMessage(content=f"抱歉，模型响应失败：{exc}")

    async def astream(self, initial_state: dict[str, Any], stream_mode=None, config: dict | None = None):
        """统一事件协议：agent_step / tool_step / final_step。"""
        messages: list[BaseMessage] = list(initial_state.get("messages") or [])
        tools = self.tools

        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=self.system_prompt)] + messages

        client = self.llm.get_client()
        if tools:
            client = bind_tools_compat(client, tools)

        tool_attempt_debug: list[dict[str, Any]] = []
        tool_result_cache: dict[str, dict[str, Any]] = {}
        last_tool_signature = ""
        repeated_tool_rounds = 0
        for step in range(self.max_steps):
            response = await self._call_model(client, messages)
            messages.append(response)
            yield {"type": "agent_step", "step": step + 1, "message": response}

            tool_calls = getattr(response, "tool_calls", None) or []
            if tool_calls:
                signatures = []
                for tc in tool_calls:
                    name = str(tc.get("name") or "")
                    args = tc.get("args")
                    signatures.append(f"{name}:{args}")
                current_signature = " | ".join(signatures)
                if current_signature and current_signature == last_tool_signature:
                    repeated_tool_rounds += 1
                else:
                    repeated_tool_rounds = 1
                    last_tool_signature = current_signature
                if repeated_tool_rounds > self.max_repeated_tool_rounds:
                    logger.warning(
                        "SimpleAgent: detected repeated tool-call rounds, break loop. step=%s repeats=%s signature=%s",
                        step + 1,
                        repeated_tool_rounds,
                        current_signature[:240],
                    )
                    tool_attempt_debug.append(
                        {
                            "source": "repeated_tool_guard",
                            "matched": True,
                            "repeat_rounds": repeated_tool_rounds,
                            "signature_preview": current_signature[:240],
                        }
                    )
                    guard_msgs = _missing_tool_response_messages(
                        tool_calls,
                        [],
                        "检测到重复工具调用，已停止继续重试",
                    )
                    messages.extend(guard_msgs)
                    yield {
                        "type": "tool_step",
                        "step": step + 1,
                        "tool_messages": guard_msgs,
                        "tool_calls": [],
                        "tool_raw_outputs": [],
                        "tool_attempt_debug": tool_attempt_debug,
                    }
                    break
                tool_attempt_debug.append(
                    {
                        "source": "structured_tool_calls",
                        "count": len(tool_calls),
                        "matched": True,
                    }
                )
                state = {"messages": messages, "tools": tools, "tool_result_cache": tool_result_cache}
                tool_out = await self.tool_runner(state, tools)
                out_msgs = tool_out.get("messages") or []
                tad = tool_out.get("tool_attempt_debug")
                if isinstance(tad, list):
                    tool_attempt_debug.extend([x for x in tad if x not in tool_attempt_debug])
                tool_calls_trace = tool_out.get("tool_calls") if isinstance(tool_out.get("tool_calls"), list) else []
                tool_raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out.get("tool_raw_outputs"), list) else []
                if isinstance(out_msgs, list) and out_msgs:
                    messages.extend(out_msgs)
                missing_tool_msgs = _missing_tool_response_messages(
                    tool_calls,
                    out_msgs if isinstance(out_msgs, list) else [],
                    "工具执行器未返回结果消息",
                )
                if missing_tool_msgs:
                    logger.warning(
                        "SimpleAgent: tool_runner returned incomplete tool messages; filled_missing=%s",
                        len(missing_tool_msgs),
                    )
                    messages.extend(missing_tool_msgs)
                    if isinstance(out_msgs, list):
                        out_msgs = [*out_msgs, *missing_tool_msgs]
                yield {
                    "type": "tool_step",
                    "step": step + 1,
                    "tool_messages": out_msgs if isinstance(out_msgs, list) else [],
                    "tool_calls": tool_calls_trace,
                    "tool_raw_outputs": tool_raw_outputs,
                    "tool_attempt_debug": tool_attempt_debug,
                }
                if _should_force_final_after_tool_success(self.system_prompt, tool_out):
                    messages.append(_final_synthesis_instruction(self.system_prompt, tool_out))
                    final_message = await self._call_model(self.llm.get_client(), messages)
                    messages.append(final_message)
                    tool_attempt_debug.append(
                        {
                            "source": "synthesize_final_after_tool_success",
                            "matched": True,
                            "content_preview": _extract_text_content(final_message)[:240],
                        }
                    )
                    yield {"type": "agent_step", "step": step + 2, "message": final_message}
                    break
                continue
            content = response.content if isinstance(response.content, str) else str(response.content or "")
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

        # Ensure we always have a user-visible final answer after tool execution.
        # Some models may stop after tool calls without producing a natural language response.
        if tools and not _has_visible_ai_text(messages):
            synthesis_client = self.llm.get_client()
            synthesis_response = await self._call_model(synthesis_client, messages)
            messages.append(synthesis_response)
            yield {"type": "agent_step", "step": self.max_steps + 1, "message": synthesis_response}
            synthesis_text = _extract_text_content(synthesis_response).strip()
            if synthesis_text:
                tool_attempt_debug.append(
                    {
                        "source": "post_tool_synthesis",
                        "matched": True,
                        "content_preview": synthesis_text[:240],
                    }
                )

        yield {"type": "final_step", "messages": messages, "tool_attempt_debug": tool_attempt_debug}

    async def ainvoke(self, initial_state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
        """单一主路径：同一套 tool-intent 判定与执行，不保留旧回退。"""
        messages: list[BaseMessage] = list(initial_state.get("messages") or [])
        tools = self.tools

        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=self.system_prompt)] + messages

        client = self.llm.get_client()
        if tools:
            client = bind_tools_compat(client, tools)

        tool_attempt_debug: list[dict[str, Any]] = []
        tool_calls_trace: list[dict[str, Any]] = []
        tool_raw_outputs: list[str] = []
        tool_result_cache: dict[str, dict[str, Any]] = {}
        last_tool_signature = ""
        repeated_tool_rounds = 0
        for step in range(self.max_steps):
            t0 = time.perf_counter()
            response = await self._call_model(client, messages)

            messages.append(response)
            logger.info("SimpleAgent: step=%s LLM done in %.2fs", step + 1, time.perf_counter() - t0)

            # 1) 结构化 tool_calls
            tool_calls = getattr(response, "tool_calls", None) or []
            if tool_calls:
                signatures = []
                for tc in tool_calls:
                    name = str(tc.get("name") or "")
                    args = tc.get("args")
                    signatures.append(f"{name}:{args}")
                current_signature = " | ".join(signatures)
                if current_signature and current_signature == last_tool_signature:
                    repeated_tool_rounds += 1
                else:
                    repeated_tool_rounds = 1
                    last_tool_signature = current_signature
                if repeated_tool_rounds > self.max_repeated_tool_rounds:
                    logger.warning(
                        "SimpleAgent: repeated tool calls break. step=%s repeats=%s signature=%s",
                        step + 1,
                        repeated_tool_rounds,
                        current_signature[:240],
                    )
                    tool_attempt_debug.append(
                        {
                            "source": "repeated_tool_guard",
                            "matched": True,
                            "repeat_rounds": repeated_tool_rounds,
                            "signature_preview": current_signature[:240],
                        }
                    )
                    guard_msgs = _missing_tool_response_messages(
                        tool_calls,
                        [],
                        "检测到重复工具调用，已停止继续重试",
                    )
                    messages.extend(guard_msgs)
                    break
                tool_attempt_debug.append(
                    {
                        "source": "structured_tool_calls",
                        "count": len(tool_calls),
                        "matched": True,
                    }
                )
                state = {"messages": messages, "tools": tools, "tool_result_cache": tool_result_cache}
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
                missing_tool_msgs = _missing_tool_response_messages(
                    tool_calls,
                    out_msgs if isinstance(out_msgs, list) else [],
                    "工具执行器未返回结果消息",
                )
                if missing_tool_msgs:
                    logger.warning(
                        "SimpleAgent: tool_runner returned incomplete tool messages; filled_missing=%s",
                        len(missing_tool_msgs),
                    )
                    messages.extend(missing_tool_msgs)
                if _should_force_final_after_tool_success(self.system_prompt, tool_out):
                    messages.append(_final_synthesis_instruction(self.system_prompt, tool_out))
                    final_message = await self._call_model(self.llm.get_client(), messages)
                    messages.append(final_message)
                    tool_attempt_debug.append(
                        {
                            "source": "synthesize_final_after_tool_success",
                            "matched": True,
                            "content_preview": _extract_text_content(final_message)[:240],
                        }
                    )
                    break
                continue

            # 2) 回退：content 中的 tool_call JSON
            # no tool calls → finish
            content = response.content if isinstance(response.content, str) else str(response.content or "")
            if content.strip():
                tool_attempt_debug.append(
                    {
                        "source": "no_tool_detected",
                        "matched": False,
                        "content_preview": content.strip()[:240],
                    }
                )
            break

        if tools and not _has_visible_ai_text(messages):
            synthesis_client = self.llm.get_client()
            synthesis_response = await self._call_model(synthesis_client, messages)
            messages.append(synthesis_response)
            synthesis_text = _extract_text_content(synthesis_response).strip()
            if synthesis_text:
                tool_attempt_debug.append(
                    {
                        "source": "post_tool_synthesis",
                        "matched": True,
                        "content_preview": synthesis_text[:240],
                    }
                )

        return {
            "messages": messages,
            "tool_attempt_debug": tool_attempt_debug,
            "tool_calls": tool_calls_trace,
            "tool_raw_outputs": tool_raw_outputs,
        }
