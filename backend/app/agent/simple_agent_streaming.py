from __future__ import annotations

import logging
from typing import Any

from app.agent.llm_client import bind_tools_compat
from app.agent.messages import BaseMessage, SystemMessage
from app.agent.platform_prompts import render_platform_prompt
from app.agent.simple_agent_finalization import (
    _deterministic_tool_summary_message,
    _final_synthesis_instruction,
    _playwright_runtime_failure_message,
    _post_tool_synthesis_instruction,
    _run_skill_script_stdout_direct_final_message,
    _script_dependency_direct_final_message,
    _should_force_final_after_tool_success,
    _summary_after_llm_failure_message,
)
from app.agent.simple_agent_introspection import (
    _bound_skill_introspection_message,
    _user_text_for_bound_skill_introspection,
)
from app.agent.simple_agent_mcp_tools import _mcp_tool_result_direct_final_message
from app.agent.simple_agent_messages import (
    _ai_response_hit_output_limit,
    _continuation_instruction,
    _extract_text_content,
    _has_visible_ai_text,
    _looks_like_text_tool_call_protocol,
    _max_output_continuations,
)
from app.agent.simple_agent_text_tool_protocol import (
    append_text_tool_protocol_retry_or_failure as _append_text_tool_protocol_retry_or_failure,
    last_message_is_text_tool_protocol_retry as _last_message_is_text_tool_protocol_retry,
    text_tool_protocol_failure_message as _text_tool_protocol_failure_message,
)
from app.agent.simple_agent_tool_errors import (
    _terminal_tool_failure_message,
    _tool_error_direct_final_message,
)
from app.agent.simple_agent_tool_flow import (
    all_workspace_write_calls_already_succeeded as _all_workspace_write_calls_already_succeeded,
    has_successful_workspace_write_output as _has_successful_workspace_write_output,
    has_workspace_mutating_tool_call as _has_workspace_mutating_tool_call,
    is_run_skill_script_workflow_step as _is_run_skill_script_workflow_step,
    post_tool_synthesis_should_use_bound_client as _post_tool_synthesis_should_use_bound_client,
    read_file_should_synthesize_after_result as _read_file_should_synthesize_after_result,
    remember_successful_workspace_writes as _remember_successful_workspace_writes,
    tool_should_stop_after_result as _tool_should_stop_after_result,
)
from app.agent.simple_agent_tool_ids import (
    _missing_tool_response_messages,
    _normalize_ai_tool_call_ids,
    _normalize_tool_message_ids,
)
from app.agent.simple_agent_tool_summary import _final_response_or_tool_summary

logger = logging.getLogger(__name__)


