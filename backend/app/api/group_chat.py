"""群聊 API - 多 DHA 群聊会话与消息"""
from __future__ import annotations

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
from langchain_core.messages import HumanMessage, AIMessage

from app.api.dha import load_dha_instances
from app.api.settings import load_app_settings
from app.api.files import get_workspace_root_path
from app.agent.llm_client import get_llm_from_config
from app.agent.graph import create_skill_execution_agent
from app.agent.leader_scheduler import leader_decide
from app.agent.tools_for_skill import build_tools_for_group_chat
from app.mcp.manager import get_mcp_manager
from app.skills.loader import get_skills_loader
from app.core.init import ensure_mcp_and_skills_initialized
from app.core.user_context import get_current_user_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["group_chat"])

SESSIONS_DIR = os.getenv("SESSIONS_DIR", "./data/sessions")
GROUP_META_FILE = "group_sessions_meta.json"
GROUP_HISTORY_PREFIX = "group_history_"

# 已废弃：不再使用 dha-chat，新建会话 0 个 DHA 时由主持人先与用户交流并推荐 DHA 加入
CHAT_DHA_ID = "dha-chat"

skills_loader = get_skills_loader()


async def _ensure_initialized():
    await ensure_mcp_and_skills_initialized()


def _safe_format_template(tpl: str, **kwargs) -> str:
    """安全渲染设置中的主持人模板。

    约定变量写法为 `{var}`。注意模板内可能包含 JSON 示例（大量 `{}`），
    因此不能直接使用 str.format（会把 JSON 大括号当成占位符并报错）。
    这里采用“只替换已知变量 token”的方式，保证不会因模板内容导致群聊中断。
    """
    out = str(tpl or "")
    for k, v in (kwargs or {}).items():
        out = out.replace("{" + str(k) + "}", "" if v is None else str(v))
    return out


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


