"""群聊 API - 多 DHA 群聊会话与消息"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from app.api.dha import load_dha_instances
from app.api.settings import load_app_settings
from app.api.settings import get_mcp_servers_for_skill
from app.api.files import get_workspace_root_path, get_workspace_root
from app.agent.llm_client import get_llm_from_config
from app.agent.graph import create_skill_execution_agent
from app.agent.leader_scheduler import leader_decide
from app.mcp.manager import get_mcp_manager
from app.skills.loader import SkillsLoader
from app.tools.filesystem_session_wrapper import wrap_filesystem_tools
from app.tools.call_api import call_api
from app.core.user_context import get_current_user_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["group_chat"])

SESSIONS_DIR = os.getenv("SESSIONS_DIR", "./data/sessions")
GROUP_META_FILE = "group_sessions_meta.json"
GROUP_HISTORY_PREFIX = "group_history_"

# 已废弃：不再使用 dha-chat，新建会话 0 个 DHA 时由主持人先与用户交流并推荐 DHA 加入
CHAT_DHA_ID = "dha-chat"

skills_loader = SkillsLoader()
_initialized = False


async def _ensure_initialized():
    global _initialized
    if not _initialized:
        mgr = get_mcp_manager()
        await mgr.initialize_all()
        skills_loader.load_all_skills()
        _initialized = True


def _ensure_sessions_dir() -> Path:
    """根据当前用户返回群聊会话目录，实现多用户隔离。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        root = user_ctx.sessions_dir.resolve()
    else:
        root = Path(SESSIONS_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_group_meta() -> Dict[str, Dict[str, Any]]:
    path = _ensure_sessions_dir() / GROUP_META_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _save_group_meta(meta: Dict[str, Dict[str, Any]]) -> None:
    path = _ensure_sessions_dir() / GROUP_META_FILE
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_group_history(group_session_id: str) -> List[Dict[str, Any]]:
    path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def _save_group_history(group_session_id: str, messages: List[Dict[str, Any]]) -> None:
    path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


def _messages_to_context(messages: List[Dict[str, Any]], max_turns: int = 15) -> str:
    """将群聊消息转为供领导人/ DHA 使用的上下文字符串（不截断，完整保留）"""
    recent = messages[-max_turns * 2:] if len(messages) > max_turns * 2 else messages
    lines = []
    for m in recent:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        dha_id = m.get("dha_id", "")
        if role == "user":
            lines.append(f"【用户】{content}")
        elif role == "host":
            lines.append(f"【主持人】{content}")
        else:
            name = dha_id or "助手"
            lines.append(f"【{name}】{content}")
    return "\n\n".join(lines)


def _normalize_discussion_goal(raw: str, max_len: int = 200) -> str:
    """从首条用户消息中提取纯讨论目标，去掉前端的「【讨论目标】」前缀，避免在 prompt 中重复出现。"""
    if not raw or not isinstance(raw, str):
        return (raw or "").strip()[:max_len] if raw else ""
    s = (raw or "").strip()
    prefix = "【讨论目标】"
    if s.startswith(prefix):
        s = s[len(prefix) :].lstrip("\n ")
    return s[:max_len] if len(s) > max_len else s


def _build_next_prompt_fallback(discussion_goal: str, context: str) -> str:
    """当主持人未输出 next_prompt 时使用的默认提示词模板。
    相比早期版本，这里刻意给出更丰富的上下文、小结和任务说明，
    避免下一轮 DHA 只拿到几个要点而信息过少。"""
    return (
        f"【群聊讨论目标】\n{discussion_goal}\n\n"
        f"【最近几轮讨论要点（按时间顺序）】\n{context}\n\n"
        "【你这一轮的任务】\n"
        "1. 在不重复前面内容的前提下，先用 1～3 句话总结当前讨论已经达成的阶段性结论或共识。\n"
        "2. 结合你的角色和专长，围绕上述目标推进 1～2 个具体子问题或子任务；必要时可以适当补充背景说明或示例。\n"
        "3. 若需要后续其他 DHA 或用户继续配合，请明确点出「接下来可以由谁做什么」。\n\n"
        "【输出要求】\n"
        "- 语言简洁但信息量充足，可以分条说明。\n"
        "- 紧扣讨论目标，不要跑题到无关方向。\n"
        "- 不要大段复述完整对话原文，侧重提炼、推进和安排后续步骤。"
    )


def _get_dha_tools(dha: Dict[str, Any], workspace_id: str) -> List:
    """根据 DHA 的 mcp_server_ids 或 skill 的 MCP 依赖获取工具列表。
    - mcp_server_ids 有值：只传这些 MCP 的工具。
    - mcp_server_ids 为空：按 skill_ids 的 MCP 依赖过滤；若 skill 无 MCP 依赖（如 weather-service），
      只传内置工具（call_api）及只读 filesystem/file-reader 工具。不提供写文件工具；若用户要保存内容到文件，请在本条回复中写出完整内容，并提示用户选中回复后点击「保存为文件」按钮。"""
    mcp_manager = get_mcp_manager()
    all_tools = mcp_manager.get_tools()
    server_ids = dha.get("mcp_server_ids") or []
    if server_ids:
        tools = [t for t in all_tools if "_" in t.name and t.name.split("_", 1)[0] in server_ids]
    else:
        # mcp_server_ids 为空：按 skill 的 MCP 依赖决定
        skill_ids = dha.get("skill_ids") or []
        server_ids_from_skill = []
        for sid in skill_ids:
            server_ids_from_skill.extend(get_mcp_servers_for_skill(sid))
        server_ids_from_skill = list(dict.fromkeys(server_ids_from_skill))  # 去重
        if server_ids_from_skill:
            tools = [t for t in all_tools if "_" in t.name and t.name.split("_", 1)[0] in server_ids_from_skill]
        else:
            # skill 无 MCP 依赖（如 weather-service），只传内置工具
            tools = []
    # 始终提供 filesystem_ 工具（读取工作区文件等），避免 DHA 误用 call_api 访问相对 URL（会触发“缺少 http/https 协议”错误）。
    # 其余 MCP 工具仍按 mcp_server_ids / skill 依赖过滤，避免跨职责调用。
    def _is_write_tool(name: str) -> bool:
        if (name or "").startswith("filesystem_"):
            return "write" in (name or "") or "edit" in (name or "")
        return (name or "") == "file-reader_write_file"
    filesystem_tools = [
        t for t in all_tools
        if (getattr(t, "name", "").startswith("filesystem_") and not _is_write_tool(getattr(t, "name", "")))
        or (getattr(t, "name", "").startswith("file-reader_") and getattr(t, "name", "") != "file-reader_write_file")
    ]
    tools = tools + filesystem_tools + [call_api]
    # 最终再过滤一次：技能若依赖 filesystem MCP 会带入 filesystem_write_file，必须排除
    tools = [t for t in tools if not _is_write_tool(getattr(t, "name", ""))]
    tools = wrap_filesystem_tools(tools, workspace_id)
    return tools


def _get_llm_for_dha(dha: Optional[Dict[str, Any]], app_settings: Dict[str, Any]) -> Any:
    """按 DHA 的 llm_provider_id 或应用默认创建 LLM"""
    provider = (dha.get("llm_provider_id") or "").strip() if dha else ""
    if not provider:
        provider = app_settings.get("default_llm", "qwen")
    return get_llm_from_config(provider, app_settings.get("llm_providers"))


def _get_dha_skill_content(dha: Dict[str, Any]) -> str:
    """获取 DHA 的技能内容（按 skill_ids 取第一个或 default）"""
    skill_ids = dha.get("skill_ids") or []
    if skill_ids:
        for sid in skill_ids:
            content = skills_loader.get_skill_full_content(sid)
            if content:
                return content
    return skills_loader.get_skill_full_content("default") or "你是通用助手，直接回答用户问题。"


def _parse_host_response(content: str) -> Optional[Dict[str, Any]]:
    """解析主持人 DHA 的回复，提取主持词与 JSON。返回 {task_done, next_speaker, reason, announcement, next_prompt} 或 None"""
    if not content or not content.strip():
        return None
    text = content.strip()
    announcement = ""
    json_str = ""
    if "```json" in text:
        parts = text.split("```json", 1)
        announcement = (parts[0] or "").strip()
        rest = parts[1].split("```", 1)[0].strip() if len(parts) > 1 else ""
        json_str = rest
    elif "```" in text:
        parts = text.split("```", 2)
        announcement = (parts[0] or "").strip()
        if len(parts) >= 2:
            json_str = (parts[1] or "").strip()
    else:
        for sep in ("\n{", "{"):
            if sep in text:
                idx = text.find(sep) if sep == "{" else text.find(sep) + 1
                announcement = text[:idx].strip()
                json_str = text[idx:].strip()
                break
        else:
            return None
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
        task_done = data.get("task_done", True)
        next_speaker = (data.get("next_speaker") or "user").strip().lower()
        reason = data.get("reason", "")
        next_prompt = (data.get("next_prompt") or "").strip()  # 主持人生成的给下一发言人的提示词
        suggested_order = data.get("suggested_order")  # 首轮任务规划：建议的 DHA 运行顺序
        if isinstance(suggested_order, list):
            suggested_order = [str(x).strip().lower() for x in suggested_order if str(x).strip()]
        else:
            suggested_order = None
        if not announcement and reason:
            announcement = reason
        return {
            "task_done": task_done,
            "next_speaker": next_speaker,
            "reason": reason,
            "announcement": announcement or "请下一位发言。",
            "next_prompt": next_prompt if next_prompt else None,
            "suggested_order": suggested_order,
        }
    except Exception:
        return None


async def _host_decide_by_dha(
    llm,
    host_dha: Dict[str, Any],
    dha_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    last_speaker_dha_id: Optional[str],
    extra_system_prompt: str,
) -> Optional[Dict[str, Any]]:
    """
    由主持人 DHA 执行主持技能，返回 {task_done, next_speaker, reason, announcement}。
    失败时返回 None，调用方应回退到 leader_decide。
    """
    skill_content = skills_loader.get_skill_full_content("group-host")
    if not skill_content:
        return None
    name = host_dha.get("name") or host_dha.get("dha_id", "主持人")
    role = host_dha.get("role") or "群聊主持人"
    skill_content = f"你是 {name}，担任本群主持人。你的角色：{role}。\n\n{skill_content}"

    dha_lines = []
    for d in dha_list:
        r = d.get("role") or "参与者"
        n = d.get("name") or d.get("dha_id", "")
        did = d.get("dha_id", "")
        dha_lines.append(f"- {n} ({did}): {r}")
    dha_text = "\n".join(dha_lines)
    user_content = (
        f"当前群聊参与者（next_speaker 必须使用以下 dha_id 之一）：\n{dha_text}\n\n"
        f"讨论目标：{discussion_goal}\n\n"
        "【最近讨论内容（按时间顺序，供你理解上下文）：】\n"
        f"{recent_messages}\n\n"
    )
    if last_speaker_dha_id:
        user_content += f"刚发言的 DHA：{last_speaker_dha_id}\n\n请判断该 DHA 是否完成任务，并指定下一发言人。"
    else:
        user_content += "请指定第一个发言人（next_speaker 为某 dha_id）。此时 task_done 可设为 true。"
    user_content += (
        "\n\n若 next_speaker 为某 dha_id，请在 JSON 中同时输出 next_prompt：\n"
        "- 这是给下一位 DHA 的「详细一点的任务提示词」，信息量可以适当丰富，不必只给几个要点。\n"
        "- 建议结构包括：当前阶段小结 / 这一轮要完成的具体子任务 / 输出风格或格式要求 / 后续可由谁接力。\n"
        "- 可以适度摘取关键上下文，但避免原样复制整段长对话；更推荐用自己的话进行精炼与组织。"
    )

    try:
        agent = create_skill_execution_agent(llm, [], skill_content, extra_system_prompt or "")
        initial_state = {"messages": [HumanMessage(content=user_content)], "tools": []}
        final_state = await agent.ainvoke(initial_state)
        out_msgs = final_state.get("messages", [])
        content_str = ""
        for m in reversed(out_msgs):
            if isinstance(m, AIMessage):
                content_str = str(m.content) if isinstance(m.content, str) else str(m.content or "")
                break
        return _parse_host_response(content_str)
    except Exception as e:
        logger.warning("主持人 DHA 调用失败，将回退到默认调度: %s", e)
        return None


async def _host_only_respond_and_recommend(
    discussion_goal: str,
    recent_messages: str,
    all_instances: List[Dict[str, Any]],
    extra_system_prompt: str,
) -> tuple[str, Optional[List[str]]]:
    """
    当前群聊 0 个成员时：主持人回复用户并推荐一位或多位 DHA 加入。
    返回 (主持人回复正文, suggested_add_dha_ids 或 None)。
    """
    skill_content = skills_loader.get_skill_full_content("group-host")
    if not skill_content:
        skill_content = "你是群聊主持人，负责协调讨论并适时推荐合适的 DHA 加入。"
    system_content = (
        "你是群聊的主持人。当前群聊尚无成员，用户正在与你交流。"
        "请根据用户的需求或讨论目标，用自然语言回复用户，并推荐一位或多位适合加入讨论的 DHA。"
        "可选 DHA 列表见下方。\n\n"
        f"{skill_content}"
    )
    dha_lines = []
    for d in all_instances:
        did = d.get("dha_id", "")
        if did == CHAT_DHA_ID:
            continue
        name = d.get("name") or did
        role = d.get("role") or "参与者"
        dha_lines.append(f"- {name} ({did}): {role}")
    dha_text = "\n".join(dha_lines) if dha_lines else "（暂无可选 DHA）"
    user_content = (
        f"讨论目标/用户消息：\n{discussion_goal}\n\n"
        f"最近对话：\n{recent_messages}\n\n"
        f"可选 DHA 列表（请从中推荐一位或多位加入，输出其 dha_id）：\n{dha_text}\n\n"
        "请先写一段给用户的回复（说明你推荐谁加入及理由），然后在最后单独一行输出 JSON。"
        '格式任选其一：{"suggested_add_dha_id": "dha_id"} 或 {"suggested_add_dha_ids": ["dha_id1", "dha_id2"]}'
    )
    app_settings = load_app_settings()
    llm = _get_llm_for_dha(None, app_settings)
    agent = create_skill_execution_agent(llm, [], system_content, extra_system_prompt or "")
    initial_state = {"messages": [HumanMessage(content=user_content)], "tools": []}
    try:
        final_state = await agent.ainvoke(initial_state)
        out_msgs = final_state.get("messages", [])
        content_str = ""
        for m in reversed(out_msgs):
            if isinstance(m, AIMessage):
                content_str = str(m.content) if isinstance(m.content, str) else str(m.content or "")
                break
        if not content_str or not content_str.strip():
            return "我已收到您的需求，您可以在「增删成员」中邀请合适的 DHA 加入讨论。", None
        text = content_str.strip()
        announcement = text
        suggested_add_dha_ids: Optional[List[str]] = None
        valid_ids = {d.get("dha_id") for d in all_instances if d.get("dha_id")}
        for sep in ("\n{", "{"):
            if sep in text:
                idx = text.find(sep) if sep == "{" else text.find(sep) + 1
                announcement = text[:idx].strip()
                # 去掉正文末尾可能残留的 ```json 或 ``` 代码块标记，避免在前端展示出多余的 “```json”
                for fence in ("```json", "```"):
                    if announcement.endswith(fence):
                        announcement = announcement[: -len(fence)].rstrip()
                json_str = text[idx:].strip()
                try:
                    data = json.loads(json_str)
                    ids_raw = data.get("suggested_add_dha_ids")
                    if isinstance(ids_raw, list) and ids_raw:
                        # 不对数量设硬性上限，仅过滤合法 id 并去重
                        cleaned = [str(x).strip() for x in ids_raw if str(x).strip() in valid_ids]
                        if cleaned:
                            # 保持顺序去重
                            suggested_add_dha_ids = list(dict.fromkeys(cleaned))
                    if not suggested_add_dha_ids:
                        sid = (data.get("suggested_add_dha_id") or "").strip()
                        if sid and sid in valid_ids:
                            suggested_add_dha_ids = [sid]
                except Exception:
                    pass
                break
        # 若 JSON 未解析出推荐列表，从正文中提取 dha-xxx 作为备用（主持人常在正文中写专家 id）
        if not suggested_add_dha_ids and valid_ids:
            dha_id_pattern = re.compile(r"dha-[a-f0-9]{8,12}", re.I)
            found = list(dict.fromkeys(dha_id_pattern.findall(text)))
            # 同样不过度限制数量，只保留当前有效实例中的 id
            suggested_add_dha_ids = [x for x in found if x in valid_ids]
        return announcement or text, suggested_add_dha_ids
    except Exception as e:
        logger.warning("主持人 0 成员推荐调用失败: %s", e)
        return "我已收到您的需求，您可以在「更多」→「增删成员」中邀请 DHA 加入讨论。", None


# ========== Pydantic 模型 ==========


class GroupSessionCreate(BaseModel):
    title: str = "新群聊"
    dha_ids: List[str] = []  # 可为空，表示单聊；之后通过邀请追加 DHA 变为群聊
    leader_dha_id: Optional[str] = ""  # 已废弃：主持人改为写死在代码流程中，不再由 DHA 担任
    speak_mode: Optional[str] = "auto"  # auto | manual


class GroupSessionUpdate(BaseModel):
    title: Optional[str] = None
    speak_mode: Optional[str] = None
    add_dha_ids: Optional[List[str]] = None  # 向已有群聊追加 DHA
    remove_dha_ids: Optional[List[str]] = None  # 从群聊中移除 DHA


class GroupChatRequest(BaseModel):
    message: Optional[str] = None
    override_next_speaker: Optional[str] = None  # dha_id | "user" | null
    action: Optional[str] = None  # "continue" 继续下一轮
    custom_prompt: Optional[str] = None  # 手动模式下，可由前端传入自定义给下一发言人的提示词（覆盖默认生成）


class GroupPromptPreviewRequest(BaseModel):
    """前端在 manual 模式下预览（并可编辑）某个 DHA 下一轮发言时将收到的提示词内容。"""

    dha_id: str


# ========== API 路由 ==========


@router.get("/group-sessions")
async def list_group_sessions():
    """获取群聊会话列表"""
    meta = _load_group_meta()
    sessions = []
    for gsid, gm in meta.items():
        sessions.append({
            "id": gsid,
            "title": gm.get("title", "新群聊"),
            "dha_ids": gm.get("dha_ids", []),
            "leader_dha_id": gm.get("leader_dha_id", ""),
            "speak_mode": gm.get("speak_mode", "auto"),
            "created_at": gm.get("created_at", ""),
            "updated_at": gm.get("updated_at", ""),
        })
    sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"status": "ok", "data": {"sessions": sessions}}


