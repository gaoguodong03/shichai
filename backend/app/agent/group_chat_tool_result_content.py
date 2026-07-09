from __future__ import annotations

from typing import Any, Dict, List


def problem_tool_result_content(tool_results: List[Dict[str, Any]]) -> str:
    for item in tool_results or []:
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
        if message:
            parts.append(message)
        for key, label in (("detail", "detail"), ("stderr", "stderr"), ("stdout", "stdout"), ("raw_output", "raw_output")):
            value = str(error_log.get(key) or "").strip()
            if value:
                parts.append(f"{label}:\n{value[:2400]}")
        if len(parts) == 1:
            parts.append(str(error_log.get("message") or "工具执行失败").strip())
        return "\n\n".join(part for part in parts if part).strip()
    return ""
