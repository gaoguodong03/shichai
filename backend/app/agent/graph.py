"""ReAct Agent 工作流"""
import asyncio
import json
import logging
import os
import time
from typing import TypedDict, Annotated, Sequence, List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, END
from app.agent.llm_client import QwenLLM

logger = logging.getLogger(__name__)

# 可通过 LLM_AGENT_TIMEOUT 调整（秒），默认 180。多轮工具调用时上下文较长，需更长时间
_LLM_AGENT_TIMEOUT = int(os.getenv("LLM_AGENT_TIMEOUT", "180"))

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
当用户消息中出现【文件引用：path】时，**必须先读取该文件**再根据内容回答。path 为当前会话工作区内相对路径（如 report.md 或 notes/report.txt）。
- **注意：没有 read_file 工具。** 读取工作区文件**必须**使用 **filesystem_read_text_file**，path 填工作区内相对路径（如 test.md）或 workspaces/<会话ID>/xxx。
- 其它二进制文件（如 PDF、DOCX、XLSX、图片等）：可尝试 filesystem_read_text_file；若内容为乱码或二进制，须告知用户无法直接解析并建议先转为文本。
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
        
        def normalize_tool_args(tool_name: str, arguments: dict) -> dict:
            """规范化各 MCP 工具的参数，避免 LLM 传入非法值导致调用失败"""
            args = dict(arguments) if arguments else {}
            # linkup_linkup-search: depth 仅接受 standard 或 deep
            if tool_name == "linkup_linkup-search":
                depth = args.get("depth")
                if depth not in ("standard", "deep"):
                    args["depth"] = "standard"
                    logger.info(f"call_tool: linkup_linkup-search depth 规范化为 standard（原值: {depth!r}）")
            # exa_web_search_exa: 参数约束已在 MCP manager 的工具描述中说明，由 LLM 按正确参数调用
            return args

        tool_results = []
        
        # 优先处理 LangChain 的结构化工具调用
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            logger.info(f"call_tool: 处理 {len(last_message.tool_calls)} 个结构化工具调用")
            for tool_call in last_message.tool_calls:
                tool_name = tool_call.get("name") or tool_call.get("id", "")
                arguments = normalize_tool_args(tool_name, tool_call.get("args", {}))
                
                logger.info(f"call_tool: 工具名称: {tool_name}, 参数: {arguments}")
                logger.info(f"call_tool: 可用工具列表: {[t.name for t in state['tools']]}")
                
                # 查找工具
                tool = None
                for t in state["tools"]:
                    if t.name == tool_name:
                        tool = t
                        logger.info(f"call_tool: 找到工具: {tool_name}")
                        break
                
                if tool:
                    logger.info(f"call_tool: 开始执行工具: {tool_name}")
                    try:
                        import asyncio
                        
                        logger.info(f"call_tool: 参数: {arguments}")
                        
                        # 优先直接调用工具函数（如果是异步函数）
                        if hasattr(tool, 'func') and asyncio.iscoroutinefunction(tool.func):
                            logger.info(f"call_tool: 直接调用异步工具函数")
                            result = await tool.func(**arguments)
                        elif hasattr(tool, 'arun'):
                            # LangChain BaseTool.arun() 需要 tool_input 参数（字符串）
                            # 将字典转换为 JSON 字符串
                            tool_input = json.dumps(arguments) if arguments else "{}"
                            logger.info(f"call_tool: 使用异步方法 arun，tool_input: {tool_input}")
                            result = await tool.arun(tool_input)
                        elif hasattr(tool, 'run'):
                            logger.info(f"call_tool: 使用同步方法 run（在线程中执行）")
                            tool_input = json.dumps(arguments) if arguments else "{}"
                            result = await asyncio.to_thread(tool.run, tool_input)
                        elif hasattr(tool, 'func'):
                            logger.info(f"call_tool: 直接调用同步工具函数")
                            result = await asyncio.to_thread(tool.func, **arguments)
                        else:
                            result = f"工具 {tool_name} 无法执行"
                            logger.error(f"call_tool: 工具 {tool_name} 没有可用的执行方法")
                        
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
            
            return {
                "messages": [
                    HumanMessage(content="\n".join(tool_results))
                ]
            }
        
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
            arguments = normalize_tool_args(tool_name, tool_call.get("arguments", {}))
            
            logger.info(f"call_tool: 工具名称: {tool_name}, 参数: {arguments}")
            logger.info(f"call_tool: 可用工具列表: {[t.name for t in state['tools']]}")
            
            # 查找工具
            tool = None
            for t in state["tools"]:
                if t.name == tool_name:
                    tool = t
                    logger.info(f"call_tool: 找到工具: {tool_name}")
                    break
            
            if tool:
                logger.info(f"call_tool: 开始执行工具: {tool_name}")
                logger.info(f"call_tool: 参数: {arguments}")
                try:
                    import asyncio
                    # 与结构化 tool_calls 分支保持一致：优先以 **kwargs 调用 func
                    if hasattr(tool, 'func') and asyncio.iscoroutinefunction(tool.func):
                        logger.info("call_tool: 直接调用异步工具函数")
                        result = await tool.func(**arguments)
                    elif hasattr(tool, 'func'):
                        logger.info("call_tool: 直接调用同步工具函数（在线程中执行）")
                        result = await asyncio.to_thread(tool.func, **arguments)
                    elif hasattr(tool, 'arun'):
                        # arun 接受 tool_input（通常是字符串）；这里统一传 JSON 字符串，避免位置参数误传
                        tool_input = json.dumps(arguments) if arguments else "{}"
                        logger.info(f"call_tool: 使用异步方法 arun，tool_input: {tool_input}")
                        result = await tool.arun(tool_input)
                    elif hasattr(tool, 'run'):
                        tool_input = json.dumps(arguments) if arguments else "{}"
                        logger.info("call_tool: 使用同步方法 run（在线程中执行）")
                        result = await asyncio.to_thread(tool.run, tool_input)
                    else:
                        result = f"工具 {tool_name} 无法执行"
                        logger.error(f"call_tool: 工具 {tool_name} 没有可用的执行方法")
                except Exception as e:
                    error_msg = f"工具 {tool_name} 执行错误: {str(e)}"
                    logger.error(f"call_tool: {error_msg}", exc_info=True)
                    result = error_msg
                
                logger.info(f"call_tool: 工具执行结果: {result}")
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
    
    # 创建图
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("agent", call_model)
    workflow.add_node("tool", call_tool)
    
    # 设置入口
    workflow.set_entry_point("agent")
    
    # 添加条件边
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "call_tool": "tool",
            "end": END
        }
    )
    
    workflow.add_edge("tool", "agent")
    
    return workflow.compile()


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
当用户消息中出现【文件引用：path】时，**必须先读取该文件**再根据内容回答。path 为当前会话工作区内相对路径（如 report.md 或 notes/report.txt）。
- **注意：没有 read_file 工具。** 读取工作区文件**必须**使用 **filesystem_read_text_file**，path 填工作区内相对路径（如 test.md）或 workspaces/<会话ID>/xxx。
- 其它二进制文件（如 PDF、DOCX、XLSX、图片等）：可尝试 filesystem_read_text_file；若内容为乱码或二进制，须告知用户无法直接解析并建议先转为文本。
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

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tool", call_tool)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue, {"call_tool": "tool", "end": END})
    workflow.add_edge("tool", "agent")
    return workflow.compile()


