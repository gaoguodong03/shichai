"""群聊 API - 多 DHA 群聊会话与消息"""
from __future__ import annotations

import asyncio
import json
import logging
import os
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
from app.agent.llm_client import get_llm_from_config
from app.agent.graph import create_skill_execution_agent
from app.agent.leader_scheduler import leader_decide
from app.mcp.manager import get_mcp_manager
from app.skills.loader import SkillsLoader
from app.tools.read_file import create_read_file_tool
from app.tools.call_api import call_api

logger = logging.getLogger(__name__)

router = APIRouter(tags=["group_chat"])

SESSIONS_DIR = os.getenv("SESSIONS_DIR", "./data/sessions")
GROUP_META_FILE = "group_sessions_meta.json"
GROUP_HISTORY_PREFIX = "group_history_"

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
    """将群聊消息转为供领导人/ DHA 使用的上下文字符串"""
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
            lines.append(f"【{name}】{content[:500]}{'…' if len(content) > 500 else ''}")
    return "\n\n".join(lines)


def _get_dha_tools(dha: Dict[str, Any]) -> List:
    """根据 DHA 的 mcp_server_ids 获取工具列表"""
    mcp_manager = get_mcp_manager()
    all_tools = mcp_manager.get_tools()
    server_ids = dha.get("mcp_server_ids") or []
    if server_ids:
        tools = [t for t in all_tools if "_" in t.name and t.name.split("_", 1)[0] in server_ids]
    else:
        tools = list(all_tools)
    tools = tools + [create_read_file_tool(), call_api]
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
    """解析主持人 DHA 的回复，提取主持词与 JSON。返回 {task_done, next_speaker, reason, announcement} 或 None"""
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
        if not announcement and reason:
            announcement = reason
        return {"task_done": task_done, "next_speaker": next_speaker, "reason": reason, "announcement": announcement or "请下一位发言。"}
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
    user_content = f"当前群聊参与者（next_speaker 必须使用以下 dha_id 之一）：\n{dha_text}\n\n讨论目标：{discussion_goal}\n\n最近讨论内容：\n\n{recent_messages}\n\n"
    if last_speaker_dha_id:
        user_content += f"刚发言的 DHA：{last_speaker_dha_id}\n\n请判断该 DHA 是否完成任务，并指定下一发言人。"
    else:
        user_content += "请指定第一个发言人（next_speaker 为某 dha_id）。此时 task_done 可设为 true。"

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


# ========== Pydantic 模型 ==========


class GroupSessionCreate(BaseModel):
    title: str = "新群聊"
    dha_ids: List[str]
    leader_dha_id: str
    speak_mode: Optional[str] = "auto"  # auto | manual


class GroupSessionUpdate(BaseModel):
    title: Optional[str] = None
    speak_mode: Optional[str] = None


class GroupChatRequest(BaseModel):
    message: Optional[str] = None
    override_next_speaker: Optional[str] = None  # dha_id | "user" | null
    action: Optional[str] = None  # "continue" 继续下一轮


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


@router.post("/group-sessions")
async def create_group_session(body: GroupSessionCreate):
    """创建群聊会话"""
    if not body.dha_ids:
        raise HTTPException(status_code=400, detail="dha_ids 不能为空")
    if body.leader_dha_id and body.leader_dha_id not in body.dha_ids:
        raise HTTPException(status_code=400, detail="leader_dha_id 必须在 dha_ids 中")

    instances = load_dha_instances()
    valid_ids = {d.get("dha_id") for d in instances}
    for did in body.dha_ids:
        if did not in valid_ids:
            raise HTTPException(status_code=400, detail=f"DHA {did} 不存在")

    gsid = f"group-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    meta = _load_group_meta()
    meta[gsid] = {
        "title": body.title or "新群聊",
        "dha_ids": body.dha_ids,
        "leader_dha_id": body.leader_dha_id or (body.dha_ids[0] if body.dha_ids else ""),
        "speak_mode": (body.speak_mode or "auto").strip().lower() if body.speak_mode else "auto",
        "created_at": now,
        "updated_at": now,
    }
    _save_group_meta(meta)
    _save_group_history(gsid, [])
    return {"status": "ok", "data": {"id": gsid, **meta[gsid]}}


