"""Parameter Mapper: model config → LiteLLM completion kwargs.

Isolates LiteLLM's call shape from persisted model configuration so Agent /
frontend / config files never depend on LiteLLM-specific field names.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Mapping, MutableMapping, Optional
from urllib.parse import urlparse

# Connection / identity fields are never forwarded as completion body params.
_CONNECTION_KEYS = frozenset(
    {
        "name",
        "provider",
        "model",
        "api_key",
        "api_key_env",
        "api_key_set",
        "base_url",
        "litellm_model",
        "label",
        "id",
        "extra_body",
        "default_llm",
        # Legacy flat vendor fields (migrated into extra_body when present).
        "enable_thinking",
        "thinking_budget",
        "thinking",
        "do_sample",
        "top_k",
        "gemini_thinking_level",
        "max_completion_tokens",
        "client_kwargs",
        "disabled_params",
    }
)

# Common completion params stored as top-level model-config fields.
_COMMON_PARAM_ALIASES: Dict[str, str] = {
    "temperature": "temperature",
    "top_p": "top_p",
    "max_tokens": "max_tokens",
    "presence_penalty": "presence_penalty",
    "frequency_penalty": "frequency_penalty",
    "seed": "seed",
    "max_retries": "num_retries",
}


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_openai_base_url(base_url: Optional[str]) -> Optional[str]:
    """Normalize an OpenAI-compatible API base URL when one is configured."""
    if base_url is None:
        return None
    value = str(base_url).strip().rstrip("/")
    if not value:
        return None

    suffix = "/chat/completions"
    if value.endswith(suffix):
        value = value[: -len(suffix)].rstrip("/")

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "LLM base_url 必须是完整的 http(s) API 基础地址，例如 "
            "https://dashscope.aliyuncs.com/compatible-mode/v1 或 https://jeniya.top/v1；"
            f"当前值为 {base_url!r}。不要只填写 /v1 或 /v1/chat/completions。"
        )
    if parsed.scheme == "http" and parsed.netloc.lower() == "jeniya.top":
        value = "https://" + value[len("http://") :]
    return value


def resolve_litellm_model_id(config: Mapping[str, Any]) -> str:
    """Build LiteLLM model id from config.provider / model / litellm_model only."""
    override = str(config.get("litellm_model") or "").strip()
    if override:
        return override

    model_name = str(config.get("model") or "").strip() or "unknown"
    if "/" in model_name:
        return model_name

    provider = str(config.get("provider") or "").strip()
    if provider:
        return f"{provider}/{model_name}"

    # OpenAI-compatible gateways (custom base_url) default to openai/* routing.
    return f"openai/{model_name}"


def resolve_extra_body(config: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the model-owned extra_body.

    Uses ``extra_body`` as the source of truth. Legacy flat vendor keys that
    older configs stored at the top level are folded in only when the same key
    is absent from ``extra_body`` (migration, not provider inference).
    """
    raw = config.get("extra_body")
    extra: Dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}

    if "enable_thinking" not in extra and isinstance(config.get("enable_thinking"), bool):
        extra["enable_thinking"] = config["enable_thinking"]
    if "thinking_budget" not in extra:
        budget = _coerce_optional_int(config.get("thinking_budget"))
        if budget is not None:
            extra["thinking_budget"] = budget
    if "thinking" not in extra and "thinking" in config:
        thinking = config.get("thinking")
        if isinstance(thinking, bool):
            extra["thinking"] = {"type": "enabled" if thinking else "disabled"}
        elif isinstance(thinking, dict):
            extra["thinking"] = dict(thinking)
    if "do_sample" not in extra and isinstance(config.get("do_sample"), bool):
        extra["do_sample"] = config["do_sample"]
    if "top_k" not in extra and "topK" not in extra:
        top_k = _coerce_optional_int(config.get("top_k"))
        if top_k is not None:
            extra["top_k"] = top_k
    if "thinkingConfig" not in extra:
        level = str(config.get("gemini_thinking_level") or "").strip().lower()
        if level:
            extra["thinkingConfig"] = {"thinkingLevel": level}

    return extra


