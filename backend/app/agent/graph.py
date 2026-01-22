"""ReAct Agent 工作流"""
from typing import TypedDict, Annotated, Sequence, List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, END
from app.agent.llm_client import QwenLLM
import json
import logging

logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[Sequence[BaseMessage], "对话消息列表"]
    tools: List[BaseTool]

def create_react_agent(llm, tools: list[BaseTool], skills_instruction: str = ""):
    """创建 ReAct Agent"""
    logger.info(f"创建 ReAct Agent，工具数量: {len(tools)}, 技能指令长度: {len(skills_instruction)}")
    
    # 构建系统提示词
    system_prompt = """你是一个有用的 AI 助手，可以使用工具来帮助用户。

你可以使用以下工具：
"""
    
    # 添加工具描述
    for tool in tools:
        system_prompt += f"- {tool.name}: {tool.description}\n"
        logger.info(f"添加工具到系统提示词: {tool.name}")
    
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

"""
    
    # 添加 Skills 指令
    if skills_instruction:
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
        
        # 使用异步调用
        response = await client.ainvoke(messages)
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
        
        tool_results = []
        
        # 优先处理 LangChain 的结构化工具调用
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            logger.info(f"call_tool: 处理 {len(last_message.tool_calls)} 个结构化工具调用")
            for tool_call in last_message.tool_calls:
                tool_name = tool_call.get("name") or tool_call.get("id", "")
                arguments = tool_call.get("args", {})
                
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
            arguments = tool_call.get("arguments", {})
            
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
                # LangChain BaseTool.arun() 需要 tool_input 参数（字符串或字典）
                # 将 arguments 字典作为 tool_input 传递
                logger.info(f"call_tool: 参数: {arguments}")
                try:
                    if hasattr(tool, 'arun'):
                        # arun 接受 tool_input 参数（可以是字符串或字典）
                        result = await tool.arun(arguments)
                    elif hasattr(tool, 'run'):
                        logger.info(f"call_tool: 使用同步方法 run（在线程中执行）")
                        # run 也接受 tool_input 参数
                        import asyncio
                        result = await asyncio.to_thread(tool.run, arguments)
                    else:
                        # 如果工具有 func 属性，直接调用
                        if hasattr(tool, 'func'):
                            logger.info(f"call_tool: 直接调用工具函数")
                            import asyncio
                            if asyncio.iscoroutinefunction(tool.func):
                                result = await tool.func(**arguments)
                            else:
                                result = await asyncio.to_thread(tool.func, **arguments)
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
