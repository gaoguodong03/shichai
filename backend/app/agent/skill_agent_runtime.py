"""Skill agent runtime built on the project-local SimpleAgent loop."""
import asyncio
import json
import logging
import os
import time
from typing import TypedDict, Annotated, Sequence, List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from app.agent.llm_client import bind_tools_compat
from app.agent.simple_agent import SimpleAgent
from app.agent.skill_agent_paths import (
    _apply_audio_asr_path_from_user_message,
    _apply_image_generation_workspace_id,
    _normalize_read_file_path_argument,
    _tool_is_workspace_plain_read_file,
)
from app.agent.skill_tool_naming import build_skill_script_tool_name
from app.agent.tool_spec import ToolSpec

logger = logging.getLogger(__name__)

def _tool_name_looks_like_bound_mcp(name: str) -> bool:
    """区分「本技能声明的 MCP 工具（server_tool）」与工作区 / 脚本 / 包装类工具。"""
    n = (name or "").strip()
    if "_" not in n:
        return False
    if n.startswith("run_skill_script_"):
        return False
    head, _ = n.split("_", 1)
    if head in ("filesystem",):
        return False
    if n in {
        "read_file",
        "write_workspace_file",
        "edit_workspace_file",
        "rename_workspace_file",
        "mkdir_workspace",
        "list_workspace_directory",
        "call_api",
    }:
        return False
    return True


