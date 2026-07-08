from __future__ import annotations

from typing import Any, Dict, List


def problem_tool_result_content(tool_results: List[Dict[str, Any]]) -> str:
    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("execution_status") or "").strip()
        if status not in {"failed", "needs_input"}:
            continue
        tool_call = item.get("tool_call") if isinstance(item.get("tool_call"), dict) else {}
        tool_name = str(tool_call.get("name") or "tool").strip()
        message = str(item.get("message") or "").strip()
        if status == "needs_input":
            fields = item.get("required_user_fields") if isinstance(item.get("required_user_fields"), list) else []
            field_lines = []
            for field in fields:
                if not isinstance(field, dict):
                    continue
                label = str(field.get("label") or field.get("key") or "").strip()
                reason = str(field.get("reason") or "").strip()
                if label or reason:
                    field_lines.append(f"- {label}: {reason}".rstrip(": "))
            parts = [f"当前步骤需要补充信息：{tool_name}"]
            if message:
                parts.append(message)
            if field_lines:
                parts.append("\n".join(field_lines))
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
