"""Skill agent runtime built on the project-local SimpleAgent loop."""
import asyncio
import json
import logging
import os
import time
from typing import TypedDict, Annotated, Sequence, List
from app.agent.messages import BaseMessage, ToolMessage
from app.agent.platform_prompts import render_platform_prompt
from app.agent.simple_agent import SimpleAgent
from app.agent.skill_execution_prompt_rules import skill_execution_extra_instructions
from app.agent.skill_agent_paths import (
    _apply_audio_asr_path_from_user_message,
    _normalize_read_file_path_argument,
    _tool_is_workspace_plain_read_file,
)
from app.agent.skill_tool_result_records import (
    _missing_tool_result_record,
    _tool_mcp_identity,
    _tool_result_record_from_exception,
    _tool_result_record_from_raw,
)
from app.agent.expert_completion_contract import ExpertFinalStatePayload, SkillScriptStdoutPayload
from app.agent.tool_spec import ToolSpec
from app.agent.tool_artifact_ingestion import ingest_tool_result

logger = logging.getLogger(__name__)


def _find_tool_by_name(tool_name: str, tools: Sequence[ToolSpec]) -> ToolSpec | None:
    for tool in tools or []:
        if getattr(tool, "name", None) == tool_name:
            return tool
    return None


def _get_tool_call_arguments(tool_call: dict) -> dict:
    """从 tool_call 得到参数字典。支持 args / arguments，若为 JSON 字符串则解析。"""
    raw = tool_call.get("args") or tool_call.get("arguments")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("tool_call arguments 非合法 JSON: %s", raw[:200])
    return {}


def _get_mcp_input_schema(tool_name: str, tools: Sequence[ToolSpec]) -> dict | None:
    """从 tools 列表中按 tool_name 取出 MCP 工具 inputSchema，用于参数契约归一化。"""
    tool = _find_tool_by_name(tool_name, tools)
    return getattr(tool, "_mcp_input_schema", None) if tool is not None else None


def _json_object_from_tool_result(value: object) -> dict | None:
    """Parse JSON object-like tool output for prompt sanitization."""
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _skill_script_prompt_summary(result: object) -> str | None:
    """Return script output safe for LLM context, excluding runtime trace fields."""
    payload = _json_object_from_tool_result(result)
    if not isinstance(payload, dict):
        return None

    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    stdout_payload = _json_object_from_tool_result(payload.get("stdout"))
    output_stdout_payload = _json_object_from_tool_result(output.get("stdout"))
    candidates = [stdout_payload, output_stdout_payload, payload]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        try:
            parsed = SkillScriptStdoutPayload.model_validate(candidate)
        except Exception:
            continue
        return json.dumps(parsed.model_dump(), ensure_ascii=False)

    summary: dict[str, object] = {}
    for key in ("ok", "code", "message"):
        if key in payload and payload.get(key) not in (None, ""):
            summary[key] = payload.get(key)
    if not summary:
        return None
    return json.dumps(summary, ensure_ascii=False)


_LLM_AGENT_TIMEOUT = int(os.getenv("LLM_AGENT_TIMEOUT", "180"))
_SKILL_AGENT_MAX_STEPS = max(2, int(os.getenv("SKILL_AGENT_MAX_STEPS", "6")))

async def _execute_tool_safely(tool: ToolSpec, arguments: dict) -> object:
    """统一执行工具，兼容 func=None 但 coroutine 可用的 ToolSpec。"""
    func = getattr(tool, "func", None)
    if callable(func):
        raw = func(**arguments)
        return await raw if asyncio.iscoroutine(raw) else raw

    coroutine_fn = getattr(tool, "coroutine", None)
    if callable(coroutine_fn):
        raw = coroutine_fn(**arguments)
        return await raw if asyncio.iscoroutine(raw) else raw

    if hasattr(tool, "arun"):
        tool_input = json.dumps(arguments) if arguments else "{}"
        return await tool.arun(tool_input)

    if hasattr(tool, "run"):
        tool_input = json.dumps(arguments) if arguments else "{}"
        return await asyncio.to_thread(tool.run, tool_input)

    raise RuntimeError(f"工具 {getattr(tool, 'name', 'unknown')} 无法执行")

