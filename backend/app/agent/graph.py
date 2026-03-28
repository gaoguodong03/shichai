"""ReAct Agent 工作流

注意：当前环境为 langgraph==0.0.51 + Python 3.13，会在 pregel 执行时触发 KeyError '__start__'。
为保证群聊/技能执行稳定，本模块改用不依赖 langgraph 的 SimpleAgent 执行循环。
"""
import asyncio
import json
import logging
import os
import time
from typing import TypedDict, Annotated, Sequence, List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from app.agent.llm_client import QwenLLM
from app.agent.simple_agent import SimpleAgent
from app.agent.tools_for_skill import build_skill_script_tool_name

logger = logging.getLogger(__name__)


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


def _get_mcp_input_schema(tool_name: str, tools: Sequence[BaseTool]) -> dict | None:
    """从 tools 列表中按 tool_name 取出 MCP 工具的 inputSchema，供 __arg1 等通用参数映射。"""
    if not tools:
        return None
    for t in tools:
        if getattr(t, "name", None) == tool_name:
            return getattr(t, "_mcp_input_schema", None)
    return None


def _extract_description_from_content(content: str, tool_name: str) -> str | None:
    """当 tool_calls 的 args 为空时，从同条 AIMessage 的 content 中解析 description。
    兼容 content 中的 ```json { "tool": "...", "arguments": { "description": "..." } } ``` 或 "description": "..."。
    """
    if not (content and isinstance(content, str) and tool_name.strip()):
        return None
    import re
    # 1) 先尝试从代码块中的 JSON 解析（含 tool / arguments）
    for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", content):
        block = block.strip()
        if not block:
            continue
        try:
            obj = json.loads(block)
            if not isinstance(obj, dict):
                continue
            # 若指定了 tool，需匹配当前工具名
            if "tool" in obj and obj.get("tool") != tool_name:
                continue
            args = obj.get("arguments") or obj
            desc = args.get("description") if isinstance(args, dict) else None
            if desc and isinstance(desc, str) and desc.strip():
                return desc.strip()
        except (json.JSONDecodeError, TypeError):
            continue
    # 2) 整段 content 当作 JSON 试一次（部分模型直接输出单个 JSON）
    try:
        obj = json.loads(content.strip())
        if isinstance(obj, dict):
            args = obj.get("arguments") or obj
            desc = args.get("description") if isinstance(args, dict) else None
            if desc and isinstance(desc, str) and desc.strip():
                return desc.strip()
    except (json.JSONDecodeError, TypeError):
        pass
    # 3) 正则匹配 "description": "..."（含简单转义）
    m = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
    if m:
        s = m.group(1).encode().decode("unicode_escape") if "\\" in m.group(1) else m.group(1)
        if s.strip():
            return s.strip()
    return None

# 可通过 LLM_AGENT_TIMEOUT 调整（秒），默认 180。多轮工具调用时上下文较长，需更长时间
_LLM_AGENT_TIMEOUT = int(os.getenv("LLM_AGENT_TIMEOUT", "180"))


def _resolve_mangled_tool_name(tool_name: str, valid_names: List[str]) -> str | None:
    """当模型将多个工具名拼接（如 amap-maps_maps_geo + amap-maps_maps_weather）时，解析出第一个有效工具名。"""
    if tool_name in valid_names:
        return tool_name
    # 优先：取最长的「合法名称且为 tool_name 前缀」
    for name in sorted(valid_names, key=len, reverse=True):
        if tool_name.startswith(name):
            return name
    # 否则：取在 tool_name 中最先出现的合法名称
    best = None
    best_pos = 999999
    for name in valid_names:
        pos = tool_name.find(name)
        if pos != -1 and pos < best_pos:
            best_pos = pos
            best = name
    return best


async def _execute_tool_safely(tool: BaseTool, arguments: dict) -> object:
    """统一执行工具，兼容 func=None 但 coroutine 可用的 StructuredTool。"""
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
    tools: List[BaseTool]