def thinking_mode_enabled(config: Mapping[str, Any]) -> bool:
    """Detect thinking/reasoning mode from the model config's extra_body only."""
    extra = resolve_extra_body(config)
    if extra.get("enable_thinking") is True:
        return True
    thinking = extra.get("thinking")
    if isinstance(thinking, dict) and str(thinking.get("type") or "").lower() == "enabled":
        return True
    if extra.get("thinkingConfig"):
        return True
    return False


def map_model_config_to_litellm_kwargs(
    config: Mapping[str, Any],
    *,
    api_key: str,
    messages: Any,
    tools: Optional[list[Any]] = None,
    tool_choice: Any = None,
    runtime_overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Convert a persisted model config into kwargs for ``litellm.acompletion``."""
    cfg = dict(config or {})
    base_url = normalize_openai_base_url(cfg.get("base_url"))

    # HTTP timeout is runtime/env only — not a user-facing model common param.
    timeout = _coerce_optional_int(os.getenv("LLM_REQUEST_TIMEOUT")) or _coerce_optional_int(
        os.getenv("QWEN_REQUEST_TIMEOUT")
    )
    if timeout is None:
        timeout = 60
    timeout_max = _coerce_optional_int(os.getenv("LLM_REQUEST_TIMEOUT_MAX")) or _coerce_optional_int(
        os.getenv("QWEN_REQUEST_TIMEOUT_MAX")
    )
    if timeout_max and timeout_max > 0:
        timeout = min(timeout, timeout_max)

    max_retries = _coerce_optional_int(cfg.get("max_retries"))
    if max_retries is None:
        max_retries = _coerce_optional_int(os.getenv("LLM_MAX_RETRIES")) or _coerce_optional_int(
            os.getenv("QWEN_MAX_RETRIES")
        )
    if max_retries is None:
        max_retries = 0

    kwargs: Dict[str, Any] = {
        "model": resolve_litellm_model_id(cfg),
        "messages": messages,
        "api_key": api_key,
        "timeout": timeout,
        "num_retries": max_retries,
    }
    if base_url:
        kwargs["api_base"] = base_url

    for src_key, dest_key in _COMMON_PARAM_ALIASES.items():
        if src_key == "max_retries":
            continue
        if src_key not in cfg:
            continue
        raw = cfg.get(src_key)
        if src_key in {"max_tokens", "seed"}:
            coerced_i = _coerce_optional_int(raw)
            if coerced_i is not None:
                kwargs[dest_key] = coerced_i
            continue
        coerced_f = _coerce_optional_float(raw)
        if coerced_f is not None:
            kwargs[dest_key] = coerced_f

    if "max_tokens" not in kwargs:
        legacy_max = _coerce_optional_int(cfg.get("max_completion_tokens"))
        if legacy_max is None:
            legacy_max = _coerce_optional_int(os.getenv("LLM_MAX_TOKENS")) or _coerce_optional_int(
                os.getenv("QWEN_MAX_TOKENS")
            )
        if legacy_max is not None:
            kwargs["max_tokens"] = legacy_max

    if "temperature" not in kwargs:
        kwargs["temperature"] = 0.7

    extra_body = resolve_extra_body(cfg)
    if extra_body:
        kwargs["extra_body"] = extra_body

    response_format = cfg.get("response_format")
    if isinstance(response_format, dict) and response_format:
        kwargs["response_format"] = dict(response_format)

    if tools:
        kwargs["tools"] = list(tools)
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice

    overrides = dict(runtime_overrides or {})
    overrides.pop("config", None)
    kwargs.update(overrides)

    return {k: v for k, v in kwargs.items() if v is not None}


def split_request_options_for_inspection(kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    """Expose mapped common/extra params without connection credentials (tests/UI)."""
    skip = {"model", "messages", "api_key", "api_base", "tools", "tool_choice"}
    return {k: v for k, v in kwargs.items() if k not in skip}


def drop_connection_keys(row: MutableMapping[str, Any]) -> Dict[str, Any]:
    """Utility for callers that want only non-connection keys from a row."""
    return {k: v for k, v in row.items() if k not in _CONNECTION_KEYS}