class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[Sequence[BaseMessage], "对话消息列表"]
    tools: List[ToolSpec]

def create_skill_execution_agent(
    llm,
    tools: list[ToolSpec],
    skill_full_content: str,
    extra_system_prompt: str = "",
    expert_self_awareness: str = "",
    synthesize_after_read_file_paths: tuple[str, ...] = (),
):
    """
    新建技能执行 Agent：仅用于「第二次调用」。
    系统提示词 = 用户设置 + 选中技能的完整内容 + 工具列表。
    按 skill 步骤执行，某一步需要时调用 MCP 工具。
    """
    logger.debug(f"新建技能执行 Agent，工具数量: {len(tools)}，技能内容长度: {len(skill_full_content)}")

    system_prompt = ""
    if extra_system_prompt and extra_system_prompt.strip():
        system_prompt += extra_system_prompt.strip() + "\n\n"
    system_prompt += skill_full_content
    if expert_self_awareness and expert_self_awareness.strip():
        system_prompt += "\n\n---\n\n" + expert_self_awareness.strip()
    tool_lines = "\n".join(f"- {tool.name}: {tool.description}" for tool in tools)
    system_prompt += "\n\n" + render_platform_prompt("skill.execution.tools_header.v1", {"tool_lines": tool_lines})
    if tools:
        logger.debug("已添加工具指令到系统提示词")
    # 若包含 Exa 工具，注入 Exa MCP 使用说明（仅调用 exa 时生效）
    exa_search_tool_name = next(
        (
            t.name
            for t in tools
            if _tool_mcp_identity(t)[1] == "web_search_exa"
        ),
        "",
    )
    if exa_search_tool_name:
        system_prompt += "\n\n" + render_platform_prompt(
            "skill.execution.exa_search.v1",
            {"tool_name": exa_search_tool_name},
        )
    system_prompt += "\n\n" + render_platform_prompt("skill.execution.response_policy.v1", {})
    system_prompt += skill_execution_extra_instructions(tools)

    async def _tool_runner(state: AgentState, tools_list: list[ToolSpec]):
        return await _call_tool_impl(state, tools_list)

    return SimpleAgent(
        llm=llm,
        tools=tools,
        system_prompt=system_prompt,
        tool_runner=_tool_runner,
        timeout_s=float(_LLM_AGENT_TIMEOUT),
        max_steps=_SKILL_AGENT_MAX_STEPS,
        synthesize_after_read_file_paths=synthesize_after_read_file_paths,
        final_output_model=ExpertFinalStatePayload,
    )


