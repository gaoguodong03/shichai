"""聊天 API"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
import os
import json
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from app.agent.llm_client import QwenLLM
from app.agent.graph import create_react_agent
from app.mcp.manager import get_mcp_manager
from app.skills.loader import SkillsLoader
from app.api.settings import load_app_settings
from app.tools.export_session import create_export_session_tool
from app.tools.read_file import create_read_file_tool

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# 使用全局单例，与 settings 共用，保证 MCP 连接状态一致
mcp_manager = None  # 延迟赋值


def _get_mcp_manager():
    global mcp_manager
    if mcp_manager is None:
        mcp_manager = get_mcp_manager()
    return mcp_manager
skills_loader = SkillsLoader()
initialized = False

# 从工具结果文本中提取工具名（graph.py 会输出：工具 <tool_name> 的执行结果: ...）
_TOOL_NAME_RE = re.compile(r"工具\s+([^\s]+)\s+的执行结果")

# MCP server_id / 工具名 -> 本轮响应关联的 skill 名称（仅用于 meta 展示）
_MCP_SERVER_TO_SKILL: Dict[str, str] = {
    "volces-icon": "app-icon-generator",
    "linkup": "wechat-article-writer",
    "exa": "wechat-article-writer",
    "fetch": "wechat-article-writer",
    "mem0": "wechat-article-writer",
}
# 内置工具（无 server_id）-> skill
_TOOL_TO_SKILL: Dict[str, str] = {
    "export_session_to_md": "session-export",
}


def _update_meta_skill_from_tool_calls(meta_context: Dict[str, Any], message) -> None:
    """根据 AIMessage 的 tool_calls 更新 meta_context['skills']"""
    if not hasattr(message, "tool_calls") or not message.tool_calls:
        return
    tc = message.tool_calls[0]
    tool_name = tc.get("name") or tc.get("id") or ""
    # 内置工具（如 export_session_to_md）
    skill_name = _TOOL_TO_SKILL.get(tool_name)
    if skill_name:
        meta_context["skills"] = [skill_name]
        return
    # MCP 工具（server_id_tool_name）
    if "_" in tool_name:
        server_id = tool_name.split("_", 1)[0]
        skill_name = _MCP_SERVER_TO_SKILL.get(server_id)
        if skill_name:
            meta_context["skills"] = [skill_name]

SESSIONS_DIR = os.getenv("SESSIONS_DIR", "./data/sessions")


# 会话级对话历史（每段对话是一段记忆）：session_id -> [HumanMessage, AIMessage, ...]，最多保留最近 N 条
_CHAT_HISTORY: Dict[str, List[BaseMessage]] = {}
_CHAT_HISTORY_MAX_MESSAGES = 5

# 会话元数据：session_id -> {title, updated_at}，用于对话历史列表展示
_SESSION_META: Dict[str, Dict[str, str]] = {}


def _ensure_sessions_dir() -> Path:
    root = Path(SESSIONS_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _save_sessions_to_disk() -> None:
    """将会话历史与元数据持久化到本地 JSON 文件"""
    try:
        root = _ensure_sessions_dir()
        history_payload: Dict[str, List[Dict[str, Any]]] = {}
        for sid, msgs in _CHAT_HISTORY.items():
            history_payload[sid] = [_message_to_dict(m) for m in msgs]
        (root / "history.json").write_text(
            json.dumps(history_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (root / "meta.json").write_text(
            json.dumps(_SESSION_META, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"已将会话历史保存到磁盘（{len(_CHAT_HISTORY)} 个会话）")
    except Exception as e:
        logger.error(f"保存会话历史到磁盘失败: {e}", exc_info=True)


def _load_sessions_from_disk() -> None:
    """从本地 JSON 文件加载会话历史与元数据"""
    try:
        root = _ensure_sessions_dir()
        history_file = root / "history.json"
        meta_file = root / "meta.json"

        if history_file.exists():
            raw = json.loads(history_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for sid, msgs in raw.items():
                    restored: List[BaseMessage] = []
                    if isinstance(msgs, list):
                        for m in msgs:
                            if not isinstance(m, dict):
                                continue
                            role = m.get("role")
                            content = m.get("content", "")
                            if role == "user":
                                restored.append(HumanMessage(content=content))
                            elif role == "assistant":
                                restored.append(AIMessage(content=content))
                            else:
                                restored.append(HumanMessage(content=content))
                    if restored:
                        _CHAT_HISTORY[str(sid)] = restored

        if meta_file.exists():
            raw_meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if isinstance(raw_meta, dict):
                for sid, meta in raw_meta.items():
                    if isinstance(meta, dict):
                        _SESSION_META[str(sid)] = {
                            "title": str(meta.get("title", "新对话")),
                            "updated_at": str(meta.get("updated_at", "")),
                        }

        logger.info(f"已从磁盘加载会话历史: {len(_CHAT_HISTORY)} 个会话")
    except Exception as e:
        logger.error(f"从磁盘加载会话历史失败: {e}", exc_info=True)

async def ensure_initialized():
    """确保管理器已初始化"""
    global initialized
    if not initialized:
        logger.info("开始初始化 MCP Manager 和 Skills Loader")
        try:
            await _get_mcp_manager().initialize_all()
            mgr = _get_mcp_manager()
            logger.info(f"MCP Manager 初始化完成，加载了 {len(mgr.tools)} 个工具")
            for tool_name in mgr.tools.keys():
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

        # 从磁盘加载历史会话
        _load_sessions_from_disk()

        initialized = True
        logger.info("初始化完成")

class ChatRequest(BaseModel):
    """聊天请求"""
    message: str
    session_id: Optional[str] = "default"
    skill_ids: Optional[List[str]] = None  # 指定使用的技能，空则全部
    mcp_server_ids: Optional[List[str]] = None  # 指定使用的 MCP，空则全部

# 导出意图关键词：命中时直接执行导出，跳过 LLM 调用
_EXPORT_KEYWORDS = ("导出", "导出为", "导出对话", "保存为 markdown", "导出为完整", ".md 文件")


def _is_export_intent(message: str) -> bool:
    """判断是否为导出意图（直接执行，不调 LLM）"""
    t = (message or "").strip()
    return any(kw in t for kw in _EXPORT_KEYWORDS)


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式聊天接口"""
    logger.info(f"收到聊天请求: session_id={request.session_id}, message={request.message[:50]}...")
    
    await ensure_initialized()
    
    session_id = request.session_id or "default"
    
    # 导出意图：直接执行导出工具，跳过 LLM
    if _is_export_intent(request.message):
        logger.info("检测到导出意图，直接执行导出，跳过 LLM")
        export_tool = create_export_session_tool(session_id)
        result = export_tool.func()
        # 更新会话历史
        history = _CHAT_HISTORY.get(session_id, [])
        new_history = list(history) + [HumanMessage(content=request.message)] + [AIMessage(content=result)]
        if len(new_history) > _CHAT_HISTORY_MAX_MESSAGES:
            new_history = new_history[-_CHAT_HISTORY_MAX_MESSAGES:]
        _CHAT_HISTORY[session_id] = new_history
        # 更新会话元数据
        title = (request.message.strip()[:50] + "…") if len(request.message.strip()) > 50 else request.message.strip() or "新对话"
        _SESSION_META[session_id] = {
            "title": title,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_sessions_to_disk()
        async def _export_stream():
            import json as json_module
            meta = {"skills": ["session-export"], "tools": ["export_session_to_md"], "mcp_servers": []}
            yield f"event: start\ndata: {json_module.dumps({'type': 'start'})}\n\n"
            yield f"event: content\ndata: {json_module.dumps({'text': result, 'meta': meta}, ensure_ascii=False)}\n\n"
            yield f"event: end\ndata: {json_module.dumps({'type': 'end'})}\n\n"
        return StreamingResponse(
            _export_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )
    
    # 获取工具和技能（支持按 skill_ids / mcp_server_ids 筛选）
    all_tools = _get_mcp_manager().get_tools()
    if request.mcp_server_ids:
        tools = [t for t in all_tools if "_" in t.name and t.name.split("_", 1)[0] in request.mcp_server_ids]
    else:
        tools = list(all_tools)
    tools = tools + [create_export_session_tool(session_id), create_read_file_tool()]
    skills_instruction = skills_loader.get_active_skills_index(request.skill_ids)
    skill_routing_rules = skills_loader.get_skill_routing_rules(request.skill_ids)
    
    logger.info(f"可用工具数量: {len(tools)}")
    for tool in tools:
        logger.info(f"  - {tool.name}: {tool.description}")
    
    logger.info(f"技能索引长度: {len(skills_instruction)} 字符")
    
    # 应用设置：系统提示词在每次 chat 前注入到 prompt
    app_settings = load_app_settings()
    extra_system_prompt = app_settings.get("system_prompt") or ""
    
    # 创建 LLM 客户端（当前仅 qwen；default_llm 可扩展）
    llm = QwenLLM()
    
    # 创建 Agent
    agent = create_react_agent(
        llm, tools, skills_instruction,
        skill_routing_rules=skill_routing_rules,
        extra_system_prompt=extra_system_prompt,
    )
    logger.info("ReAct Agent 创建完成")
    # 加载该会话的历史消息，并与本条用户消息一起作为上下文发给大模型
    history = _CHAT_HISTORY.get(session_id, [])
    if len(history) > _CHAT_HISTORY_MAX_MESSAGES:
        history = history[-_CHAT_HISTORY_MAX_MESSAGES:]
    new_user_msg = HumanMessage(content=request.message)
    messages_for_agent = list(history) + [new_user_msg]
    
    initial_state = {
        "messages": messages_for_agent,
        "tools": tools
    }
    logger.info(f"初始状态准备完成，消息数量: {len(initial_state['messages'])}（含历史 {len(history)} 条）")
    
    async def event_generator():
        """事件生成器 - 使用完整的 ReAct Agent 工作流"""
        # 确保 json 模块可用
        import json as json_module
        try:
            logger.info("开始执行 Agent 工作流")
            # 发送开始事件
            yield f"event: start\ndata: {json_module.dumps({'type': 'start'})}\n\n"

            # meta 透传：skill 先根据用户消息推断（文案/校庆等->wechat-article-writer），后续若调用了工具则按工具所属 server 覆盖
            inferred_skill = skills_loader.infer_skill_from_message(request.message)
            meta_context: Dict[str, Any] = {
                "skills": [inferred_skill] if inferred_skill else [],
                "tools": [],
                "mcp_servers": [],
            }
            # 累积本轮助手回复，用于写入会话历史
            accumulated_content: List[str] = []
            
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
                                # 根据本条调用的工具更新 meta.skills（用于前端显示当前技能）
                                _update_meta_skill_from_tool_calls(meta_context, message)
                                
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
                                    accumulated_content.append(content_str)
                                    logger.info(f"✓ 发送文本内容（长度: {len(content_str)}）")
                                    yield f"event: content\ndata: {json_module.dumps({'text': content_str, 'meta': meta_context}, ensure_ascii=False)}\n\n"
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
                                _update_meta_skill_from_tool_calls(meta_context, message)
                                
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
                                    yield f"event: content\ndata: {json_module.dumps({'text': content_str, 'meta': meta_context}, ensure_ascii=False)}\n\n"
                                    has_sent_content = True
                                    
                                    # 如果有工具调用，也发送 react_step
                                    if has_tool_calls:
                                        yield f"event: react_step\ndata: {json_module.dumps({'type': 'thought', 'content': content_str}, ensure_ascii=False)}\n\n"
                                elif has_tool_calls:
                                    # 只有工具调用，没有文本内容 - 只发送 react_step，不发送空的 content
                                    logger.info("检测到工具调用（无文本内容），只发送 react_step")
                                    yield f"event: react_step\ndata: {json_module.dumps({'type': 'thought', 'content': '正在调用工具...'}, ensure_ascii=False)}\n\n"
                                # 如果既没有内容也没有工具调用，不发送任何内容（可能是中间状态）
                            logger.info("消息是字典格式，尝试提取内容")
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
                                accumulated_content.append(content_str)
                                logger.info(f"✓ 发送字典消息内容（长度: {len(content_str)}）")
                                yield f"event: content\ndata: {json_module.dumps({'text': content_str, 'meta': meta_context}, ensure_ascii=False)}\n\n"
                                has_sent_content = True
                            else:
                                logger.warning("字典消息内容为空，跳过发送")
                        
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
                            # 从文本中尽可能提取 tool/mcp server 名
                            tool_name = None
                            m = _TOOL_NAME_RE.search(str(content))
                            if m:
                                tool_name = m.group(1)
                            if tool_name:
                                meta_context["tools"] = [tool_name]
                                # 约定工具名格式: <server_id>_<tool>
                                server_id = tool_name.split("_", 1)[0] if "_" in tool_name else ""
                                if server_id:
                                    meta_context["mcp_servers"] = [server_id]
                                    skill_name = _MCP_SERVER_TO_SKILL.get(server_id)
                                    if skill_name:
                                        meta_context["skills"] = [skill_name]
                            yield f"event: react_step\ndata: {json_module.dumps({'type': 'tool_result', 'content': content, 'meta': meta_context}, ensure_ascii=False)}\n\n"
                
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
                            _update_meta_skill_from_tool_calls(meta_context, message)
                            
                            content_str = str(content) if content else ""
                            content_stripped = content_str.strip()
                            
                            # 只有当有实际文本内容时才发送（忽略只有工具调用的消息）
                            if content_stripped:
                                accumulated_content.append(content_str)
                                logger.info(f"✓ 发送文本内容（从状态更新，长度: {len(content_str)}）")
                                yield f"event: content\ndata: {json_module.dumps({'text': content_str, 'meta': meta_context}, ensure_ascii=False)}\n\n"
                                has_sent_content = True
                            elif has_tool_calls:
                                # 只有工具调用，发送 react_step
                                logger.info("从状态更新检测到工具调用（无文本内容）")
                                yield f"event: react_step\ndata: {json_module.dumps({'type': 'thought', 'content': '正在调用工具...'}, ensure_ascii=False)}\n\n"
                            # 如果既没有内容也没有工具调用，不发送（可能是中间状态）
                        
                        elif isinstance(message, HumanMessage):
                            content = message.content
                            logger.info(f"工具执行结果（从状态更新）: {content}")
                            tool_name = None
                            m = _TOOL_NAME_RE.search(str(content))
                            if m:
                                tool_name = m.group(1)
                            if tool_name:
                                meta_context["tools"] = [tool_name]
                                server_id = tool_name.split("_", 1)[0] if "_" in tool_name else ""
                                if server_id:
                                    meta_context["mcp_servers"] = [server_id]
                                    skill_name = _MCP_SERVER_TO_SKILL.get(server_id)
                                    if skill_name:
                                        meta_context["skills"] = [skill_name]
                            yield f"event: react_step\ndata: {json_module.dumps({'type': 'tool_result', 'content': content, 'meta': meta_context}, ensure_ascii=False)}\n\n"
                    
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
                                accumulated_content.append(content_str)
                                logger.info(f"✓ 从最终状态发送内容（长度: {len(content_str)}）")
                                yield f"event: content\ndata: {json_module.dumps({'text': content_str, 'meta': meta_context}, ensure_ascii=False)}\n\n"
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
                                    accumulated_content.append(content_str)
                                    logger.info(f"✓ 从增量发送内容（长度: {len(content_str)}）")
                                    yield f"event: content\ndata: {json_module.dumps({'text': content_str, 'meta': meta_context}, ensure_ascii=False)}\n\n"
                                    has_sent_content = True
                                    break
                
                if not has_sent_content:
                    logger.warning("无法从最终状态获取内容")
                    accumulated_content.append("（没有收到响应）")
                    yield f"event: content\ndata: {json_module.dumps({'text': '（没有收到响应）', 'meta': meta_context}, ensure_ascii=False)}\n\n"
                    has_sent_content = True
            
            # 触发一次读取，避免 last_agent_response “只赋值未使用”
            if last_agent_response is not None:
                logger.info("已生成最后一条 Agent 响应")
            logger.info(f"Agent 工作流执行完成，共处理 {event_count} 个事件，已发送内容: {has_sent_content}")
            # 将会话历史写入内存：历史 + 本轮用户消息 + 本轮助手回复
            full_content = "".join(accumulated_content).strip() if accumulated_content else ""
            new_history = list(history) + [new_user_msg] + [AIMessage(content=full_content or "(无响应)")]
            if len(new_history) > _CHAT_HISTORY_MAX_MESSAGES:
                new_history = new_history[-_CHAT_HISTORY_MAX_MESSAGES:]
            _CHAT_HISTORY[session_id] = new_history
            # 更新会话元数据：标题取首条用户消息前 50 字，更新时间
            title = (request.message.strip()[:50] + "…") if len(request.message.strip()) > 50 else request.message.strip() or "新对话"
            _SESSION_META[session_id] = {
                "title": title,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            logger.info(f"已更新会话 {session_id} 历史，共 {len(new_history)} 条消息")
            # 持久化到磁盘
            _save_sessions_to_disk()
            # 发送结束事件
            yield f"event: end\ndata: {json_module.dumps({'type': 'end'})}\n\n"
        except asyncio.CancelledError:
            # 客户端断开、超时等导致取消，正常退出，不视为错误
            logger.info("chat_stream: 请求已取消（客户端断开或超时）")
        except Exception as e:
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

def _message_to_dict(msg: BaseMessage) -> Dict[str, Any]:
    """将 LangChain 消息转为 API 可序列化格式"""
    if isinstance(msg, HumanMessage):
        return {"role": "user", "content": msg.content if isinstance(msg.content, str) else str(msg.content)}
    if isinstance(msg, AIMessage):
        return {"role": "assistant", "content": msg.content if isinstance(msg.content, str) else str(msg.content)}
    return {"role": "unknown", "content": str(getattr(msg, "content", ""))}


@router.get("/sessions")
async def list_sessions():
    """获取会话列表（对话历史用）"""
    # 确保有 default 会话的元数据（从未发过消息时也可展示）
    if "default" not in _SESSION_META and "default" in _CHAT_HISTORY:
        first_msg = None
        for m in _CHAT_HISTORY.get("default", []):
            if isinstance(m, HumanMessage):
                c = m.content if isinstance(m.content, str) else str(m.content)
                first_msg = (c.strip()[:50] + "…") if len(c.strip()) > 50 else (c.strip() or "新对话")
                break
        _SESSION_META["default"] = {
            "title": first_msg or "新对话",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    # 合并：有历史的会话 + 有元数据的会话，按 updated_at 倒序
    session_ids = set(_CHAT_HISTORY.keys()) | set(_SESSION_META.keys())
    result = []
    for sid in session_ids:
        meta = _SESSION_META.get(sid, {})
        title = meta.get("title")
        if title is None and sid in _CHAT_HISTORY:
            for m in _CHAT_HISTORY[sid]:
                if isinstance(m, HumanMessage):
                    c = m.content if isinstance(m.content, str) else str(m.content)
                    title = (c.strip()[:50] + "…") if len(c.strip()) > 50 else (c.strip() or "新对话")
                    break
        title = title or "新对话"
        updated_at = meta.get("updated_at", "")
        result.append({"id": sid, "title": title, "updated_at": updated_at})
    result.sort(key=lambda x: x["updated_at"] or "", reverse=True)
    return {"status": "ok", "data": {"sessions": result}}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取指定会话的完整消息列表"""
    history = _CHAT_HISTORY.get(session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Session not found")
    meta = _SESSION_META.get(session_id, {})
    messages = [_message_to_dict(m) for m in history]
    return {
        "status": "ok",
        "data": {
            "id": session_id,
            "title": meta.get("title", "新对话"),
            "updated_at": meta.get("updated_at", ""),
            "messages": messages,
        },
    }


def _export_session_to_md(session_id: str, filename: str = None) -> tuple[str, str]:
    """将会话导出为 markdown 文件，返回 (relative_path, download_url)"""
    from pathlib import Path
    from app.api.files import AGENT_OUTPUTS_DIR

    history = _CHAT_HISTORY.get(session_id, [])
    if not history:
        raise HTTPException(status_code=400, detail="Session has no messages")
    lines = ["# 对话导出\n", f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "---\n"]
    for msg in history:
        if isinstance(msg, HumanMessage):
            lines.append("## 用户\n\n")
        else:
            lines.append("## 助手\n\n")
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        lines.append(content.strip())
        lines.append("\n\n")
    md = "".join(lines)
    root = Path(AGENT_OUTPUTS_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    fn = filename or f"session-{session_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    fn = fn.replace("..", "").replace("/", "")
    if not fn.endswith(".md"):
        fn += ".md"
    filepath = root / fn
    filepath.write_text(md, encoding="utf-8")
    rel = str(filepath.relative_to(root)).replace("\\", "/")
    return rel, f"/api/files/download?path={rel}"


@router.post("/sessions/{session_id}/export")
async def export_session(session_id: str, filename: str = None):
    """将会话导出为 markdown 文件"""
    try:
        rel_path, download_url = _export_session_to_md(session_id, filename)
        return {"status": "ok", "data": {"path": rel_path, "download_url": download_url}}
    except HTTPException:
        raise


@router.post("/chat")
async def chat(request: ChatRequest):
    """非流式聊天接口（用于测试）"""
    # 简化实现，实际应该使用流式接口
    return {"message": "请使用 /chat/stream 接口"}