def create_react_agent(
    llm,
    tools: list[BaseTool],
    skills_instruction: str = "",
    skill_routing_rules: str = "",
    extra_system_prompt: str = "",
):
    """创建 ReAct Agent。extra_system_prompt 为设置中的系统提示词，每次 chat 前注入到 prompt 最前。
    skill_routing_rules 由 SkillsLoader.get_skill_routing_rules() 动态生成，来自各 SKILL.md 的 description。"""
    logger.info(f"创建 ReAct Agent，工具数量: {len(tools)}, 技能指令长度: {len(skills_instruction)}, 技能路由规则长度: {len(skill_routing_rules)}, 额外系统提示词长度: {len(extra_system_prompt)}")
    
    # 构建系统提示词：先拼接设置中的系统提示词（每次 chat 前注入）
    system_prompt = ""
    if extra_system_prompt and extra_system_prompt.strip():
        system_prompt += extra_system_prompt.strip() + "\n\n"
    system_prompt += """你是一个有用的 AI 助手，可以使用工具来帮助用户。

你可以使用以下工具：
"""
    
    # 添加工具描述
    for tool in tools:
        system_prompt += f"- {tool.name}: {tool.description}\n"
    if tools:
        logger.info("已添加工具指令到系统提示词")
    # 若包含 Exa 工具，注入 Exa MCP 使用说明（仅调用 exa 时生效）
    if any(t.name == "exa_web_search_exa" for t in tools):
        system_prompt += """
## Exa 搜索工具使用说明
调用 exa_web_search_exa 时**必须**使用参数名 query（必需）传递搜索关键词，不要使用 __arg1。示例：{"query": "北京 烟花 燃放", "numResults": 10}。
可选参数：numResults（数量）、livecrawl（'fallback'|'preferred'|'always'|'never'）、type（'auto'|'fast'）。type 不要用 'news' 等无效值。

"""
    system_prompt += """
当你需要使用工具时，请按照以下格式回复：
```json
{
    "action": "tool_call",
    "tool": "tool_name",
    "arguments": {...}
}
```

当你不需要使用工具时，直接回复用户的问题。

## 文件引用
当用户消息中出现【文件引用：…】时，**必须先读取该文件**再根据内容回答。
- 标签可能为 **【文件引用：显示名｜工作区内相对路径】**：竖线「｜」后为真实路径（可含多级目录，如 `output/pages/xxx/text.md`）。调用 **file-reader_read_file** 时 **path 必须使用竖线后的完整相对路径**，不要只用显示名或只猜文件名。
- 若仅有 **【文件引用：path】** 且无竖线，则 path 即为工作区内相对路径（如 `report.md` 或 `notes/report.txt`）。
- **注意：没有 read_file 工具。** 读取工作区文件**必须**使用 **file-reader_read_file**，path 填上述工作区内相对路径（必要时含子目录）；仅在无法表示为单段相对路径时才使用 `workspaces/<会话ID>/…` 形式。
- **保存内容到工作区**：当前没有写文件工具。若用户要求将某内容保存到文件，请在本条回复中直接写出要保存的**完整内容**，并提示用户：选中本条回复后点击「保存为文件」按钮即可保存到工作区。
- 其它二进制文件（如 PDF、DOCX、XLSX、图片等）：可尝试 file-reader_read_file；若内容为乱码或二进制，须告知用户无法直接解析并建议先转为文本。
不要猜测文件内容。

"""
    
    # 添加 Skills 指令（技能选择规则由 SkillsLoader 从各 SKILL.md 的 when_to_use/description 动态生成）
    if skills_instruction:
        if skill_routing_rules:
            system_prompt += """
## 技能选择（必须优先执行）

根据用户请求**先判断应使用哪个技能**，然后**仅按该技能的说明执行**，不要混用其他技能的工具或话术：

"""
            system_prompt += skill_routing_rules
            system_prompt += """

确定技能后，只调用该技能所需工具，并只输出该技能风格的回答。

"""
        else:
            system_prompt += """
## 技能选择（必须优先执行）

根据用户请求选择最合适的技能，按该技能说明执行，不要混用其他技能的工具或话术。

"""
        system_prompt += f"\n## 可用技能\n{skills_instruction}\n"
        logger.info("已添加技能指令到系统提示词")

    # 定义节点
    def should_continue(state: AgentState):
        """判断是否继续"""
        messages = state["messages"]
        last_message = messages[-1]
        
        logger.info(f"should_continue: 检查最后一条消息，类型: {type(last_message).__name__}")
        
        # 检查最后一条消息是否包含工具调用
        if isinstance(last_message, AIMessage):
            # 优先检查 LangChain 的结构化工具调用
            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                logger.info(f"should_continue: 检测到 {len(last_message.tool_calls)} 个结构化工具调用")
                return "call_tool"
            
            # 回退到文本解析（兼容旧格式）
            content = last_message.content
            logger.info(f"should_continue: AIMessage 内容 (前200字符): {str(content)[:200]}...")
            
            if isinstance(content, str) and "tool_call" in content.lower():
                try:
                    # 尝试解析 JSON
                    if "```json" in content:
                        json_str = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        json_str = content.split("```")[1].split("```")[0].strip()
                    else:
                        json_str = content
                    
                    logger.info(f"should_continue: 尝试解析 JSON: {json_str[:200]}...")
                    tool_call = json.loads(json_str)
                    logger.info(f"should_continue: 解析成功，action: {tool_call.get('action')}, tool: {tool_call.get('tool')}")
                    
                    if tool_call.get("action") == "tool_call":
                        return "call_tool"
                except Exception as e:
                    logger.warning(f"should_continue: JSON 解析失败: {e}")
        
        return "end"
    
    async def call_model(state: AgentState):
        """调用模型（异步版本）"""
        messages = list(state["messages"])
        # 添加系统消息
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages
        
        # 使用 bind_tools 让 LLM 返回结构化工具调用
        client = llm.get_client()
        if tools:
            client = client.bind_tools(tools)
        
        # 日志：本次输入大模型的提示词概览
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
        logger.info("输入大模型的提示词:\n" + "\n".join(msg_summary))
        
        # 使用异步调用（带超时，避免卡死）
        logger.info("call_model: 正在调用 LLM...")
        try:
            response = await asyncio.wait_for(client.ainvoke(messages), timeout=float(_LLM_AGENT_TIMEOUT))
        except asyncio.TimeoutError:
            logger.error(f"call_model: LLM 调用超时（{_LLM_AGENT_TIMEOUT}秒）")
            response = AIMessage(content="抱歉，模型响应超时，请稍后重试或检查网络与 API 配置。")
        logger.info(f"call_model: LLM 响应类型: {type(response).__name__}")
        logger.info(f"call_model: LLM 响应内容类型: {type(response.content).__name__}")
        logger.info(f"call_model: LLM 响应内容 (前200字符): {str(response.content)[:200]}...")
        
        # 检查是否有工具调用
        if hasattr(response, 'tool_calls') and response.tool_calls:
            logger.info(f"call_model: 检测到 {len(response.tool_calls)} 个工具调用")
            for tool_call in response.tool_calls:
                logger.info(f"call_model: 工具调用 - {tool_call.get('name')}, 参数: {tool_call.get('args')}")
        else:
            logger.info(f"call_model: 没有工具调用，响应内容: {str(response.content)[:200]}...")
        
        return {"messages": messages + [response]}
    
    async def call_tool(state: AgentState):
        """调用工具（异步版本）"""
        messages = state["messages"]
        last_message = messages[-1]
        
        logger.info(f"call_tool: 开始处理工具调用，最后一条消息类型: {type(last_message).__name__}")
        
        def normalize_tool_args(tool_name: str, arguments: dict, tools_list: Sequence[BaseTool]) -> dict:
            """规范化工具参数。run_skill_script_* 不做 MCP 规范化；其余名含 '_' 的用 MCP 规范化，并传入 schema 以便 __arg1 自动映射到首参。"""
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

        tool_results = []
        
        # 优先处理 LangChain 的结构化工具调用
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            logger.info(f"call_tool: 处理 {len(last_message.tool_calls)} 个结构化工具调用")
            for tool_call in last_message.tool_calls:
                tool_name = tool_call.get("name") or tool_call.get("id", "")
                arguments = normalize_tool_args(tool_name, _get_tool_call_arguments(tool_call), state["tools"])
                # 若 volces-icon 的 description 仍为空，从同条消息 content 中解析（模型常把参数写在正文 JSON 里）
                if tool_name == "volces-icon_generate_app_icon" and not (arguments.get("description") or "").strip():
                    fallback = _extract_description_from_content(str(last_message.content or ""), tool_name)
                    if fallback:
                        arguments["description"] = fallback
                        logger.info(f"call_tool: 已从 content 补全 description，长度: {len(fallback)}")
                logger.info(f"call_tool: 工具名称: {tool_name}, 参数: {arguments}")
                logger.info(f"call_tool: 可用工具列表: {[t.name for t in state['tools']]}")
                
                # 查找工具（若不存在则尝试纠错：模型可能将多个工具名拼接）
                tool = None
                valid_names = [t.name for t in state["tools"]]
                if tool_name not in valid_names:
                    resolved = _resolve_mangled_tool_name(tool_name, valid_names)
                    if resolved:
                        tool_name = resolved
                        logger.info(f"call_tool: 工具名纠错后使用: {tool_name}")
                for t in state["tools"]:
                    if t.name == tool_name:
                        tool = t
                        logger.info(f"call_tool: 找到工具: {tool_name}")
                        break
                
                if tool:
                    logger.info(f"call_tool: 开始执行工具: {tool_name}")
                    try:
                        logger.info(f"call_tool: 参数: {arguments}")
                        result = await _execute_tool_safely(tool, arguments)
                        
                        logger.info(f"call_tool: 工具执行结果: {result}")
                        tool_results.append(f"工具 {tool_name} 的执行结果: {result}")
                    except Exception as e:
                        error_msg = f"工具 {tool_name} 执行错误: {str(e)}"
                        logger.error(f"call_tool: {error_msg}", exc_info=True)
                        tool_results.append(error_msg)
                else:
                    error_msg = f"工具 {tool_name} 不存在。可用工具: {', '.join([t.name for t in state['tools']])}"
                    logger.error(f"call_tool: {error_msg}")
                    tool_results.append(error_msg)
            
            tool_msgs: list[ToolMessage] = []
            for i, tr in enumerate(tool_results):
                tcid = (last_message.tool_calls[i].get("id") if i < len(last_message.tool_calls) else None) or f"tool-{i}"
                tool_msgs.append(ToolMessage(content=tr, tool_call_id=str(tcid)))
            return {"messages": tool_msgs}
        
        # 回退到文本解析（兼容旧格式）
        content = last_message.content
        logger.info(f"call_tool: 消息内容 (前200字符): {str(content)[:200]}...")
        
        try:
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content
            
            logger.info(f"call_tool: 提取的 JSON: {json_str}")
            tool_call = json.loads(json_str)
            tool_name = tool_call.get("tool")
            arguments = normalize_tool_args(tool_name, _get_tool_call_arguments(tool_call), state["tools"])
            if tool_name == "volces-icon_generate_app_icon" and not (arguments.get("description") or "").strip():
                fallback = _extract_description_from_content(str(last_message.content or ""), tool_name)
                if fallback:
                    arguments["description"] = fallback
                    logger.info(f"call_tool: 已从 content 补全 description，长度: {len(fallback)}")
            logger.info(f"call_tool: 工具名称: {tool_name}, 参数: {arguments}")
            logger.info(f"call_tool: 可用工具列表: {[t.name for t in state['tools']]}")
            
            # 查找工具（若不存在则尝试纠错：模型可能将多个工具名拼接，如 amap-maps_maps_geoamap-maps_maps_weather）
            tool = None
            resolved_name: str | None = None
            for t in state["tools"]:
                if t.name == tool_name:
                    tool = t
                    logger.info(f"call_tool: 找到工具: {tool_name}")
                    break
            if not tool:
                resolved_name = _resolve_mangled_tool_name(tool_name, [t.name for t in state["tools"]])
                if resolved_name:
                    tool_name = resolved_name
                    for t in state["tools"]:
                        if t.name == tool_name:
                            tool = t
                            logger.info(f"call_tool: 工具名纠错后使用: {tool_name}")
                            break
            
            if tool:
                logger.info(f"call_tool: 开始执行工具: {tool_name}")
                logger.info(f"call_tool: 参数: {arguments}")
                try:
                    result = await _execute_tool_safely(tool, arguments)
                except Exception as e:
                    error_msg = f"工具 {tool_name} 执行错误: {str(e)}"
                    logger.error(f"call_tool: {error_msg}", exc_info=True)
                    result = error_msg
                
                logger.info(f"call_tool: 工具执行结果: {result}")
                if resolved_name:
                    result = f"{result}\n\n（注意：您填写了拼接后的工具名，已仅执行第一个工具「{tool_name}」。请在下一条回复中单独调用其余工具，每次一个。）"
                return {
                    "messages": [
                        HumanMessage(content=f"工具 {tool_name} 的执行结果: {result}")
                    ]
                }
            else:
                error_msg = f"工具 {tool_name} 不存在。可用工具: {', '.join([t.name for t in state['tools']])}"
                logger.error(f"call_tool: {error_msg}")
                return {
                    "messages": [
                        HumanMessage(content=error_msg)
                    ]
                }
        except json.JSONDecodeError as e:
            error_msg = f"工具调用 JSON 解析错误: {str(e)}"
            logger.error(f"call_tool: {error_msg}")
            return {
                "messages": [
                    HumanMessage(content=error_msg)
                ]
            }
        except Exception as e:
            error_msg = f"工具调用错误: {str(e)}"
            logger.error(f"call_tool: {error_msg}", exc_info=True)
            return {
                "messages": [
                    HumanMessage(content=error_msg)
                ]
            }
    
    async def _tool_runner(state: AgentState, tools_list: list[BaseTool]):
        return await call_tool(state)

    return SimpleAgent(
        llm=llm,
        tools=tools,
        system_prompt=system_prompt,
        tool_runner=_tool_runner,
        timeout_s=float(_LLM_AGENT_TIMEOUT),
    )


