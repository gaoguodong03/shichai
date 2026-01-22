"""聊天 API"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json
import logging
from langchain_core.messages import HumanMessage, AIMessage
from app.agent.llm_client import QwenLLM
from app.agent.graph import create_react_agent
from app.mcp.manager import MCPToolManager
from app.skills.loader import SkillsLoader

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# 全局管理器（实际应该使用依赖注入）
mcp_manager = MCPToolManager()
skills_loader = SkillsLoader()
initialized = False

async def ensure_initialized():
    """确保管理器已初始化"""
    global initialized
    if not initialized:
        logger.info("开始初始化 MCP Manager 和 Skills Loader")
        try:
            await mcp_manager.initialize_all()
            logger.info(f"MCP Manager 初始化完成，加载了 {len(mcp_manager.tools)} 个工具")
            for tool_name in mcp_manager.tools.keys():
                logger.info(f"  - 工具: {tool_name}")
        except Exception as e:
            logger.error(f"Failed to initialize MCP managers: {e}", exc_info=True)
        
        try:
            skills_loader.load_all_skills()
            logger.info(f"Skills Loader 初始化完成，加载了 {len(skills_loader.skills)} 个技能")
            for skill_name in skills_loader.skills.keys():
                logger.info(f"  - 技能: {skill_name}")
        except Exception as e:
            logger.error(f"Failed to load skills: {e}", exc_info=True)
        
        initialized = True
        logger.info("初始化完成")

class ChatRequest(BaseModel):
    """聊天请求"""
    message: str
    session_id: Optional[str] = "default"

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式聊天接口"""
    logger.info(f"收到聊天请求: session_id={request.session_id}, message={request.message[:50]}...")
    
    await ensure_initialized()
    
    # 获取工具和技能
    tools = mcp_manager.get_tools()
    skills_instruction = skills_loader.get_active_skills_instructions()
    
    logger.info(f"可用工具数量: {len(tools)}")
    for tool in tools:
        logger.info(f"  - {tool.name}: {tool.description}")
    
    logger.info(f"技能指令长度: {len(skills_instruction)} 字符")
    
    # 创建 LLM 客户端
    llm = QwenLLM()
    
    # 创建 Agent
    agent = create_react_agent(llm, tools, skills_instruction)
    logger.info("ReAct Agent 创建完成")
    
    # 初始状态
    initial_state = {
        "messages": [HumanMessage(content=request.message)],
        "tools": tools
    }
    logger.info(f"初始状态准备完成，消息数量: {len(initial_state['messages'])}")
    
    async def event_generator():
        """事件生成器 - 使用完整的 ReAct Agent 工作流"""
        # 确保 json 模块可用
        import json as json_module
        try:
            logger.info("开始执行 Agent 工作流")
            # 发送开始事件
            yield f"event: start\ndata: {json_module.dumps({'type': 'start'})}\n\n"
            
            # 使用 LangGraph 运行完整的 ReAct 循环
            # 流式执行 Agent 工作流
            event_count = 0
            last_agent_response = None  # 保存最后一个 agent 响应
            has_sent_content = False  # 跟踪是否已发送内容
            final_state = None  # 保存最终状态
            
            # 跟踪上一个状态，以便检测新消息
            previous_messages = initial_state.get("messages", [])
            
            async for event in agent.astream(initial_state):
                final_state = event  # 保存最后一个状态
                event_count += 1
                logger.info(f"收到 Agent 事件 #{event_count}: {list(event.keys())}")
                
                # LangGraph 的 astream 可能返回两种格式：
                # 1. 节点输出格式: {"agent": [AIMessage(...)], "tool": [HumanMessage(...)]}
                # 2. 状态更新格式: {"messages": [...]}
                
                # 处理节点输出格式（优先）
                if "agent" in event:
                    agent_output = event["agent"]
                    logger.info(f"agent 节点输出类型: {type(agent_output).__name__}")
                    
                    # 如果 agent 输出是字典且包含 messages 键，提取 messages
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        logger.info(f"agent 输出是状态字典，包含 {len(agent_output['messages'])} 条消息")
                        messages = agent_output["messages"]
                        # 找出最后一条 AIMessage
                        for message in reversed(messages):
                            if isinstance(message, AIMessage):
                                logger.info(f"找到 AIMessage，内容: {str(message.content)[:200]}...")
                                # 处理这条 AIMessage
                                last_agent_response = message
                                content = message.content
                                logger.info(f"Agent 响应内容类型: {type(content)}, 内容 (前200字符): {str(content)[:200]}...")
                                
                                # 检查是否有工具调用
                                has_tool_calls = hasattr(message, 'tool_calls') and message.tool_calls
                                logger.info(f"Agent 响应 - 是否有工具调用: {has_tool_calls}")
                                
                                # 处理文本内容
                                content_str = ""
                                if isinstance(content, str):
                                    content_str = content
                                elif content is not None:
                                    content_str = str(content)
                                
                                content_stripped = content_str.strip() if content_str else ""
                                logger.info(f"内容 strip 后长度: {len(content_stripped)}")
                                
                                # 只有当有实际文本内容时才发送 content 事件
                                if content_stripped:
                                    logger.info(f"✓ 发送文本内容（长度: {len(content_str)}）")
                                    yield f"event: content\ndata: {json_module.dumps({'text': content_str}, ensure_ascii=False)}\n\n"
                                    has_sent_content = True
                                    
                                    # 如果有工具调用，也发送 react_step
                                    if has_tool_calls:
                                        yield f"event: react_step\ndata: {json_module.dumps({'type': 'thought', 'content': content_str}, ensure_ascii=False)}\n\n"
                                elif has_tool_calls:
                                    # 只有工具调用，没有文本内容 - 只发送 react_step，不发送空的 content
                                    logger.info("检测到工具调用（无文本内容），只发送 react_step")
                                    yield f"event: react_step\ndata: {json_module.dumps({'type': 'thought', 'content': '正在调用工具...'}, ensure_ascii=False)}\n\n"
                                break  # 找到最后一条 AIMessage 后退出
                        else:
                            logger.warning("在 agent 状态字典中未找到 AIMessage")
                    # 如果 agent 输出是列表或单个消息对象
                    elif isinstance(agent_output, list):
                        messages = agent_output
                        logger.info(f"处理 agent 节点输出（列表格式），消息数量: {len(messages)}")
                        
                        for idx, message in enumerate(messages):
                            logger.info(f"消息 #{idx}: 类型={type(message).__name__}, 是否为 AIMessage={isinstance(message, AIMessage)}")
                            
                            # 处理 AIMessage 对象
                            if isinstance(message, AIMessage):
                                last_agent_response = message  # 保存最后一个响应
                                content = message.content
                                logger.info(f"Agent 响应内容类型: {type(content)}, 内容 (前200字符): {str(content)[:200]}...")
                                
                                # 检查是否有工具调用
                                has_tool_calls = hasattr(message, 'tool_calls') and message.tool_calls
                                logger.info(f"Agent 响应 - 是否有工具调用: {has_tool_calls}")
                                
                                # 处理文本内容
                                content_str = ""
                                if isinstance(content, str):
                                    content_str = content
                                elif content is not None:
                                    content_str = str(content)
                                
                                content_stripped = content_str.strip() if content_str else ""
                                logger.info(f"内容 strip 后长度: {len(content_stripped)}")
                                
                                # 只有当有实际文本内容时才发送 content 事件
                                if content_stripped:
                                    logger.info(f"✓ 发送文本内容（长度: {len(content_str)}）")
                                    yield f"event: content\ndata: {json_module.dumps({'text': content_str}, ensure_ascii=False)}\n\n"
                                    has_sent_content = True
                                    
                                    # 如果有工具调用，也发送 react_step
                                    if has_tool_calls:
                                        yield f"event: react_step\ndata: {json_module.dumps({'type': 'thought', 'content': content_str}, ensure_ascii=False)}\n\n"
                                elif has_tool_calls:
                                    # 只有工具调用，没有文本内容 - 只发送 react_step，不发送空的 content
                                    logger.info("检测到工具调用（无文本内容），只发送 react_step")
                                    yield f"event: react_step\ndata: {json_module.dumps({'type': 'thought', 'content': '正在调用工具...'}, ensure_ascii=False)}\n\n"
                                # 如果既没有内容也没有工具调用，不发送任何内容（可能是中间状态）
                            logger.info(f"消息是字典格式，尝试提取内容")
                            # 尝试从字典中提取内容 - 只提取 content 字段，不要发送整个字典
                            content = message.get("content")
                            
                            # 如果 content 是列表（可能是多部分内容），提取文本部分
                            if isinstance(content, list):
                                text_parts = [str(item.get("text", item)) for item in content if isinstance(item, dict)]
                                content = " ".join(text_parts) if text_parts else None
                            
                            if not content:
                                content = message.get("text")
                            
                            logger.info(f"从字典提取的内容: {repr(str(content)[:200]) if content else 'None'}")
                            
                            content_str = str(content) if content else ""
                            content_stripped = content_str.strip()
                            
                            # 只有当有实际内容时才发送，不要发送整个字典
                            if content_stripped:
                                logger.info(f"✓ 发送字典消息内容（长度: {len(content_str)}）")
                                yield f"event: content\ndata: {json_module.dumps({'text': content_str}, ensure_ascii=False)}\n\n"
                                has_sent_content = True
                            else:
                                logger.warning(f"字典消息内容为空，跳过发送")
                        
                        else:
                            logger.warning(f"消息 #{idx} 类型未知，跳过处理。类型: {type(message).__name__}")
                
                elif "tool" in event:
                    messages = event["tool"]
                    if not isinstance(messages, list):
                        messages = [messages]
                    logger.info(f"处理 tool 节点输出，消息数量: {len(messages)}")
                    
                    for message in messages:
                        if isinstance(message, HumanMessage):
                            content = message.content
                            logger.info(f"工具执行结果: {content}")
                            yield f"event: react_step\ndata: {json_module.dumps({'type': 'tool_result', 'content': content}, ensure_ascii=False)}\n\n"
                
                # 处理状态更新格式（备用）
                elif "messages" in event:
                    current_messages = event["messages"]
                    logger.info(f"状态更新: messages 数量从 {len(previous_messages)} 变为 {len(current_messages)}")
                    
                    # 找出新添加的消息
                    new_messages = current_messages[len(previous_messages):]
                    logger.info(f"检测到 {len(new_messages)} 条新消息")
                    
                    for idx, message in enumerate(new_messages):
                        logger.info(f"新消息 #{idx}: 类型={type(message).__name__}")
                        
                        if isinstance(message, AIMessage):
                            last_agent_response = message
                            content = message.content
                            
                            # 检查是否有工具调用
                            has_tool_calls = hasattr(message, 'tool_calls') and message.tool_calls
                            
                            content_str = str(content) if content else ""
                            content_stripped = content_str.strip()
                            
                            # 只有当有实际文本内容时才发送（忽略只有工具调用的消息）
                            if content_stripped:
                                logger.info(f"✓ 发送文本内容（从状态更新，长度: {len(content_str)}）")
                                yield f"event: content\ndata: {json_module.dumps({'text': content_str}, ensure_ascii=False)}\n\n"
                                has_sent_content = True
                            elif has_tool_calls:
                                # 只有工具调用，发送 react_step
                                logger.info("从状态更新检测到工具调用（无文本内容）")
                                yield f"event: react_step\ndata: {json_module.dumps({'type': 'thought', 'content': '正在调用工具...'}, ensure_ascii=False)}\n\n"
                            # 如果既没有内容也没有工具调用，不发送（可能是中间状态）
                        
                        elif isinstance(message, HumanMessage):
                            content = message.content
                            logger.info(f"工具执行结果（从状态更新）: {content}")
                            yield f"event: react_step\ndata: {json_module.dumps({'type': 'tool_result', 'content': content}, ensure_ascii=False)}\n\n"
                    
                    # 更新 previous_messages 以便下次比较
                    previous_messages = current_messages
                else:
                    logger.info(f"事件格式未知，跳过。事件键: {list(event.keys())}")
            
            # 如果整个流程结束都没有发送内容，从最终状态中获取最后一条消息
            if not has_sent_content:
                logger.warning("整个流程结束但没有发送任何内容，尝试从最终状态获取")
                
                # 方法1: 从保存的 final_state 获取
                if final_state and "messages" in final_state:
                    messages = final_state["messages"]
                    logger.info(f"最终状态中有 {len(messages)} 条消息")
                    
                    # 找出最后一条 AIMessage
                    for message in reversed(messages):
                        if isinstance(message, AIMessage):
                            content = message.content
                            content_str = str(content) if content else ""
                            content_stripped = content_str.strip()
                            
                            if content_stripped:
                                logger.info(f"✓ 从最终状态发送内容（长度: {len(content_str)}）")
                                yield f"event: content\ndata: {json_module.dumps({'text': content_str}, ensure_ascii=False)}\n\n"
                                has_sent_content = True
                                break
                
                # 方法2: 如果 final_state 没有 messages，尝试从 initial_state 的增量中获取
                if not has_sent_content and previous_messages:
                    # 比较初始和最终状态
                    if final_state and "messages" in final_state:
                        current_messages = final_state["messages"]
                        new_messages = current_messages[len(initial_state.get("messages", [])):]
                        logger.info(f"从增量中检测到 {len(new_messages)} 条新消息")
                        
                        for message in reversed(new_messages):
                            if isinstance(message, AIMessage):
                                content = message.content
                                content_str = str(content) if content else ""
                                content_stripped = content_str.strip()
                                
                                if content_stripped:
                                    logger.info(f"✓ 从增量发送内容（长度: {len(content_str)}）")
                                    yield f"event: content\ndata: {json_module.dumps({'text': content_str}, ensure_ascii=False)}\n\n"
                                    has_sent_content = True
                                    break
                
                if not has_sent_content:
                    logger.warning("无法从最终状态获取内容")
                    yield f"event: content\ndata: {json_module.dumps({'text': '（没有收到响应）'}, ensure_ascii=False)}\n\n"
                    has_sent_content = True
            
            logger.info(f"Agent 工作流执行完成，共处理 {event_count} 个事件，已发送内容: {has_sent_content}")
            # 发送结束事件
            yield f"event: end\ndata: {json_module.dumps({'type': 'end'})}\n\n"
        except Exception as e:
            import traceback
            error_msg = str(e)
            logger.error(f"Error in chat_stream: {error_msg}", exc_info=True)
            yield f"event: error\ndata: {json_module.dumps({'error': error_msg})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.post("/chat")
async def chat(request: ChatRequest):
    """非流式聊天接口（用于测试）"""
    # 简化实现，实际应该使用流式接口
    return {"message": "请使用 /chat/stream 接口"}