async def stream_simple_agent(agent: Any, initial_state: dict[str, Any], stream_mode=None, config: dict | None = None):
    messages: list[BaseMessage] = list(initial_state.get("messages") or [])
    tools = agent.tools

    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=agent.system_prompt)] + messages

    introspection_message = _bound_skill_introspection_message(
        agent.system_prompt,
        _user_text_for_bound_skill_introspection(messages),
    )
    if introspection_message is not None:
        tool_attempt_debug = [
            {
                "source": "bound_skill_introspection_direct_final",
                "matched": True,
                "content_preview": _extract_text_content(introspection_message)[:240],
            }
        ]
        messages.append(introspection_message)
        yield {"type": "agent_step", "step": 1, "message": introspection_message}
        yield {"type": "final_step", "messages": messages, "tool_attempt_debug": tool_attempt_debug}
        return

    client = agent.llm.get_client()
    if tools:
        client = bind_tools_compat(client, tools)

    tool_attempt_debug: list[dict[str, Any]] = []
    tool_result_cache: dict[str, dict[str, Any]] = {}
    all_tool_raw_outputs: list[str] = []
    all_tool_results: list[dict[str, Any]] = []
    successful_workspace_write_keys: set[str] = set()
    last_tool_signature = ""
    repeated_tool_rounds = 0
    output_continuations = 0
    text_tool_protocol_retries = 0
    for step in range(agent.max_steps):
        response = await agent._call_model(client, messages, step=step + 1)
        if not (getattr(response, "tool_calls", None) or []) and _looks_like_text_tool_call_protocol(response):
            text_tool_protocol_retries, protocol_message, should_retry = _append_text_tool_protocol_retry_or_failure(
                response=response,
                messages=messages,
                tool_attempt_debug=tool_attempt_debug,
                retry_count=text_tool_protocol_retries,
            )
            if should_retry:
                continue
            yield {"type": "agent_step", "step": step + 1, "message": protocol_message}
            break
        tool_call_id_map = _normalize_ai_tool_call_ids(response)
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
            if repeated_tool_rounds > agent.max_repeated_tool_rounds:
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
                    render_platform_prompt("agent.repeated_tool_guard.v1", {}),
                )
                messages.extend(guard_msgs)
                yield {
                    "type": "tool_step",
                    "step": step + 1,
                    "tool_messages": guard_msgs,
                    "tool_calls": [],
                    "tool_results": [],
                    "tool_raw_outputs": [],
                    "tool_attempt_debug": tool_attempt_debug,
                }
                break
            if _all_workspace_write_calls_already_succeeded(tool_calls, successful_workspace_write_keys):
                tool_attempt_debug.append(
                    {
                        "source": "structured_duplicate_workspace_write_ignored",
                        "matched": True,
                        "signature_preview": current_signature[:240],
                    }
                )
                duplicate_msgs = _missing_tool_response_messages(
                    tool_calls,
                    [],
                    render_platform_prompt("agent.duplicate_workspace_write_guard.v1", {}),
                )
                messages.extend(duplicate_msgs)
                yield {
                    "type": "tool_step",
                    "step": step + 1,
                    "tool_messages": duplicate_msgs,
                    "tool_calls": [],
                    "tool_results": [],
                    "tool_raw_outputs": [],
                    "tool_attempt_debug": tool_attempt_debug,
                }
                continue
            tool_attempt_debug.append(
                {
                    "source": "structured_tool_calls",
                    "count": len(tool_calls),
                    "matched": True,
                }
            )
            state = {
                "messages": messages,
                "tools": tools,
                "tool_result_cache": tool_result_cache,
                "workspace_id": initial_state.get("workspace_id", ""),
            }
            tool_out = await agent.tool_runner(state, tools)
            out_msgs = tool_out.get("messages") or []
            tad = tool_out.get("tool_attempt_debug")
            if isinstance(tad, list):
                tool_attempt_debug.extend([x for x in tad if x not in tool_attempt_debug])
            tool_calls_trace = tool_out.get("tool_calls") if isinstance(tool_out.get("tool_calls"), list) else []
            tool_raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out.get("tool_raw_outputs"), list) else []
            tool_results = tool_out.get("tool_results") if isinstance(tool_out.get("tool_results"), list) else []
            all_tool_raw_outputs.extend([str(x) for x in tool_raw_outputs if str(x or "")])
            all_tool_results.extend([x for x in tool_results if isinstance(x, dict)])
            _remember_successful_workspace_writes(tool_out, successful_workspace_write_keys)
            if isinstance(out_msgs, list) and out_msgs:
                _normalize_tool_message_ids(out_msgs, tool_call_id_map)
            if isinstance(out_msgs, list) and out_msgs:
                messages.extend(out_msgs)
            missing_tool_msgs = _missing_tool_response_messages(
                tool_calls,
                out_msgs if isinstance(out_msgs, list) else [],
                render_platform_prompt("agent.tool_call.missing_response.default_reason.v1", {}),
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
                "tool_results": tool_results,
                "tool_raw_outputs": tool_raw_outputs,
                "tool_attempt_debug": tool_attempt_debug,
            }
            terminal_failure_message = _terminal_tool_failure_message(tool_out)
            if terminal_failure_message is not None:
                messages.append(terminal_failure_message)
                tool_attempt_debug.append(
                    {
                        "source": "terminal_tool_failure_direct_final",
                        "matched": True,
                        "content_preview": _extract_text_content(terminal_failure_message)[:240],
                    }
                )
                yield {"type": "agent_step", "step": step + 2, "message": terminal_failure_message}
                break
            dependency_final_message = _script_dependency_direct_final_message(tool_out)
            if dependency_final_message is not None:
                messages.append(dependency_final_message)
                tool_attempt_debug.append(
                    {
                        "source": "script_dependency_direct_final",
                        "matched": True,
                        "content_preview": _extract_text_content(dependency_final_message)[:240],
                    }
                )
                yield {"type": "agent_step", "step": step + 2, "message": dependency_final_message}
                break
            playwright_failure_message = _playwright_runtime_failure_message(tool_out)
            if playwright_failure_message is not None:
                messages.append(playwright_failure_message)
                tool_attempt_debug.append(
                    {
                        "source": "playwright_runtime_failure_direct_final",
                        "matched": True,
                        "content_preview": _extract_text_content(playwright_failure_message)[:240],
                    }
                )
                yield {"type": "agent_step", "step": step + 2, "message": playwright_failure_message}
                break
            tool_error_message = _tool_error_direct_final_message(tool_out, messages, tool_attempt_debug)
            if tool_error_message is not None:
                messages.append(tool_error_message)
                tool_attempt_debug.append(
                    {
                        "source": "tool_error_direct_final",
                        "matched": True,
                        "content_preview": _extract_text_content(tool_error_message)[:240],
                    }
                )
                yield {"type": "agent_step", "step": step + 2, "message": tool_error_message}
                break
            script_stdout_final_message = _run_skill_script_stdout_direct_final_message(tool_out)
            if script_stdout_final_message is not None:
                messages.append(script_stdout_final_message)
                tool_attempt_debug.append(
                    {
                        "source": "run_skill_script_stdout_direct_final",
                        "matched": True,
                        "content_preview": _extract_text_content(script_stdout_final_message)[:240],
                    }
                )
                yield {"type": "agent_step", "step": step + 2, "message": script_stdout_final_message}
                break
            mcp_direct_final_message = _mcp_tool_result_direct_final_message(tool_out)
            if mcp_direct_final_message is not None:
                messages.append(mcp_direct_final_message)
                tool_attempt_debug.append(
                    {
                        "source": "mcp_tool_result_direct_final",
                        "matched": True,
                        "content_preview": _extract_text_content(mcp_direct_final_message)[:240],
                    }
                )
                yield {"type": "agent_step", "step": step + 2, "message": mcp_direct_final_message}
                break
            if _is_run_skill_script_workflow_step(tool_out):
                tool_attempt_debug.append(
                    {
                        "source": "script_workflow_step_continue",
                        "matched": True,
                    }
                )
                continue
            if _should_force_final_after_tool_success(agent.system_prompt, tool_out):
                messages.append(_final_synthesis_instruction(agent.system_prompt, tool_out))
                final_message = await agent._call_model(agent.llm.get_client(), messages, step=step + 2)
                if _looks_like_text_tool_call_protocol(final_message):
                    text_tool_protocol_retries, protocol_message, should_retry = _append_text_tool_protocol_retry_or_failure(
                        response=final_message,
                        messages=messages,
                        tool_attempt_debug=tool_attempt_debug,
                        retry_count=text_tool_protocol_retries,
                    )
                    if should_retry:
                        final_message = await agent._call_model(agent.llm.get_client(), messages, step=step + 2)
                        if _looks_like_text_tool_call_protocol(final_message):
                            text_tool_protocol_retries, protocol_message, _should_retry = _append_text_tool_protocol_retry_or_failure(
                                response=final_message,
                                messages=messages,
                                tool_attempt_debug=tool_attempt_debug,
                                retry_count=text_tool_protocol_retries,
                            )
                            yield {"type": "agent_step", "step": step + 2, "message": protocol_message}
                            break
                    else:
                        yield {"type": "agent_step", "step": step + 2, "message": protocol_message}
                        break
                final_message = _final_response_or_tool_summary(
                    final_message,
                    all_tool_raw_outputs,
                    tool_attempt_debug,
                )
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
            if _tool_should_stop_after_result(tool_out, agent.stop_after_tool_names, tool_attempt_debug):
                break
            if _read_file_should_synthesize_after_result(tool_out, agent.synthesize_after_read_file_paths, tool_attempt_debug):
                messages.append(_post_tool_synthesis_instruction(all_tool_raw_outputs))
                final_message = await agent._call_model(client, messages, step=step + 2)
                if _looks_like_text_tool_call_protocol(final_message):
                    text_tool_protocol_retries, protocol_message, should_retry = _append_text_tool_protocol_retry_or_failure(
                        response=final_message,
                        messages=messages,
                        tool_attempt_debug=tool_attempt_debug,
                        retry_count=text_tool_protocol_retries,
                    )
                    if should_retry:
                        final_message = await agent._call_model(client, messages, step=step + 2)
                        if _looks_like_text_tool_call_protocol(final_message):
                            text_tool_protocol_retries, protocol_message, _should_retry = _append_text_tool_protocol_retry_or_failure(
                                response=final_message,
                                messages=messages,
                                tool_attempt_debug=tool_attempt_debug,
                                retry_count=text_tool_protocol_retries,
                            )
                            yield {"type": "agent_step", "step": step + 2, "message": protocol_message}
                            break
                    else:
                        yield {"type": "agent_step", "step": step + 2, "message": protocol_message}
                        break
                synthesized_tool_message, synthesized_tool_out = await agent._coerce_and_execute_synthesis_tool_calls(
                    final_message,
                    messages=messages,
                    tools=tools,
                    tool_result_cache=tool_result_cache,
                    tool_attempt_debug=tool_attempt_debug,
                    tool_raw_outputs=all_tool_raw_outputs,
                    initial_state=initial_state,
                    step=step + 2,
                    previous_tool_signature=current_signature,
                    successful_workspace_write_keys=successful_workspace_write_keys,
                )
                if synthesized_tool_message is not None and synthesized_tool_out is not None:
                    yield {"type": "agent_step", "step": step + 2, "message": synthesized_tool_message}
                    yield {
                        "type": "tool_step",
                        "step": step + 2,
                        "tool_messages": synthesized_tool_out.get("messages") or [],
                        "tool_calls": synthesized_tool_out.get("tool_calls") or [],
                        "tool_results": synthesized_tool_out.get("tool_results") or [],
                        "tool_raw_outputs": synthesized_tool_out.get("tool_raw_outputs") or [],
                        "tool_attempt_debug": tool_attempt_debug,
                    }
                    continue
                final_message = _final_response_or_tool_summary(
                    final_message,
                    all_tool_raw_outputs,
                    tool_attempt_debug,
                )
                if not _extract_text_content(final_message).strip():
                    final_message = _deterministic_tool_summary_message(all_tool_raw_outputs)
                messages.append(final_message)
                yield {"type": "agent_step", "step": step + 2, "message": final_message}
                break
            if agent.synthesize_after_tools and tools:
                messages.append(_post_tool_synthesis_instruction(all_tool_raw_outputs))
                synthesis_client = client if _post_tool_synthesis_should_use_bound_client(tool_out) else agent.llm.get_client()
                final_message = await agent._call_model(synthesis_client, messages, step=step + 2)
                if _looks_like_text_tool_call_protocol(final_message):
                    text_tool_protocol_retries, protocol_message, should_retry = _append_text_tool_protocol_retry_or_failure(
                        response=final_message,
                        messages=messages,
                        tool_attempt_debug=tool_attempt_debug,
                        retry_count=text_tool_protocol_retries,
                    )
                    if should_retry:
                        final_message = await agent._call_model(synthesis_client, messages, step=step + 2)
                        if _looks_like_text_tool_call_protocol(final_message):
                            text_tool_protocol_retries, protocol_message, _should_retry = _append_text_tool_protocol_retry_or_failure(
                                response=final_message,
                                messages=messages,
                                tool_attempt_debug=tool_attempt_debug,
                                retry_count=text_tool_protocol_retries,
                            )
                            yield {"type": "agent_step", "step": step + 2, "message": protocol_message}
                            break
                    else:
                        yield {"type": "agent_step", "step": step + 2, "message": protocol_message}
                        break
                synthesized_tool_message, synthesized_tool_out = await agent._coerce_and_execute_synthesis_tool_calls(
                    final_message,
                    messages=messages,
                    tools=tools,
                    tool_result_cache=tool_result_cache,
                    tool_attempt_debug=tool_attempt_debug,
                    tool_raw_outputs=all_tool_raw_outputs,
                    initial_state=initial_state,
                    step=step + 2,
                    previous_tool_signature=current_signature,
                    successful_workspace_write_keys=successful_workspace_write_keys,
                )
                if synthesized_tool_message is not None and synthesized_tool_out is not None:
                    yield {"type": "agent_step", "step": step + 2, "message": synthesized_tool_message}
                    yield {
                        "type": "tool_step",
                        "step": step + 2,
                        "tool_messages": synthesized_tool_out.get("messages") or [],
                        "tool_calls": synthesized_tool_out.get("tool_calls") or [],
                        "tool_results": synthesized_tool_out.get("tool_results") or [],
                        "tool_raw_outputs": synthesized_tool_out.get("tool_raw_outputs") or [],
                        "tool_attempt_debug": tool_attempt_debug,
                    }
                    continue
                final_message = _final_response_or_tool_summary(
                    final_message,
                    all_tool_raw_outputs,
                    tool_attempt_debug,
                )
                if not _extract_text_content(final_message).strip():
                    final_message = _deterministic_tool_summary_message(all_tool_raw_outputs)
                messages.append(final_message)
                tool_attempt_debug.append(
                    {
                        "source": "post_tool_synthesis_unbound",
                        "matched": True,
                        "content_preview": _extract_text_content(final_message)[:240],
                    }
                )
                yield {"type": "agent_step", "step": step + 2, "message": final_message}
                break
            continue
        content = response.content if isinstance(response.content, str) else str(response.content or "")
        if content.strip():
            if _looks_like_text_tool_call_protocol(response):
                text_tool_protocol_retries, protocol_message, should_retry = _append_text_tool_protocol_retry_or_failure(
                    response=response,
                    messages=messages,
                    tool_attempt_debug=tool_attempt_debug,
                    retry_count=text_tool_protocol_retries,
                )
                if should_retry:
                    continue
                yield {"type": "agent_step", "step": step + 1, "message": protocol_message}
                break
            summary_after_failure = _summary_after_llm_failure_message(all_tool_raw_outputs, response)
            if summary_after_failure is not None:
                messages.append(summary_after_failure)
                tool_attempt_debug.append(
                    {
                        "source": "llm_failure_after_tool_outputs_summary",
                        "matched": True,
                        "content_preview": _extract_text_content(summary_after_failure)[:240],
                    }
                )
                yield {"type": "agent_step", "step": step + 1, "message": summary_after_failure}
                break
            tool_attempt_debug.append(
                {
                    "source": "no_tool_detected",
                    "matched": False,
                    "content_preview": content.strip()[:240],
                }
            )
            if _ai_response_hit_output_limit(response) and output_continuations < _max_output_continuations():
                output_continuations += 1
                tool_attempt_debug.append(
                    {
                        "source": "output_limit_continuation",
                        "matched": True,
                        "round": output_continuations,
                    }
                )
                messages.append(_continuation_instruction())
                continue
            yield {
                "type": "tool_step",
                "step": step + 1,
                "tool_messages": [],
                "tool_calls": [],
                "tool_results": [],
                "tool_raw_outputs": [],
                "tool_attempt_debug": tool_attempt_debug,
            }

        break

    if _last_message_is_text_tool_protocol_retry(messages):
        failure_message = _text_tool_protocol_failure_message()
        messages.append(failure_message)
        tool_attempt_debug.append(
            {
                "source": "text_tool_call_protocol_failed",
                "matched": True,
                "retry_count": text_tool_protocol_retries,
                "content_preview": "",
            }
        )
        yield {"type": "agent_step", "step": agent.max_steps + 1, "message": failure_message}

    # Ensure we always have a user-visible final answer after tool execution.
    # Some models may stop after tool calls without producing a natural language response.
    if agent.synthesize_after_tools and tools and not _has_visible_ai_text(messages):
        synthesis_client = agent.llm.get_client()
        messages.append(_post_tool_synthesis_instruction(all_tool_raw_outputs))
        synthesis_response = await agent._call_model(synthesis_client, messages, step=agent.max_steps + 1)
        synthesis_response = _final_response_or_tool_summary(
            synthesis_response,
            all_tool_raw_outputs,
            tool_attempt_debug,
        )
        if not _extract_text_content(synthesis_response).strip():
            synthesis_response = _deterministic_tool_summary_message(all_tool_raw_outputs)
        messages.append(synthesis_response)
        yield {"type": "agent_step", "step": agent.max_steps + 1, "message": synthesis_response}
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
