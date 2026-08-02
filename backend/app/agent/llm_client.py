"""LLM 客户端 - 经 Parameter Mapper + LiteLLM 统一调用，与具体厂商解耦。"""
from __future__ import annotations
import logging

import json
import os
from typing import Any, Dict, Optional

from app.agent.llm_parameter_mapper import (
    map_model_config_to_litellm_kwargs,
    normalize_openai_base_url,
    resolve_litellm_model_id,
    resolve_extra_body,
    split_request_options_for_inspection,
    thinking_mode_enabled as _thinking_mode_from_config,
)
from app.agent.llm_prompt_trace import instrument_llm_client as _instrument_llm_client
from app.agent.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from app.agent.tool_spec import tools_to_openai_tools
from app.api.settings_env_vars import resolve_platform_env_value

# 默认模型配置（种子预设；用户可自由增删改，不是固定官方白名单）
_JENIYA_BASE = "https://jeniya.top/v1"
_JENIYA_KEY = "JENIYA_API_KEY"
_DEFAULT_LLM_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "qwen3-max": {
        "provider": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3-max",
        "api_key_env": "QWEN_API_KEY",
        "extra_body": {"enable_thinking": False},
    },
    "gpt-4o": {
        "provider": "openai",
        "base_url": _JENIYA_BASE,
        "model": "gpt-4o",
        "api_key_env": _JENIYA_KEY,
    },
    "gemini-3-pro-preview": {
        "provider": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3-pro-preview",
        "api_key_env": "GEMINI_API_KEY",
    },
    "claude-sonnet-4-6": {
        "provider": "openai",
        "base_url": _JENIYA_BASE,
        "model": "claude-sonnet-4-6",
        "api_key_env": _JENIYA_KEY,
    },
    "glm-4.7": {
        "provider": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.7",
        "api_key_env": "ZHIPUAI_API_KEY",
    },
    "deepseek-chat": {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "extra_body": {"thinking": {"type": "disabled"}},
    },
    "moonshot-v1-128k": {
        "provider": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-128k",
        "api_key_env": "MOONSHOT_API_KEY",
    },
}


def _client_thinking_mode_enabled(client: Any) -> bool:
    if bool(getattr(client, "_thinking_mode_enabled", False)):
        return True
    raw = getattr(client, "_raw_client", None)
    return bool(getattr(raw, "_thinking_mode_enabled", False))


def bind_tools_compat(client: Any, tools: list[Any], *, tool_choice_strategy: str | None = None) -> Any:
    """绑定工具；调用方可显式选择 auto，思考模式也不强制 required。"""
    if not tools:
        return client
    binding_tools = tools_to_openai_tools(tools)
    strategy = tool_choice_strategy or os.getenv("LLM_TOOL_CHOICE_STRATEGY", "required") or "required"
    strategy = strategy.strip().lower()
    if strategy in ("", "default"):
        strategy = "required"
    if _client_thinking_mode_enabled(client) and strategy in ("required", "any"):
        strategy = "auto"
    if strategy == "auto":
        return client.bind_tools(binding_tools)
    if strategy in ("required", "any"):
        return client.bind_tools(binding_tools, tool_choice="required")
    if strategy == "none":
        return client.bind_tools(binding_tools, tool_choice="none")
    return client.bind_tools(binding_tools, tool_choice="required")


def resolve_llm_provider_entry(
    llm_name: str,
    providers_config: Optional[Dict[str, Dict[str, Any]]] = None,
) -> tuple[str, Dict[str, Any]]:
    """Resolve model name to its config row without changing missing references."""
    providers = providers_config or _DEFAULT_LLM_PROVIDERS
    llm_key = str(llm_name or "").strip() or "qwen3-max"
    providers_by_lower = {str(k).strip().lower(): v for k, v in providers.items()}
    resolved_name = llm_key
    cfg = providers.get(llm_key) or providers_by_lower.get(llm_key.lower())
    if not cfg:
        return resolved_name, {}
    return resolved_name, dict(cfg or {})


