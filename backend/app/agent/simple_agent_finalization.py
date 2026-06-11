from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def _extract_text_content(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return str(content or "")


def _env_truthy(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


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


def _successful_tool_payload(tool_out: dict[str, Any]) -> dict[str, Any] | None:
    raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out, dict) else None
    if not isinstance(raw_outputs, list):
        return None
    for raw in reversed(raw_outputs):
        payload = _json_loads_maybe(raw)
        if not isinstance(payload, dict):
            continue
        ok = payload.get("ok")
        returncode = payload.get("returncode", payload.get("exit_code"))
        if ok is True or returncode == 0:
            return payload
    return None


def _payload_requests_final(payload: dict[str, Any]) -> bool:
    for key in ("final", "done", "skill_session_end", "session_end"):
        value = payload.get(key)
        if value is True:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on", "done", "final"}:
            return True
    stdout_payload = _json_loads_maybe(payload.get("stdout"))
    if isinstance(stdout_payload, dict):
        for key in ("final", "done", "skill_session_end", "session_end"):
            value = stdout_payload.get(key)
            if value is True:
                return True
            if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on", "done", "final"}:
                return True
    return False


def _has_run_skill_script_call(tool_out: dict[str, Any]) -> bool:
    calls = tool_out.get("tool_calls") if isinstance(tool_out, dict) else None
    if not isinstance(calls, list):
        return False
    for call in calls:
        if isinstance(call, dict) and str(call.get("tool") or call.get("name") or "").startswith("run_skill_script_"):
            return True
    return False


def _large_script_success_min_raw_chars() -> int:
    raw = (os.getenv("SKILL_AGENT_LARGE_SCRIPT_SUCCESS_DIRECT_FINAL_MIN_CHARS") or "8000").strip()
    try:
        return max(0, int(raw))
    except Exception:
        return 8000


def _compact_multiline_text(text: str, *, limit: int = 6000) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    head_len = max(1000, limit // 2)
    tail_len = max(1000, limit - head_len - 80)
    return (
        text[:head_len].rstrip()
        + "\n\n...（中间内容已省略）...\n\n"
        + text[-tail_len:].lstrip()
    )[:limit].rstrip()


def _large_run_skill_script_success_direct_final_message(tool_out: dict[str, Any]) -> AIMessage | None:
    if not _env_truthy("SKILL_AGENT_DIRECT_FINAL_ON_LARGE_SCRIPT_SUCCESS", "1"):
        return None
    if not _has_run_skill_script_call(tool_out):
        return None
    raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out, dict) else None
    if not isinstance(raw_outputs, list):
        return None
    if sum(len(str(item or "")) for item in raw_outputs) < _large_script_success_min_raw_chars():
        return None
    payload = _successful_tool_payload(tool_out)
    if payload is None:
        return None
    stdout = str(payload.get("stdout") or "").strip()
    stderr = str(payload.get("stderr") or "").strip()
    script = str(payload.get("script") or "").strip()
    if not stdout and not stderr:
        return None

    parts = ["脚本执行成功。"]
    if script:
        parts.append(f"脚本：{script}")
    if stdout:
        parsed_stdout = _json_loads_maybe(stdout)
        if isinstance(parsed_stdout, (dict, list)):
            stdout = json.dumps(parsed_stdout, ensure_ascii=False, indent=2)
        parts.append(_compact_multiline_text(stdout))
    elif stderr:
        parts.append("stdout 为空，以下是 stderr 摘要：")
        parts.append(_compact_multiline_text(stderr, limit=2400))
    return AIMessage(content="\n\n".join(part for part in parts if part).strip())


def _script_dependency_direct_final_message(tool_out: dict[str, Any]) -> AIMessage | None:
    raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out, dict) else None
    if not isinstance(raw_outputs, list):
        return None
    message = _script_dependency_fallback_summary([str(raw or "") for raw in raw_outputs])
    if not message:
        return None
    return AIMessage(content=message)


