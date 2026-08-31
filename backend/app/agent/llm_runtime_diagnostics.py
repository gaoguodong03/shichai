"""Canonical LLM fault taxonomy and per-request call diagnostics."""
from __future__ import annotations

import contextlib
import contextvars
import time
from datetime import datetime, timezone
from typing import Any, Iterator


LLM_SERVICE_NOT_CONFIGURED = "LLM_SERVICE_NOT_CONFIGURED"
LLM_SERVICE_CONFIG_INVALID = "LLM_SERVICE_CONFIG_INVALID"
LLM_SERVICE_UNREACHABLE = "LLM_SERVICE_UNREACHABLE"
LLM_RESPONSE_INVALID = "LLM_RESPONSE_INVALID"
LLM_SERVICE_ERROR = "LLM_SERVICE_ERROR"


LLM_FAULT_DEFINITIONS: dict[str, dict[str, str]] = {
    LLM_SERVICE_NOT_CONFIGURED: {
        "name": "大模型服务未配置",
        "description": "当前主持人或专家引用的模型、密钥变量或模型服务尚未完成配置。",
        "action": "检查资源中心的模型引用、api_key_env，并在设置中配置对应环境变量。",
    },
    LLM_SERVICE_CONFIG_INVALID: {
        "name": "大模型服务配置错误",
        "description": "模型服务拒绝了当前配置，常见原因是密钥、模型名称、地址或请求参数错误。",
        "action": "核对 API Key、模型名称、Base URL 和模型参数后重试。",
    },
    LLM_SERVICE_UNREACHABLE: {
        "name": "大模型服务无法连接",
        "description": "平台未能连接到模型服务，或模型服务在超时前没有响应。",
        "action": "检查网络、Base URL 和服务状态；若为临时故障，请稍后重试。",
    },
    LLM_RESPONSE_INVALID: {
        "name": "大模型响应不正确",
        "description": "模型服务已响应，但返回为空、缺少必要字段或未通过本次任务的结构校验。",
        "action": "重试本轮；若持续出现，请检查模型是否支持当前 JSON/工具调用协议。",
    },
    LLM_SERVICE_ERROR: {
        "name": "大模型服务异常",
        "description": "模型调用失败，但未能归入更具体的标准故障类型。",
        "action": "查看日志中的异常摘要和模型服务状态后重试。",
    },
}


_collector_var: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "llm_call_collector",
    default=None,
)
_operation_var: contextvars.ContextVar[str] = contextvars.ContextVar("llm_call_operation", default="")
_default_operation_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "llm_call_default_operation",
    default="llm_completion",
)


def llm_fault_definition(code: str) -> dict[str, str] | None:
    definition = LLM_FAULT_DEFINITIONS.get(str(code or "").strip())
    return dict(definition) if definition else None