def _skill_execution_extra_instructions(tools: List[ToolSpec]) -> str:
    """随实际绑定工具生成「多步规则 / 工作区 / call_api」说明，避免禁用能力后仍误导模型。"""
    names = {getattr(t, "name", "") for t in tools}
    parts: List[str] = []
    script_names = sorted(n for n in names if n.startswith("run_skill_script_"))
    if not script_names:
        parts.append(
            "## 多步任务规则\n"
            "需要多步工具调用时，连续完成所有必要步骤；任务完成后再回复。\n\n"
        )
    file_lines: List[str] = []
    if "read_file" in names:
        file_lines.append("- read_file: 读取工作区内相对路径对应的文件内容（例如 note/test.md、notes/report.md）。")
    if "write_workspace_file" in names:
        file_lines.append("- write_workspace_file: 将文本写入工作区文件（path 为相对路径，如 note/draft.md）。")
    if "edit_workspace_file" in names:
        file_lines.append("- edit_workspace_file: 对工作区内文件做增量修改（用 old_text → new_text）。")
    if "rename_workspace_file" in names:
        file_lines.append("- rename_workspace_file: 重命名工作区内文件或目录。")
    if "mkdir_workspace" in names:
        file_lines.append("- mkdir_workspace: 在工作区内新建目录。")
    if "list_workspace_directory" in names:
        file_lines.append("- list_workspace_directory: 递归列出目录中文件（含子目录）。")
    if file_lines:
        parts.append("## 文件操作（当前会话工作区）\n\n你拥有以下与「当前会话工作区」相关的工具：\n")
        parts.append("\n".join(file_lines) + "\n\n**强制规则（优先级很高）：**\n")
        parts.append(
            "- 这些文件工具是任务过程能力，不限于用户显式要求保存或读取；只要当前任务需要检查已有文件、"
            "创建目录、沉淀阶段产物、保存可复用资料或交付最终文件，就主动调用相应工具。\n"
        )
        if "read_file" in names:
            parts.append(
                "- 当用户消息中出现「读取/打开/查看/查/展示 + 某个路径或文件名」时，"
                "你**必须优先调用 `read_file`**，而不是只用自然语言解释路径是否正确；"
                "path 必须用**用户本条消息里写的路径**，不要用会话里较早提到的旧文件路径。\n"
            )
        if "write_workspace_file" in names or "edit_workspace_file" in names:
            parts.append(
                "- 当用户明确要求「保存/写入/覆盖某个文件」，或本轮任务需要把中间产物、最终产物沉淀为工作区文件时，"
                "优先调用 `write_workspace_file` 或 `edit_workspace_file`，而不是只说「请手动保存」或把全部内容堆在回复里。\n"
            )
        if "write_workspace_file" in names:
            parts.append(_WORKSPACE_TASK_FILE_RULE)
            parts.append(
                "- 对网页采集、资料检索、素材整理任务，采集到多条独立素材时，不要把所有素材写进一个文件；"
                "应为每一条独立素材分开调用 `write_workspace_file`，保存为 `materials/<序号>-<简短标题>.md` "
                "等工作区相对路径，再在最终答复汇总文件清单。\n"
            )
        parts.append("- 对于【文件引用：…】标签，path 一律视为工作区内相对路径使用（如 `report.md` 或 `notes/report.txt`）。\n")
        parts.append(
            "- 所有 path 都应当是**当前会话工作区的相对路径**，不要暴露或要求用户输入任何 "
            "`agent-outputs/`、`workspaces/<会话ID>/...` 这类内部前缀。\n\n"
            "- 如果本轮任务说“材料包/提纲/草稿/分析已整理”等，但没有给出明确文件路径或【文件引用】，"
            "上一位专家的可见发言在最近讨论中；不要根据任务产物名称自行构造 Markdown 文件名再调用 `read_file`。\n\n"
            "若工具返回「文件不存在」，请先列出工作区目录或让用户确认真实路径；不要凭空猜测文件内容。\n\n"
        )
    if "call_api" in names:
        parts.append(
            "## 外部 HTTP（call_api）\n\n"
            "当需要获取**公开**网页或 HTTP API 的响应时，使用 `call_api`。参数为 "
            "`url`、`method`、`headers_json`、`body`；POST/PUT 时显式设置 method，并把 headers_json/body 写成 JSON 字符串。"
            "服务端已做基础 SSRF 防护，无法访问内网或本机地址；若页面需登录或强反爬，结果可能不完整。\n\n"
        )
    if "audio-asr_transcribe_audio_file" in names:
        parts.append(
            "## 音频转写路径规则\n\n"
            "调用 `audio-asr_transcribe_audio_file` 时，如果用户消息包含【文件引用：…】或工作区文件名，"
            "path 使用用户本条消息中的工作区相对路径即可（例如 `meeting.mp3`）。运行时会在工具执行前把它转换成 "
            "`backend/data/...` 完整数据路径；不要要求用户提供 `backend/data/`、`users/<user_id>/`、"
            "`sessions/workspaces/<session_id>/` 等内部路径。\n\n"
        )
    if script_names:
        parts.append(
            "## 技能脚本工具\n\n"
            "用结构化工具调用执行当前技能脚本：`script_path` 填 scripts/ 下相对路径，"
            "`cli_args_json` 填 JSON 数组字符串（如 `[\"--query\",\"用户原话\"]`）。"
            "不要用 `input_json`，不要传宿主机绝对路径。\n\n"
            + "\n".join(f"- `{n}`" for n in script_names)
            + "\n\n"
        )
    mcp_names = sorted({getattr(t, "name", "") for t in tools if _tool_name_looks_like_bound_mcp(getattr(t, "name", ""))})
    if mcp_names:
        parts.append(
            "## 本技能绑定的 MCP 工具\n\n"
            "以下工具由本技能声明并已加载；当流程需要对应外部能力（检索、地图、浏览器、读特定格式文件等）时，"
            "**必须优先使用这些 MCP 工具**完成步骤，不要用无关工具替代或仅靠猜测。"
            "参数以该工具 schema 为准，不要把所有参数塞进 `__arg1`，除非该工具本身只接受单字符串参数。\n\n"
            + "\n".join(f"- `{n}`" for n in mcp_names)
            + "\n\n"
        )
    return "".join(parts)


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
    """从 tools 列表中按 tool_name 取出 MCP 工具的 inputSchema，供 __arg1 等通用参数映射。"""
    if not tools:
        return None
    for t in tools:
        if getattr(t, "name", None) == tool_name:
            return getattr(t, "_mcp_input_schema", None)
    return None


_LLM_AGENT_TIMEOUT = int(os.getenv("LLM_AGENT_TIMEOUT", "180"))
_SKILL_AGENT_MAX_STEPS = max(2, int(os.getenv("SKILL_AGENT_MAX_STEPS", "6")))
_SKILL_AGENT_MAX_REPEATED_TOOL_ROUNDS = max(
    1, int(os.getenv("SKILL_AGENT_MAX_REPEATED_TOOL_ROUNDS", "1"))
)

_WORKSPACE_TASK_FILE_RULE = (
    "- 调度任务由平台通过本轮提示词传入，不要创建、读取或覆盖 `speaker_task.txt`、`next_speaker.txt`。\n"
    "- 只有在工具返回写入成功后，才能对用户说文件已保存至工作区；不要仅凭自然语言回复写出"
    "「报告已保存至工作区」或类似结论。\n"
)