def _playwright_runtime_failure_message(tool_out: dict[str, Any]) -> AIMessage | None:
    raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out, dict) else None
    if not isinstance(raw_outputs, list):
        return None
    combined = "\n".join(str(raw or "") for raw in raw_outputs)
    if not combined.strip():
        return None

    lower = combined.lower()
    missing_package = bool(
        re.search(r"no module named ['\"](?:playwright|patchright)['\"]", combined, re.I)
        or re.search(r"cannot find module ['\"](?:playwright|@playwright/test|patchright)['\"]", combined, re.I)
        or re.search(r"modulenotfounderror:.*(?:playwright|patchright)", combined, re.I | re.S)
    )
    missing_browser = bool(
        (
            "executable doesn't exist" in lower
            and ("playwright" in lower or "chromium" in lower or "ms-playwright" in lower)
        )
        or "looks like playwright was just installed or updated" in lower
        or ("playwright install" in lower and ("chromium" in lower or "browser" in lower))
    )
    if not missing_package and not missing_browser:
        return None

    reason = "未安装 playwright/patchright 依赖" if missing_package else "缺少 Playwright 浏览器可执行文件/Chromium 缓存"
    detail = _compact_multiline_text(combined, limit=1200)
    content = (
        f"Playwright 运行环境不可用：{reason}，本轮爬取没有成功。\n\n"
        "请先在沙箱设置中切换到 Playwright 版并重建/预热沙箱；如果使用用户 requirements，"
        "确认其中包含 playwright 或 patchright。若错误是缺少 Chromium 浏览器缓存，请使用内置 Playwright 沙箱镜像，"
        "或启用浏览器安装后重建沙箱。\n\n"
        f"错误摘要：\n{detail}"
    )
    return AIMessage(content=content)


def _should_force_final_after_tool_success(system_prompt: str, tool_out: dict[str, Any]) -> bool:
    if not _env_truthy("SKILL_AGENT_FORCE_FINAL_ON_SUCCESS", "1"):
        return False
    payload = _successful_tool_payload(tool_out)
    if payload is None:
        return False
    if _payload_requests_final(payload):
        return True
    return _env_truthy("SKILL_AGENT_FORCE_FINAL_ON_ANY_SCRIPT_SUCCESS", "0") and _has_run_skill_script_call(tool_out)


def _final_synthesis_instruction(system_prompt: str, tool_out: dict[str, Any]) -> HumanMessage:
    payload = _successful_tool_payload(tool_out) or {}
    stdout = str(payload.get("stdout") or "").strip()
    stderr = str(payload.get("stderr") or "").strip()
    message = str(payload.get("message") or "工具执行成功。").strip() or "工具执行成功。"
    parts = [
        "工具已经执行成功。请严格遵循上方专家与技能系统提示词，基于工具结果输出最终自然语言答复。",
        "不要再次调用任何工具；不要说还需要执行脚本；stdout/stderr 是工具返回字段，不是文件路径。",
        f"工具状态：{message}",
    ]
    if stdout:
        parsed_stdout = _json_loads_maybe(stdout)
        if isinstance(parsed_stdout, (dict, list)):
            stdout = json.dumps(parsed_stdout, ensure_ascii=False, indent=2)
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    return HumanMessage(content="\n\n".join(parts))


def _raw_tool_outputs_summary(raw_outputs: list[str], *, limit: int = 2000) -> str:
    snippets: list[str] = []
    for raw in raw_outputs or []:
        text = str(raw or "").strip()
        if not text:
            continue
        payload = _json_loads_maybe(text)
        if isinstance(payload, dict):
            for key in ("summary", "answer", "content", "text", "result", "results", "output", "stdout", "message"):
                value = payload.get(key)
                if value in (None, ""):
                    continue
                if isinstance(value, str):
                    nested = _json_loads_maybe(value)
                    if isinstance(nested, (dict, list)):
                        value = nested
                if isinstance(value, (dict, list)):
                    text = json.dumps(value, ensure_ascii=False, indent=2)
                else:
                    text = str(value)
                break
            else:
                text = json.dumps(payload, ensure_ascii=False, indent=2)
        elif isinstance(payload, list):
            text = json.dumps(payload, ensure_ascii=False, indent=2)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            snippets.append("\n".join(lines[:12]))
        if sum(len(s) for s in snippets) >= limit:
            break
    summary = "\n\n".join(snippets).strip()
    return summary[:limit].rstrip()