def resolve_llm_api_key(
    cfg: Dict[str, Any],
    env_vars: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Resolve model credentials only through the api_key_env contract."""
    api_key_env = str(cfg.get("api_key_env") or "").strip()
    if not api_key_env:
        return None
    api_key = resolve_platform_env_value(api_key_env, env_vars)
    return (str(api_key).strip() or None) if api_key else None


def describe_llm_provider(llm_name: str, cfg: Dict[str, Any]) -> str:
    """Return provider model text for notices without using legacy display labels."""
    model = str(cfg.get("model") or llm_name or "").strip()
    return model or str(llm_name or "").strip() or "unknown"


def build_llm_credential_notice(llm_name: str, cfg: Dict[str, Any]) -> str:
    """User-facing notice when an LLM provider has no usable API key."""
    model_desc = describe_llm_provider(llm_name, cfg)
    return (
        f"模型型号为 {model_desc}，此时没有配置密钥或密钥错误。"
        "请前往「设置 → 环境变量」添加变量，并在「资源中心 → 配置模型」中为该模型填写 api_key_env 后重试。"
    )


def is_llm_credential_error_message(text: str) -> bool:
    """Detect auth/key failures returned by upstream LLM gateways."""
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    needles = (
        "缺少 api key",
        "api key",
        "api_key",
        "invalid api key",
        "incorrect api key",
        "authentication",
        "unauthorized",
        "401",
        "invalid token",
        "无效的令牌",
        "no api key",
        "authenticationerror",
        "permission denied",
    )
    return any(needle in normalized for needle in needles)


def get_llm_from_config(
    llm_name: str,
    providers_config: Optional[Dict[str, Dict[str, Any]]] = None,
    env_vars: Optional[Dict[str, str]] = None,
) -> "LLMClient":
    """
    根据 llm_name 从配置新建 LLM 客户端。
    解析顺序：模型 api_key_env 指向的平台内用户级环境变量 > 同名宿主机环境变量。
    """
    resolved_name, cfg = resolve_llm_provider_entry(llm_name, providers_config)
    if not cfg:
        raise ValueError(f"模型配置不存在：{resolved_name}")

    api_key_env = str(cfg.get("api_key_env") or "").strip()
    if not api_key_env:
        raise ValueError(f"模型配置缺少 api_key_env：{resolved_name}")
    api_key = resolve_llm_api_key(cfg, env_vars)
    if not api_key:
        raise ValueError(f"缺少环境变量 {api_key_env}")
    base_url = cfg.get("base_url")
    model = cfg.get("model")
    return LLMClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        provider_config=cfg,
    )


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _message_to_openai(message: Any) -> dict[str, Any]:
    content = getattr(message, "content", "")
    if isinstance(message, SystemMessage) or getattr(message, "type", "") == "system":
        return {"role": "system", "content": content}
    if isinstance(message, HumanMessage) or getattr(message, "type", "") in {"human", "user"}:
        return {"role": "user", "content": content}
    if isinstance(message, ToolMessage) or getattr(message, "type", "") == "tool":
        return {
            "role": "tool",
            "content": content,
            "tool_call_id": str(getattr(message, "tool_call_id", "") or ""),
        }
    if isinstance(message, dict):
        return dict(message)

    row: dict[str, Any] = {"role": "assistant", "content": content}
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        row["tool_calls"] = [_tool_call_to_openai(call, idx) for idx, call in enumerate(tool_calls)]
    return row


def _tool_call_to_openai(tool_call: Any, idx: int) -> dict[str, Any]:
    call_id = str(_get_value(tool_call, "id") or _get_value(tool_call, "tool_call_id") or f"tool-{idx}")
    name = str(_get_value(tool_call, "name") or _get_value(tool_call, "tool") or "tool")
    args = _get_value(tool_call, "args")
    if args is None:
        args = _get_value(tool_call, "arguments")
    if isinstance(args, str):
        arguments = args
    else:
        arguments = _compact_json(args or {})
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


def _messages_to_openai(messages: Any) -> Any:
    if isinstance(messages, (str, int, float, bool)) or messages is None:
        return messages
    if isinstance(messages, (list, tuple)):
        return [_message_to_openai(message) for message in messages]
    return messages


def _raw_tool_call_to_dict(tool_call: Any, idx: int) -> tuple[dict[str, Any], dict[str, Any]]:
    function = _get_value(tool_call, "function") or {}
    call_id = str(_get_value(tool_call, "id") or f"tool-{idx}")
    name = str(_get_value(function, "name") or "tool")
    arguments_raw = _get_value(function, "arguments") or "{}"
    try:
        parsed_args = json.loads(arguments_raw) if isinstance(arguments_raw, str) else arguments_raw
    except Exception:
        parsed_args = {}
    if not isinstance(parsed_args, dict):
        parsed_args = {}
    raw = {
        "id": call_id,
        "type": str(_get_value(tool_call, "type") or "function"),
        "function": {
            "name": name,
            "arguments": arguments_raw,
        },
    }
    return raw, {"id": call_id, "name": name, "args": parsed_args}


def _openai_message_to_ai_message(message: Any, *, finish_reason: Any = None) -> AIMessage:
    content = _get_value(message, "content") or ""
    raw_tool_calls: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    for idx, raw_call in enumerate(_get_value(message, "tool_calls") or []):
        raw, normalized = _raw_tool_call_to_dict(raw_call, idx)
        raw_tool_calls.append(raw)
        tool_calls.append(normalized)
    additional_kwargs = {"tool_calls": raw_tool_calls} if raw_tool_calls else {}
    response_metadata = {"finish_reason": finish_reason} if finish_reason else {}
    return AIMessage(
        content=content,
        additional_kwargs=additional_kwargs,
        response_metadata=response_metadata,
        tool_calls=tool_calls,
    )


class LiteLLMChatClient:
    """Unified chat adapter: Parameter Mapper → litellm.acompletion / completion."""

    def __init__(
        self,
        *,
        model_config: Dict[str, Any],
        api_key: str,
        tools: Optional[list[Any]] = None,
        tool_choice: Any = None,
        thinking_mode_enabled: bool = False,
    ):
        self._model_config = dict(model_config or {})
        self._api_key = api_key
        self._model = str(self._model_config.get("model") or "").strip() or "unknown"
        self._litellm_model = resolve_litellm_model_id(self._model_config)
        preview = map_model_config_to_litellm_kwargs(
            self._model_config,
            api_key=api_key,
            messages=[],
        )
        self._client_options = {
            "api_key": api_key,
            "base_url": preview.get("api_base"),
            "timeout": preview.get("timeout"),
            "max_retries": preview.get("num_retries"),
        }
        self._request_options = split_request_options_for_inspection(preview)
        self._tools = list(tools or [])
        self._tool_choice = tool_choice
        self._thinking_mode_enabled = thinking_mode_enabled

    def bind(self, **kwargs: Any) -> "LiteLLMChatClient":
        merged_config = {**self._model_config, **kwargs}
        return self._clone(model_config=merged_config)

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "LiteLLMChatClient":
        return self._clone(
            tools=list(tools or []),
            tool_choice=kwargs.get("tool_choice", self._tool_choice),
        )

    async def ainvoke(self, inp: Any, *args: Any, **kwargs: Any) -> AIMessage:
        del args
        import litellm

        response = await litellm.acompletion(**self._completion_kwargs(inp, kwargs))
        return self._response_to_ai_message(response)

    def invoke(self, inp: Any, *args: Any, **kwargs: Any) -> AIMessage:
        del args
        import litellm

        response = litellm.completion(**self._completion_kwargs(inp, kwargs))
        return self._response_to_ai_message(response)

    async def astream(self, inp: Any, *args: Any, **kwargs: Any):
        del args
        yield await self.ainvoke(inp, **kwargs)

    def stream(self, inp: Any, *args: Any, **kwargs: Any):
        del args
        yield self.invoke(inp, **kwargs)

    def _clone(self, **overrides: Any) -> "LiteLLMChatClient":
        return LiteLLMChatClient(
            model_config=overrides.get("model_config", self._model_config),
            api_key=overrides.get("api_key", self._api_key),
            tools=overrides.get("tools", self._tools),
            tool_choice=overrides.get("tool_choice", self._tool_choice),
            thinking_mode_enabled=overrides.get("thinking_mode_enabled", self._thinking_mode_enabled),
        )

    def _completion_kwargs(self, inp: Any, runtime_kwargs: Dict[str, Any]) -> dict[str, Any]:
        return map_model_config_to_litellm_kwargs(
            self._model_config,
            api_key=self._api_key,
            messages=_messages_to_openai(inp),
            tools=self._tools or None,
            tool_choice=self._tool_choice,
            runtime_overrides=runtime_kwargs,
        )

    @staticmethod
    def _response_to_ai_message(response: Any) -> AIMessage:
        choices = _get_value(response, "choices") or []
        if not choices:
            return AIMessage(content="")
        choice = choices[0]
        return _openai_message_to_ai_message(
            _get_value(choice, "message") or {},
            finish_reason=_get_value(choice, "finish_reason"),
        )


class LLMClient:
    """Model-config holder that builds a unified LiteLLMChatClient."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        provider_config: Optional[Dict[str, Any]] = None,
    ):
        self.provider_config = dict(provider_config or {})
        if base_url is not None and "base_url" not in self.provider_config:
            self.provider_config["base_url"] = base_url
        if model is not None and "model" not in self.provider_config:
            self.provider_config["model"] = model
        if "temperature" not in self.provider_config:
            self.provider_config["temperature"] = temperature
        if max_tokens is not None and "max_tokens" not in self.provider_config:
            self.provider_config["max_tokens"] = max_tokens

        self.base_url = normalize_openai_base_url(self.provider_config.get("base_url"))
        if self.base_url:
            self.provider_config["base_url"] = self.base_url
        self.model = str(self.provider_config.get("model") or "").strip() or "qwen3-max"
        self.provider_config["model"] = self.model
        self.temperature = self.provider_config.get("temperature", temperature)
        self.max_tokens = self.provider_config.get("max_tokens")

        if api_key and str(api_key).strip():
            self.api_key = str(api_key).strip()
        else:
            self.api_key = None

        if not self.api_key:
            raise ValueError("缺少 API Key：请通过模型配置 api_key_env 解析平台环境变量后创建 LLM 客户端。")

    def get_client(self):
        """获取经 Parameter Mapper + LiteLLM 统一调用的 Chat 客户端。"""
        try:
            import litellm  # noqa: F401
            logging.getLogger("LiteLLM").setLevel(logging.WARNING)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"litellm is required for LLM client: {e}") from e

        thinking = _thinking_mode_from_config(self.provider_config)
        client = LiteLLMChatClient(
            model_config=self.provider_config,
            api_key=self.api_key,
            thinking_mode_enabled=thinking,
        )
        return _instrument_llm_client(
            client,
            provider_base_url=self.base_url or "",
            model_name=self.model,
            thinking_mode_enabled=thinking,
        )


# Re-export mapper helpers used by tests / settings.
__all__ = [
    "LLMClient",
    "LiteLLMChatClient",
    "bind_tools_compat",
    "build_llm_credential_notice",
    "describe_llm_provider",
    "get_llm_from_config",
    "is_llm_credential_error_message",
    "normalize_openai_base_url",
    "resolve_extra_body",
    "resolve_litellm_model_id",
    "resolve_llm_api_key",
    "resolve_llm_provider_entry",
]