def create_skill_execution_agent(
    llm,
    tools: list[BaseTool],
    skill_full_content: str,
    extra_system_prompt: str = "",
    t_request_start: float = None,
):
    """
    创建技能执行 Agent：仅用于「第二次调用」。
    系统提示词 = 用户设置 + 选中技能的完整内容 + 工具列表。
    按 skill 步骤执行，某一步需要时调用 MCP 工具。
    """
    logger.info(f"创建技能执行 Agent，工具数量: {len(tools)}，技能内容长度: {len(skill_full_content)}")

    system_prompt = ""
    if extra_system_prompt and extra_system_prompt.strip():
        system_prompt += extra_system_prompt.strip() + "\n\n"
    system_prompt += """你是一个有用的 AI 助手，正在按以下技能说明执行用户请求。

"""
    system_prompt += skill_full_content
    system_prompt += """

你可以使用以下工具：
"""
    for tool in tools:
        system_prompt += f"- {tool.name}: {tool.description}\n"
    if tools:
        logger.info("已添加工具指令到系统提示词")
    # 若包含 Exa 工具，注入 Exa MCP 使用说明（仅调用 exa 时生效）
    if any(t.name == "exa_web_search_exa" for t in tools):
        system_prompt += """
## Exa 搜索工具使用说明
调用 exa_web_search_exa 时**必须**使用参数名 query（必需）传递搜索关键词，不要使用 __arg1。示例：{"query": "北京 烟花 燃放", "numResults": 10}。
可选参数：numResults（数量）、livecrawl（'fallback'|'preferred'|'always'|'never'）、type（'auto'|'fast'）。type 不要用 'news' 等无效值。

"""
    system_prompt += """
当你需要使用工具时，请按照以下格式回复：
```json
{
    "action": "tool_call",
    "tool": "tool_name",
    "arguments": {...}
}
```

当你不需要使用工具时，直接回复用户的问题。

## 多步任务规则
若用户请求需要多步工具调用才能完成（例如路线规划：地理编码×2 + 路线查询），**必须连续完成所有步骤**，不要在某一步后停下询问用户「需要什么」「接下来做什么」。只有在任务完全完成后才可回复。

## 文件引用
当用户消息中出现【文件引用：…】时，**必须先读取该文件**再根据内容回答。
- 标签可能为 **【文件引用：显示名｜工作区内相对路径】**：竖线「｜」后为真实路径（可含多级目录，如 `output/pages/xxx/text.md`）。调用 **file-reader_read_file** 时 **path 必须使用竖线后的完整相对路径**，不要只用显示名或只猜文件名。
- 若仅有 **【文件引用：path】** 且无竖线，则 path 即为工作区内相对路径（如 `report.md` 或 `notes/report.txt`）。
- **注意：没有 read_file 工具。** 读取工作区文件**必须**使用 **file-reader_read_file**，path 填上述工作区内相对路径（必要时含子目录）；仅在无法表示为单段相对路径时才使用 `workspaces/<会话ID>/…` 形式。
- **保存内容到工作区**：当前没有写文件工具。若用户要求将某内容保存到文件，请在本条回复中直接写出要保存的**完整内容**，并提示用户：选中本条回复后点击「保存为文件」按钮即可保存到工作区。
- 其它二进制文件（如 PDF、DOCX、XLSX、图片等）：可尝试 file-reader_read_file；若内容为乱码或二进制，须告知用户无法直接解析并建议先转为文本。
不要猜测文件内容。
"""

    async def call_model(state: AgentState, config=None):
        messages = list(state["messages"])
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages

        client = llm.get_client()
        if tools:
            client = client.bind_tools(tools)
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
        logger.info("输入大模型的提示词（技能执行）:\n" + "\n".join(msg_summary))
        t0 = time.perf_counter()
        elapsed = (t0 - t_request_start) if t_request_start else 0
        logger.info(f"call_model: 开始调用 LLM (流程已耗时 {elapsed:.2f}s)")
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
            logger.info(f"call_model LLM 完成: {time.perf_counter() - t0:.2f}s")
        except asyncio.TimeoutError:
            logger.error(f"call_model: LLM 调用超时（{_LLM_AGENT_TIMEOUT}秒）")
            response = AIMessage(content="抱歉，模型响应超时，请稍后重试。")
        return {"messages": messages + [response]}

    def should_continue(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if isinstance(last_message, AIMessage):
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "call_tool"
            if isinstance(last_message.content, str) and "tool_call" in last_message.content.lower():
                try:
                    if "```json" in last_message.content:
                        json_str = last_message.content.split("```json")[1].split("```")[0].strip()
                    elif "```" in last_message.content:
                        json_str = last_message.content.split("```")[1].split("```")[0].strip()
                    else:
                        json_str = last_message.content
                    tool_call = json.loads(json_str)
                    if tool_call.get("action") == "tool_call":
                        return "call_tool"
                except Exception:
                    pass
        return "end"

    async def call_tool(state: AgentState):
        return await _call_tool_impl(state, tools)

    async def _tool_runner(state: AgentState, tools_list: list[BaseTool]):
        return await _call_tool_impl(state, tools_list)

    return SimpleAgent(
        llm=llm,
        tools=tools,
        system_prompt=system_prompt,
        tool_runner=_tool_runner,
        timeout_s=float(_LLM_AGENT_TIMEOUT),
    )


async def _call_tool_impl(state: AgentState, tools: list[BaseTool]):
    """工具调用实现（供 create_skill_execution_agent 复用）"""
    messages = state["messages"]
    last_message = messages[-1]
    tool_results = []
    tool_attempt_debug: list[dict] = []
    tool_calls_trace: list[dict] = []
    tool_raw_outputs: list[str] = []
    max_tool_result_chars = 4000

    def _safe_tool_result_for_prompt(result: object) -> str:
        """限制工具结果进入模型上下文的长度，避免超长内容（如 base64 图片）撑爆 token。"""
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

    def normalize_tool_args(tool_name: str, arguments: dict, tools_list: Sequence[BaseTool]) -> dict:
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

    def _resolve_tool_name_for_skill_call(raw_name: str, tools_list: Sequence[BaseTool]) -> str:
        requested = str(raw_name or "").strip()
        valid_names = [getattr(t, "name", "") for t in tools_list if getattr(t, "name", "")]
        if requested in valid_names:
            return requested
        # 兼容非法字符 skill_id：run_skill_script_新-skill -> run_skill_script_<sanitized>
        if requested.startswith("run_skill_script_"):
            skill_suffix = requested[len("run_skill_script_") :]
            normalized = build_skill_script_tool_name(skill_suffix)
            if normalized in valid_names:
                return normalized
        # 别名兼容：群聊里常见模型按单聊习惯调用 run_skill_script
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
                tool_attempt_debug.append({
                    "requested_tool": requested_tool_name,
                    "resolved_tool": tool_name,
                    "matched": True,
                    "available_tools": [t.name for t in state["tools"]][:30],
                })
                try:
                    t_tool = time.perf_counter()
                    tool_calls_trace.append({"tool": tool_name, "arguments": arguments})
                    result = await _execute_tool_safely(tool, arguments)
                    result_for_prompt = _safe_tool_result_for_prompt(result)
                    tool_results.append(ToolMessage(content=f"工具 {tool_name} 的执行结果: {result_for_prompt}", tool_call_id=tool_call_id))
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
                        content="工具 read_file 已废弃。请改用 file-reader_read_file 读取工作区文件，path 填工作区内相对路径（如 test.md 或 workspaces/<会话ID>/test.md）。",
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
            tool_attempt_debug.append({
                "requested_tool": requested_tool_name,
                "resolved_tool": tool_name,
                "matched": True,
                "available_tools": [t.name for t in state["tools"]][:30],
            })
            try:
                tool_calls_trace.append({"tool": tool_name, "arguments": arguments})
                result = await _execute_tool_safely(tool, arguments)
                result_for_prompt = _safe_tool_result_for_prompt(result)
                tool_raw_outputs.append(str(result))
                return {
                    "messages": [ToolMessage(content=f"工具 {tool_name} 的执行结果: {result_for_prompt}", tool_call_id=str(tool_name or 'tool'))],
                    "tool_attempt_debug": tool_attempt_debug,
                    "tool_calls": tool_calls_trace,
                    "tool_raw_outputs": tool_raw_outputs,
                }
            except Exception as e:
                tool_raw_outputs.append(f"工具 {tool_name} 执行错误: {str(e)}")
                return {
                    "messages": [ToolMessage(content=f"工具 {tool_name} 执行错误: {str(e)}", tool_call_id=str(tool_name or 'tool'))],
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
                "messages": [ToolMessage(content="工具 read_file 已废弃。请改用 file-reader_read_file 读取工作区文件，path 填工作区内相对路径（如 test.md 或 workspaces/<会话ID>/test.md）。", tool_call_id="read_file")],
                "tool_attempt_debug": tool_attempt_debug,
                "tool_calls": tool_calls_trace,
                "tool_raw_outputs": tool_raw_outputs,
            }
        return {
            "messages": [ToolMessage(content=f"工具 {tool_name} 不存在", tool_call_id=str(tool_name or 'tool'))],
            "tool_attempt_debug": tool_attempt_debug,
            "tool_calls": tool_calls_trace,
            "tool_raw_outputs": tool_raw_outputs,
        }
    except Exception as e:
        return {
            "messages": [ToolMessage(content=f"工具调用解析错误: {str(e)}", tool_call_id="tool_call_parse_error")],
            "tool_attempt_debug": tool_attempt_debug,
            "tool_calls": tool_calls_trace,
            "tool_raw_outputs": tool_raw_outputs,
        }
