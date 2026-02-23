"""聊天 API"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
import os
import json
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

try:
    from langchain_core.messages import messages_from_dict
except ImportError:
    messages_from_dict = None
from app.agent.llm_client import get_llm_from_config, QwenLLM
from app.agent.graph import create_skill_execution_agent
from app.agent.skill_selector import select_skill
from app.mcp.manager import get_mcp_manager, normalize_mcp_kwargs_for_call
from app.skills.loader import SkillsLoader
from app.api.settings import load_app_settings
from app.tools.export_session import create_export_session_tool
from app.tools.read_file import create_read_file_tool
from app.tools.run_skill_script import create_run_skill_script_tool
from app.tools.call_api import call_api

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
# 从图标工具结果中提取图片 URL，用于格式化为 Markdown 图片以便前端渲染
_IMAGE_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# 技能 -> 关联的 MCP server_id 列表（一个技能可对应多个 MCP，一个 MCP 可被多技能共用）
_SKILL_MCP_SERVERS: Dict[str, List[str]] = {
    "wechat-article-writer": ["linkup", "exa", "fetch", "mem0"],
    "amap-maps": ["amap-maps"],
    "app-icon-generator": ["volces-icon"],
    "blog-write": ["linkup", "exa", "fetch", "zhipu-web-search"],
    "data-report": ["linkup", "exa", "fetch"],
    "zhipu-web-search": ["zhipu-web-search"],
}
# 由 _SKILL_MCP_SERVERS 反推：server_id -> skill_id（取首个，用于 meta 展示）
_MCP_SERVER_TO_SKILL: Dict[str, str] = {}
for _sk, _srv_list in _SKILL_MCP_SERVERS.items():
    for _s in _srv_list:
        if _s not in _MCP_SERVER_TO_SKILL:
            _MCP_SERVER_TO_SKILL[_s] = _sk


def _get_mcp_servers_for_skill(skill_id: str) -> List[str]:
    """根据 skill_id 返回其关联的 MCP server_id 列表。用于技能执行时只传入该技能的工具。"""
    return list(_SKILL_MCP_SERVERS.get(skill_id, []))
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
    existing = meta_context.get("skills") or []
    # 内置工具（如 export_session_to_md）
    skill_name = _TOOL_TO_SKILL.get(tool_name)
    if skill_name:
        # 只有在当前没有 skill 标记时才覆盖，避免把用户显式选择的 skill 覆盖掉
        if not existing:
            meta_context["skills"] = [skill_name]
        return
    # MCP 工具（server_id_tool_name）
    if "_" in tool_name:
        server_id = tool_name.split("_", 1)[0]
        skill_name = _MCP_SERVER_TO_SKILL.get(server_id)
        if skill_name:
            if not existing:
                meta_context["skills"] = [skill_name]

SESSIONS_DIR = os.getenv("SESSIONS_DIR", "./data/sessions")


# 会话级对话历史（每段对话是一段记忆）：session_id -> [HumanMessage, AIMessage, ...]
# 不再对历史消息条数做硬性上限，轮次（Turn）数量理论上不设上限。
_CHAT_HISTORY: Dict[str, List[BaseMessage]] = {}
_CHAT_HISTORY_MAX_MESSAGES = 5  # 保留旧常量以兼容，但不再用于截断

# 每个 Session 的轮次摘要：session_id -> [turn_summary1, turn_summary2, ...]
_TURN_SUMMARIES: Dict[str, List[str]] = {}

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
        # 轮次摘要单独持久化，避免破坏原有 history 结构
        turn_payload: Dict[str, List[str]] = {}
        for sid, turns in _TURN_SUMMARIES.items():
            # 只保存非空摘要
            clean_turns = [str(t).strip() for t in turns if str(t).strip()]
            if clean_turns:
                turn_payload[sid] = clean_turns
        (root / "turn_summaries.json").write_text(
            json.dumps(turn_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"已将会话历史与轮次摘要保存到磁盘（{len(_CHAT_HISTORY)} 个会话）")
    except Exception as e:
        logger.error(f"保存会话历史到磁盘失败: {e}", exc_info=True)


def _load_sessions_from_disk() -> None:
    """从本地 JSON 文件加载会话历史与元数据"""
    try:
        root = _ensure_sessions_dir()
        history_file = root / "history.json"
        meta_file = root / "meta.json"
        turn_file = root / "turn_summaries.json"

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
                                raw_list = m.get("tool_raw_results")
                                skill_id = m.get("skill_id")
                                additional: Dict[str, Any] = {}
                                if isinstance(raw_list, list) and raw_list:
                                    additional["tool_raw_results"] = raw_list
                                if skill_id is not None:
                                    additional["skill_id"] = skill_id
                                kwargs = {"additional_kwargs": additional} if additional else {}
                                restored.append(AIMessage(content=content, **kwargs))
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

        # 加载轮次摘要（若存在），只保留最近 N 轮以控制内存
        if turn_file.exists():
            raw_turns = json.loads(turn_file.read_text(encoding="utf-8"))
            if isinstance(raw_turns, dict):
                for sid, turns in raw_turns.items():
                    if isinstance(turns, list):
                        clean = [str(t) for t in turns if isinstance(t, (str, int, float))]
                        _TURN_SUMMARIES[str(sid)] = clean[-_HISTORY_WINDOW_TURNS:]

        logger.info(f"已从磁盘加载会话历史: {len(_CHAT_HISTORY)} 个会话；轮次摘要: {len(_TURN_SUMMARIES)} 个会话")
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
        except asyncio.CancelledError:
            raise  # 请求被取消（如前端断开/超时），直接向上抛，不转为 500
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


class SessionTitleBody(BaseModel):
    """更新会话标题请求体"""

    title: str

# 导出意图关键词：命中时直接执行导出，跳过 LLM 调用
_EXPORT_KEYWORDS = ("导出", "导出为", "导出对话", "保存为 markdown", "导出为完整", ".md 文件")


def _is_export_intent(message: str) -> bool:
    """判断是否为导出意图（直接执行，不调 LLM）"""
    t = (message or "").strip()
    return any(kw in t for kw in _EXPORT_KEYWORDS)


# 单轮摘要建议字数：稍详细以便后续轮次不丢关键信息，但单轮有上限
_TURN_SUMMARY_MAX_CHARS = 220


async def _summarize_turn_with_llm(
    llm: "QwenLLM",
    user_text: str,
    assistant_text: str,
    max_input_chars: int = 3000,
) -> str:
    """
    使用 LLM 为单个 Turn（用户 + 助手）生成摘要。
    - 摘要稍详细（约 150–220 字），包含：用户问题要点、助手是否调用工具/搜索及关键结论或数据。
    - 仅作为「历史记忆」发给后续轮次的大模型，不直接展示给用户。
    """
    from langchain_core.messages import SystemMessage, HumanMessage

    user_text = (user_text or "").strip()
    assistant_text = (assistant_text or "").strip()

    # 粗略截断输入，避免异常长上下文
    if len(user_text) > max_input_chars // 3:
        user_text = user_text[: max_input_chars // 3] + "…"
    if len(assistant_text) > max_input_chars * 2 // 3:
        assistant_text = assistant_text[: max_input_chars * 2 // 3] + "…"

    try:
        client = llm.get_client()
        system_prompt = (
            "你是对话摘要助手。请用 150–220 字的中文，总结下面用户与助手本轮对话，必须包含：\n"
            "1. 用户问题或需求要点（一句话概括）。\n"
            "2. 助手做了什么：若调用了工具/搜索，写出工具类型或搜索关键词及结果要点；若直接回答，写出关键结论、数据、链接或名称。\n"
            "3. 若有重要约定、结论、数字、链接，请保留在摘要中。\n"
            "不要加入新内容，不要复述无关客套，不要漏掉对后续对话有用的关键信息。"
        )
        content = f"【用户】\n{user_text}\n\n【助手】\n{assistant_text}"
        resp = await client.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=content),
            ]
        )
        summary = (getattr(resp, "content", "") or "").strip()
        if summary:
            # 单轮摘要过长时截断，避免历史摘要总长膨胀
            if len(summary) > _TURN_SUMMARY_MAX_CHARS:
                summary = summary[:_TURN_SUMMARY_MAX_CHARS].rstrip() + "…"
            return summary
    except Exception as e:
        logger.error(f"生成 Turn 摘要失败: {e}", exc_info=True)

    # 回退：简单拼接截断版用户 / 助手内容
    fallback_user = user_text[:100] + ("…" if len(user_text) > 100 else "")
    fallback_assistant = assistant_text[:150] + ("…" if len(assistant_text) > 150 else "")
    return f"用户：{fallback_user} 助手：{fallback_assistant}"


# 记忆窗口：只保留最近 N 轮摘要，传入 LLM 的上下文
_HISTORY_WINDOW_TURNS = 10
# 历史摘要总字符上限，避免提示词过长
_HISTORY_SUMMARY_MAX_TOTAL_CHARS = 3200


def _append_turn_summary(session_id: str, summary: str) -> None:
    """将单轮摘要追加到内存结构中。空摘要会被忽略。只保留最近 _HISTORY_WINDOW_TURNS 轮。"""
    s = (summary or "").strip()
    if not s:
        return
    turns = _TURN_SUMMARIES.get(session_id)
    if turns is None:
        _TURN_SUMMARIES[session_id] = [s]
    else:
        turns.append(s)
        if len(turns) > _HISTORY_WINDOW_TURNS:
            _TURN_SUMMARIES[session_id] = turns[-_HISTORY_WINDOW_TURNS:]


def _build_history_summary(session_id: str, history: List[BaseMessage], max_chars_per_msg: int = 200) -> str:
    """
    从历史消息构建摘要，用于多轮 chat 的上下文。

    优先使用「按 Turn 的 LLM 摘要」：
    - 若存在 _TURN_SUMMARIES[session_id]，则直接拼接这些摘要。
    - 否则按原始消息对 (Human + AI) 构造简要预览文本，作为回退。
    """
    if not history:
        return ""

    # 1. 优先使用已生成的 Turn 摘要（每个元素对应一轮），只取最近 10 轮
    turn_summaries = _TURN_SUMMARIES.get(session_id) or []
    if turn_summaries:
        recent = turn_summaries[-_HISTORY_WINDOW_TURNS:]
        lines: List[str] = []
        for idx, s in enumerate(recent, start=1):
            summary_str = (s or "").strip()
            if not summary_str:
                continue
            lines.append(f"第{idx}轮：{summary_str}")
        if lines:
            raw = "\n".join(lines)
            # 总长超过上限时，从最早轮开始丢弃，只保留能塞进上限的最近几轮
            if len(raw) > _HISTORY_SUMMARY_MAX_TOTAL_CHARS:
                kept: List[str] = []
                total = 0
                for line in reversed(lines):
                    if total + len(line) + 1 > _HISTORY_SUMMARY_MAX_TOTAL_CHARS:
                        break
                    kept.insert(0, line)
                    total += len(line) + 1
                raw = "\n".join(kept)
            return raw

    # 2. 无 Turn 摘要时，先收集所有轮次，再取最近 10 轮做简要预览
    all_turns: List[tuple] = []
    i = 0
    n = len(history)
    while i < n:
        msg = history[i]
        i += 1
        if not isinstance(msg, HumanMessage):
            continue
        user_content = getattr(msg, "content", "") or ""
        user_preview = str(user_content)[:max_chars_per_msg]
        if len(str(user_content)) > max_chars_per_msg:
            user_preview += "…"
        assistant_preview = ""
        while i < n:
            next_msg = history[i]
            i += 1
            if isinstance(next_msg, AIMessage):
                ai_content = getattr(next_msg, "content", "") or ""
                assistant_preview = str(ai_content)[:max_chars_per_msg]
                if len(str(ai_content)) > max_chars_per_msg:
                    assistant_preview += "…"
                break
        all_turns.append((user_preview, assistant_preview))

    recent_turns = all_turns[-_HISTORY_WINDOW_TURNS:]
    lines = []
    for idx, (up, ap) in enumerate(recent_turns, start=1):
        lines.append(f"第{idx}轮：")
        lines.append(f"- 用户：{up}")
        if ap:
            lines.append(f"- 助手：{ap}")
        lines.append("")
    return "\n".join(lines).strip()


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式聊天接口"""
    t_start = time.perf_counter()
    logger.info(f"收到聊天请求: session_id={request.session_id}, message={request.message[:50]}...")
    
    await ensure_initialized()
    logger.info(f"[TIMING] ensure_initialized: {time.perf_counter() - t_start:.2f}s")
    
    session_id = request.session_id or "default"
    
    # 导出意图：直接执行导出工具，跳过 LLM
    if _is_export_intent(request.message):
        logger.info("检测到导出意图，直接执行导出，跳过 LLM")
        export_tool = create_export_session_tool(session_id)
        result = export_tool.func()
        # 更新会话历史
        history = _CHAT_HISTORY.get(session_id, [])
        # 追加本次用户消息与导出结果，不再按条数截断，会话完整保留
        new_history = list(history) + [HumanMessage(content=request.message)] + [AIMessage(content=result)]
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
        all_tools = [t for t in all_tools if "_" in t.name and t.name.split("_", 1)[0] in request.mcp_server_ids]
    skills_for_selection = skills_loader.get_skills_for_selection(request.skill_ids)

    logger.info(f"MCP 工具总数: {len(all_tools)}")
    logger.info(f"技能数量（用于选择）: {len(skills_for_selection)}")

    app_settings = load_app_settings()
    extra_system_prompt = app_settings.get("system_prompt") or ""
    provider_id = app_settings.get("default_llm", "qwen")
    llm = get_llm_from_config(provider_id, app_settings.get("llm_providers"))
    logger.info(f"使用 LLM provider: {provider_id}")

    # 加载历史，构建摘要（多轮 chat 时加入）
    # 使用该 session 下的全部历史消息，按 Turn 摘要传给大模型
    history = _CHAT_HISTORY.get(session_id, [])
    history_summary = _build_history_summary(session_id, history) if history else None

    # 阶段一：技能选择（仅 name+description）
    # 如果前端已显式指定 skill_ids 且只有一个，直接使用该 skill，跳过第一次 LLM 选择
    if request.skill_ids and len(skills_for_selection) == 1:
        selected_skill_id = skills_for_selection[0].get("skill_id")
        logger.info(f"前端显式指定 skill_ids，仅一个技能，直接使用: {selected_skill_id}")
    else:
        t_skill_start = time.perf_counter()
        selected_skill_id = await select_skill(llm, request.message, skills_for_selection, history_summary)
        logger.info(f"[TIMING] select_skill: {time.perf_counter() - t_skill_start:.2f}s")
        # 技能选择与 Agent 调用间隔，避免 DashScope 限流（如 qwen3-max 仅 1 RPS 时）导致第二次请求 429 触发重试
        delay_sec = float(os.getenv("QWEN_REQUEST_DELAY_SEC", "1"))
        if delay_sec > 0:
            await asyncio.sleep(delay_sec)
            logger.info(f"[TIMING] 固定延迟 sleep({delay_sec}): {delay_sec:.2f}s")
        if selected_skill_id is None and len(skills_for_selection) == 1:
            selected_skill_id = skills_for_selection[0].get("skill_id")
        if selected_skill_id is None and skills_for_selection:
            selected_skill_id = skills_for_selection[0].get("skill_id")
        if selected_skill_id is None and skills_loader.get_skill_full_content("default"):
            selected_skill_id = "default"

    # 按选中技能过滤工具：只传入该技能关联的 MCP 工具，加快响应、减少混淆
    server_ids = _get_mcp_servers_for_skill(selected_skill_id) if selected_skill_id else []
    skill_tools_fallback = False  # 是否因技能 MCP 无工具而回退到全部工具
    if server_ids:
        tools = [t for t in all_tools if "_" in t.name and t.name.split("_", 1)[0] in server_ids]
        if not tools:
            logger.warning(f"技能 {selected_skill_id} 关联的 MCP {server_ids} 无可用工具（可能未启动），回退到全部工具")
            tools = list(all_tools)
            skill_tools_fallback = True
        else:
            logger.info(f"已按技能 {selected_skill_id} 过滤工具，仅传入 {server_ids} 的 {len(tools)} 个工具")
    else:
        tools = list(all_tools)
    # file-reader MCP 用于读取 PDF/DOC/Excel，始终加入（技能过滤时可能被排除）
    file_reader_tools = [t for t in all_tools if "_" in t.name and t.name.startswith("file-reader_")]
    tool_names = {t.name for t in tools}
    extra_tools = [create_export_session_tool(session_id), create_read_file_tool(), call_api]
    if selected_skill_id:
        extra_tools.append(create_run_skill_script_tool(selected_skill_id))
    tools = tools + [t for t in file_reader_tools if t.name not in tool_names] + extra_tools
    logger.info(f"最终可用工具数量: {len(tools)}")

    skill_full_content = ""
    if selected_skill_id:
        skill_full_content = skills_loader.get_skill_full_content(selected_skill_id)
    if not skill_full_content:
        skill_full_content = "你是通用助手，直接回答用户问题。若需要外部能力可调用工具。"
    # 当技能所需 MCP 工具不可用时，注入回退提示，避免 LLM 尝试调用不存在的工具
    if skill_tools_fallback and selected_skill_id == "amap-maps":
        skill_full_content += """

**重要**：amap-maps 工具当前不可用（MCP 可能未连接或 Node.js 未安装）。请使用以下替代方式：
- 地理编码/路线规划：用 `linkup_linkup-search` 或 `exa_web_search_exa` 搜索在线地图工具、高德 API 文档或地址经纬度；
- 直接告知用户需在本地配置 amap-maps MCP（安装 Node.js、设置 AMAP_MAPS_API_KEY、重启后端）。"""

    # 阶段二：技能执行（完整 skill 内容 + 工具）
    t_agent_create = time.perf_counter()
    agent = create_skill_execution_agent(llm, tools, skill_full_content, extra_system_prompt, t_request_start=t_start)
    logger.info(f"[TIMING] create_skill_execution_agent: {time.perf_counter() - t_agent_create:.2f}s")

    # 构建输入：用户问题 + 历史摘要（若有）
    user_content = request.message.strip()
    if history_summary:
        user_content = f"历史对话摘要：\n{history_summary}\n\n当前用户输入：\n{user_content}"
    messages_for_agent = [HumanMessage(content=user_content)]

    initial_state = {
        "messages": messages_for_agent,
        "tools": tools
    }
    logger.info(f"初始状态准备完成，消息数量: {len(initial_state['messages'])}，选中技能: {selected_skill_id}")

    new_user_msg = HumanMessage(content=request.message)

    async def event_generator():
        """事件生成器 - 使用完整的 ReAct Agent 工作流"""
        # 确保 json 模块可用
        import json as json_module
        try:
            logger.info("开始执行 Agent 工作流")
            # 发送开始事件
            yield f"event: start\ndata: {json_module.dumps({'type': 'start'})}\n\n"

            # meta 透传：使用选中的 skill_id，后续若调用了工具则按工具所属 server 覆盖
            meta_context: Dict[str, Any] = {
                "skills": [selected_skill_id] if selected_skill_id else [],
                "tools": [],
                "mcp_servers": [],
            }
            # 累积本轮助手回复，用于写入会话历史
            accumulated_content: List[str] = []
            # MCP 原始返回列表，纳入注册流程并持久化；前端用单独字段存一份复制，仅点击「原始输出」时显示
            accumulated_raw_tool_results: List[str] = []
            
            # 使用 LangGraph 运行完整的 ReAct 循环
            # 流式执行 Agent 工作流
            event_count = 0
            last_agent_response = None  # 保存最后一个 agent 响应
            has_sent_content = False  # 跟踪是否已发送内容
            final_state = None  # 保存最终状态
            
            # 跟踪上一个状态，以便检测新消息
            previous_messages = initial_state.get("messages", [])
            
            t_loop_start = time.perf_counter()
            t_last = t_loop_start
            # stream_mode: updates=节点事件, messages=LLM token 流, values=完整状态（供 fallback）
            async for stream_item in agent.astream(initial_state, stream_mode=["updates", "messages", "values"]):
                # 多模式时返回 (mode, chunk)
                if isinstance(stream_item, tuple) and len(stream_item) == 2:
                    mode, chunk = stream_item
                    if mode == "values":
                        final_state = chunk
                        continue
                    if mode == "messages":
                        # token 流：chunk 为 (msg_chunk, metadata)，仅从 agent 节点流式输出
                        msg_chunk, meta = chunk if isinstance(chunk, tuple) and len(chunk) >= 2 else (chunk, {})
                        if meta.get("langgraph_node") != "agent":
                            continue
                        if hasattr(msg_chunk, "content") and msg_chunk.content:
                            txt = msg_chunk.content if isinstance(msg_chunk.content, str) else str(msg_chunk.content or "")
                            if txt:
                                accumulated_content.append(txt)
                                has_sent_content = True
                                yield f"event: content\ndata: {json_module.dumps({'text': txt, 'meta': meta_context}, ensure_ascii=False)}\n\n"
                        continue
                    event = chunk  # updates 模式的 chunk
                else:
                    event = stream_item
                    mode = "updates"
                
                t_now = time.perf_counter()
                event_keys = list(event.keys()) if isinstance(event, dict) else []
                logger.info(f"[TIMING] 事件 #{event_count + 1} {event_keys}: 距上次 {t_now - t_last:.2f}s, 累计 {t_now - t_start:.2f}s")
                t_last = t_now
                # final_state 由 values 模式提供（含 messages），此处不覆盖
                event_count += 1
                logger.info(f"收到 Agent 事件 #{event_count}: {event_keys}")
                # updates 格式：{"agent": [...]} 或 {"tool": [...]}
                if "agent" in event:
                    agent_output = event["agent"]
                    logger.info(f"agent 节点输出类型: {type(agent_output).__name__}")
                    
                    aimsg = None
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        for m in reversed(agent_output["messages"]):
                            if isinstance(m, AIMessage):
                                aimsg = m
                                break
                    elif isinstance(agent_output, list):
                        for m in reversed(agent_output):
                            if isinstance(m, AIMessage):
                                aimsg = m
                                break
                    if aimsg:
                        last_agent_response = aimsg
                        content_str = str(aimsg.content) if isinstance(aimsg.content, str) else str(aimsg.content or "")
                        has_tool_calls = hasattr(aimsg, 'tool_calls') and aimsg.tool_calls
                        _update_meta_skill_from_tool_calls(meta_context, aimsg)
                        # 若有 messages 结构则保留供 fallback 使用（values 可能未到达）
                        if isinstance(agent_output, dict) and "messages" in agent_output:
                            final_state = {"messages": agent_output["messages"]}
                        # token 已通过 stream_mode="messages" 流式发送；若未收到流则此处发送完整内容（兼容 API 不支持流式）
                        if content_str.strip():
                            accumulated_content.append(content_str)
                            # 有 tool_calls 时同一段内容会通过 react_step 的 thought 下发，不再重复发 content 事件避免前端显示两遍；
                            # 仅在「无 tool_calls 且尚未发送过最终内容」时，用 content 事件作为兜底输出。
                            if not has_tool_calls and not has_sent_content:
                                yield f"event: content\ndata: {json_module.dumps({'text': content_str, 'meta': meta_context}, ensure_ascii=False)}\n\n"
                                has_sent_content = True
                        if has_tool_calls:
                            # 结构化 tool_calls：同时附带单条和数组，便于前端展示「单步多次工具调用」
                            tool_calls_payload = []
                            for tco in aimsg.tool_calls:
                                tool_name = tco.get("name") or tco.get("id", "")
                                args = tco.get("args") or {}
                                # read_file（内置工具）：展示层将 __arg1 显示为 path，方便理解
                                if (
                                    isinstance(args, dict)
                                    and tool_name == "read_file"
                                    and "__arg1" in args
                                    and "path" not in args
                                ):
                                    args = dict(args)
                                    args["path"] = args.pop("__arg1")
                                # 对 MCP 工具使用与 manager 相同的参数归一化逻辑，
                                # 确保前端展示的就是「最终发给 MCP 的参数」（含 __arg1 -> 首参 等通用映射）。
                                if isinstance(args, dict) and "_" in tool_name:
                                    server_id, original_tool_name = tool_name.split("_", 1)
                                    input_schema = None
                                    try:
                                        mcp = _get_mcp_manager()
                                        t = mcp.tools.get(tool_name) if getattr(mcp, "tools", None) else None
                                        if t is not None:
                                            input_schema = getattr(t, "_mcp_input_schema", None)
                                    except Exception:
                                        pass
                                    args = normalize_mcp_kwargs_for_call(
                                        server_id=server_id,
                                        original_tool_name=original_tool_name,
                                        kwargs=args,
                                        input_schema=input_schema,
                                    )
                                payload = {
                                    "action": "tool_call",
                                    "tool": tool_name,
                                    "arguments": args,
                                }
                                tool_calls_payload.append(payload)
                                # 写入 accumulated_content 以供历史保存（每个调用一个 JSON 代码块）
                                tc_json = json_module.dumps(payload, ensure_ascii=False, indent=2)
                                accumulated_content.append(f"\n```json\n{tc_json}\n```\n")
                            react_data = {
                                "type": "thought",
                                "content": content_str.strip() or "正在调用工具...",
                                "meta": meta_context,
                            }
                            if tool_calls_payload:
                                # 向后兼容：保留单条 tool_call，同时提供 tool_calls 数组
                                react_data["tool_call"] = tool_calls_payload[0]
                                react_data["tool_calls"] = tool_calls_payload
                            yield f"event: react_step\ndata: {json_module.dumps(react_data, ensure_ascii=False)}\n\n"
                
                elif "tool" in event:
                    messages = event["tool"]
                    if not isinstance(messages, list):
                        messages = [messages]
                    logger.info(f"处理 tool 节点输出，消息数量: {len(messages)}")
                    for message in messages:
                        # LangGraph 流式返回的 event["tool"] 项可能是 {"messages": [HumanMessage(...)]} 的包装
                        if isinstance(message, dict) and "messages" in message and isinstance(message["messages"], list) and message["messages"]:
                            message = message["messages"][0]
                        # 流式 updates 中可能是 dict（LangGraph 序列化），不一定是 HumanMessage 实例
                        if isinstance(message, HumanMessage):
                            content = message.content
                        elif isinstance(message, dict):
                            content = None
                            if messages_from_dict:
                                try:
                                    restored = messages_from_dict([message])
                                    if restored and hasattr(restored[0], "content"):
                                        content = restored[0].content
                                        if isinstance(content, list):
                                            content = content[0].get("text", str(content)) if content and isinstance(content[0], dict) else (content[0] if content else "")
                                except Exception:
                                    pass
                            if content is None or content == "":
                                data_val = message.get("data")
                                content = (
                                    message.get("content")
                                    or (data_val.get("content") if isinstance(data_val, dict) else (data_val if isinstance(data_val, str) else None))
                                    or (message.get("kwargs") or {}).get("content")
                                    or ""
                                )
                            if isinstance(content, list):
                                content = content[0].get("text", str(content)) if content and isinstance(content[0], dict) else (content[0] if content else "")
                            content = content or ""
                        else:
                            content = None
                        if content is not None:
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
                            # MCP 原始返回：纳入注册流程（累积并随助手消息持久化），并随 tool_result 事件下发给前端
                            raw_content = str(content)
                            accumulated_raw_tool_results.append(raw_content)
                            # 图标生成工具：若结果中含 URL，格式化为 Markdown 图片，随 tool_result 的 content 下发（前端可选展示）
                            display_content = raw_content
                            if tool_name == "volces-icon_generate_app_icon":
                                first_url = _IMAGE_URL_RE.search(display_content)
                                if first_url:
                                    url = first_url.group(0).rstrip(".,;:!?)]")
                                    display_content = display_content + "\n\n![生成的图标]({})".format(url)
                            payload = {
                                "type": "tool_result",
                                "content": display_content,
                                "raw_content": raw_content,
                                "meta": meta_context,
                            }
                            logger.info(f"发送 tool_result 事件, tool={tool_name}, raw_content 长度={len(raw_content)}, content 长度={len(display_content)}")
                            yield f"event: react_step\ndata: {json_module.dumps(payload, ensure_ascii=False)}\n\n"
                
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
            logger.info(f"[TIMING] Agent 工作流总耗时: {time.perf_counter() - t_start:.2f}s")
            logger.info(f"Agent 工作流执行完成，共处理 {event_count} 个事件，已发送内容: {has_sent_content}")
            # 将会话历史写入内存：历史 + 本轮用户消息 + 本轮助手回复（含 MCP 原始返回列表、本回答使用的 skill_id）
            full_content = "".join(accumulated_content).strip() if accumulated_content else ""
            aimessage_kwargs: Dict[str, Any] = {}
            additional: Dict[str, Any] = {}
            if accumulated_raw_tool_results:
                additional["tool_raw_results"] = accumulated_raw_tool_results
            if selected_skill_id:
                additional["skill_id"] = selected_skill_id
            if additional:
                aimessage_kwargs["additional_kwargs"] = additional
            new_history = list(history) + [new_user_msg] + [AIMessage(content=full_content or "(无响应)", **aimessage_kwargs)]
            _CHAT_HISTORY[session_id] = new_history
            # 使用 LLM 为本轮对话生成摘要，并追加到 Turn 摘要列表
            try:
                turn_summary = await _summarize_turn_with_llm(llm, request.message, full_content or "(无响应)")
                _append_turn_summary(session_id, turn_summary)
            except Exception as e:
                logger.error(f"生成并追加本轮摘要失败: {e}", exc_info=True)
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
            elapsed_sec = time.perf_counter() - t_start
            logger.info(
                f"chat_stream: 请求已取消｜耗时 {elapsed_sec:.1f}s｜事件数 {event_count}｜已发内容 {has_sent_content}"
            )
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
        out: Dict[str, Any] = {"role": "assistant", "content": msg.content if isinstance(msg.content, str) else str(msg.content)}
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        if kwargs.get("tool_raw_results") is not None:
            out["tool_raw_results"] = kwargs["tool_raw_results"]
        if kwargs.get("skill_id") is not None:
            out["skill_id"] = kwargs["skill_id"]
        return out
    return {"role": "unknown", "content": str(getattr(msg, "content", ""))}