@router.post("/group-sessions/{group_session_id}/prompt-preview")
async def preview_next_speaker_prompt(group_session_id: str, body: GroupPromptPreviewRequest):
    """
    预览指定 DHA 作为下一发言人时，将要收到的用户侧提示词（HumanMessage 内容）。

    仅用于前端 manual 模式下展示/编辑提示词，不实际触发 LLM 调用。
    """
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    m = meta[group_session_id]
    dha_ids = m.get("dha_ids", [])
    if body.dha_id not in dha_ids:
        raise HTTPException(status_code=400, detail="DHA 不在该群聊中")

    messages = _load_group_history(group_session_id)

    # 讨论目标：取首条用户消息（去掉前端已加的「【讨论目标】」前缀，避免重复）
    discussion_goal = ""
    for msg in messages:
        if msg.get("role") == "user":
            discussion_goal = _normalize_discussion_goal(msg.get("content") or "")
            break
    if not discussion_goal:
        discussion_goal = "待用户提出讨论主题"

    # 与实际调用时保持一致的上下文拼接逻辑
    context = _messages_to_context(messages)
    user_content = (
        f"【群聊讨论目标】\n{discussion_goal}\n\n"
        f"【最近讨论】\n{context}\n\n"
        "请紧扣讨论目标发言，不要偏离主题。"
    )

    return {"status": "ok", "data": {"prompt": user_content}}