@router.get("/group-sessions/{group_session_id}")
async def get_group_session(group_session_id: str):
    """获取群聊详情与消息"""
    meta = _load_group_meta()
    if group_session_id not in meta:
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
    """更新群聊：重命名、发言模式等"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    if body.title is not None and str(body.title).strip():
        meta[group_session_id]["title"] = body.title.strip()
    if body.speak_mode is not None and body.speak_mode.strip().lower() in ("auto", "manual"):
        meta[group_session_id]["speak_mode"] = body.speak_mode.strip().lower()
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
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("dha_id") and m.get("dha_id") != leader_dha_id:
            last_speaker_dha_id = m.get("dha_id")
            break

    # 讨论目标：取首条用户消息
    discussion_goal = ""
    for msg in messages:
        if msg.get("role") == "user":
            discussion_goal = (msg.get("content") or "")[:200]
            break
    if not discussion_goal:
        discussion_goal = "待用户提出讨论主题"

    app_settings = load_app_settings()
    extra_system_prompt = app_settings.get("system_prompt") or ""

    import json as json_module

    async def event_gen():
        nonlocal last_speaker_dha_id
        consecutive_same_dha = 0  # 限制同一 DHA 连续发言次数
        try:
            yield f"event: start\ndata: {json_module.dumps({'type': 'start'})}\n\n"

            next_speaker = None
            speak_mode = m.get("speak_mode", "auto")  # auto | manual

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
            elif speak_mode == "manual":
                # 手动模式：必须由前端传 override_next_speaker，否则不自动选人
                next_speaker = None
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
                    announcement = None
                else:
                    announcement = decision.get("announcement")
                next_speaker = decision.get("next_speaker", "user")
                task_done = decision.get("task_done", True)
                if not task_done and last_speaker_dha_id:
                    next_speaker = last_speaker_dha_id
                if last_speaker_dha_id is None and next_speaker == "user" and dha_ids:
                    next_speaker = dha_ids[0]
                if messages and messages[-1].get("role") == "user" and next_speaker == "user" and dha_ids:
                    idx = dha_ids.index(last_speaker_dha_id) + 1 if last_speaker_dha_id in dha_ids else 0
                    next_speaker = dha_ids[idx % len(dha_ids)]
                # 主持人发言：写入一条 assistant(leader_dha_id)，并下发 message 事件供前端逐条展示
                if leader_dha_id and next_speaker in dha_ids:
                    host_content = announcement if announcement else None
                    if not host_content:
                        next_dha = dha_map.get(next_speaker)
                        next_name = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                        host_content = f"下面由 {next_name} 发言。"
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "assistant",
                        "dha_id": leader_dha_id,
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    messages.append(host_msg)
                    _save_group_history(group_session_id, messages)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"

            while next_speaker and next_speaker in dha_ids:
                dha = dha_map.get(next_speaker)
                if not dha:
                    next_speaker = "user"
                    break

                tools = _get_dha_tools(dha)
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
                user_content = f"【群聊讨论目标】\n{discussion_goal}\n\n【最近讨论】\n{context}\n\n请基于以上上下文，以你的角色参与讨论并发言。"
                initial_state = {"messages": [HumanMessage(content=user_content)], "tools": tools}

                accumulated = []
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
                            content_str = str(aimsg.content) if isinstance(aimsg.content, str) else str(aimsg.content or "")
                            if content_str.strip() and content_str not in accumulated:
                                accumulated.append(content_str)
                                yield f"event: content\ndata: {json_module.dumps({'text': content_str, 'dha_id': next_speaker, 'meta': {}}, ensure_ascii=False)}\n\n"

                full_content = "".join(accumulated) if accumulated else "(无文本输出)"
                assistant_msg = {
                    "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                    "role": "assistant",
                    "dha_id": next_speaker,
                    "content": full_content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                messages.append(assistant_msg)
                _save_group_history(group_session_id, messages)
                meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                _save_group_meta(meta)
                yield f"event: message\ndata: {json_module.dumps(assistant_msg, ensure_ascii=False)}\n\n"

                last_speaker_dha_id = next_speaker
                # manual 模式：该 DHA 回答后直接结束，不再交给主持人
                if speak_mode == "manual":
                    yield f"event: end\ndata: {json_module.dumps({'type': 'end', 'waiting_for_user': True})}\n\n"
                    return
                # auto：主持人 DHA 或默认调度决定下一发言人
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
                # 主持人发言
                if leader_dha_id and (next_speaker in dha_ids or next_speaker in ("user", "end")):
                    host_content = announcement
                    if not host_content and next_speaker in dha_ids:
                        next_dha = dha_map.get(next_speaker)
                        next_name = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                        host_content = f"下面由 {next_name} 发言。"
                    if not host_content:
                        host_content = "请用户补充或继续提问。" if next_speaker == "user" else "讨论结束。"
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "assistant",
                        "dha_id": leader_dha_id,
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    messages.append(host_msg)
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

            if next_speaker == "end":
                yield f"event: end\ndata: {json_module.dumps({'type': 'end', 'discussion_ended': True})}\n\n"
            else:
                yield f"event: end\ndata: {json_module.dumps({'type': 'end', 'waiting_for_user': True})}\n\n"

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
            discussion_goal = (msg.get("content") or "")[:200]
            break
    if not discussion_goal:
        discussion_goal = "待用户提出讨论主题"

    app_settings = load_app_settings()
    extra_system_prompt = app_settings.get("system_prompt") or ""
    speak_mode = m.get("speak_mode", "auto")

    next_speaker = None
    if request.override_next_speaker is not None:
        next_speaker = request.override_next_speaker.strip().lower()
        if next_speaker == "user" or next_speaker == "end":
            return {"status": "ok", "data": {"messages": messages}}
        if next_speaker not in dha_ids:
            next_speaker = None
    if next_speaker is None and speak_mode != "manual":
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
        if leader_dha_id and next_speaker in dha_ids:
            host_content = announcement or None
            if not host_content:
                next_dha = dha_map.get(next_speaker)
                next_name = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                host_content = f"下面由 {next_name} 发言。"
            host_msg = {
                "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                "role": "assistant",
                "dha_id": leader_dha_id,
                "content": host_content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            messages.append(host_msg)
            _save_group_history(group_session_id, messages)

    consecutive_same_dha = 0
    while next_speaker and next_speaker in dha_ids:
        dha = dha_map.get(next_speaker)
        if not dha:
            break
        tools = _get_dha_tools(dha)
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
        user_content = f"【群聊讨论目标】\n{discussion_goal}\n\n【最近讨论】\n{context}\n\n请基于以上上下文，以你的角色参与讨论并发言。"
        initial_state = {"messages": [HumanMessage(content=user_content)], "tools": tools}

        try:
            final_state = await agent.ainvoke(initial_state)
            out_msgs = final_state.get("messages", [])
            content_str = ""
            for msg in reversed(out_msgs):
                if isinstance(msg, AIMessage):
                    content_str = str(msg.content) if isinstance(msg.content, str) else str(msg.content or "")
                    break
            if not content_str.strip():
                content_str = "(无文本输出)"
        except Exception as e:
            logger.exception("群聊 DHA 调用异常")
            content_str = f"调用异常: {e}"

        messages.append({
            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
            "role": "assistant",
            "dha_id": next_speaker,
            "content": content_str,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _save_group_history(group_session_id, messages)
        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_group_meta(meta)

        if speak_mode == "manual":
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
        if leader_dha_id and (next_speaker in dha_ids or next_speaker in ("user", "end")):
            host_content = announcement
            if not host_content and next_speaker in dha_ids:
                next_dha = dha_map.get(next_speaker)
                next_name = (next_dha.get("name") or next_speaker) if next_dha else next_speaker
                host_content = f"下面由 {next_name} 发言。"
            if not host_content:
                host_content = "请用户补充或继续提问。" if next_speaker == "user" else "讨论结束。"
            host_msg = {
                "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                "role": "assistant",
                "dha_id": leader_dha_id,
                "content": host_content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            messages.append(host_msg)
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