@router.get("/sessions")
async def list_sessions():
    """获取会话列表（对话历史用）"""
    try:
        await ensure_initialized()
    except asyncio.CancelledError:
        # 初始化时被取消（如前端超时/断开），返回空列表避免 500，前端可重试
        return {"status": "ok", "data": {"sessions": []}}
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
    await ensure_initialized()
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


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话（内存与持久化均移除）"""
    await ensure_initialized()
    _CHAT_HISTORY.pop(session_id, None)
    _SESSION_META.pop(session_id, None)
    _TURN_SUMMARIES.pop(session_id, None)
    _save_sessions_to_disk()
    return {"status": "ok", "data": {"id": session_id}}


@router.put("/sessions/{session_id}/title")
async def update_session_title(session_id: str, body: SessionTitleBody):
    """更新指定会话的标题"""
    await ensure_initialized()
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    # 如果该会话在历史或元数据中均不存在，则视为 404
    if session_id not in _CHAT_HISTORY and session_id not in _SESSION_META:
        raise HTTPException(status_code=404, detail="Session not found")

    meta = _SESSION_META.get(session_id) or {}
    meta["title"] = title
    meta.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
    _SESSION_META[session_id] = meta
    _save_sessions_to_disk()
    return {
        "status": "ok",
        "data": {
            "id": session_id,
            "title": title,
            "updated_at": meta["updated_at"],
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
    await ensure_initialized()
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