def _markdown_code_block(text: str, info: str = "text") -> str:
    max_run = max((len(match.group(0)) for match in re.finditer(r"`{3,}", text or "")), default=2)
    fence = "`" * max(3, max_run + 1)
    return f"{fence}{info}\n{text.rstrip()}\n{fence}"


def _post_tool_synthesis_instruction(raw_outputs: list[str]) -> HumanMessage:
    parts = [
        "工具已经执行完成。请基于最近的工具返回，直接给用户一段可展示的最终答复。",
        "不要再次调用任何工具；如果工具结果不足以回答，请明确说明已获得的信息和缺口。",
        "如果 read_file 返回文件不存在，但本轮任务或最近讨论中已经包含所需内容，不要把内部读文件失败作为最终答复，直接基于已有上下文完成发言。",
    ]
    summary = _raw_tool_outputs_summary(raw_outputs, limit=2400)
    if summary:
        parts.append(f"工具返回摘要：\n{summary}")
    return HumanMessage(content="\n\n".join(parts))


def _deterministic_tool_fallback_message(raw_outputs: list[str]) -> AIMessage:
    dependency_message = _script_dependency_fallback_summary(raw_outputs)
    if dependency_message:
        return AIMessage(content=dependency_message)
    summary = _raw_tool_outputs_summary(raw_outputs, limit=2400)
    if summary:
        content = (
            "工具已执行完成。以下是本轮工具返回摘要："
            f"\n\n{_markdown_code_block(summary)}"
        )
    else:
        content = "工具已执行完成，但本轮没有捕获到可展示的工具返回内容。"
    return AIMessage(content=content)


def _script_dependency_fallback_summary(raw_outputs: list[str]) -> str:
    def _iter_json_objects(text: str):
        decoder = json.JSONDecoder()
        pos = 0
        while pos < len(text):
            start = text.find("{", pos)
            if start < 0:
                break
            try:
                obj, end = decoder.raw_decode(text[start:])
            except Exception:
                pos = start + 1
                continue
            if isinstance(obj, dict):
                yield obj
            pos = start + max(end, 1)

    def _candidate_texts(payload: dict[str, Any]) -> list[str]:
        out: list[str] = []
        for key in ("stderr", "stdout", "message", "error", "gateway_error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value)
        return out

    def _dependency_message(payload: dict[str, Any]) -> str | None:
        if payload.get("code") != "package_not_installed":
            return None
        package = str(payload.get("package") or "").strip()
        if not package:
            return None
        return f"没装这个依赖：{package}"

    for raw in raw_outputs or []:
        payload = _json_loads_maybe(raw)
        if isinstance(payload, dict):
            msg = _dependency_message(payload)
            if msg:
                return msg
            for text in _candidate_texts(payload):
                nested = _json_loads_maybe(text)
                if isinstance(nested, dict):
                    msg = _dependency_message(nested)
                    if msg:
                        return msg
                for obj in _iter_json_objects(text):
                    msg = _dependency_message(obj)
                    if msg:
                        return msg
        for obj in _iter_json_objects(str(raw or "")):
            msg = _dependency_message(obj)
            if msg:
                return msg
    return ""


def _is_llm_failure_message(message: BaseMessage) -> bool:
    text = _extract_text_content(message).strip()
    return text.startswith("抱歉，模型响应失败：") or text.startswith("抱歉，模型响应超时")


def _fallback_after_llm_failure_message(raw_outputs: list[str], response: BaseMessage) -> AIMessage | None:
    if not raw_outputs or not _is_llm_failure_message(response):
        return None
    return _deterministic_tool_fallback_message(raw_outputs)
