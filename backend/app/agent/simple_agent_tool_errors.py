from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from app.agent.simple_agent_finalization import (
    _align_final_response_with_written_workspace_paths,
    _compact_multiline_text,
    _deterministic_tool_fallback_message,
    _json_loads_maybe,
)
from app.agent.simple_agent_introspection import _WRAPPED_USER_CONTEXT_MARKERS, _section_text
from app.agent.simple_agent_messages import _coerce_text_tool_calls_to_structured, _last_user_text
from app.agent.simple_agent_tool_ids import _tool_call_args


_TERMINAL_TOOL_FAILURE_MARKERS = (
    "OpenSandbox lifecycle API 连接失败",
    "OpenSandbox host_path 挂载失败",
    "Docker Desktop File Sharing",
)

_RECOVERABLE_COORDINATION_READ_PATHS: frozenset[str] = frozenset()


def _terminal_tool_failure_message(tool_out: dict[str, Any]) -> AIMessage | None:
    raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out, dict) else None
    if not isinstance(raw_outputs, list):
        return None
    combined = "\n".join(str(x or "") for x in raw_outputs)
    if not combined.strip():
        return None
    marker = next((item for item in _TERMINAL_TOOL_FAILURE_MARKERS if item in combined), "")
    if not marker:
        return None
    if "lifecycle API" in marker:
        detail = (
            "OpenSandbox 服务当前不可达，工具无法启动沙箱。请先确认 1Panel 编排里的 opensandbox-server 已启动，"
            "并检查 OPENSANDBOX_DOMAIN/OPENSANDBOX_HOST_PORT 是否是应用容器可访问的地址。"
            "本地 conda 调试时，需要显式启动本地 OpenSandbox 服务或配置 OPENSANDBOX_COMPOSE_FILE 指向本地 compose。"
        )
    else:
        detail = (
            "OpenSandbox 的 host_path 挂载不可用。远程 1Panel 部署请确认 SANDBOX_HOST_PATH_MAP 和 "
            "OPENSANDBOX_ALLOWED_HOST_PATHS 指向 Docker daemon 可见的宿主路径；本地 Docker Desktop 调试请检查 File Sharing。"
        )
    return AIMessage(content=f"工具运行环境不可用：{detail}")


def _normalize_workspace_path_for_compare(path: Any) -> str:
    text = str(path or "").strip().replace("\\", "/").strip("/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


def _last_group_current_user_section(messages: list[BaseMessage]) -> str:
    text = _last_user_text(messages)
    if not text or not any(marker in text for marker in _WRAPPED_USER_CONTEXT_MARKERS):
        return ""
    current = _section_text(text, "【本轮用户输入】")
    if current and current not in {"（无）", "(无)"}:
        return current
    return ""


def _tool_call_display_name(tool_call: Any) -> str:
    if isinstance(tool_call, dict):
        return str(tool_call.get("tool") or tool_call.get("name") or "tool").strip() or "tool"
    return str(getattr(tool_call, "tool", None) or getattr(tool_call, "name", None) or "tool").strip() or "tool"


def _tool_call_display_path(tool_call: Any) -> str:
    args = _tool_call_args(tool_call)
    for key in ("path", "script_path", "__arg1"):
        value = args.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _tool_call_error_label(tool_out: dict[str, Any], idx: int) -> str:
    calls = tool_out.get("tool_calls") if isinstance(tool_out, dict) else None
    call: Any = None
    if isinstance(calls, list) and calls:
        call = calls[min(idx, len(calls) - 1)]
    name = _tool_call_display_name(call) if call is not None else "tool"
    path = _tool_call_display_path(call) if call is not None else ""
    return f"{name}: {path}" if path else name


def _is_recoverable_coordination_tool_error(
    tool_out: dict[str, Any],
    idx: int,
    text: str,
    messages: list[BaseMessage] | None = None,
) -> bool:
    if "文件不存在" not in text:
        return False
    calls = tool_out.get("tool_calls") if isinstance(tool_out, dict) else None
    if not isinstance(calls, list) or not calls:
        return False
    call = calls[min(idx, len(calls) - 1)]
    if _tool_call_display_name(call) != "read_file":
        return False
    path = _normalize_workspace_path_for_compare(_tool_call_display_path(call))
    if path in _RECOVERABLE_COORDINATION_READ_PATHS:
        return True
    if not path or messages is None:
        return False
    last_user = _last_user_text(messages)
    if not last_user or not any(marker in last_user for marker in _WRAPPED_USER_CONTEXT_MARKERS):
        return False
    current_user = _last_group_current_user_section(messages)
    if path in current_user or path.split("/")[-1] in current_user:
        return False
    return True


def _error_text_from_raw_tool_output(raw: Any) -> str | None:
    payload = _json_loads_maybe(raw)
    if isinstance(payload, dict):
        returncode = payload.get("returncode", payload.get("exit_code"))
        is_error = payload.get("ok") is False or (isinstance(returncode, int) and returncode != 0)
        if not is_error:
            return None
        message = str(payload.get("message") or payload.get("error") or payload.get("code") or "工具执行失败").strip()
        parts = [message]
        for key in ("stderr", "stdout", "gateway_error"):
            value = str(payload.get(key) or "").strip()
            if value:
                parts.append(f"{key}:\n{_compact_multiline_text(value, limit=1800)}")
        return "\n\n".join(parts)

    text = str(raw or "").strip()
    if not text:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("错误："):
            return stripped
    return None


def _tool_error_direct_final_message(
    tool_out: dict[str, Any],
    messages: list[BaseMessage] | None = None,
    tool_attempt_debug: list[dict[str, Any]] | None = None,
) -> AIMessage | None:
    raw_outputs = tool_out.get("tool_raw_outputs") if isinstance(tool_out, dict) else None
    if not isinstance(raw_outputs, list):
        return None
    for idx, raw in enumerate(raw_outputs):
        label = _tool_call_error_label(tool_out, idx)
        if label.startswith("run_skill_script"):
            continue
        error_text = _error_text_from_raw_tool_output(raw)
        if not error_text:
            continue
        if _is_recoverable_coordination_tool_error(tool_out, idx, error_text, messages):
            if tool_attempt_debug is not None:
                tool_attempt_debug.append(
                    {
                        "source": "recoverable_context_read_file_missing",
                        "matched": True,
                        "label": label,
                    }
                )
            continue
        return AIMessage(content=f"当前步骤失败：{label}\n\n{_compact_multiline_text(error_text, limit=2400)}")
    return None


def _final_response_or_tool_fallback(
    response: BaseMessage,
    raw_outputs: list[str],
    tool_attempt_debug: list[dict[str, Any]],
) -> BaseMessage:
    _, debug = _coerce_text_tool_calls_to_structured(response)
    if debug is None:
        return _align_final_response_with_written_workspace_paths(response, raw_outputs)
    debug = {**debug, "source": "dsml_text_tool_calls_final_fallback"}
    tool_attempt_debug.append(debug)
    return _align_final_response_with_written_workspace_paths(
        _deterministic_tool_fallback_message(raw_outputs),
        raw_outputs,
    )