def _build_archive_segments(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将会话消息归档分段（按轮次）并按专家聚合，不包含主持人。

    轮次定义（尽量符合用户直觉）：
    - 遇到 user 消息，开启新一轮；
    - 在这一轮内收集后续 assistant（专家）发言（按 dha_id 分组，保留顺序）；
    - role=host 的消息跳过（不归档）。
    """
    segments: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def _ensure_current() -> Dict[str, Any]:
        nonlocal current
        if current is None:
            current = {
                "user": None,
                "experts": {},  # dha_id -> {dha_id, messages:[{message_id, content, timestamp, skill_id?}]}
            }
        return current

    def _flush():
        nonlocal current
        if not current:
            current = None
            return
        # 只要这一轮有 user 或有专家发言就保留
        has_user = bool(current.get("user"))
        experts = current.get("experts") or {}
        has_expert = any((v.get("messages") or []) for v in experts.values()) if isinstance(experts, dict) else False
        if has_user or has_expert:
            # experts 由 dict 转 list，保持插入顺序（Python 3.7+ dict 有序）
            expert_list = []
            if isinstance(experts, dict):
                for _, v in experts.items():
                    if isinstance(v, dict):
                        expert_list.append(v)
            segments.append(
                {
                    "user": current.get("user"),
                    "experts": expert_list,
                }
            )
        current = None

    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = (m.get("role") or "").strip()
        if role == "host":
            continue
        if role == "user":
            _flush()
            cur = _ensure_current()
            cur["user"] = {
                "message_id": m.get("message_id"),
                "content": m.get("content") or "",
                "timestamp": m.get("timestamp"),
            }
            continue
        if role == "assistant":
            cur = _ensure_current()
            dha_id = (m.get("dha_id") or "").strip()
            if not dha_id:
                continue
            experts = cur.get("experts")
            if not isinstance(experts, dict):
                experts = {}
                cur["experts"] = experts
            if dha_id not in experts:
                experts[dha_id] = {"dha_id": dha_id, "messages": []}
            item = {
                "message_id": m.get("message_id"),
                "content": m.get("content") or "",
                "timestamp": m.get("timestamp"),
            }
            if m.get("skill_id") is not None:
                item["skill_id"] = m.get("skill_id")
            experts[dha_id]["messages"].append(item)
            continue
        # 其他 role 忽略

    _flush()
    return segments


@router.get("/sessions/{group_session_id}/archive")
async def get_group_archive(group_session_id: str):
    """会话归档：按轮次分段，并展示每位专家发言（不包含主持人）。"""
    # 确保会话存在
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    messages = _load_group_history(group_session_id)
    segments = _build_archive_segments(messages)
    # dha_map 用于前端展示名字
    instances = load_dha_instances()
    dha_map = {d.get("dha_id"): {"name": d.get("name") or d.get("dha_id"), "role": d.get("role") or ""} for d in instances if d.get("dha_id")}
    return {"status": "ok", "data": {"segments": segments, "dha_map": dha_map}}


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


def _title_from_first_message(text: str, max_chars: int = 10) -> str:
    """根据用户首次发送生成会话标题，约 max_chars 字以内。去掉【讨论目标】等前缀，取首行或截断。"""
    if not text or not isinstance(text, str):
        return ""
    s = text.strip()
    for prefix in ("【讨论目标】", "【给下一 DHA 的提示】"):
        if s.startswith(prefix):
            s = s[len(prefix) :].lstrip("\n ")
    first_line = s.split("\n")[0].strip() if s else ""
    if not first_line:
        return ""
    if len(first_line) > max_chars:
        return first_line[:max_chars].rstrip()
    return first_line


def _build_next_prompt_fallback(discussion_goal: str, context: str) -> str:
    """当主持人未输出 next_prompt 时使用的默认提示词模板。
    刻意给出较完整的最近讨论内容，便于下一位专家（尤其是配图/生成类）有足够信息执行。"""
    return (
        f"【群聊讨论目标】\n{discussion_goal}\n\n"
        f"【最近几轮讨论内容（按时间顺序，含用户与各位专家的发言要点）】\n{context}\n\n"
        "【你这一轮的任务】\n"
        "1. 先用 1～3 句话总结当前讨论已达成的结论或共识。\n"
        "2. 结合你的角色与专长，完成本轮的 1～2 个具体子任务；可从上方「最近几轮讨论内容」中摘取关键信息（链接、主题、用户偏好、已有文案等）直接使用。\n"
        "3. 若涉及生成图片/配图/封面：请根据讨论中的文案或要点确定配图主题与风格，并说明所需尺寸或数量（若已提及）。\n"
        "4. 若需要其他专家或用户接力，请明确说明「接下来可由谁做什么」。\n\n"
        "【输出要求】信息量充足、紧扣目标；可分条书写；避免大段照抄全文，侧重提炼与执行。"
    )


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
    """解析主持人 DHA 的回复，提取主持词与 JSON。

    期望 JSON 字段（可选）：
    - task_done: bool
    - next_speaker: "user" 或某 dha_id
    - reason / announcement: str
    - next_prompt: str
    - suggested_add_dha_ids: [dha_id, ...] 或 suggested_add_dha_id: dha_id
    - suggested_order: [dha_id, ...]
    """
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
        # 主持人建议邀请的成员（可选）
        suggested_add_dha_ids = None
        ids_raw = data.get("suggested_add_dha_ids")
        if isinstance(ids_raw, list) and ids_raw:
            cleaned = [str(x).strip() for x in ids_raw if str(x).strip()]
            if cleaned:
                suggested_add_dha_ids = list(dict.fromkeys(cleaned))
        if not suggested_add_dha_ids:
            sid = (data.get("suggested_add_dha_id") or "").strip()
            if sid:
                suggested_add_dha_ids = [sid]
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
            "suggested_add_dha_ids": suggested_add_dha_ids,
        }
    except Exception:
        return None


def _heuristic_recommend_dhas(
    discussion_goal: str, all_instances: List[Dict[str, Any]], max_n: Optional[int] = None
) -> List[str]:
    """0 成员时兜底推荐：用简单关键词匹配 name/role，返回 dha_id 列表（去重、保序）。

    max_n 为 None 时返回尽可能多的候选（按匹配度排序）。
    """
    goal = (discussion_goal or "").strip().lower()
    scored = []
    for d in all_instances or []:
        did = (d.get("dha_id") or "").strip()
        if not did:
            continue
        name = str(d.get("name") or "").lower()
        role = str(d.get("role") or "").lower()
        hay = f"{did} {name} {role}"
        score = 0
        # 朴素：目标词命中越多越靠前
        for token in (goal.replace("，", " ").replace("。", " ").replace(",", " ").split() if goal else []):
            if token and token in hay:
                score += 3
        # 常见意图兜底
        if any(k in goal for k in ("天气", "气温", "下雨", "预报")) and any(k in hay for k in ("天气", "气象")):
            score += 5
        if any(k in goal for k in ("写", "文案", "公众号", "文章", "标题")) and any(k in hay for k in ("写作", "文案", "编辑", "公众号", "内容")):
            score += 5
        if any(k in goal for k in ("图", "封面", "配图", "logo", "海报")) and any(k in hay for k in ("设计", "封面", "配图", "海报", "图像", "logo")):
            score += 5
        if any(k in goal for k in ("数据", "报表", "分析", "表格", "excel")) and any(k in hay for k in ("数据", "分析", "报表", "excel")):
            score += 5
        scored.append((score, did))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [did for s, did in scored if s > 0]
    if max_n is not None:
        picked = picked[: max(0, int(max_n))]
    if not picked:
        # 仍然没有命中：选前 max_n 个
        for d in all_instances or []:
            did = (d.get("dha_id") or "").strip()
            if did and did not in picked:
                picked.append(did)
            if max_n is not None and len(picked) >= max_n:
                break
    if max_n is not None:
        return picked[:max(0, int(max_n))]
    return picked


async def _host_decide_by_dha(
    llm,
    host_dha: Dict[str, Any],
    dha_list: List[Dict[str, Any]],
    discussion_goal: str,
    recent_messages: str,
    last_speaker_dha_id: Optional[str],
    extra_system_prompt: str,
    available_to_add: Optional[List[Dict[str, Any]]] = None,
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
    host_system = (host_dha.get("system_prompt") or "").strip()
    if host_system:
        skill_content = f"{host_system}\n\n{skill_content}"

    dha_lines = []
    for d in dha_list:
        r = d.get("role") or "参与者"
        n = d.get("name") or d.get("dha_id", "")
        did = d.get("dha_id", "")
        dha_lines.append(f"- {n} ({did}): {r}")
    dha_text = "\n".join(dha_lines)

    # 可邀请的专家列表：主持人用它来输出 suggested_add_dha_ids
    add_lines = []
    for d in (available_to_add or []):
        did = (d.get("dha_id") or "").strip()
        if not did:
            continue
        n = (d.get("name") or did) if isinstance(d.get("name") or did, str) else did
        r = d.get("role") or "参与者"
        skills = d.get("skill_ids") or []
        skills_txt = ""
        if isinstance(skills, list) and skills:
            skills_txt = " skills=" + ",".join([str(x) for x in skills if str(x).strip()][:4])
        add_lines.append(f"- {n} ({did}): {r}{skills_txt}")
    available_text = "\n".join(add_lines) if add_lines else "（暂无可邀请专家）"
    app_settings = load_app_settings()
    host_prompts = app_settings.get("host_prompts") or {}
    if not isinstance(host_prompts, dict):
        host_prompts = {}
    host_master_prompt = str(host_prompts.get("host_master_prompt") or "")

    user_content = (
        f"【当前群聊参与者（next_speaker 必须使用以下 dha_id 之一）】\n{dha_text}\n\n"
        f"【讨论目标】\n{discussion_goal}\n\n"
        "【最近讨论内容（按时间顺序）】\n"
        f"{recent_messages}\n\n"
        f"【可邀请专家列表（需要补人时，从此列表选择 suggested_add_dha_ids）】\n{available_text}\n\n"
    )
    if last_speaker_dha_id:
        user_content += f"【刚发言的专家】{last_speaker_dha_id}\n\n"
    else:
        user_content += "【当前为首轮】尚无上一位专家发言。\n\n"

    try:
        # 将 host_master_prompt 作为额外 system prompt 注入
        agent = create_skill_execution_agent(llm, [], skill_content, (host_master_prompt + "\n\n" + (extra_system_prompt or "")).strip())
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
    当前群聊 0 个成员时：主持人回复用户并推荐一位或多位专家加入。
    返回 (主持人回复正文, suggested_add_dha_ids 或 None)。
    """
    skill_content = skills_loader.get_skill_full_content("group-host")
    if not skill_content:
        skill_content = "你是群聊主持人，负责协调讨论并适时推荐合适的专家加入。"
    app_settings = load_app_settings()
    host_prompts = app_settings.get("host_prompts") or {}
    if not isinstance(host_prompts, dict):
        host_prompts = {}
    host_zero_member_policy = str(host_prompts.get("host_zero_member_policy") or "")
    system_content = (host_zero_member_policy + "\n\n" + str(skill_content or "")).strip()
    dha_lines = []
    for d in all_instances:
        did = d.get("dha_id", "")
        if did == CHAT_DHA_ID:
            continue
        name = d.get("name") or did
        role = d.get("role") or "参与者"
        dha_lines.append(f"- {name} ({did}): {role}")
    dha_text = "\n".join(dha_lines) if dha_lines else "（暂无可选专家）"
    llm = _get_llm_for_dha(None, app_settings)
    user_content = (
        f"【讨论目标/用户消息】\n{discussion_goal}\n\n"
        f"【最近对话】\n{recent_messages}\n\n"
        f"【可选专家列表】\n{dha_text}\n\n"
    )
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
            # LLM 没输出：直接兜底推荐
            fallback_ids = _heuristic_recommend_dhas(discussion_goal, all_instances, max_n=None)
            return "我已收到您的需求，建议先邀请以下专家加入讨论（可在下方一键邀请）。", fallback_ids or None
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
        # 若 JSON 未解析出推荐列表，从正文中提取 dha-xxx 作为备用（主持人常在正文中写专家 id，如 dha-url-to-blog、dha-2be73edd）
        if not suggested_add_dha_ids and valid_ids:
            dha_id_pattern = re.compile(r"dha-[a-zA-Z0-9\-]+", re.I)
            found = list(dict.fromkeys(dha_id_pattern.findall(text)))
            suggested_add_dha_ids = [x for x in found if x in valid_ids]
        return announcement or text, suggested_add_dha_ids
    except Exception as e:
        logger.warning("主持人 0 成员推荐调用失败: %s", e)
        fallback_ids = _heuristic_recommend_dhas(discussion_goal, all_instances, max_n=None)
        return "我已收到您的需求，建议先邀请以下专家加入讨论（可在下方一键邀请）。", fallback_ids or None


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


# ========== 统一会话用内部接口（供 api/sessions 复用） ==========


def create_session_internal(
    title: str = "新对话",
    dha_ids: Optional[List[str]] = None,
    speak_mode: str = "auto",
) -> Dict[str, Any]:
    """创建一条会话（主持人必在，dha_ids 可为空）。返回 meta 条目（含 id）。"""
    instances = load_dha_instances()
    valid_ids = {d.get("dha_id") for d in instances}
    dha_ids = list(dha_ids or [])
    for did in dha_ids:
        if did not in valid_ids:
            raise HTTPException(status_code=400, detail=f"DHA {did} 不存在")
    gsid = f"group-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    meta = _load_group_meta()
    meta[gsid] = {
        "title": title or "新对话",
        "dha_ids": dha_ids,
        "leader_dha_id": "",
        "speak_mode": (speak_mode or "auto").strip().lower(),
        "created_at": now,
        "updated_at": now,
    }
    _save_group_meta(meta)
    _save_group_history(gsid, [])
    # 工作区目录延后创建：仅在用户首次使用工作区（列表/上传/导出等）时由 files API 或 export 创建
    return {"id": gsid, **meta[gsid]}


def export_session_to_markdown(session_id: str, filename: Optional[str] = None) -> tuple:
    """将会话历史导出为 Markdown 到该会话工作区。历史来自 group_history。返回 (rel_path, download_url)。"""
    from app.api.files import get_workspace_root

    messages = _load_group_history(session_id)
    if not messages:
        raise HTTPException(status_code=400, detail="会话无消息，无法导出")
    lines = ["# 对话导出\n", f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "---\n"]
    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        dha_id = msg.get("dha_id", "")
        if role == "user":
            lines.append("## 用户\n\n")
        elif role == "host":
            lines.append("## 主持人\n\n")
        else:
            label = dha_id or "助手"
            lines.append(f"## {label}\n\n")
        lines.append(content)
        lines.append("\n\n")
    md = "".join(lines)
    ws_root = get_workspace_root(session_id)
    fn = filename or f"session-{session_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    fn = fn.replace("..", "").replace("/", "")
    if not fn.endswith(".md"):
        fn += ".md"
    filepath = ws_root / fn
    filepath.write_text(md, encoding="utf-8")
    rel = str(filepath.relative_to(ws_root)).replace("\\", "/")
    return rel, f"/api/workspaces/{session_id}/files/download?path={rel}"


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
    """创建群聊会话。dha_ids 为空时表示「主持人为先」：用户先与主持人交流。"""
    if body.leader_dha_id and body.dha_ids and body.leader_dha_id not in body.dha_ids:
        raise HTTPException(status_code=400, detail="leader_dha_id 必须在 dha_ids 中")
    data = create_session_internal(
        title=body.title or "新群聊",
        dha_ids=body.dha_ids or [],
        speak_mode=body.speak_mode or "auto",
    )
    return {"status": "ok", "data": data}


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
    """删除群聊会话：同时删除 meta、群聊历史文件与该会话的工作区目录。"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    del meta[group_session_id]
    _save_group_meta(meta)
    # 删除群聊历史
    path = _ensure_sessions_dir() / f"{GROUP_HISTORY_PREFIX}{group_session_id}.json"
    if path.exists():
        path.unlink()
    # 删除该会话对应的工作区目录（若存在）
    try:
        ws_root = get_workspace_root_path(group_session_id)
        if ws_root.exists() and ws_root.is_dir():
            import shutil

            shutil.rmtree(ws_root)
    except Exception:
        logger.warning("删除群聊 %s 的 workspace 目录失败，可手动清理。", group_session_id, exc_info=True)
    return {"status": "ok", "data": {"id": group_session_id, "deleted": True}}


@router.delete("/group-sessions/{group_session_id}/messages/{message_id}")
async def delete_group_message(group_session_id: str, message_id: str):
    """从会话列表和会话历史中彻底删除一条消息（含专家发言），避免污染下一轮 DHA 的上下文。"""
    meta = _load_group_meta()
    if group_session_id not in meta:
        raise HTTPException(status_code=404, detail="Group session not found")
    messages = _load_group_history(group_session_id)
    before = len(messages)
    messages = [m for m in messages if m.get("message_id") != message_id]
    if len(messages) == before:
        raise HTTPException(status_code=404, detail="Message not found")
    _save_group_history(group_session_id, messages)
    return {"status": "ok", "data": {"message_id": message_id, "deleted": True}}


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
    # 当前不在群内的专家，主持人可在「完成不了工作」时建议邀请
    available_to_add = [d for d in instances if d.get("dha_id") and d.get("dha_id") not in dha_ids and d.get("dha_id") != CHAT_DHA_ID]

    messages = _load_group_history(group_session_id)

    # 用户消息
    if request.message and request.message.strip():
        first_user_message = not any(m.get("role") == "user" for m in messages)
        messages.append({
            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
            "role": "user",
            "content": request.message.strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _save_group_history(group_session_id, messages)
        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        if first_user_message:
            current_title = (meta[group_session_id].get("title") or "").strip()
            if current_title in ("新对话", "新群聊", ""):
                auto_title = _title_from_first_message(request.message.strip(), max_chars=10)
                if auto_title:
                    meta[group_session_id]["title"] = auto_title
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
    # 已废弃：不再提供全局 system_prompt；主持人提示词改为在主持人 DHA（is_leader）实例上维护
    extra_system_prompt = ""
    # speak_mode 从会话 meta 读取（m 为 meta[group_session_id]），manual 时仅主持人给建议并结束，等用户选人/改提示词后再发
    speak_mode = m.get("speak_mode", "auto")

    import json as json_module

    async def event_gen():
        nonlocal last_speaker_dha_id, dha_ids, dha_list, available_to_add
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
                yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                # 自动邀请并继续跑：若主持人给出推荐列表，则直接把这些专家加入会话，并进入后续主持调度流程
                if suggested_add_dha_ids:
                    valid_ids = {d.get("dha_id") for d in instances if d.get("dha_id")}
                    picked = [x for x in suggested_add_dha_ids if x in valid_ids]
                    picked = list(dict.fromkeys(picked))
                    if picked:
                        # 更新 meta 与本次请求内的 dha_ids/dha_list/dha_map
                        meta[group_session_id]["dha_ids"] = picked
                        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                        _save_group_meta(meta)
                        dha_ids = picked
                        dha_list = [d for d in instances if d.get("dha_id") in dha_ids]
                        available_to_add = [d for d in instances if d.get("dha_id") and d.get("dha_id") not in dha_ids and d.get("dha_id") != CHAT_DHA_ID]
                        # 继续往下走：next_speaker 仍为 None，后续会进入主持人调度选择下一位发言人
                    else:
                        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                        _save_group_meta(meta)
                        yield f"event: end\ndata: {json_module.dumps({'type': 'end', 'waiting_for_user': True}, ensure_ascii=False)}\n\n"
                        return
                else:
                    meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                    _save_group_meta(meta)
                    yield f"event: end\ndata: {json_module.dumps({'type': 'end', 'waiting_for_user': True}, ensure_ascii=False)}\n\n"
                    return

            # 1 个 DHA 时也走主持人流程，主持人会点名后再由该 DHA 发言
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
                        llm_host, host_dha, dha_list, discussion_goal, recent, last_speaker_dha_id, extra_system_prompt, available_to_add
                    )
                if decision is None:
                    llm_default = _get_llm_for_dha(None, app_settings)
                    decision = await leader_decide(llm_default, dha_list, discussion_goal, recent, last_speaker_dha_id, available_to_add)
                announcement = decision.get("announcement")
                suggested = (decision.get("next_speaker") or "").strip().lower()
                suggested_add = decision.get("suggested_add_dha_ids") or []
                valid_ids = {d.get("dha_id") for d in instances}
                suggested_add = [x for x in suggested_add if x in valid_ids]
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
                if suggested_add:
                    host_msg["suggested_add_dha_ids"] = suggested_add
                    host_msg["suggested_add_dha_id"] = suggested_add[0]
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
                    # 否则仍然等待用户选择；但若主持人建议新增成员，则自动邀请后继续跑
                    if suggested_add:
                        new_ids = [x for x in suggested_add if x not in dha_ids]
                        if new_ids:
                            dha_ids = dha_ids + new_ids
                            meta[group_session_id]["dha_ids"] = dha_ids
                            meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                            _save_group_meta(meta)
                            dha_list = [d for d in instances if d.get("dha_id") in dha_ids]
                            available_to_add = [d for d in instances if d.get("dha_id") and d.get("dha_id") not in dha_ids and d.get("dha_id") != CHAT_DHA_ID]
                            next_speaker = new_ids[0]
                        else:
                            next_speaker = dha_ids[0] if dha_ids else "user"
                    else:
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
                        llm_host, host_dha, dha_list, discussion_goal, recent, last_speaker_dha_id, extra_system_prompt, available_to_add
                    )
                if decision is None:
                    llm_default = _get_llm_for_dha(None, app_settings)
                    decision = await leader_decide(llm_default, dha_list, discussion_goal, recent, last_speaker_dha_id, available_to_add)
                announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                suggested_add = (decision.get("suggested_add_dha_ids") or [])
                valid_ids = {d.get("dha_id") for d in instances}
                suggested_add = [x for x in suggested_add if x in valid_ids]
                # 由主持人/调度明确给出下一位发言人。
                # 不再根据 task_done 强制让上一位 DHA 连续发言，
                # 每一小轮都回到主持人决策，再由 decision["next_speaker"] 指定下一位。
                next_speaker = decision.get("next_speaker", "user")
                if last_speaker_dha_id is None and next_speaker == "user" and dha_ids:
                    next_speaker = dha_ids[0]
                if messages and messages[-1].get("role") == "user" and next_speaker == "user" and dha_ids and not suggested_add:
                    idx = dha_ids.index(last_speaker_dha_id) + 1 if last_speaker_dha_id in dha_ids else 0
                    next_speaker = dha_ids[idx % len(dha_ids)]
                # 主持人建议新增成员时：自动邀请并继续跑（不再等待用户确认）
                if suggested_add and next_speaker == "user":
                    host_content = announcement or "当前成员无法完成该工作，已自动邀请新成员加入继续处理。"
                    # 追加新成员（去重）
                    new_ids = [x for x in suggested_add if x not in dha_ids]
                    if new_ids:
                        dha_ids = dha_ids + new_ids
                        meta[group_session_id]["dha_ids"] = dha_ids
                        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                        _save_group_meta(meta)
                        dha_list = [d for d in instances if d.get("dha_id") in dha_ids]
                        available_to_add = [d for d in instances if d.get("dha_id") and d.get("dha_id") not in dha_ids and d.get("dha_id") != CHAT_DHA_ID]
                        next_speaker = new_ids[0]
                    else:
                        next_speaker = dha_ids[0] if dha_ids else "user"
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host" if not leader_dha_id else "assistant",
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "auto_invited_dha_ids": new_ids,
                    }
                    if leader_dha_id:
                        host_msg["dha_id"] = leader_dha_id
                    messages.append(host_msg)
                    _save_group_history(group_session_id, messages)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
                # 主持人发言（单人会话时也由主持人先点名，再让该 DHA 发言）
                if next_speaker in dha_ids:
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
                # 在自动或手动模式下，单次流中专家发言超过一定轮次（默认 32）时强制停下来，让用户确认是否继续，
                # 避免在服务器上长时间无限循环。
                if dha_turns >= 32:
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

                tools = build_tools_for_group_chat(get_mcp_manager().get_tools(), dha, group_session_id)
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
                    user_content = (request.custom_prompt or "").strip()
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
                # 将历史对话加载在提示词末尾，一并发给下一位专家，便于其掌握完整上下文
                user_content = (user_content or "").strip() + "\n\n【历史对话（供参考）】\n" + context
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
                # 单人会话也走主持人：主持人提取/补充参数与 next_prompt，可让同一专家多轮发言直到出结果
                # 手动模式：仍由主持人决定下一发言人并展示建议，再结束，等用户点「确认并继续」
                if speak_mode != "auto":
                    host_msg = {}
                    decision = None
                    host_dha = dha_map.get(leader_dha_id) if leader_dha_id else None
                    if leader_dha_id and leader_dha_id in dha_ids and host_dha:
                        llm_host = _get_llm_for_dha(host_dha, app_settings)
                        decision = await _host_decide_by_dha(
                            llm_host, host_dha, dha_list, discussion_goal, _messages_to_context(messages),
                            last_speaker_dha_id, extra_system_prompt, available_to_add
                        )
                    if decision is None:
                        llm_default = _get_llm_for_dha(None, app_settings)
                        decision = await leader_decide(llm_default, dha_list, discussion_goal, _messages_to_context(messages), last_speaker_dha_id, available_to_add)
                    next_speaker_manual = decision.get("next_speaker", "user")
                    if not decision.get("task_done", True) and last_speaker_dha_id:
                        next_speaker_manual = last_speaker_dha_id
                    suggested_add = (decision.get("suggested_add_dha_ids") or [])
                    suggested_add = [x for x in suggested_add if x in {d.get("dha_id") for d in instances}]
                    announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                    if next_speaker_manual in dha_ids or next_speaker_manual in ("user", "end"):
                        host_content = announcement
                        if not host_content and next_speaker_manual in dha_ids:
                            next_dha = dha_map.get(next_speaker_manual)
                            host_content = f"下面由 {next_dha.get('name') or next_speaker_manual} 发言。" if next_dha else f"下面由 {next_speaker_manual} 发言。"
                        if not host_content:
                            host_content = "请用户补充或继续提问。" if next_speaker_manual == "user" else "讨论结束。"
                        if suggested_add and next_speaker_manual == "user":
                            host_content = announcement or "当前成员无法完成该工作，已自动邀请新成员加入继续处理。"
                        host_msg = {
                            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                            "role": "host" if not leader_dha_id else "assistant",
                            "content": host_content,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        if leader_dha_id:
                            host_msg["dha_id"] = leader_dha_id
                        if suggested_add:
                            # 手动模式也自动邀请：更新会话成员
                            new_ids = [x for x in suggested_add if x not in dha_ids]
                            if new_ids:
                                dha_ids = dha_ids + new_ids
                                meta[group_session_id]["dha_ids"] = dha_ids
                                meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                                _save_group_meta(meta)
                                dha_list = [d for d in instances if d.get("dha_id") in dha_ids]
                                available_to_add = [d for d in instances if d.get("dha_id") and d.get("dha_id") not in dha_ids and d.get("dha_id") != CHAT_DHA_ID]
                            host_msg["auto_invited_dha_ids"] = new_ids
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
                    if suggested_add:
                        end_data["auto_invited_dha_ids"] = host_msg.get("auto_invited_dha_ids") or []
                    yield f"event: end\ndata: {json_module.dumps(end_data)}\n\n"
                    return
                # auto 且多 DHA：主持人决定下一发言人
                decision = None
                host_dha = dha_map.get(leader_dha_id) if leader_dha_id else None
                if leader_dha_id and leader_dha_id in dha_ids and host_dha:
                    llm_host = _get_llm_for_dha(host_dha, app_settings)
                    decision = await _host_decide_by_dha(
                        llm_host, host_dha, dha_list, discussion_goal, _messages_to_context(messages),
                        last_speaker_dha_id, extra_system_prompt, available_to_add
                    )
                if decision is None:
                    llm_default = _get_llm_for_dha(None, app_settings)
                    decision = await leader_decide(llm_default, dha_list, discussion_goal, _messages_to_context(messages), last_speaker_dha_id, available_to_add)
                task_done = decision.get("task_done", True)
                next_speaker = decision.get("next_speaker", "user")
                if not task_done:
                    next_speaker = last_speaker_dha_id
                suggested_add = (decision.get("suggested_add_dha_ids") or [])
                suggested_add = [x for x in suggested_add if x in {d.get("dha_id") for d in instances}]
                announcement = decision.get("announcement") if isinstance(decision.get("announcement"), str) else None
                # 主持人建议新增成员时：自动邀请并继续跑
                if suggested_add and next_speaker == "user":
                    new_ids = [x for x in suggested_add if x not in dha_ids]
                    if new_ids:
                        dha_ids = dha_ids + new_ids
                        meta[group_session_id]["dha_ids"] = dha_ids
                        meta[group_session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                        _save_group_meta(meta)
                        dha_list = [d for d in instances if d.get("dha_id") in dha_ids]
                        available_to_add = [d for d in instances if d.get("dha_id") and d.get("dha_id") not in dha_ids and d.get("dha_id") != CHAT_DHA_ID]
                        next_speaker = new_ids[0]
                    else:
                        next_speaker = dha_ids[0] if dha_ids else "user"
                    host_content = announcement or "当前成员无法完成该工作，已自动邀请新成员加入继续处理。"
                    host_msg = {
                        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
                        "role": "host" if not leader_dha_id else "assistant",
                        "content": host_content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "auto_invited_dha_ids": new_ids,
                    }
                    if leader_dha_id:
                        host_msg["dha_id"] = leader_dha_id
                    messages.append(host_msg)
                    _save_group_history(group_session_id, messages)
                    yield f"event: message\ndata: {json_module.dumps(host_msg, ensure_ascii=False)}\n\n"
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
                # 限制同一 DHA 连续发言（仅多人时；单人时主持人可多次指定同一专家并补充提示词，直到出结果）
                if not single_dha_mode:
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