def _resolve_mangled_tool_name(tool_name: str, valid_names: List[str]) -> str | None:
    """当模型将多个工具名拼接（如 amap-maps_maps_geo + amap-maps_maps_weather）时，解析出第一个有效工具名。"""
    if tool_name in valid_names:
        return tool_name
    for name in sorted(valid_names, key=len, reverse=True):
        if tool_name.startswith(name):
            return name
    best = None
    best_pos = 999999
    for name in valid_names:
        pos = tool_name.find(name)
        if pos != -1 and pos < best_pos:
            best_pos = pos
            best = name
    return best


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
    t_request_start: float = None,
    stop_after_tool_names: tuple[str, ...] = (),
    synthesize_after_tools: bool = True,
    synthesize_after_read_file_paths: tuple[str, ...] = (),
):
    """
    创建技能执行 Agent：仅用于「第二次调用」。
    系统提示词 = 用户设置 + 选中技能的完整内容 + 工具列表。
    按 skill 步骤执行，某一步需要时调用 MCP 工具。
    """
    logger.debug(f"创建技能执行 Agent，工具数量: {len(tools)}，技能内容长度: {len(skill_full_content)}")

    system_prompt = ""
    if extra_system_prompt and extra_system_prompt.strip():
        system_prompt += extra_system_prompt.strip() + "\n\n"
    system_prompt += """你是一个有用的 AI 助手，正在按以下技能说明执行用户请求。

"""
    system_prompt += skill_full_content
    if expert_self_awareness and expert_self_awareness.strip():
        system_prompt += "\n\n---\n\n" + expert_self_awareness.strip()
    system_prompt += """

你可以使用以下工具：
"""
    for tool in tools:
        system_prompt += f"- {tool.name}: {tool.description}\n"
    if tools:
        logger.debug("已添加工具指令到系统提示词")
    # 若包含 Exa 工具，注入 Exa MCP 使用说明（仅调用 exa 时生效）
    if any(t.name == "exa_web_search_exa" for t in tools):
        system_prompt += """
## Exa 搜索工具使用说明
调用 exa_web_search_exa 时**必须**使用参数名 query（必需）传递搜索关键词，不要使用 __arg1。示例：{"query": "北京 烟花 燃放", "numResults": 10}。
可选参数：numResults（数量）、livecrawl（'fallback'|'preferred'|'always'|'never'）、type（'auto'|'fast'）。type 不要用 'news' 等无效值。

"""
    system_prompt += """
当你需要使用工具时，**必须**使用模型的结构化工具调用（tool_calls / function calling）来调用工具；
不要输出任何形如 `{"action":"tool_call", ...}` 的 JSON 作为正文（那是历史兼容格式，已移除）。

当你不需要使用工具时，直接回复用户的问题。

"""
    system_prompt += _skill_execution_extra_instructions(tools)

    async def call_model(state: AgentState, config=None):
        messages = list(state["messages"])
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages

        client = llm.get_client()
        if tools:
            client = bind_tools_compat(client, tools)
        msg_summary = []
        for i, m in enumerate(messages):
            role = getattr(m, "type", type(m).__name__.replace("Message", "").lower())
            content = getattr(m, "content", str(m)) or ""
            s = str(content)
            if role == "system":
                msg_summary.append(f"  [{i+1}] {role}: 共 {len(s)} 字符，前150字: {s[:150]}…" if len(s) > 150 else f"  [{i+1}] {role}: {s}")
            else:
                preview = (s[:150] + "…") if len(s) > 150 else s
                msg_summary.append(f"  [{i+1}] {role}: {preview}")
        logger.debug("输入大模型的提示词（技能执行）:\n" + "\n".join(msg_summary))
        t0 = time.perf_counter()
        elapsed = (t0 - t_request_start) if t_request_start else 0
        logger.debug(f"call_model: 开始调用 LLM (流程已耗时 {elapsed:.2f}s)")
        try:
            # 优先 astream：token 级流式，供 stream_mode="messages" 推送；传入 config 以支持 tracer（Python < 3.11 需显式传递）
            invoke_kw = {"config": config} if config is not None else {}

            async def _consume_stream():
                resp = None
                async for chunk in client.astream(messages, **invoke_kw):
                    resp = chunk if resp is None else resp + chunk
                return resp if resp is not None else AIMessage(content="")

            try:
                response = await asyncio.wait_for(
                    _consume_stream(), timeout=float(_LLM_AGENT_TIMEOUT)
                )
            except Exception as stream_err:
                logger.warning(f"call_model: astream 失败，回退到 ainvoke: {stream_err}")
                response = await asyncio.wait_for(
                    client.ainvoke(messages, **invoke_kw), timeout=float(_LLM_AGENT_TIMEOUT)
                )
            logger.debug(f"call_model LLM 完成: {time.perf_counter() - t0:.2f}s")
        except asyncio.TimeoutError:
            logger.error(f"call_model: LLM 调用超时（{_LLM_AGENT_TIMEOUT}秒）")
            response = AIMessage(content="抱歉，模型响应超时，请稍后重试。")
        return {"messages": messages + [response]}

    async def _tool_runner(state: AgentState, tools_list: list[ToolSpec]):
        return await _call_tool_impl(state, tools_list)

    return SimpleAgent(
        llm=llm,
        tools=tools,
        system_prompt=system_prompt,
        tool_runner=_tool_runner,
        timeout_s=float(_LLM_AGENT_TIMEOUT),
        max_steps=_SKILL_AGENT_MAX_STEPS,
        max_repeated_tool_rounds=_SKILL_AGENT_MAX_REPEATED_TOOL_ROUNDS,
        stop_after_tool_names=stop_after_tool_names,
        synthesize_after_tools=synthesize_after_tools,
        synthesize_after_read_file_paths=synthesize_after_read_file_paths,
    )