@router.post("/group-sessions")
async def create_group_session(body: GroupSessionCreate):
    """创建群聊会话。dha_ids 为空时表示「主持人为先」：用户先与主持人交流，由主持人推荐 DHA 加入后变为群聊；不再使用 Chat。"""
    if body.leader_dha_id and body.dha_ids and body.leader_dha_id not in body.dha_ids:
        raise HTTPException(status_code=400, detail="leader_dha_id 必须在 dha_ids 中")

    instances = load_dha_instances()
    valid_ids = {d.get("dha_id") for d in instances}
    dha_ids = list(body.dha_ids) if body.dha_ids else []
    # 未选任何 DHA 时保持为空：用户与主持人对话，主持人可推荐 DHA 加入（不再默认使用 Chat）
    for did in dha_ids:
        if did not in valid_ids:
            raise HTTPException(status_code=400, detail=f"DHA {did} 不存在")

    gsid = f"group-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    meta = _load_group_meta()
    meta[gsid] = {
        "title": body.title or "新群聊",
        "dha_ids": dha_ids,
        "leader_dha_id": (body.leader_dha_id or "").strip() or "",  # 主持人已改为固定逻辑，不再使用 DHA
        "speak_mode": (body.speak_mode or "auto").strip().lower() if body.speak_mode else "auto",
        "created_at": now,
        "updated_at": now,
    }
    _save_group_meta(meta)
    _save_group_history(gsid, [])
    # 为每个新建群聊创建专属工作区目录（workspace_id 与 group_session_id 相同）
    try:
        get_workspace_root(gsid)
    except Exception:
        logger.warning("创建群聊 %s 对应的 workspace 目录失败，但不影响会话本身创建。", gsid, exc_info=True)
    return {"status": "ok", "data": {"id": gsid, **meta[gsid]}}


