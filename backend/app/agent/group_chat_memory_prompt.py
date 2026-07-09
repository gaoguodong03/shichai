"""Group-chat memory facts and expert action prompt assembly helpers."""
from __future__ import annotations

import logging
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from app.agent.group_context import (
    normalize_compare_text as _normalize_compare_text,
    shorten_text as _shorten_text,
)
from app.agent.group_memory_store import build_dispatch_context, upsert_facts, upsert_index_entries

logger = logging.getLogger(__name__)


def _build_action_prompt_fallback(discussion_goal: str, context: str) -> str:
    """Build the default expert action prompt when the host provides no instruction."""
    return (
        f"【群聊讨论目标】\n{discussion_goal}\n\n"
        f"【最近几轮讨论内容（按时间顺序，含用户与各位专家的发言要点）】\n{context}\n\n"
        "【你这一轮的任务】\n"
        "1. 直接进入你的角色发言或交付结果，不要先写任务说明。\n"
        "2. 结合你的角色与专长，完成本轮的 1～2 个具体子任务；可从上方「最近几轮讨论内容」中摘取关键信息（链接、主题、用户偏好、已有文案等）直接使用。\n"
        "3. 若涉及生成图片/配图/封面：请根据讨论中的文案或要点确定配图主题与风格，并说明所需尺寸或数量（若已提及）。\n"
        "4. 仅输出你本轮可交付结果，不要在正文中安排下一位角色。\n\n"
        "【输出要求】信息量充足、紧扣目标；可分条书写；避免大段照抄全文，侧重提炼与执行；不要用任务说明式开头。"
    )


def _get_group_memory_settings(app_settings: Dict[str, Any]) -> Dict[str, Any]:
    cfg = app_settings.get("group_memory") if isinstance(app_settings, dict) else {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "max_logs": int(cfg.get("max_logs", 20)),
        "max_facts": int(cfg.get("max_facts", 60)),
        "dispatch_top_k": int(cfg.get("dispatch_top_k", 3)),
    }


def _extract_facts_from_response(text: str, max_items: int = 4) -> List[str]:
    content = (text or "").strip()
    if not content:
        return []
    lines: List[str] = []
    for line in content.splitlines():
        item = line.strip()
        if not item:
            continue
        if item.startswith(("-", "*", "1.", "2.", "3.", "4.", "5.")):
            item = item.lstrip("-*0123456789. ").strip()
        if len(item) < 6:
            continue
        lines.append(item[:220])
        if len(lines) >= max_items:
            break
    if lines:
        return lines
    compact = content.replace("\n", " ")
    chunks = [item.strip() for item in re.split(r"[。；;.!?！？]", compact) if item.strip()]
    return [item[:220] for item in chunks[:max_items]]


def _normalize_workspace_index_path(value: Any) -> str:
    path = str(value or "").strip().strip('"').strip("'")
    if not path:
        return ""
    match = re.search(r"(?:[?&]path=)([^\"'\s)]+)", path)
    if match:
        path = unquote(match.group(1))
    if "://" in path and "path=" not in str(value or ""):
        return ""
    path = path.replace("\\", "/")
    path = re.sub(r"^/workspace/", "", path)
    path = re.sub(r"^workspace/", "", path)
    while path.startswith("./"):
        path = path[2:]
    path = path.lstrip("/")
    path = path.strip().strip("，,。.;；)")
    if not path or path in {"memory/facts.md", "memory/index.md"}:
        return ""
    return path[:240]


def _iter_artifact_paths(payload: Any) -> List[str]:
    paths: List[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key or "").lower()
            if key_text in {
                "path",
                "file_path",
                "filepath",
                "workspace_path",
                "output_path",
                "download_url",
                "output",
                "markdown",
            }:
                normalized = _normalize_workspace_index_path(value)
                if normalized:
                    paths.append(normalized)
            paths.extend(_iter_artifact_paths(value))
    elif isinstance(payload, list):
        for item in payload:
            paths.extend(_iter_artifact_paths(item))
    return paths


def _extract_paths_from_tool_output_value(value: Any) -> List[str]:
    text = str(value or "")
    paths: List[str] = []
    try:
        decoded = json.loads(text)
    except Exception:
        decoded = None
    if decoded is not None:
        paths.extend(_iter_artifact_paths(decoded))
    for pattern in (
        r"已写入当前 Chat 工作区文件[:：]\s*([^\s]+)",
        r"已写入当前工作区文件[:：]\s*([^\s]+)",
        r"/api/workspaces/[^\"'\s)]+/files/download\?path=([^\"'\s)]+)",
    ):
        for match in re.finditer(pattern, text):
            normalized = _normalize_workspace_index_path(match.group(1))
            if normalized:
                paths.append(normalized)
    return paths