async def _call_tool_impl(state: AgentState, tools: list[BaseTool]):
    """工具调用实现（供 create_skill_execution_agent 复用）"""
    messages = state["messages"]
    last_message = messages[-1]
    tool_results = []

    def normalize_tool_args(tool_name: str, arguments: dict) -> dict:
        args = dict(arguments) if arguments else {}
        if tool_name == "linkup_linkup-search":
            depth = args.get("depth")
            if depth not in ("standard", "deep"):
                args["depth"] = "standard"
        if tool_name == "volces-icon_generate_app_icon":
            if "description" not in args and ("prompt" in args or "input" in args):
                args["description"] = args.get("prompt") or args.get("input", "")
                for k in ("prompt", "input"):
                    args.pop(k, None)
        return args

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            tool_name = tool_call.get("name") or tool_call.get("id", "")
            arguments = normalize_tool_args(tool_name, tool_call.get("args", {}))
            tool = None
            for t in state["tools"]:
                if t.name == tool_name:
                    tool = t
                    break
            if tool:
                try:
                    t_tool = time.perf_counter()
                    if hasattr(tool, "func") and asyncio.iscoroutinefunction(tool.func):
                        result = await tool.func(**arguments)
                    elif hasattr(tool, "arun"):
                        tool_input = json.dumps(arguments) if arguments else "{}"
                        result = await tool.arun(tool_input)
                    elif hasattr(tool, "run"):
                        tool_input = json.dumps(arguments) if arguments else "{}"
                        result = await asyncio.to_thread(tool.run, tool_input)
                    elif hasattr(tool, "func"):
                        result = await asyncio.to_thread(tool.func, **arguments)
                    else:
                        result = f"工具 {tool_name} 无法执行"
                    tool_results.append(f"工具 {tool_name} 的执行结果: {result}")
                except Exception as e:
                    tool_results.append(f"工具 {tool_name} 执行错误: {str(e)}")
            else:
                if tool_name == "read_file":
                    tool_results.append(
                        "工具 read_file 已废弃。请改用 filesystem_read_text_file 读取工作区文件，path 填工作区内相对路径（如 test.md 或 workspaces/<会话ID>/test.md）。"
                    )
                else:
                    tool_results.append(f"工具 {tool_name} 不存在。可用: {', '.join([t.name for t in state['tools']])}")
        return {"messages": [HumanMessage(content="\n".join(tool_results))]}

    content = last_message.content
    try:
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content
        tool_call = json.loads(json_str)
        tool_name = tool_call.get("tool")
        arguments = normalize_tool_args(tool_name, tool_call.get("arguments", {}))
        tool = None
        for t in state["tools"]:
            if t.name == tool_name:
                tool = t
                break
        if tool:
            try:
                if hasattr(tool, "func") and asyncio.iscoroutinefunction(tool.func):
                    result = await tool.func(**arguments)
                elif hasattr(tool, "func"):
                    result = await asyncio.to_thread(tool.func, **arguments)
                elif hasattr(tool, "arun"):
                    result = await tool.arun(json.dumps(arguments) if arguments else "{}")
                else:
                    result = await asyncio.to_thread(tool.run, json.dumps(arguments) if arguments else "{}")
                return {"messages": [HumanMessage(content=f"工具 {tool_name} 的执行结果: {result}")]}
            except Exception as e:
                return {"messages": [HumanMessage(content=f"工具 {tool_name} 执行错误: {str(e)}")]}
        if tool_name == "read_file":
            return {"messages": [HumanMessage(content="工具 read_file 已废弃。请改用 filesystem_read_text_file 读取工作区文件，path 填工作区内相对路径（如 test.md 或 workspaces/<会话ID>/test.md）。")]}
        return {"messages": [HumanMessage(content=f"工具 {tool_name} 不存在")]}
    except Exception as e:
        return {"messages": [HumanMessage(content=f"工具调用解析错误: {str(e)}")]}