@router.get("/group-sessions/{group_session_id}")
async def get_group_session(group_session_id: str):
    """获取群聊详情与消息"""
    meta = _load_group_meta()
    # #region agent log
    _log_path = Path(__file__).resolve().parents[3] / ".cursor" / "debug-1338a6.log"
    _found = group_session_id in meta
    try:
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        _log_path.open("a").write(
            json.dumps({"sessionId": "1338a6", "location": "group_chat.get_group_session", "message": "get_group_session", "data": {"group_session_id": group_session_id, "found": _found}, "timestamp": int(time.time() * 1000), "hypothesisId": "H1"}) + "\n"
        )
    except Exception:
        pass
    # #endregion
    if not _found:
        raise HTTPException(status_code=404, detail="Group session not found")
    m = meta[group_session_id]
    messages = _load_group_history(group_session_id)
    instances = load_dha_instances()
    dha_map_raw = {d.get("dha_id"): d for d in instances if d.get("dha_id")}
    dha_ids_in_group = set(m.get("dha_ids", []))
    dha_ids_in_messages = {msg.get("dha_id") for msg in messages if msg.get("dha_id")}
    relevant_ids = dha_ids_in_group | dha_ids_in_messages
    dha_map = {
        k: {
            "name": v.get("name") or "",
            "role": v.get("role") or "",
            "is_leader": v.get("is_leader", False),
        }
        for k, v in dha_map_raw.items()
        if k in relevant_ids
    }
    return {
        "status": "ok",
        "data": {
            "id": group_session_id,
            "title": m.get("title", "新群聊"),
            "dha_ids": m.get("dha_ids", []),
            "leader_dha_id": m.get("leader_dha_id", ""),
            "speak_mode": m.get("speak_mode", "auto"),
            "created_at": m.get("created_at", ""),
            "updated_at": m.get("updated_at", ""),
            "messages": messages,
            "dha_map": dha_map,
        },
    }


@router.put("/group-sessions/{group_session_id}")
async def update_group_session(group_session_id: str, body: GroupSessionUpdate):
    """更新群聊：重命名、发言模式、追加 DHA 等。若会话不在 meta 中但请求为邀请（add_dha_ids），则自动创建该会话条目以避免 404。"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        if body.add_dha_ids:
            now = datetime.now(timezone.utc).isoformat()
            meta[group_session_id] = {
                "title": "新群聊",
                "dha_ids": [],
                "leader_dha_id": "",
                "speak_mode": "auto",
                "created_at": now,
                "updated_at": now,
            }
            _save_group_meta(meta)
            path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
            if not path.exists():
                _save_group_history(group_session_id, [])
        else:
            raise HTTPException(status_code=404, detail="Group session not found")
    if body.title is not None and str(body.title).strip():
        meta[group_session_id]["title"] = body.title.strip()
    if body.speak_mode is not None and body.speak_mode.strip().lower() in ("auto", "manual"):
        meta[group_session_id]["speak_mode"] = body.speak_mode.strip().lower()
    if body.add_dha_ids or body.remove_dha_ids:
        instances = load_dha_instances()
        valid_ids = {d.get("dha_id") for d in instances if d.get("dha_id")}
        current = set(meta[group_session_id].get("dha_ids", []))
        if body.add_dha_ids:
            for did in body.add_dha_ids:
                if did not in valid_ids:
                    raise HTTPException(status_code=400, detail=f"DHA {did} 不存在")
                current.add(did)
            current.discard(CHAT_DHA_ID)
        if body.remove_dha_ids:
            for did in body.remove_dha_ids:
                current.discard(did)
        meta[group_session_id]["dha_ids"] = list(current)
    meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_group_meta(meta)
    return {"status": "ok", "data": meta[group_session_id]}


@router.delete("/group-sessions/{group_session_id}")
async def delete_group_session(group_session_id: str):
    """删除群聊会话"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    del meta[group_session_id]
    _save_group_meta(meta)
    path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    if path.exists():
        path.unlink()
    # 同步删除该群聊对应的 workspace 目录（若存在）
    try:
        ws_root = get_workspace_root_path(group_session_id)
        if ws_root.exists() and ws_root.is_dir():
            import shutil

            shutil.rmtree(ws_root)
    except Exception:
        logger.warning("删除群聊 %s 的 workspace 目录失败，可手动清理。", group_session_id, exc_info=True)
    return {"status": "ok", "data": {"id": group_session_id, "deleted": True}}


