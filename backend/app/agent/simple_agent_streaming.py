from __future__ import annotations

import json
import logging
from typing import Any

from app.agent.llm_client import bind_tools_compat
from app.agent.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from app.agent.platform_prompts import render_platform_prompt
from app.agent.structured_llm_output import invoke_pydantic_tool_output
from app.agent.simple_agent_finalization import (
    _post_tool_decision_instruction,
    _tool_budget_finalization_instruction,
    _tool_budget_structured_finalization_instruction,
)
from app.agent.simple_agent_introspection import (
    _bound_skill_introspection_message,
    _user_text_for_bound_skill_introspection,
)
from app.agent.simple_agent_messages import (
    _ai_response_hit_output_limit,
    _continuation_instruction,
    _extract_text_content,
    _looks_like_text_tool_call_protocol,
    _max_output_continuations,
)
from app.agent.simple_agent_text_tool_protocol import (
    append_text_tool_protocol_retry_or_failure as _append_text_tool_protocol_retry_or_failure,
    last_message_is_text_tool_protocol_retry as _last_message_is_text_tool_protocol_retry,
    text_tool_protocol_failure_message as _text_tool_protocol_failure_message,
)
from app.agent.simple_agent_tool_flow import (
    all_workspace_write_calls_already_succeeded as _all_workspace_write_calls_already_succeeded,
    has_successful_workspace_write_output as _has_successful_workspace_write_output,
    has_workspace_mutating_tool_call as _has_workspace_mutating_tool_call,
    read_file_should_synthesize_after_result as _read_file_should_synthesize_after_result,
    remember_successful_workspace_writes as _remember_successful_workspace_writes,
)
from app.agent.simple_agent_tool_ids import (
    _missing_tool_response_messages,
    _normalize_ai_tool_call_ids,
    _normalize_tool_message_ids,
)
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
            if _read_file_should_synthesize_after_result(tool_out, agent.synthesize_after_read_file_paths, tool_attempt_debug):
                messages.append(_post_tool_decision_instruction(all_tool_raw_outputs, tool_results=all_tool_results))
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
                synthesized_tool_message, synthesized_tool_out = await agent._execute_post_tool_decision_tool_calls(
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
                    all_tool_raw_outputs.extend(
                        [str(x) for x in (synthesized_tool_out.get("tool_raw_outputs") or []) if str(x or "")]
                    )
                    all_tool_results.extend(
                        [x for x in (synthesized_tool_out.get("tool_results") or []) if isinstance(x, dict)]
                    )
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
                if getattr(final_message, "tool_calls", None):
                    break
                messages.append(final_message)
                yield {"type": "agent_step", "step": step + 2, "message": final_message}
                break
            if tools:
                messages.append(_post_tool_decision_instruction(all_tool_raw_outputs, tool_results=all_tool_results))
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
                synthesized_tool_message, synthesized_tool_out = await agent._execute_post_tool_decision_tool_calls(
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
                    all_tool_raw_outputs.extend(
                        [str(x) for x in (synthesized_tool_out.get("tool_raw_outputs") or []) if str(x or "")]
                    )
                    all_tool_results.extend(
                        [x for x in (synthesized_tool_out.get("tool_results") or []) if isinstance(x, dict)]
                    )
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
                if getattr(final_message, "tool_calls", None):
                    break
                messages.append(final_message)
                tool_attempt_debug.append(
                    {
                        "source": "post_tool_decision_final_state",
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

    last_ai_message = next((item for item in reversed(messages) if isinstance(item, AIMessage)), None)
    if (
        (all_tool_results or all_tool_raw_outputs)
        and last_ai_message is not None
        and bool(getattr(last_ai_message, "tool_calls", None))
        and not _last_message_is_text_tool_protocol_retry(messages)
    ):
        if agent.final_output_model is not None:
            messages.append(
                _tool_budget_structured_finalization_instruction(
                    tool_name=agent.final_output_tool_name,
                    tool_results=all_tool_results,
                )
            )
            retry_messages = [
                *messages,
                HumanMessage(
                    content=render_platform_prompt(
                        "agent.structured_output.protocol_retry.v1",
                        {"schema_name": agent.final_output_model.__name__},
                    )
                ),
            ]
            parsed_final = await invoke_pydantic_tool_output(
                agent.llm.get_client(),
                messages,
                agent.final_output_model,
                tool_name=agent.final_output_tool_name,
                retry_messages=retry_messages,
            )
            final_message = AIMessage(
                content=json.dumps(parsed_final.model_dump(mode="json", exclude_none=True), ensure_ascii=False)
            )
        else:
            messages.append(_tool_budget_finalization_instruction(tool_results=all_tool_results))
            finalizer_client = agent.llm.get_client()
            bind_fn = getattr(finalizer_client, "bind", None)
            if callable(bind_fn):
                finalizer_client = bind_fn(response_format={"type": "json_object"})
            final_message = await agent._call_model(finalizer_client, messages, step=agent.max_steps + 1)
        messages.append(final_message)
        tool_attempt_debug.append(
            {
                "source": "tool_budget_exhausted_finalizer",
                "matched": True,
                "content_preview": _extract_text_content(final_message)[:240],
            }
        )
        yield {"type": "agent_step", "step": agent.max_steps + 1, "message": final_message}

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

    yield {"type": "final_step", "messages": messages, "tool_attempt_debug": tool_attempt_debug}
