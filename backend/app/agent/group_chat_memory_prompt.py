"""Group-chat memory facts and expert action prompt assembly helpers."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from app.agent.group_context import (
    normalize_compare_text as _normalize_compare_text,
    shorten_text as _shorten_text,
)
from app.agent.group_memory_store import build_dispatch_context, upsert_facts, upsert_index_entries
from app.agent.platform_prompts import render_platform_prompt

logger = logging.getLogger(__name__)


def _build_action_prompt_fallback(discussion_goal: str, context: str) -> str:
    """Build the default expert action prompt when the host provides no instruction."""
    return render_platform_prompt(
        "expert.action.default.v1",
        {"discussion_goal": discussion_goal, "recent_history": context},
    )


def _host_instruction_block(host_instruction: str) -> str:
    """Render the optional host instruction block through the central prompt registry."""
    text = (host_instruction or "").strip()
    if not text:
        return ""
    return render_platform_prompt("expert.action.host_instruction.v1", {"host_instruction": text})


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


def _extract_index_paths_from_message(msg: Dict[str, Any]) -> List[str]:
    paths: List[str] = []
    skill_result = msg.get("skill_result") if isinstance(msg, dict) else None
    artifacts = skill_result.get("artifacts") if isinstance(skill_result, dict) else []
    for artifact in artifacts if isinstance(artifacts, list) else []:
        if not isinstance(artifact, dict):
            continue
        normalized = _normalize_workspace_index_path(artifact.get("path"))
        if normalized:
            paths.append(normalized)

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
    body = (msg or {}).get("message")
    content = str(body.get("content") if isinstance(body, dict) else "").strip()
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
        host_line = (host_next_action or "").strip()
        return render_platform_prompt(
            "expert.action.memory.v1",
            {
                "host_instruction_block": _host_instruction_block(host_line),
                "discussion_goal": discussion_goal,
                "memory_prompt": str(dispatch.get("rendered") or "").strip(),
            },
        )

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

    host_anchor = _host_instruction_block(host_instruction) if host_instruction and not host_already_in_prompt else ""

    if (not prompt_text) or compact_len < 120 or missing_core >= 2:
        return render_platform_prompt(
            "expert.action.structured_missing.v1",
            {
                "host_instruction_block": host_anchor,
                "discussion_goal": discussion_goal,
                "input_prompt": context_excerpt,
            },
        )

    parts = [prompt_text]
    if not has_goal:
        parts.append(f"【群聊讨论目标】\n{discussion_goal}")
    if not has_input:
        parts.append(f"【输入依据】\n{context_excerpt}")
    if not has_output_format:
        parts.append(render_platform_prompt("expert.action.output_format.v1", {}))
    if not has_boundary:
        parts.append(render_platform_prompt("expert.action.boundary.v1", {}))
    if not has_delivery:
        parts.append(render_platform_prompt("expert.action.delivery.v1", {}))
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