async def _call_tool_impl(state: AgentState, tools: list[ToolSpec]):
    """工具调用实现（供 create_skill_execution_agent 复用）"""
    messages = state["messages"]
    last_message = messages[-1]
    tool_results = []
    tool_attempt_debug: list[dict] = []
    tool_calls_trace: list[dict] = []
    tool_result_records: list[dict] = []
    tool_raw_outputs: list[str] = []
    max_tool_result_chars = 8000
    tool_result_cache = state.get("tool_result_cache") if isinstance(state, dict) else None
    if not isinstance(tool_result_cache, dict):
        tool_result_cache = {}

    def _cache_key_for_tool(tool_name: str, arguments: dict) -> str:
        try:
            args_key = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            args_key = str(arguments or {})
        return f"{tool_name}:{args_key}"

    def _cacheable_script_result(result: object) -> bool:
        try:
            parsed = json.loads(str(result or ""))
        except Exception:
            return True
        if isinstance(parsed, dict) and parsed.get("ok") is False:
            return False
        stdout = parsed.get("stdout") if isinstance(parsed, dict) else None
        if isinstance(stdout, str) and stdout.strip().startswith("{"):
            try:
                stdout_payload = json.loads(stdout)
            except Exception:
                stdout_payload = None
            if isinstance(stdout_payload, dict):
                try:
                    return SkillScriptStdoutPayload.model_validate(stdout_payload).execution_status != "failed"
                except Exception:
                    return False
        return True

    def _script_done_instruction(*, cached: bool = False) -> str:
        prefix = "已复用同一轮内相同参数的脚本执行结果。" if cached else "脚本已执行完成。"
        return "\n\n" + render_platform_prompt("skill.execution.script_done_instruction.v1", {"prefix": prefix})

    def _tool_message_content(tool_name: str, result_for_prompt: str, *, cached: bool = False) -> str:
        suffix = _script_done_instruction(cached=cached) if tool_name.startswith("run_skill_script_") else ""
        return render_platform_prompt(
            "skill.execution.tool_message_content.v1",
            {"tool_name": tool_name, "result_for_prompt": result_for_prompt, "suffix": suffix},
        )

    def _tool_error_message(tool_name: str, error: object) -> str:
        return render_platform_prompt(
            "skill.execution.tool_error_message.v1",
            {"tool_name": tool_name, "error": str(error)},
        )

    def _tool_missing_message(tool_name: str, available_tools: list[str] | None = None) -> str:
        return render_platform_prompt(
            "skill.execution.tool_missing_message.v1",
            {"tool_name": tool_name, "available_tools": ", ".join(available_tools or [])},
        )

    def _tool_parse_error_message(error: object) -> str:
        return render_platform_prompt("skill.execution.tool_parse_error_message.v1", {"error": str(error)})

    def _read_workspace_unavailable_message() -> str:
        return render_platform_prompt("skill.execution.read_workspace_unavailable.v1", {})

    def _audio_transcription_text_for_prompt(tool_name: str, result: object) -> str | None:
        if not tool_name.startswith("run_skill_script_audio-transcription"):
            return None
        if isinstance(result, dict):
            text = json.dumps(result, ensure_ascii=False)
        else:
            text = str(result) if not isinstance(result, str) else result
        try:
            outer = json.loads(text)
        except Exception:
            return None
        stdout = outer.get("stdout") if isinstance(outer, dict) else None
        if not isinstance(stdout, str) or not stdout.strip():
            return None
        try:
            payload = json.loads(stdout.strip())
        except Exception:
            return stdout.strip()
        if not isinstance(payload, dict):
            return stdout.strip()
        transcript = payload.get("text")
        if not isinstance(transcript, str) or not transcript.strip():
            return stdout.strip()
        return transcript.strip()

    def _safe_tool_result_for_prompt(result: object, tool_name: str = "") -> str:
        """限制工具结果进入模型上下文的长度，避免超长内容（如 base64 图片）撑爆 token。"""
        if tool_name.startswith("run_skill_script_"):
            script_summary = _skill_script_prompt_summary(result)
            if script_summary is not None:
                return script_summary
        audio_transcription_text = _audio_transcription_text_for_prompt(tool_name, result)
        if audio_transcription_text is not None:
            return audio_transcription_text
        text = str(result) if not isinstance(result, str) else result
        stripped = text.strip()
        if stripped.startswith("data:image/"):
            preview = stripped[:120]
            return (
                f"[图片数据已生成，原始 data URL 过长，已省略；长度约 {len(stripped)} 字符]\n"
                f"预览前缀: {preview}..."
            )
        if len(text) > max_tool_result_chars:
            return text[:max_tool_result_chars].rstrip() + "\n...[工具结果已截断]"
        return text

    def normalize_tool_args(tool_name: str, arguments: dict, tools_list: Sequence[ToolSpec]) -> dict:
        """与主 call_tool 一致：MCP 工具按 schema 做严格参数归一化。"""
        args = dict(arguments) if arguments else {}
        if tool_name.startswith("run_skill_script_"):
            return args
        tool = _find_tool_by_name(tool_name, tools_list)
        if tool is not None:
            server_name, original_tool_name = _tool_mcp_identity(tool)
            if server_name and original_tool_name:
                input_schema = getattr(tool, "_mcp_input_schema", None)
                from app.mcp.manager import normalize_mcp_kwargs_for_call
                return normalize_mcp_kwargs_for_call(server_name, original_tool_name, args, input_schema=input_schema)
        idx = tool_name.find("_")
        if idx >= 0:
            server_name = tool_name[:idx]
            original_tool_name = tool_name[idx + 1:]
            input_schema = _get_mcp_input_schema(tool_name, tools_list)
            from app.mcp.manager import normalize_mcp_kwargs_for_call
            return normalize_mcp_kwargs_for_call(server_name, original_tool_name, args, input_schema=input_schema)
        return args

    workspace_id = str(state.get("workspace_id") or "") if isinstance(state, dict) else ""

    def _resolve_tool_name_for_skill_call(raw_name: str, tools_list: Sequence[ToolSpec]) -> str:
        requested = str(raw_name or "").strip()
        valid_names = [getattr(t, "name", "") for t in tools_list if getattr(t, "name", "")]
        if requested in valid_names:
            return requested
        return requested

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            requested_tool_name = tool_call.get("name") or tool_call.get("id", "")
            tool_name = _resolve_tool_name_for_skill_call(requested_tool_name, state["tools"])
            tool_call_id = str(tool_call.get("id") or tool_call.get("tool_call_id") or tool_name or "tool")
            arguments = normalize_tool_args(tool_name, _get_tool_call_arguments(tool_call), tools)
            tool = None
            for t in state["tools"]:
                if t.name == tool_name:
                    tool = t
                    break
            if tool:
                if tool_name == "audio-asr_transcribe_audio_file":
                    _apply_audio_asr_path_from_user_message(arguments, messages, workspace_id)
                if _tool_is_workspace_plain_read_file(tool_name):
                    _normalize_read_file_path_argument(arguments)
                tool_attempt_debug.append({
                    "requested_tool": requested_tool_name,
                    "resolved_tool": tool_name,
                    "matched": True,
                    "available_tools": [t.name for t in state["tools"]][:30],
                })
                try:
                    t_tool = time.perf_counter()
                    tool_calls_trace.append({"tool": tool_name, "arguments": arguments})
                    cache_key = _cache_key_for_tool(tool_name, arguments)
                    cached_entry = tool_result_cache.get(cache_key) if tool_name.startswith("run_skill_script_") else None
                    if isinstance(cached_entry, dict):
                        result = cached_entry.get("raw", "")
                        result_for_prompt = str(cached_entry.get("prompt") or _safe_tool_result_for_prompt(result, tool_name))
                        logger.info(
                            "sandbox_script_cache_hit tool=%s args_hash=%s raw_len=%s",
                            tool_name,
                            str(abs(hash(cache_key))),
                            len(str(result)),
                        )
                        tool_attempt_debug.append({
                            "source": "run_skill_script_cache_hit",
                            "tool": tool_name,
                            "matched": True,
                        })
                        tool_results.append(ToolMessage(content=_tool_message_content(tool_name, result_for_prompt, cached=True), tool_call_id=tool_call_id))
                        tool_raw_outputs.append(str(result))
                        tool_result_records.append(
                            _tool_result_record_from_raw(
                                tool_name=tool_name,
                                tool=tool,
                                arguments=arguments,
                                tool_call_id=tool_call_id,
                                raw_result=result,
                                duration_ms=int((time.perf_counter() - t_tool) * 1000),
                            )
                        )
                    else:
                        logger.debug(
                            "skill_tool_execute_start tool=%s arg_keys=%s",
                            tool_name,
                            sorted(arguments.keys()) if isinstance(arguments, dict) else [],
                        )
                        result = await _execute_tool_safely(tool, arguments)
                        result = await ingest_tool_result(result, workspace_id=workspace_id)
                        result_for_prompt = _safe_tool_result_for_prompt(result, tool_name)
                        logger.info(
                            "skill_tool_execute_done tool=%s elapsed_ms=%s result_len=%s",
                            tool_name,
                            int((time.perf_counter() - t_tool) * 1000),
                            len(str(result)),
                        )
                        if tool_name.startswith("run_skill_script_") and _cacheable_script_result(result):
                            tool_result_cache[cache_key] = {"raw": str(result), "prompt": result_for_prompt}
                            logger.debug(
                                "sandbox_script_cache_store tool=%s args_hash=%s raw_len=%s",
                                tool_name,
                                str(abs(hash(cache_key))),
                                len(str(result)),
                            )
                        tool_results.append(ToolMessage(content=_tool_message_content(tool_name, result_for_prompt), tool_call_id=tool_call_id))
                        tool_raw_outputs.append(str(result))
                        tool_result_records.append(
                            _tool_result_record_from_raw(
                                tool_name=tool_name,
                                tool=tool,
                                arguments=arguments,
                                tool_call_id=tool_call_id,
                                raw_result=result,
                                duration_ms=int((time.perf_counter() - t_tool) * 1000),
                            )
                        )
                except Exception as e:
                    logger.warning(
                        "skill_tool_execute_failed tool=%s elapsed_ms=%s err=%s",
                        tool_name,
                        int((time.perf_counter() - t_tool) * 1000) if "t_tool" in locals() else 0,
                        str(e)[:500],
                    )
                    error_message = _tool_error_message(tool_name, e)
                    tool_results.append(ToolMessage(content=error_message, tool_call_id=tool_call_id))
                    tool_raw_outputs.append(error_message)
                    tool_result_records.append(
                        _tool_result_record_from_exception(
                            tool_name=tool_name,
                            tool=tool,
                            arguments=arguments,
                            tool_call_id=tool_call_id,
                            error=e,
                            duration_ms=int((time.perf_counter() - t_tool) * 1000) if "t_tool" in locals() else 0,
                        )
                    )
            else:
                tool_attempt_debug.append({
                    "requested_tool": requested_tool_name,
                    "resolved_tool": tool_name,
                    "matched": False,
                    "available_tools": [t.name for t in state["tools"]][:30],
                })
                if tool_name == "read_workspace_file":
                    try:
                        missing_result = _missing_tool_result_record(
                            tool_name=tool_name,
                            arguments=arguments if "arguments" in locals() else {},
                            tool_call_id=tool_call_id,
                            available_tools=[t.name for t in state["tools"]],
                        )
                        tool_result_records.append(missing_result)
                    except ValueError:
                        logger.warning("skip_unknown_source_tool_record tool=%s", tool_name)
                    tool_results.append(ToolMessage(content=_read_workspace_unavailable_message(), tool_call_id=tool_call_id))
                else:
                    try:
                        missing_result = _missing_tool_result_record(
                            tool_name=tool_name,
                            arguments=arguments if "arguments" in locals() else {},
                            tool_call_id=tool_call_id,
                            available_tools=[t.name for t in state["tools"]],
                        )
                        tool_result_records.append(missing_result)
                    except ValueError:
                        logger.warning("skip_unknown_source_tool_record tool=%s", tool_name)
                    tool_results.append(
                        ToolMessage(
                            content=_tool_missing_message(tool_name, [t.name for t in state["tools"]]),
                            tool_call_id=tool_call_id,
                        )
                    )
        return {
            "messages": tool_results,
            "tool_attempt_debug": tool_attempt_debug,
            "tool_calls": tool_calls_trace,
            "tool_results": tool_result_records,
            "tool_raw_outputs": tool_raw_outputs,
        }

    return {
        "messages": [],
        "tool_attempt_debug": tool_attempt_debug,
        "tool_calls": tool_calls_trace,
        "tool_results": tool_result_records,
        "tool_raw_outputs": tool_raw_outputs,
    }