@router.post("/group-sessions/{group_session_id}/chat/stream")
async def group_chat_stream(group_session_id: str, request: GroupChatRequest):
    """群聊流式对话：用户消息或继续下一轮，支持 override_next_speaker"""
    await _ensure_initialized()

    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    m = meta[group_session_id]
    dha_ids = m.get("dha_ids", [])
    leader_dha_id = m.get("leader_dha_id", "")
    instances = load_dha_instances()
    dha_map = {d.get("dha_id"): d for d in instances}
    dha_list = [d for d in instances if d.get("dha_id") in dha_ids]

    messages = _load_group_history(group_session_id)

    # 用户消息
    if request.message and request.message.strip():
        messages.append({
            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
            "role": "user",
            "content": request.message.strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _save_group_history(group_session_id, messages)
        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_group_meta(meta)

    # 上一发言人（用于主持人/领导人判断 task_done；排除主持人本人，只计参与讨论的 DHA）
    last_speaker_dha_id = None
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("dha_id") and msg.get("dha_id") != leader_dha_id:
            last_speaker_dha_id = msg.get("dha_id")
            break

    # 讨论目标：取首条用户消息（去掉前端已加的「【讨论目标】」前缀，避免重复）
    discussion_goal = ""
    for msg in messages:
        if msg.get("role") == "user":
            discussion_goal = _normalize_discussion_goal(msg.get("content") or "")
            break
    if not discussion_goal:
        discussion_goal = "待用户提出讨论主题"

    app_settings = load_app_settings()
    extra_system_prompt = app_settings.get("system_prompt") or ""
    # speak_mode 从会话 meta 读取（m 为 meta[group_session_id]），manual 时仅主持人给建议并结束，等用户选人/改提示词后再发
    speak_mode = m.get("speak_mode", "auto")

    import json as json_module

    async def event_gen():
        nonlocal last_speaker_dha_id
        consecutive_same_dha = 0  # 限制同一 DHA 连续发言次数
        custom_prompt_used = False  # custom_prompt 仅对本次请求的首个 DHA 生效
        dha_turns = 0  # 本次流中 DHA 总发言轮次
        try:
            yield f"event: start\ndata: {json_module.dumps({'type': 'start'})}\n\n"

            next_speaker = None

            # 0 个 DHA：主持人为先，主持人回复用户并推荐若干 DHA 加入（不再使用 Chat）
            if len(dha_ids) == 0:
                recent = _messages_to_context(messages)
                all_instances = [d for d in instances if d.get("dha_id") and d.get("dha_id") != CHAT_DHA_ID]
                host_content, suggested_add_dha_ids = await _host_only_respond_and_recommend(
                    discussion_goal, recent, all_instances, extra_system_prompt
                )
                host_msg = {
                    "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                    "role": "host",
                    "content": host_content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                if suggested_add_dha_ids:
                    host_msg["suggested_add_dha_ids"] = suggested_add_dha_ids
                    host_msg["suggested_add_dha_id"] = suggested_add_dha_ids[0]
                messages.append(host_msg)
                _save_group_history(group_session_id, messages)
                meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                _save_group_meta(meta)
                yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                end_data = {"type": "end", "waiting_for_user": True}
                if suggested_add_dha_ids:
                    end_data["suggested_add_dha_ids"] = suggested_add_dha_ids
                    end_data["suggested_add_dha_id"] = suggested_add_dha_ids[0]
                yield f"event: end\ndata: {json_module.dumps(end_data)}\n\n"
                return

            # 仅 1 个 DHA 时跳过主持人，直接 user -> DHA（chat 风格）
            single_dha_mode = len(dha_ids) == 1

            if request.override_next_speaker is not None:
                next_speaker = request.override_next_speaker.strip().lower()
                if next_speaker == "user":
                    yield f"event: end\ndata: {json_module.dumps({'type': 'end', 'waiting_for_user': True})}\n\n"
                    return
                if next_speaker == "end":
                    yield f"event: end\ndata: {json_module.dumps({'type': 'end', 'discussion_ended': True})}\n\n"
                    return
                if next_speaker and next_speaker not in dha_ids:
                    next_speaker = None
            elif single_dha_mode:
                # 1 DHA：直接指定该 DHA 发言，无主持人
                next_speaker = dha_ids[0]
            elif speak_mode != "auto":
                # 非自动（manual）模式：主持人先给出建议。
                # 如果已经明确推荐了下一位 DHA，则在同一条流中直接进入该 DHA 的发言；
                # 仅在主持人没有给出明确下一位时，才等待用户选择。
                recent = _messages_to_context(messages)
                decision = None
                host_dha = dha_map.get(leader_dha_id) if leader_dha_id in dha_ids else None
                if leader_dha_id and host_dha:
                    llm_host = _get_llm_for_dha(host_dha, app_settings)
                    decision = await _host_decide_by_dha(
                        llm_host, host_dha, dha_list, discussion_goal, recent, last_speaker_dha_id, extra_system_prompt
                    )
                if decision is None:
                    llm_default = _get_llm_for_dha(None, app_settings)
                    decision = await leader_decide(llm_default, dha_list, discussion_goal, recent, last_speaker_dha_id)
                announcement = decision.get("announcement")
                suggested = (decision.get("next_speaker") or "").strip().lower()
                if suggested in dha_ids:
                    next_dha = dha_map.get(suggested)
                    next_name = (next_dha.get("name") or suggested) if next_dha else suggested
                    host_content = announcement or f"建议由 {next_name} 发言，请选择发言人并发送。"
                else:
                    host_content = announcement or "请选择下一发言人并发送。"
                host_msg = {
                    "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                    "role": "host" if not leader_dha_id else "assistant",
                    "content": host_content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                if leader_dha_id:
                    host_msg["dha_id"] = leader_dha_id
                messages.append(host_msg)
                # 保存并把主持人建议发给前端
                if suggested in dha_ids:
                    context = _messages_to_context(messages)
                    next_dha = dha_map.get(suggested)
                    host_msg["next_dha_name"] = (next_dha.get("name") or suggested) if next_dha else suggested
                    host_msg["next_prompt"] = (decision.get("next_prompt") or "").strip() or _build_next_prompt_fallback(discussion_goal, context)
                if decision.get("suggested_order"):
                    host_msg["suggested_order"] = decision["suggested_order"]
                _save_group_history(group_session_id, messages)
                yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                # 如果主持人已经明确推荐了下一位 DHA，则直接把该 DHA 作为下一发言人继续往下走，
                # 不再发 waiting_for_user，让前端自动看到该 DHA 的发言。
                if suggested in dha_ids:
                    next_speaker = suggested
                    # host_msg.next_prompt 已写入，后续 DHA 会自动读取最近的 next_prompt 作为输入
                else:
                    # 否则仍然等待用户选择
                    end_data = {"type": "end", "waiting_for_user": True}
                    yield f"event: end\ndata: {json_module.dumps(end_data)}\n\n"
                    return
            else:
                # auto：由主持人 DHA 或默认调度决定下一发言人
                recent = _messages_to_context(messages)
                decision = None
                host_dha = dha_map.get(leader_dha_id) if leader_dha_id else None
                if leader_dha_id and leader_dha_id in dha_ids and host_dha:
                    llm_host = _get_llm_for_dha(host_dha, app_settings)
                    decision = await _host_decide_by_dha(
                        llm_host, host_dha, dha_list, discussion_goal, recent, last_speaker_dha_id, extra_system_prompt
                    )
                if decision is None:
                    llm_default = _get_llm_for_dha(None, app_settings)
                    decision = await leader_decide(llm_default, dha_list, discussion_goal, recent, last_speaker_dha_id)
                announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                # 由主持人/调度明确给出下一位发言人。
                # 不再根据 task_done 强制让上一位 DHA 连续发言，
                # 每一小轮都回到主持人决策，再由 decision["next_speaker"] 指定下一位。
                next_speaker = decision.get("next_speaker", "user")
                if last_speaker_dha_id is None and next_speaker == "user" and dha_ids:
                    next_speaker = dha_ids[0]
                if messages and messages[-1].get("role") == "user" and next_speaker == "user" and dha_ids:
                    idx = dha_ids.index(last_speaker_dha_id) + 1 if last_speaker_dha_id in dha_ids else 0
                    next_speaker = dha_ids[idx % len(dha_ids)]
                # 主持人发言（1 DHA 时跳过）
                if next_speaker in dha_ids and not single_dha_mode:
                    host_content = announcement if announcement else None
                    if not host_content:
                        next_dha = dha_map.get(next_speaker)
                        next_name = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                        host_content = f"下面由 {next_name} 发言。"
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host" if not leader_dha_id else "assistant",
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    if leader_dha_id:
                        host_msg["dha_id"] = leader_dha_id
                    messages.append(host_msg)
                    context = _messages_to_context(messages)
                    next_dha = dha_map.get(next_speaker)
                    host_msg["next_dha_name"] = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                    host_msg["next_prompt"] = (decision.get("next_prompt") or "").strip() or _build_next_prompt_fallback(discussion_goal, context)
                    if decision.get("suggested_order"):
                        host_msg["suggested_order"] = decision["suggested_order"]
                    _save_group_history(group_session_id, messages)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                    # 这里不再发送 waiting_for_user 的 end 事件，而是直接在同一条流中继续执行
                    # 下方 while next_speaker 循环会立刻进入对应 DHA 的发言，实现“主持人点名后自动发言”。

            while next_speaker and next_speaker in dha_ids:
                # 在自动或手动模式下，单次流中 DHA 发言超过一定轮次（例如 10）时强制停下来，让用户确认是否继续，
                # 避免在服务器上长时间无限循环。
                if dha_turns >= 10:
                    end_data = {
                        "type": "end",
                        "waiting_for_user": True,
                        "suggested_next_speaker": next_speaker,
                        "turns_limit_reached": True,
                    }
                    yield f"event: end\ndata: {json_module.dumps(end_data)}\n\n"
                    return
                dha_turns += 1
                dha = dha_map.get(next_speaker)
                if not dha:
                    next_speaker = "user"
                    break

                tools = _get_dha_tools(dha, group_session_id)
                skill_content = _get_dha_skill_content(dha)
                role = dha.get("role") or ""
                dha_system = (dha.get("system_prompt") or "").strip()
                if dha_system:
                    skill_content = f"{dha_system}\n\n{skill_content}"
                if role:
                    skill_content = f"你的角色：{role}\n\n{skill_content}"

                llm_dha = _get_llm_for_dha(dha, app_settings)
                agent = create_skill_execution_agent(llm_dha, tools, skill_content, extra_system_prompt)
                context = _messages_to_context(messages)
                if not custom_prompt_used and request.custom_prompt:
                    user_content = request.custom_prompt
                    custom_prompt_used = True
                else:
                    # 优先使用刚写入的 host_msg 的 next_prompt（主持人产出或默认模板），否则用默认
                    last_next_prompt = None
                    for _m in reversed(messages):
                        if _m.get("next_prompt"):
                            last_next_prompt = (_m.get("next_prompt") or "").strip()
                            break
                    user_content = last_next_prompt or (
                        f"【群聊讨论目标】\n{discussion_goal}\n\n"
                        f"【最近讨论】\n{context}\n\n"
                        "请紧扣讨论目标发言，不要偏离主题。"
                    )
                initial_state = {"messages": [HumanMessage(content=user_content)], "tools": tools}

                accumulated = []
                accumulated_raw_tool_results: List[str] = []
                try:
                    async for stream_item in agent.astream(initial_state, stream_mode=["updates", "messages", "values"]):
                        if isinstance(stream_item, tuple) and len(stream_item) == 2:
                            mode, chunk = stream_item
                            if mode == "messages":
                                msg_chunk, meta_info = chunk if isinstance(chunk, tuple) and len(chunk) >= 2 else (chunk, {})
                                if meta_info.get("langgraph_node") == "agent" and hasattr(msg_chunk, "content") and msg_chunk.content:
                                    txt = msg_chunk.content if isinstance(msg_chunk.content, str) else str(msg_chunk.content or "")
                                    if txt:
                                        accumulated.append(txt)
                                        yield f"event: content\ndata: {json_module.dumps({'text': txt, 'dha_id': next_speaker, 'meta': {}}, ensure_ascii=False)}\n\n"
                            continue
                        event = stream_item if not isinstance(stream_item, tuple) else stream_item[1]
                        if isinstance(event, dict) and "tool" in event:
                            tool_msgs = event["tool"]
                            if isinstance(tool_msgs, dict) and "messages" in tool_msgs:
                                tool_msgs = tool_msgs["messages"] or []
                            if not isinstance(tool_msgs, list):
                                tool_msgs = [tool_msgs]
                            for tm in tool_msgs:
                                content = None
                                if isinstance(tm, dict) and "messages" in tm and isinstance(tm["messages"], list) and tm["messages"]:
                                    tm = tm["messages"][0]
                                if isinstance(tm, HumanMessage):
                                    content = tm.content
                                elif isinstance(tm, dict) and tm.get("content"):
                                    content = tm["content"]
                                if content is not None:
                                    raw_str = str(content) if not isinstance(content, str) else content
                                    accumulated_raw_tool_results.append(raw_str)
                        if isinstance(event, dict) and "agent" in event:
                            agent_out = event["agent"]
                            aimsg = None
                            if isinstance(agent_out, dict) and "messages" in agent_out:
                                for m in reversed(agent_out["messages"]):
                                    if isinstance(m, AIMessage):
                                        aimsg = m
                                        break
                            elif isinstance(agent_out, list):
                                for m in reversed(agent_out):
                                    if isinstance(m, AIMessage):
                                        aimsg = m
                                        break
                            if aimsg:
                                has_tool_calls = hasattr(aimsg, "tool_calls") and aimsg.tool_calls
                                if has_tool_calls:
                                    for tco in aimsg.tool_calls:
                                        tool_name = tco.get("name") or tco.get("id", "")
                                        args = tco.get("args") or {}
                                        payload = {"action": "tool_call", "tool": tool_name, "arguments": args}
                                        tc_json = json_module.dumps(payload, ensure_ascii=False, indent=2)
                                        block = f"\n```json\n{tc_json}\n```\n"
                                        accumulated.append(block)
                                        yield f"event: content\ndata: {json_module.dumps({'text': block, 'dha_id': next_speaker, 'meta': {}}, ensure_ascii=False)}\n\n"
                                content_str = str(aimsg.content) if isinstance(aimsg.content, str) else str(aimsg.content or "")
                                if content_str.strip() and content_str not in accumulated:
                                    accumulated.append(content_str)
                                    yield f"event: content\ndata: {json_module.dumps({'text': content_str, 'dha_id': next_speaker, 'meta': {}}, ensure_ascii=False)}\n\n"
                except Exception as stream_err:
                    logger.warning("群聊 agent astream 失败，回退到 ainvoke: %s", stream_err)
                    try:
                        final_state = await agent.ainvoke(initial_state)
                        out_msgs = final_state.get("messages", [])
                        for m in out_msgs:
                            if isinstance(m, AIMessage):
                                if hasattr(m, "tool_calls") and m.tool_calls:
                                    for tco in m.tool_calls:
                                        tool_name = tco.get("name") or tco.get("id", "")
                                        args = tco.get("args") or {}
                                        payload = {"action": "tool_call", "tool": tool_name, "arguments": args}
                                        tc_json = json_module.dumps(payload, ensure_ascii=False, indent=2)
                                        accumulated.append(f"\n```json\n{tc_json}\n```\n")
                                content_str = str(m.content) if isinstance(m.content, str) else str(m.content or "")
                                if content_str.strip():
                                    accumulated.append(content_str)
                        if not accumulated_raw_tool_results:
                            for msg in out_msgs:
                                if isinstance(msg, HumanMessage) and msg.content:
                                    raw_str = str(msg.content) if isinstance(msg.content, str) else str(msg.content or "")
                                    if raw_str and ("工具 " in raw_str and " 的执行结果:" in raw_str or "执行错误" in raw_str):
                                        accumulated_raw_tool_results.append(raw_str)
                    except Exception as invoke_err:
                        logger.exception("群聊 agent ainvoke 也失败: %s", invoke_err)
                        accumulated.append(f"(调用异常: {invoke_err})")

                full_content = "".join(accumulated) if accumulated else "(无文本输出)"
                skill_id = (dha.get("skill_ids") or ["default"])[0] if dha else "default"
                assistant_msg = {
                    "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                    "role": "assistant",
                    "dha_id": next_speaker,
                    "content": full_content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "skill_id": skill_id,
                }
                if accumulated_raw_tool_results:
                    assistant_msg["tool_raw_results"] = accumulated_raw_tool_results
                messages.append(assistant_msg)
                _save_group_history(group_session_id, messages)
                meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                _save_group_meta(meta)
                yield f"event: message\ndata: {json_module.dumps(assistant_msg, ensure_ascii=False)}\n\n"

                last_speaker_dha_id = next_speaker
                # 单 DHA：直接结束，等用户下一条
                if single_dha_mode:
                    end_data = {"type": "end", "waiting_for_user": True}
                    yield f"event: end\ndata: {json_module.dumps(end_data)}\n\n"
                    return
                # 手动模式：仍由主持人决定下一发言人并展示建议，再结束，等用户点「确认并继续」
                if speak_mode != "auto":
                    host_msg = {}
                    decision = None
                    host_dha = dha_map.get(leader_dha_id) if leader_dha_id else None
                    if leader_dha_id and leader_dha_id in dha_ids and host_dha:
                        llm_host = _get_llm_for_dha(host_dha, app_settings)
                        decision = await _host_decide_by_dha(
                            llm_host, host_dha, dha_list, discussion_goal, _messages_to_context(messages),
                            last_speaker_dha_id, extra_system_prompt
                        )
                    if decision is None:
                        llm_default = _get_llm_for_dha(None, app_settings)
                        decision = await leader_decide(llm_default, dha_list, discussion_goal, _messages_to_context(messages), last_speaker_dha_id)
                    next_speaker_manual = decision.get("next_speaker", "user")
                    if not decision.get("task_done", True) and last_speaker_dha_id:
                        next_speaker_manual = last_speaker_dha_id
                    announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                    if next_speaker_manual in dha_ids or next_speaker_manual in ("user", "end"):
                        host_content = announcement
                        if not host_content and next_speaker_manual in dha_ids:
                            next_dha = dha_map.get(next_speaker_manual)
                            host_content = f"下面由 {next_dha.get('name') or next_speaker_manual} 发言。" if next_dha else f"下面由 {next_speaker_manual} 发言。"
                        if not host_content:
                            host_content = "请用户补充或继续提问。" if next_speaker_manual == "user" else "讨论结束。"
                        host_msg = {
                            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                            "role": "host" if not leader_dha_id else "assistant",
                            "content": host_content,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        if leader_dha_id:
                            host_msg["dha_id"] = leader_dha_id
                        messages.append(host_msg)
                        if next_speaker_manual in dha_ids:
                            context = _messages_to_context(messages)
                            next_dha = dha_map.get(next_speaker_manual)
                            host_msg["next_dha_name"] = (next_dha.get("name") or next_speaker_manual) if next_dha else next_speaker_manual
                            host_msg["next_prompt"] = (decision.get("next_prompt") or "").strip() or _build_next_prompt_fallback(discussion_goal, context)
                        _save_group_history(group_session_id, messages)
                        yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                    end_data = {"type": "end", "waiting_for_user": True, "suggested_next_speaker": next_speaker_manual}
                    if next_speaker_manual in dha_ids and host_msg.get("next_prompt"):
                        end_data["next_prompt"] = host_msg["next_prompt"]
                    yield f"event: end\ndata: {json_module.dumps(end_data)}\n\n"
                    return
                # auto 且多 DHA：主持人决定下一发言人
                decision = None
                host_dha = dha_map.get(leader_dha_id) if leader_dha_id else None
                if leader_dha_id and leader_dha_id in dha_ids and host_dha:
                    llm_host = _get_llm_for_dha(host_dha, app_settings)
                    decision = await _host_decide_by_dha(
                        llm_host, host_dha, dha_list, discussion_goal, _messages_to_context(messages),
                        last_speaker_dha_id, extra_system_prompt
                    )
                if decision is None:
                    llm_default = _get_llm_for_dha(None, app_settings)
                    decision = await leader_decide(llm_default, dha_list, discussion_goal, _messages_to_context(messages), last_speaker_dha_id)
                task_done = decision.get("task_done", True)
                next_speaker = decision.get("next_speaker", "user")
                if not task_done:
                    next_speaker = last_speaker_dha_id
                announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                # 主持人发言：leader_dha_id 为空时用 role=host（固定逻辑）
                if next_speaker in dha_ids or next_speaker in ("user", "end"):
                    host_content = announcement
                    if not host_content and next_speaker in dha_ids:
                        next_dha = dha_map.get(next_speaker)
                        next_name = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                        host_content = f"下面由 {next_name} 发言。"
                    if not host_content:
                        host_content = "请用户补充或继续提问。" if next_speaker == "user" else "讨论结束。"
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host" if not leader_dha_id else "assistant",
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    if leader_dha_id:
                        host_msg["dha_id"] = leader_dha_id
                    messages.append(host_msg)
                    if next_speaker in dha_ids:
                        context = _messages_to_context(messages)
                        next_dha = dha_map.get(next_speaker)
                        host_msg["next_dha_name"] = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                        host_msg["next_prompt"] = (decision.get("next_prompt") or "").strip() or _build_next_prompt_fallback(discussion_goal, context)
                    if decision.get("suggested_order"):
                        host_msg["suggested_order"] = decision["suggested_order"]
                    _save_group_history(group_session_id, messages)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                # 限制同一 DHA 连续发言
                if next_speaker == last_speaker_dha_id:
                    if task_done or consecutive_same_dha >= 1:
                        idx = dha_ids.index(last_speaker_dha_id) + 1 if last_speaker_dha_id in dha_ids else 0
                        next_speaker = dha_ids[idx % len(dha_ids)] if dha_ids else "user"
                        consecutive_same_dha = 0
                    else:
                        consecutive_same_dha += 1
                else:
                    consecutive_same_dha = 0
                # auto 模式下：不再每轮暂停，直接继续 while 循环让下一 DHA 发言，直到任务完成（next_speaker 为 user/end）再结束

            if next_speaker == "end":
                yield f"event: end\ndata: {json_module.dumps({'type': 'end', 'discussion_ended': True})}\n\n"
            else:
                end_data = {"type": "end", "waiting_for_user": True, "suggested_next_speaker": next_speaker}
                yield f"event: end\ndata: {json_module.dumps(end_data)}\n\n"

        except Exception as e:
            logger.exception("群聊流式输出异常")
            yield f"event: error\ndata: {json_module.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/group-sessions/{group_session_id}/chat")
async def group_chat(group_session_id: str, request: GroupChatRequest):
    """群聊非流式对话：简单返回完整回复，便于前端直接显示"""
    await _ensure_initialized()

    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    m = meta[group_session_id]
    dha_ids = m.get("dha_ids", [])
    leader_dha_id = m.get("leader_dha_id", "")
    instances = load_dha_instances()
    dha_map = {d.get("dha_id"): d for d in instances}
    dha_list = [d for d in instances if d.get("dha_id") in dha_ids]

    messages = _load_group_history(group_session_id)

    if request.message and request.message.strip():
        messages.append({
            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
            "role": "user",
            "content": request.message.strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _save_group_history(group_session_id, messages)
        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_group_meta(meta)

    last_speaker_dha_id = None
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("dha_id") and msg.get("dha_id") != leader_dha_id:
            last_speaker_dha_id = msg.get("dha_id")
            break

    discussion_goal = ""
    for msg in messages:
        if msg.get("role") == "user":
            discussion_goal = _normalize_discussion_goal(msg.get("content") or "")
            break
    if not discussion_goal:
        discussion_goal = "待用户提出讨论主题"

    app_settings = load_app_settings()
    extra_system_prompt = app_settings.get("system_prompt") or ""
    speak_mode = m.get("speak_mode", "auto")
    single_dha_mode = len(dha_ids) == 1

    # 0 个 DHA：主持人为先，主持人回复并推荐若干 DHA 加入
    if len(dha_ids) == 0:
        recent = _messages_to_context(messages)
        all_instances = [d for d in instances if d.get("dha_id") and d.get("dha_id") != CHAT_DHA_ID]
        host_content, suggested_add_dha_ids = await _host_only_respond_and_recommend(
            discussion_goal, recent, all_instances, extra_system_prompt
        )
        host_msg = {
            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
            "role": "host",
            "content": host_content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if suggested_add_dha_ids:
            host_msg["suggested_add_dha_ids"] = suggested_add_dha_ids
            host_msg["suggested_add_dha_id"] = suggested_add_dha_ids[0]
        messages.append(host_msg)
        _save_group_history(group_session_id, messages)
        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_group_meta(meta)
        return {
            "status": "ok",
            "data": {
                "messages": messages,
                "suggested_add_dha_ids": suggested_add_dha_ids,
                "suggested_add_dha_id": suggested_add_dha_ids[0] if suggested_add_dha_ids else None,
            },
        }

    next_speaker = None
    if request.override_next_speaker is not None:
        next_speaker = request.override_next_speaker.strip().lower()
        if next_speaker == "user" or next_speaker == "end":
            return {"status": "ok", "data": {"messages": messages}}
        if next_speaker not in dha_ids:
            next_speaker = None
    if next_speaker is None and single_dha_mode:
        next_speaker = dha_ids[0]
    if next_speaker is None and speak_mode != "auto":
        # 非自动：仅主持人给建议，不跑 DHA
        recent = _messages_to_context(messages)
        decision = None
        host_dha = dha_map.get(leader_dha_id) if leader_dha_id in dha_ids else None
        if leader_dha_id and host_dha:
            llm_host = _get_llm_for_dha(host_dha, app_settings)
            decision = await _host_decide_by_dha(
                llm_host, host_dha, dha_list, discussion_goal, recent, last_speaker_dha_id, extra_system_prompt
            )
        if decision is None:
            llm_default = _get_llm_for_dha(None, app_settings)
            decision = await leader_decide(llm_default, dha_list, discussion_goal, recent, last_speaker_dha_id)
        announcement = decision.get("announcement")
        suggested = (decision.get("next_speaker") or "").strip().lower()
        if suggested in dha_ids:
            next_dha = dha_map.get(suggested)
            next_name = (next_dha.get("name") or suggested) if next_dha else suggested
            host_content = announcement or f"建议由 {next_name} 发言，请选择发言人并发送。"
        else:
            host_content = announcement or "请选择下一发言人并发送。"
        host_msg = {
            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
            "role": "host" if not leader_dha_id else "assistant",
            "content": host_content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if leader_dha_id:
            host_msg["dha_id"] = leader_dha_id
        messages.append(host_msg)
        _save_group_history(group_session_id, messages)
        return {"status": "ok", "data": {"messages": messages}}
    if next_speaker is None and speak_mode == "auto":
        recent = _messages_to_context(messages)
        decision = None
        host_dha = dha_map.get(leader_dha_id) if leader_dha_id in dha_ids else None
        if leader_dha_id and host_dha:
            llm_host = _get_llm_for_dha(host_dha, app_settings)
            decision = await _host_decide_by_dha(
                llm_host, host_dha, dha_list, discussion_goal, recent, last_speaker_dha_id, extra_system_prompt
            )
        if decision is None:
            llm_default = _get_llm_for_dha(None, app_settings)
            decision = await leader_decide(llm_default, dha_list, discussion_goal, recent, last_speaker_dha_id)
        next_speaker = decision.get("next_speaker", "user")
        task_done = decision.get("task_done", True)
        if not task_done and last_speaker_dha_id:
            next_speaker = last_speaker_dha_id
        if last_speaker_dha_id is None and next_speaker == "user" and dha_ids:
            next_speaker = dha_ids[0]
        if messages and messages[-1].get("role") == "user" and next_speaker == "user" and dha_ids:
            idx = dha_ids.index(last_speaker_dha_id) + 1 if last_speaker_dha_id in dha_ids else 0
            next_speaker = dha_ids[idx % len(dha_ids)]
        announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
        if next_speaker in dha_ids and not single_dha_mode:
            host_content = announcement or None
            if not host_content:
                next_dha = dha_map.get(next_speaker)
                next_name = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                host_content = f"下面由 {next_name} 发言。"
            host_msg = {
                "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                "role": "host" if not leader_dha_id else "assistant",
                "content": host_content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if leader_dha_id:
                host_msg["dha_id"] = leader_dha_id
            messages.append(host_msg)
            _save_group_history(group_session_id, messages)

    consecutive_same_dha = 0
    custom_prompt_used = False  # 非流式模式下，custom_prompt 仅对本次请求的首个 DHA 生效
    while next_speaker and next_speaker in dha_ids:
        dha = dha_map.get(next_speaker)
        if not dha:
            break
        tools = _get_dha_tools(dha, group_session_id)
        skill_content = _get_dha_skill_content(dha)
        role = dha.get("role") or ""
        dha_system = (dha.get("system_prompt") or "").strip()
        if dha_system:
            skill_content = f"{dha_system}\n\n{skill_content}"
        if role:
            skill_content = f"你的角色：{role}\n\n{skill_content}"

        llm_dha = _get_llm_for_dha(dha, app_settings)
        agent = create_skill_execution_agent(llm_dha, tools, skill_content, extra_system_prompt)
        context = _messages_to_context(messages)
        if not custom_prompt_used and request.custom_prompt:
            user_content = request.custom_prompt
            custom_prompt_used = True
        else:
            last_next_prompt = None
            for _m in reversed(messages):
                if _m.get("next_prompt"):
                    last_next_prompt = (_m.get("next_prompt") or "").strip()
                    break
            user_content = last_next_prompt or (
                f"【群聊讨论目标】\n{discussion_goal}\n\n"
                f"【最近讨论】\n{context}\n\n"
                "请紧扣讨论目标发言，不要偏离主题。"
            )
        initial_state = {"messages": [HumanMessage(content=user_content)], "tools": tools}

        tool_raw_results: List[str] = []
        content_parts: List[str] = []
        try:
            final_state = await agent.ainvoke(initial_state)
            out_msgs = final_state.get("messages", [])
            for msg in out_msgs:
                if isinstance(msg, AIMessage):
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tco in msg.tool_calls:
                            tool_name = tco.get("name") or tco.get("id", "")
                            args = tco.get("args") or {}
                            payload = {"action": "tool_call", "tool": tool_name, "arguments": args}
                            content_parts.append(f"\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n")
                    c = str(msg.content) if isinstance(msg.content, str) else str(msg.content or "")
                    if c.strip():
                        content_parts.append(c)
            for msg in out_msgs:
                if isinstance(msg, HumanMessage) and msg.content:
                    raw_str = str(msg.content) if isinstance(msg.content, str) else str(msg.content or "")
                    if raw_str and ("工具 " in raw_str and " 的执行结果:" in raw_str or "执行错误" in raw_str):
                        tool_raw_results.append(raw_str)
        except Exception as e:
            logger.exception("群聊 DHA 调用异常")
            content_parts = [f"调用异常: {e}"]

        content_str = "".join(content_parts).strip() if content_parts else "(无文本输出)"
        skill_id = (dha.get("skill_ids") or ["default"])[0] if dha else "default"
        asst_msg = {
            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
            "role": "assistant",
            "dha_id": next_speaker,
            "content": content_str,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skill_id": skill_id,
        }
        if tool_raw_results:
            asst_msg["tool_raw_results"] = tool_raw_results
        messages.append(asst_msg)
        _save_group_history(group_session_id, messages)
        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_group_meta(meta)

        if single_dha_mode or speak_mode != "auto":
            break
        last_speaker_dha_id = next_speaker
        decision = None
        host_dha = dha_map.get(leader_dha_id) if leader_dha_id in dha_ids else None
        if leader_dha_id and host_dha:
            llm_host = _get_llm_for_dha(host_dha, app_settings)
            decision = await _host_decide_by_dha(
                llm_host, host_dha, dha_list, discussion_goal, _messages_to_context(messages),
                last_speaker_dha_id, extra_system_prompt
            )
        if decision is None:
            llm_default = _get_llm_for_dha(None, app_settings)
            decision = await leader_decide(llm_default, dha_list, discussion_goal, _messages_to_context(messages), last_speaker_dha_id)
        task_done = decision.get("task_done", True)
        next_speaker = decision.get("next_speaker", "user")
        if not task_done:
            next_speaker = last_speaker_dha_id
        announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
        if next_speaker in dha_ids or next_speaker in ("user", "end"):
            host_content = announcement
            if not host_content and next_speaker in dha_ids:
                next_dha = dha_map.get(next_speaker)
                next_name = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                host_content = f"下面由 {next_name} 发言。"
            if not host_content:
                host_content = "请用户补充或继续提问。" if next_speaker == "user" else "讨论结束。"
            host_msg = {
                "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                "role": "host" if not leader_dha_id else "assistant",
                "content": host_content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if leader_dha_id:
                host_msg["dha_id"] = leader_dha_id
            messages.append(host_msg)
            if next_speaker in dha_ids:
                context = _messages_to_context(messages)
                next_dha = dha_map.get(next_speaker)
                host_msg["next_dha_name"] = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                host_msg["next_prompt"] = (decision.get("next_prompt") or "").strip() or _build_next_prompt_fallback(discussion_goal, context)
            _save_group_history(group_session_id, messages)
        if next_speaker == last_speaker_dha_id:
            if task_done or consecutive_same_dha >= 1:
                idx = dha_ids.index(last_speaker_dha_id) + 1 if last_speaker_dha_id in dha_ids else 0
                next_speaker = dha_ids[idx % len(dha_ids)] if dha_ids else "user"
                consecutive_same_dha = 0
            else:
                consecutive_same_dha += 1
        else:
            consecutive_same_dha = 0

    return {"status": "ok", "data": {"messages": messages}}