def _extract_index_paths_from_message(msg: Dict[str, Any]) -> List[str]:
    paths: List[str] = []
    tool_results = msg.get("tool_results") if isinstance(msg, dict) else []
    for result in tool_results if isinstance(tool_results, list) else []:
        if not isinstance(result, dict):
            continue
        call = result.get("tool_call")
        if isinstance(call, dict):
            args = call.get("arguments") or {}
            if isinstance(args, dict):
                for key in ("path", "file_path", "output_path", "target_path", "dst_path", "new_path", "workspace_path"):
                    normalized = _normalize_workspace_index_path(args.get(key))
                    if normalized:
                        paths.append(normalized)
        for artifact in result.get("artifacts") or []:
            if not isinstance(artifact, dict):
                continue
            for key in ("path", "url"):
                normalized = _normalize_workspace_index_path(artifact.get(key))
                if normalized:
                    paths.append(normalized)
        output = result.get("output")
        if isinstance(output, dict):
            for key in ("text", "markdown", "stdout", "stderr", "json_data"):
                paths.extend(_extract_paths_from_tool_output_value(output.get(key)))
        error_log = result.get("error_log")
        if isinstance(error_log, dict):
            for key in ("message", "detail", "stdout", "stderr", "raw_output"):
                paths.extend(_extract_paths_from_tool_output_value(error_log.get(key)))

    deduped: List[str] = []
    seen = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _summarize_index_work(content: str) -> str:
    for raw in (content or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = line.lstrip("-*0123456789. #").strip()
        if line:
            return line[:180]
    return "更新工作区文件"


def _persist_group_memory_turn(
    *,
    session_id: str,
    msg: Dict[str, Any],
    discussion_goal: str,
    input_prompt_summary: str,
    app_settings: Dict[str, Any],
    workspace_root: Optional[Path] = None,
) -> None:
    """Maintain facts.md from visible expert messages."""
    _ = discussion_goal, input_prompt_summary
    mem = _get_group_memory_settings(app_settings)
    if not mem["enabled"]:
        return
    speaker = (msg or {}).get("speaker")
    if not isinstance(speaker, dict) or str(speaker.get("type") or "").strip() != "expert":
        return
    content = str((msg or {}).get("content") or "").strip()
    if content:
        facts_delta = _extract_facts_from_response(content)
    else:
        facts_delta = []
    if facts_delta:
        upsert_facts(
            session_id=session_id,
            facts_delta=facts_delta,
            max_facts=mem["max_facts"],
            workspace_root=workspace_root,
        )
    index_paths = _extract_index_paths_from_message(msg)
    if index_paths:
        upsert_index_entries(
            session_id=session_id,
            entries_delta=[
                {
                    "agent_name": str(speaker.get("agent_name") or "unknown"),
                    "skill": str(speaker.get("skill") or "default"),
                    "summary": _summarize_index_work(content),
                    "files": index_paths,
                }
            ],
            max_entries=mem["max_facts"],
            workspace_root=workspace_root,
        )


def _build_action_prompt_with_memory(
    session_id: str,
    target_agent_name: str,
    discussion_goal: str,
    context: str,
    app_settings: Dict[str, Any],
    host_next_action: Optional[str] = None,
) -> str:
    mem = _get_group_memory_settings(app_settings)
    if not mem["enabled"]:
        return (host_next_action or "").strip() or _build_action_prompt_fallback(discussion_goal, context)

    dispatch = {"has_memory": False, "rendered": ""}
    try:
        dispatch = build_dispatch_context(
            session_id=session_id,
            target_agent_name=target_agent_name,
            goal=discussion_goal,
            k=mem["dispatch_top_k"],
            max_facts=mem["max_facts"],
        )
    except Exception:
        logger.warning("group memory read failed", exc_info=True)

    if dispatch.get("has_memory"):
        chunks: List[str] = []
        host_line = (host_next_action or "").strip()
        if host_line:
            chunks.append(
                "【主持人本轮指派（必须按此执行；与下方记忆摘录冲突时以本段为准）】\n" + host_line
            )
        chunks.extend(
            [
                f"【群聊讨论目标】\n{discussion_goal}",
                "【任务要求】\n直接进入本轮角色发言或可执行结果，不要先说明当前子任务；若信息不足，先提出最小补充问题（最多 2 个）。",
                str(dispatch.get("rendered") or "").strip(),
            ]
        )
        chunks.append("【输出要求】\n聚焦执行，不复读整段历史；不要在正文中指定下一位角色。")
        return "\n\n".join([chunk for chunk in chunks if chunk])

    return (host_next_action or "").strip() or _build_action_prompt_fallback(discussion_goal, context)


def _ensure_structured_action_prompt(
    prompt: str,
    discussion_goal: str,
    context: str,
    target_agent_name: str,
    *,
    host_round_instruction: Optional[str] = None,
) -> str:
    """Lightly validate expert action prompt structure and fill missing execution anchors."""
    _ = target_agent_name
    prompt_text = (prompt or "").strip()
    context_excerpt = _shorten_text(context, max_chars=1600)
    host_instruction = (host_round_instruction or "").strip()
    host_already_in_prompt = bool(
        host_instruction
        and (
            "【主持人本轮指派" in prompt_text
            or "主持人本轮指派" in prompt_text
            or (len(host_instruction) >= 20 and host_instruction[: min(80, len(host_instruction))] in prompt_text)
        )
    )
    has_goal = ("【群聊讨论目标】" in prompt_text) or ("讨论目标" in prompt_text)
    has_input = any(
        key in prompt_text
        for key in (
            "【最近讨论】",
            "【最近几轮讨论内容",
            "【输入依据】",
            "【上下文】",
            "【已知信息】",
            "【关键事实】",
        )
    )
    has_output_format = any(key in prompt_text for key in ("【输出格式】", "【输出要求】", "格式要求", "请按以下格式"))
    has_boundary = any(key in prompt_text for key in ("【边界条件】", "若信息不足", "不要", "禁止", "最多"))
    has_delivery = any(key in prompt_text for key in ("【交付标准】", "【完成标准】", "验收标准", "达标"))
    compact_len = len(_normalize_compare_text(prompt_text))
    missing_core = sum([not has_goal, not has_input, not has_output_format])

    host_anchor = ""
    if host_instruction and not host_already_in_prompt:
        host_anchor = (
            "【主持人本轮指派（必须按此执行；与下方模板冲突时以本段为准）】\n" + host_instruction + "\n\n"
        )

    if (not prompt_text) or compact_len < 120 or missing_core >= 2:
        parts: List[str] = []
        if host_anchor:
            parts.append(host_anchor.rstrip())
        parts.extend(
            [
                f"【群聊讨论目标】\n{discussion_goal}",
                f"【输入依据】\n{context_excerpt}",
                "【你本轮要完成的事情】\n"
                "1. 直接输出本轮角色发言或可执行结果，不要先说明你理解的子任务；\n"
                "2. 聚焦具体内容，不要泛泛解释；\n"
                "3. 只交付本轮结果，不要在正文中指定下一位角色。",
                "【输出格式】\n- 使用分点输出；\n- 每点尽量包含“动作 + 结果”；\n- 涉及链接/参数请显式写出。",
                "【边界条件】\n- 信息不足时，仅提出最多 2 个最小补充问题；\n- 不要复读整段历史，不要偏离讨论目标。",
                "【交付标准】\n- 结论清晰、可执行。",
            ]
        )
        return "\n\n".join(parts)

    parts = [prompt_text]
    if not has_goal:
        parts.append(f"【群聊讨论目标】\n{discussion_goal}")
    if not has_input:
        parts.append(f"【输入依据】\n{context_excerpt}")
    if not has_output_format:
        parts.append("【输出格式】\n请分点给出“动作 + 结果”，必要时给出链接/参数。")
    if not has_boundary:
        parts.append("【边界条件】\n若信息不足，仅提出最多 2 个最小补充问题；不要复读整段历史。")
    if not has_delivery:
        parts.append("【交付标准】\n输出应可直接执行，并能让下一位专家无歧义接力。")
    return "\n\n".join(parts)


def build_checked_expert_action_prompt(
    session_id: str,
    target_agent_name: str,
    discussion_goal: str,
    context: str,
    app_settings: Dict[str, Any],
    host_next_action: Optional[str] = None,
) -> str:
    raw = _build_action_prompt_with_memory(
        session_id=session_id,
        target_agent_name=target_agent_name,
        discussion_goal=discussion_goal,
        context=context,
        app_settings=app_settings,
        host_next_action=host_next_action,
    )
    return _ensure_structured_action_prompt(
        prompt=raw,
        discussion_goal=discussion_goal,
        context=context,
        target_agent_name=target_agent_name,
        host_round_instruction=host_next_action,
    )