def _exception_text(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {exc}".strip().lower()


def classify_llm_failure(exc: BaseException) -> str | None:
    """Map provider/LiteLLM/protocol exceptions to one stable public code."""
    explicit_code = str(getattr(exc, "llm_fault_code", "") or "").strip()
    if explicit_code in LLM_FAULT_DEFINITIONS:
        return explicit_code

    text = _exception_text(exc)
    class_name = exc.__class__.__name__.lower()
    module_name = str(exc.__class__.__module__ or "").lower()
    status_code = getattr(exc, "status_code", None)

    if class_name in {"structuredoutputprotocolerror", "expertfinalstateprotocolerror"}:
        return LLM_RESPONSE_INVALID
    if any(
        marker in text
        for marker in (
            "模型配置不存在",
            "模型配置缺少 api_key_env",
            "缺少环境变量",
            "缺少 api key",
            "missing api key",
            "api key not set",
        )
    ):
        return LLM_SERVICE_NOT_CONFIGURED
    if status_code in {401, 403, 404, 422} or any(
        marker in text
        for marker in (
            "authenticationerror",
            "permissiondenied",
            "unauthorized",
            "forbidden",
            "invalid api key",
            "incorrect api key",
            "invalid_api_key",
            "model not found",
            "notfounderror",
            "badrequesterror",
            "invalid base url",
            "unsupported model",
        )
    ):
        return LLM_SERVICE_CONFIG_INVALID
    network_markers = (
        "apiconnectionerror",
        "connecterror",
        "connection error",
        "connection refused",
        "connection reset",
        "network is unreachable",
        "service unavailable",
        "gateway timeout",
        "timed out",
        "timeout",
        "dns",
    )
    is_provider_exception = any(name in module_name for name in ("litellm", "openai", "anthropic", "httpx", "httpcore"))
    is_transport_exception = isinstance(exc, (TimeoutError, ConnectionError)) or class_name in {
        "apiconnectionerror",
        "connecterror",
        "connecttimeout",
        "readtimeout",
        "apitimeouterror",
        "timeout",
    }
    if status_code in {408, 429, 500, 502, 503, 504} or (
        (is_provider_exception or is_transport_exception)
        and any(marker in text for marker in network_markers)
    ):
        return LLM_SERVICE_UNREACHABLE
    if any(
        marker in text
        for marker in (
            "no choices",
            "empty response",
            "no response from",
            "invalid json",
            "malformed response",
        )
    ):
        return LLM_RESPONSE_INVALID
    if "litellm" in module_name or "openai" in module_name or "anthropic" in module_name:
        return LLM_SERVICE_ERROR
    return None


@contextlib.contextmanager
def collect_llm_calls(default_operation: str) -> Iterator[list[dict[str, Any]]]:
    """Collect outbound LLM call facts so the caller can link them to a message."""
    calls: list[dict[str, Any]] = []
    collector_token = _collector_var.set(calls)
    operation_token = _default_operation_var.set(str(default_operation or "llm_completion").strip())
    try:
        yield calls
    finally:
        _default_operation_var.reset(operation_token)
        _collector_var.reset(collector_token)


@contextlib.contextmanager
def llm_call_operation(operation: str) -> Iterator[None]:
    token = _operation_var.set(str(operation or "").strip())
    try:
        yield
    finally:
        _operation_var.reset(token)


def current_llm_operation() -> str:
    return _operation_var.get() or _default_operation_var.get() or "llm_completion"


def _runtime_timestamp() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d%H%M%S") + f"{dt.microsecond // 10000:02d}"


def start_llm_call(
    *,
    method: str,
    model: str,
    provider_base_url: str,
    input_metrics: dict[str, Any],
) -> tuple[dict[str, Any] | None, float]:
    collector = _collector_var.get()
    if collector is None:
        return None, time.perf_counter()
    record: dict[str, Any] = {
        "operation": current_llm_operation(),
        "method": str(method or "").strip(),
        "model": str(model or "").strip(),
        "provider_base_url": str(provider_base_url or "").strip(),
        "created_at": _runtime_timestamp(),
        "status": "pending",
        "input_metrics": dict(input_metrics or {}),
    }
    collector.append(record)
    return record, time.perf_counter()


def finish_llm_call(
    record: dict[str, Any] | None,
    started_at: float,
    *,
    response_metadata: dict[str, Any] | None = None,
    output_metrics: dict[str, Any] | None = None,
    output_content: str = "",
) -> None:
    if record is None:
        return
    record.update(
        {
            "status": "succeeded",
            "duration_ms": max(0, round((time.perf_counter() - started_at) * 1000)),
            "response_metadata": dict(response_metadata or {}),
            "output_metrics": dict(output_metrics or {}),
            "output_content": str(output_content or ""),
        }
    )


def fail_llm_call(record: dict[str, Any] | None, started_at: float, exc: BaseException) -> None:
    if record is None:
        return
    code = classify_llm_failure(exc) or LLM_SERVICE_ERROR
    record.update(
        {
            "status": "failed",
            "duration_ms": max(0, round((time.perf_counter() - started_at) * 1000)),
            "error_code": code,
            "error_type": exc.__class__.__name__,
            "error_summary": str(exc) or exc.__class__.__name__,
        }
    )


def mark_latest_llm_call_failed(exc: BaseException) -> None:
    """Mark a received-but-invalid response as a failed LLM call."""
    collector = _collector_var.get()
    if not collector:
        return
    record = collector[-1]
    record["status"] = "failed"
    record["error_code"] = classify_llm_failure(exc) or LLM_RESPONSE_INVALID
    record["error_type"] = exc.__class__.__name__
    record["error_summary"] = str(exc) or exc.__class__.__name__
