from __future__ import annotations

from typing import Any, Dict, List

from app.agent.structured_output_contracts import ArtifactRef


EMPTY_EXPERT_CONTENT = "模型没有返回可展示的文字内容。"
TOOL_SUMMARY_ONLY_CONTENT = "模型没有返回可展示的专家回复；本轮只有工具执行摘要。请重新执行本轮专家步骤。"
_DETERMINISTIC_TOOL_SUMMARY_PREFIXES = (
    "工具已执行完成。以下是本轮工具返回摘要：",
    "工具已执行完成，但本轮没有捕获到可展示的工具返回内容。",
)


def _is_deterministic_tool_summary(content: str) -> bool:
    text = str(content or "").strip()
    return any(text.startswith(prefix) for prefix in _DETERMINISTIC_TOOL_SUMMARY_PREFIXES)


def collect_artifacts(tool_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collect public artifact references emitted by tools into skill_result."""
    artifacts: list[dict[str, Any]] = []
    for result in tool_results or []:
        if not isinstance(result, dict):
            continue
        raw_artifacts = result.get("artifacts")
        if not isinstance(raw_artifacts, list):
            continue
        for item in raw_artifacts:
            if not isinstance(item, dict):
                continue
            public_ref = {
                "type": item.get("type"),
                "name": item.get("name"),
                "path": item.get("path"),
            }
            try:
                artifacts.append(ArtifactRef.model_validate(public_ref).model_dump())
            except Exception:
                continue
    return artifacts


def _minimal_artifact_delivery_content(artifacts: List[Dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in artifacts or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("path") or "").strip()
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        label = name or path
        lines.append(f"- {label}：{path}")
    if not lines:
        return ""
    return "已生成工作区产物：\n" + "\n".join(lines)


def build_expert_skill_result(*, content: str, tool_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build an expert turn skill_result from model text and structured tool results."""
    from app.agent.group_chat_skill_session import skill_result_from_content

    visible_content = str(content or "").strip() or EMPTY_EXPERT_CONTENT
    has_failed = any(item.get("execution_status") == "failed" for item in tool_results if isinstance(item, dict))
    has_blocked = any(item.get("execution_status") == "blocked" for item in tool_results if isinstance(item, dict))
    status = "failed" if has_failed else "blocked" if has_blocked else "succeeded"
    artifacts = collect_artifacts(tool_results)
    result = skill_result_from_content(
        status=status,
        content=visible_content,
        artifacts=artifacts,
        tool_results=tool_results,
    )
    result_content = str(result.get("content") or "").strip()
    if tool_results and _is_deterministic_tool_summary(visible_content) and result_content == visible_content:
        artifact_delivery = _minimal_artifact_delivery_content(artifacts)
        if status == "succeeded" and artifact_delivery:
            result["content"] = artifact_delivery
            result["next_action"] = {
                "handoff": "host",
                "resume": "none",
                "reason": "stage_completed",
                "instruction": artifact_delivery,
            }
            return result
        result["execution_status"] = "failed"
        result["content"] = TOOL_SUMMARY_ONLY_CONTENT
        result["next_action"] = {
            "handoff": "user",
            "resume": "same_skill",
            "reason": "protocol_error",
            "instruction": "模型没有返回可展示的专家回复；请重新执行本轮专家步骤。",
        }
    return result


def problem_tool_result_content(tool_results: List[Dict[str, Any]]) -> str:
    """Return a user-facing failure summary without exposing execution logs."""
    problem_items = [
        item
        for item in (tool_results or [])
        if isinstance(item, dict) and str(item.get("execution_status") or "").strip() in {"failed", "blocked"}
    ]
    problem_items.sort(key=lambda item: 0 if str(item.get("execution_status") or "").strip() == "failed" else 1)
    for item in problem_items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("execution_status") or "").strip()
        if status not in {"failed", "blocked"}:
            continue
        tool_call = item.get("tool_call") if isinstance(item.get("tool_call"), dict) else {}
        tool_name = str(tool_call.get("name") or "tool").strip()
        message = str(item.get("message") or "").strip()
        if status == "blocked":
            parts = [f"当前步骤需要补充信息：{tool_name}"]
            if message:
                parts.append(message)
            return "\n\n".join(parts).strip()
        error_log = item.get("error_log") if isinstance(item.get("error_log"), dict) else {}
        parts = [f"当前步骤失败：{tool_name}"]
        failure_message = message or str(error_log.get("message") or "").strip()
        if failure_message:
            parts.append(failure_message)
        if len(parts) == 1:
            parts.append("工具执行失败")
        return "\n\n".join(part for part in parts if part).strip()
    return ""