async def _call_tool_impl(state: AgentState, tools: list[ToolSpec]):
    """工具调用实现（供 create_skill_execution_agent 复用）"""
    messages = state["messages"]
    last_message = messages[-1]
    tool_results = []
    tool_attempt_debug: list[dict] = []
    tool_calls_trace: list[dict] = []
    tool_raw_outputs: list[str] = []
    max_tool_result_chars = 4000
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
            if isinstance(stdout_payload, dict) and stdout_payload.get("ok") is False:
                return False
        return True

    def _script_done_instruction(*, cached: bool = False) -> str:
        prefix = "已复用同一轮内相同参数的脚本执行结果。" if cached else "脚本已执行完成。"
        return (
            f"\n\n{prefix}请直接基于上方工具结果中的 stdout/stderr/returncode 生成最终答复。"
            "stdout/stderr 是返回字段，不是工作区文件；不要调用 read_file 读取 stdout、stderr 或 scripts/<脚本名>，"
            "也不要再次调用同一个脚本和相同参数。"
        )

    def _tool_message_content(tool_name: str, result_for_prompt: str, *, cached: bool = False) -> str:
        suffix = _script_done_instruction(cached=cached) if tool_name.startswith("run_skill_script_") else ""
        return f"工具 {tool_name} 的执行结果: {result_for_prompt}{suffix}"

    def _audio_transcription_text_for_prompt(tool_name: str, result: object) -> str | None:
        if not tool_name.startswith("run_skill_script_audio-transcription"):
            return None
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
        """与主 call_tool 一致：MCP 工具用 schema 做 __arg1→首参 等映射。"""
        args = dict(arguments) if arguments else {}
        if tool_name.startswith("run_skill_script_"):
            return args
        idx = tool_name.find("_")
        if idx >= 0:
            server_id = tool_name[:idx]
            original_tool_name = tool_name[idx + 1:]
            input_schema = _get_mcp_input_schema(tool_name, tools_list)
            from app.mcp.manager import normalize_mcp_kwargs_for_call
            return normalize_mcp_kwargs_for_call(server_id, original_tool_name, args, input_schema=input_schema)
        return args

    workspace_id = str(state.get("workspace_id") or "") if isinstance(state, dict) else ""

    def _resolve_tool_name_for_skill_call(raw_name: str, tools_list: Sequence[ToolSpec]) -> str:
        requested = str(raw_name or "").strip()
        valid_names = [getattr(t, "name", "") for t in tools_list if getattr(t, "name", "")]
        if requested in valid_names:
            return requested
        if requested.startswith("run_skill_script_"):
            skill_suffix = requested[len("run_skill_script_") :]
            normalized = build_skill_script_tool_name(skill_suffix)
            if normalized in valid_names:
                return normalized
        if requested == "run_skill_script":
            candidates = [n for n in valid_names if n.startswith("run_skill_script_")]
            if len(candidates) == 1:
                return candidates[0]
        resolved = _resolve_mangled_tool_name(requested, valid_names)
        return resolved or requested

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
                if tool_name == "image-generation_generate_image":
                    _apply_image_generation_workspace_id(arguments, workspace_id)
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
                    else:
                        result = await _execute_tool_safely(tool, arguments)
                        result_for_prompt = _safe_tool_result_for_prompt(result, tool_name)
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
                except Exception as e:
                    tool_results.append(ToolMessage(content=f"工具 {tool_name} 执行错误: {str(e)}", tool_call_id=tool_call_id))
                    tool_raw_outputs.append(f"工具 {tool_name} 执行错误: {str(e)}")
            else:
                tool_attempt_debug.append({
                    "requested_tool": requested_tool_name,
                    "resolved_tool": tool_name,
                    "matched": False,
                    "available_tools": [t.name for t in state["tools"]][:30],
                })
                if tool_name == "read_file":
                    tool_results.append(ToolMessage(
                        content="当前专家未启用 read_file，无法读取工作区文件。请先启用文件读取能力，或让用户提供文件内容。",
                        tool_call_id=tool_call_id,
                    ))
                else:
                    tool_results.append(ToolMessage(content=f"工具 {tool_name} 不存在。可用: {', '.join([t.name for t in state['tools']])}", tool_call_id=tool_call_id))
        return {
            "messages": tool_results,
            "tool_attempt_debug": tool_attempt_debug,
            "tool_calls": tool_calls_trace,
            "tool_raw_outputs": tool_raw_outputs,
        }

    content = last_message.content
    try:
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content
        tool_call = json.loads(json_str)
        requested_tool_name = tool_call.get("tool")
        tool_name = _resolve_tool_name_for_skill_call(requested_tool_name, state["tools"])
        arguments = normalize_tool_args(tool_name, _get_tool_call_arguments(tool_call), tools)
        tool = None
        for t in state["tools"]:
            if t.name == tool_name:
                tool = t
                break
        if tool:
            if tool_name == "audio-asr_transcribe_audio_file":
                _apply_audio_asr_path_from_user_message(arguments, messages, workspace_id)
            if tool_name == "image-generation_generate_image":
                _apply_image_generation_workspace_id(arguments, workspace_id)
            if _tool_is_workspace_plain_read_file(tool_name):
                _normalize_read_file_path_argument(arguments)
            tool_attempt_debug.append({
                "requested_tool": requested_tool_name,
                "resolved_tool": tool_name,
                "matched": True,
                "available_tools": [t.name for t in state["tools"]][:30],
            })
            try:
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
                else:
                    result = await _execute_tool_safely(tool, arguments)
                    result_for_prompt = _safe_tool_result_for_prompt(result, tool_name)
                    if tool_name.startswith("run_skill_script_") and _cacheable_script_result(result):
                        tool_result_cache[cache_key] = {"raw": str(result), "prompt": result_for_prompt}
                        logger.debug(
                            "sandbox_script_cache_store tool=%s args_hash=%s raw_len=%s",
                            tool_name,
                            str(abs(hash(cache_key))),
                            len(str(result)),
                        )
                tool_raw_outputs.append(str(result))
                # 注意：当模型没有返回结构化 tool_calls（而是通过 content JSON 回退解析）时，
                # 不能向 OpenAI ChatCompletions 发送 role=tool 的消息（必须紧跟在带 tool_calls 的 assistant 之后）。
                # 这里将工具输出作为普通 HumanMessage 反馈给模型，确保消息序列合法。
                return {
                    "messages": [HumanMessage(content=_tool_message_content(tool_name, result_for_prompt, cached=isinstance(cached_entry, dict)))],
                    "tool_attempt_debug": tool_attempt_debug,
                    "tool_calls": tool_calls_trace,
                    "tool_raw_outputs": tool_raw_outputs,
                }
            except Exception as e:
                tool_raw_outputs.append(f"工具 {tool_name} 执行错误: {str(e)}")
                return {
                    "messages": [HumanMessage(content=f"工具 {tool_name} 执行错误: {str(e)}")],
                    "tool_attempt_debug": tool_attempt_debug,
                    "tool_calls": tool_calls_trace,
                    "tool_raw_outputs": tool_raw_outputs,
                }
        tool_attempt_debug.append({
            "requested_tool": requested_tool_name,
            "resolved_tool": tool_name,
            "matched": False,
            "available_tools": [t.name for t in state["tools"]][:30],
        })
        if tool_name == "read_file":
            return {
                "messages": [HumanMessage(content="当前专家未启用 read_file，无法读取工作区文件。请先启用文件读取能力，或让用户提供文件内容。")],
                "tool_attempt_debug": tool_attempt_debug,
                "tool_calls": tool_calls_trace,
                "tool_raw_outputs": tool_raw_outputs,
            }
        return {
            "messages": [HumanMessage(content=f"工具 {tool_name} 不存在")],
            "tool_attempt_debug": tool_attempt_debug,
            "tool_calls": tool_calls_trace,
            "tool_raw_outputs": tool_raw_outputs,
        }
    except Exception as e:
        return {
            "messages": [HumanMessage(content=f"工具调用解析错误: {str(e)}")],
            "tool_attempt_debug": tool_attempt_debug,
            "tool_calls": tool_calls_trace,
            "tool_raw_outputs": tool_raw_outputs,
        }
