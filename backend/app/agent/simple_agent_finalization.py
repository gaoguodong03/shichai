from __future__ import annotations

import json
from typing import Any

from app.agent.messages import HumanMessage
from app.agent.platform_prompts import render_platform_prompt

def _json_loads_maybe(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _tool_facts_summary_block(tool_results: list[dict[str, Any]] | None) -> str:
    lines: list[str] = []
    for idx, item in enumerate(tool_results or [], start=1):
        if not isinstance(item, dict):
            continue
        tool_call = item.get("tool_call") if isinstance(item.get("tool_call"), dict) else {}
        tool_name = str(tool_call.get("name") or "tool").strip()
        kind = str(tool_call.get("kind") or "").strip()
        provider = str(tool_call.get("provider") or "").strip()
        status = str(item.get("execution_status") or "").strip()
        parts = [f"{idx}. tool={tool_name}"]
        if kind:
            parts.append(f"source={kind}")
        if provider:
            parts.append(f"provider={provider}")
        if status:
            parts.append(f"status={status}")
        lines.append("- " + "；".join(parts))
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        artifacts = output.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    continue
                artifact_type = str(artifact.get("type") or "").strip()
                artifact_name = str(artifact.get("name") or "").strip()
                artifact_path = str(artifact.get("path") or "").strip()
                if not artifact_path:
                    continue
                label = artifact_name or artifact_path
                suffix = f" ({artifact_type})" if artifact_type else ""
                lines.append(f"  - artifact={label}{suffix}: {artifact_path}")
    if not lines:
        return ""
    return (
        "\n\n## 结构化工具事实\n"
        "以下事实由平台从工具执行记录提取；原始工具 stdout/stderr/MCP 正文只属于运行日志，不要在最终回复中复述。\n"
        + "\n".join(lines)
    )


def _post_tool_decision_instruction(raw_outputs: list[str], *, tool_results: list[dict[str, Any]] | None = None) -> HumanMessage:
    return HumanMessage(
        content=render_platform_prompt(
            "agent.after_tool_result.decision.v1",
            {"summary_block": _tool_facts_summary_block(tool_results)},
        )
    )


def _tool_budget_finalization_instruction(*, tool_results: list[dict[str, Any]] | None = None) -> HumanMessage:
    return HumanMessage(
        content=render_platform_prompt(
            "agent.tool_budget.finalize.v1",
            {"summary_block": _tool_facts_summary_block(tool_results)},
        )
    )


def _tool_budget_structured_finalization_instruction(
    *,
    tool_results: list[dict[str, Any]] | None = None,
) -> HumanMessage:
    return HumanMessage(
        content=render_platform_prompt(
            "agent.tool_budget.structured_finalize.v1",
            {"summary_block": _tool_facts_summary_block(tool_results)},
        )
    )
