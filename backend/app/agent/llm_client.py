"""LLM 客户端 - 支持 Qwen 及 OpenAI 兼容 API，可配置化切换"""
import json
import logging
import os
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from app.agent.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from app.agent.tool_spec import tools_to_openai_tools
from app.api.settings_env_vars import resolve_platform_env_value

logger = logging.getLogger(__name__)

# 默认 provider 配置（当 app_settings 无 llm_providers 时使用）；与 settings 中 _DEFAULT_LLM_PROVIDERS 保持一致
_JENIYA_BASE = "https://jeniya.top/v1"
_JENIYA_KEY = "JENIYA_API_KEY"
_DEFAULT_LLM_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "qwen3-max": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3-max",
        "api_key_env": "QWEN_API_KEY",
    },
    "gpt-4o": {"base_url": _JENIYA_BASE, "model": "gpt-4o", "api_key_env": _JENIYA_KEY},
    "gemini-3-pro-preview": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3-pro-preview",
        "api_key_env": "GEMINI_API_KEY",
    },
    "claude-sonnet-4-6": {
        "base_url": _JENIYA_BASE,
        "model": "claude-sonnet-4-6",
        "api_key_env": _JENIYA_KEY,
    },
    "glm-4.7": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.7",
        "api_key_env": "ZHIPUAI_API_KEY",
    },
    "deepseek-chat": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "thinking": False,
    },
    "moonshot-v1-128k": {
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


def bind_tools_compat(client: Any, tools: list[Any]) -> Any:
    """绑定工具：思考模式不强制 required，避免 Qwen 等网关 400。"""
    if not tools:
        return client
    binding_tools = tools_to_openai_tools(tools)
    strategy = (os.getenv("LLM_TOOL_CHOICE_STRATEGY", "required") or "required").strip().lower()
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
    """Resolve API key without constructing an LLM client."""
    api_key_env = str(cfg.get("api_key_env") or "").strip()
    api_key = resolve_platform_env_value(api_key_env, env_vars) if api_key_env else None
    if not api_key:
        api_key = (cfg.get("api_key") or "").strip() or None
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
) -> "QwenLLM":
    """
    根据 llm_name 从配置新建 LLM 客户端。
    解析顺序：平台内用户级环境变量 > 宿主机环境变量 > 配置中的内联 api_key。
    """
    resolved_name, cfg = resolve_llm_provider_entry(llm_name, providers_config)
    if not cfg:
        raise ValueError(f"模型配置不存在：{resolved_name}")

    api_key = resolve_llm_api_key(cfg, env_vars)
    base_url = cfg.get("base_url")
    model = cfg.get("model")
    return QwenLLM(
        api_key=api_key,
        base_url=base_url,
        model=model,
        provider_config=cfg,
    )


def _parse_int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _is_qwen_model(model: Optional[str]) -> bool:
    if not model:
        return False
    normalized = str(model).strip().lower()
    model_name = normalized.rsplit("/", 1)[-1]
    return model_name == "qwen" or model_name.startswith("qwen")


def _provider_fingerprint(config: Dict[str, Any], base_url: Optional[str], model: Optional[str]) -> str:
    return " ".join(
        str(x or "").lower()
        for x in (config.get("id"), config.get("provider"), base_url, model)
    )


def _is_provider_like(fingerprint: str, *needles: str) -> bool:
    return any(n in fingerprint for n in needles)


def _qwen_no_thinking_extra_body(base_url: Optional[str]) -> Dict[str, Any]:
    if "dashscope" in (base_url or "").lower():
        return {"enable_thinking": False}
    return {"chat_template_kwargs": {"enable_thinking": False}}


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _clean_client_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}


def prompt_log_mode() -> str:
    mode = (os.getenv("PROMPT_LOG_MODE") or "summary").strip().lower()
    if mode in {"0", "false", "off", "none", "disabled"}:
        return "off"
    if mode in {"full", "body", "raw", "debug"}:
        return "full"
    return "summary"


def should_log_full_prompts() -> bool:
    return prompt_log_mode() == "full"


def _set_if_present(target: Dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        target[key] = value


def normalize_openai_base_url(base_url: Optional[str]) -> Optional[str]:
    """Return a provider base URL suitable for OpenAI-compatible clients."""
    if base_url is None:
        return None
    value = str(base_url).strip().rstrip("/")
    if not value:
        return None

    # UI/API users sometimes paste the full Chat Completions endpoint. The SDK
    # appends /chat/completions itself, so keep only the API base.
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


class OpenAIChatClient:
    """Project-local chat adapter over the OpenAI-compatible SDK."""

    def __init__(
        self,
        *,
        async_client: Any,
        model: str,
        request_options: Optional[Dict[str, Any]] = None,
        client_options: Optional[Dict[str, Any]] = None,
        sync_client: Any = None,
        tools: Optional[list[Any]] = None,
        tool_choice: Any = None,
        thinking_mode_enabled: bool = False,
    ):
        self._async_client = async_client
        self._sync_client = sync_client
        self._model = model
        self._request_options = dict(request_options or {})
        self._client_options = dict(client_options or {})
        self._tools = list(tools or [])
        self._tool_choice = tool_choice
        self._thinking_mode_enabled = thinking_mode_enabled

    def bind(self, **kwargs: Any) -> "OpenAIChatClient":
        merged = {**self._request_options, **kwargs}
        return self._clone(request_options=merged)

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "OpenAIChatClient":
        return self._clone(
            tools=list(tools or []),
            tool_choice=kwargs.get("tool_choice", self._tool_choice),
        )

    async def ainvoke(self, inp: Any, *args: Any, **kwargs: Any) -> AIMessage:
        del args
        response = await self._async_client.chat.completions.create(**self._create_kwargs(inp, kwargs))
        return self._response_to_ai_message(response)

    def invoke(self, inp: Any, *args: Any, **kwargs: Any) -> AIMessage:
        del args
        if self._sync_client is None:
            raise RuntimeError("sync OpenAI client is not configured")
        response = self._sync_client.chat.completions.create(**self._create_kwargs(inp, kwargs))
        return self._response_to_ai_message(response)

    async def astream(self, inp: Any, *args: Any, **kwargs: Any):
        del args
        yield await self.ainvoke(inp, **kwargs)

    def stream(self, inp: Any, *args: Any, **kwargs: Any):
        del args
        yield self.invoke(inp, **kwargs)

    def _clone(self, **overrides: Any) -> "OpenAIChatClient":
        return OpenAIChatClient(
            async_client=self._async_client,
            sync_client=self._sync_client,
            model=overrides.get("model", self._model),
            request_options=overrides.get("request_options", self._request_options),
            client_options=overrides.get("client_options", self._client_options),
            tools=overrides.get("tools", self._tools),
            tool_choice=overrides.get("tool_choice", self._tool_choice),
            thinking_mode_enabled=overrides.get("thinking_mode_enabled", self._thinking_mode_enabled),
        )

    def _create_kwargs(self, inp: Any, runtime_kwargs: Dict[str, Any]) -> dict[str, Any]:
        runtime_kwargs = dict(runtime_kwargs or {})
        runtime_kwargs.pop("config", None)
        payload = {
            "model": self._model,
            "messages": _messages_to_openai(inp),
            **self._request_options,
            **runtime_kwargs,
        }
        if self._tools:
            payload["tools"] = self._tools
        if self._tool_choice is not None:
            payload["tool_choice"] = self._tool_choice
        return _clean_client_kwargs(payload)

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


class QwenLLM:
    """Qwen LLM 客户端（兼容 OpenAI API）"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        provider_config: Optional[Dict[str, Any]] = None,
    ):
        self.provider_config = provider_config or {}
        self.base_url = normalize_openai_base_url(
            base_url or os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        # 可通过 QWEN_MODEL 覆盖，默认 qwen3-max（阿里云最新旗舰，替代已弃用的 turbo）
        self.model = model or os.getenv("QWEN_MODEL", "qwen3-max")
        self.temperature = _coerce_optional_float(self.provider_config.get("temperature"))
        if self.temperature is None:
            self.temperature = temperature
        env_max_tokens = _coerce_optional_int(os.getenv("LLM_MAX_TOKENS")) or _coerce_optional_int(os.getenv("QWEN_MAX_TOKENS"))
        self.max_tokens = _coerce_optional_int(self.provider_config.get("max_tokens"))
        if self.max_tokens is None:
            self.max_tokens = (
                _coerce_optional_int(self.provider_config.get("max_completion_tokens"))
                or env_max_tokens
                or max_tokens
            )

        # 勿对非 DashScope 的 base_url 回退到 QWEN_API_KEY，否则 Jeniya 等中转会收到阿里云 Key → 401「无效的令牌」
        if api_key and str(api_key).strip():
            self.api_key = str(api_key).strip()
        elif "dashscope.aliyuncs.com" in (self.base_url or ""):
            self.api_key = (os.getenv("QWEN_API_KEY") or "").strip() or None
        else:
            self.api_key = (os.getenv("JENIYA_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip() or None

        if not self.api_key:
            raise ValueError(
                "缺少 API Key：DashScope 请设置 QWEN_API_KEY；Jeniya/OpenAI 兼容中转请设置 JENIYA_API_KEY（或 OPENAI_API_KEY）"
            )

    def get_client(self):
        """获取项目本地 OpenAI SDK Chat 客户端适配器"""
        try:
            from openai import AsyncOpenAI, OpenAI
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"openai SDK is required for LLM client: {e}") from e
        # 可通过 QWEN_REQUEST_TIMEOUT 调整（秒）。默认 60s 适合前端交互；
        # 慢模型/慢网关可在 provider 配置里单独设置 request_timeout=180。
        request_timeout = _parse_int_env("QWEN_REQUEST_TIMEOUT", 60)
        # max_retries：默认 0，失败即失败，避免一次超时后后台继续重试拖慢反馈。
        max_retries = _parse_int_env("QWEN_MAX_RETRIES", 0)
        request_timeout = _coerce_optional_int(self.provider_config.get("request_timeout")) or request_timeout
        request_timeout_max = _parse_int_env("QWEN_REQUEST_TIMEOUT_MAX", 0)
        if request_timeout_max > 0:
            request_timeout = min(request_timeout, request_timeout_max)
        max_retries = _coerce_optional_int(self.provider_config.get("max_retries"))
        if max_retries is None:
            max_retries = _parse_int_env("QWEN_MAX_RETRIES", 0)
        client_kwargs = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "timeout": request_timeout,
            "max_retries": max_retries,
        }
        request_options = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        # 只接收官方常见 Chat/Message API 明确支持的白名单字段；不要透传任意用户字段。
        _set_if_present(request_options, "top_p", _coerce_optional_float(self.provider_config.get("top_p")))
        _set_if_present(request_options, "presence_penalty", _coerce_optional_float(self.provider_config.get("presence_penalty")))
        _set_if_present(request_options, "frequency_penalty", _coerce_optional_float(self.provider_config.get("frequency_penalty")))
        _set_if_present(request_options, "seed", _coerce_optional_int(self.provider_config.get("seed")))

        fingerprint = _provider_fingerprint(self.provider_config, self.base_url, self.model)
        extra_body: Dict[str, Any] = {}
        enable_thinking = self.provider_config.get("enable_thinking")
        thinking_budget = _coerce_optional_int(self.provider_config.get("thinking_budget"))
        thinking = self.provider_config.get("thinking")
        do_sample = self.provider_config.get("do_sample")
        top_k = _coerce_optional_int(self.provider_config.get("top_k"))
        gemini_thinking_level = str(self.provider_config.get("gemini_thinking_level") or "").strip().lower()

        if _is_provider_like(fingerprint, "qwen", "dashscope", "aliyun", "bailian"):
            if isinstance(enable_thinking, bool):
                extra_body["enable_thinking"] = enable_thinking
            if thinking_budget is not None:
                extra_body["thinking_budget"] = thinking_budget
        if _is_provider_like(fingerprint, "deepseek"):
            extra_body["thinking"] = {"type": "enabled" if thinking is True else "disabled"}
        elif _is_provider_like(fingerprint, "glm", "zhipu", "bigmodel") and isinstance(thinking, bool):
            extra_body["thinking"] = {"type": "enabled" if thinking else "disabled"}
        if _is_provider_like(fingerprint, "glm", "zhipu", "bigmodel") and isinstance(do_sample, bool):
            extra_body["do_sample"] = do_sample
        if _is_provider_like(fingerprint, "gemini", "google", "generativelanguage"):
            if top_k is not None:
                extra_body["topK"] = top_k
            if gemini_thinking_level == "low":
                extra_body["thinkingConfig"] = {"thinkingLevel": "low"}
        elif _is_provider_like(fingerprint, "claude", "anthropic") and top_k is not None:
            extra_body["top_k"] = top_k

        if extra_body:
            request_options["extra_body"] = extra_body
        elif _is_qwen_model(self.model):
            request_options["extra_body"] = _qwen_no_thinking_extra_body(self.base_url)
        thinking_mode_enabled = bool(
            extra_body.get("enable_thinking") is True
            or (isinstance(extra_body.get("thinking"), dict) and extra_body["thinking"].get("type") == "enabled")
            or extra_body.get("thinkingConfig")
        )
        client_kwargs = _clean_client_kwargs(client_kwargs)
        request_options = _clean_client_kwargs(request_options)
        client = OpenAIChatClient(
            async_client=AsyncOpenAI(**client_kwargs),
            sync_client=OpenAI(**client_kwargs),
            model=self.model,
            request_options=request_options,
            client_options=client_kwargs,
            thinking_mode_enabled=thinking_mode_enabled,
        )
        return _instrument_llm_client(
            client,
            provider_base_url=self.base_url,
            model_name=self.model,
            thinking_mode_enabled=thinking_mode_enabled,
        )

class _TracedLLMClient:
    """对底层 LLM client 的只读代理：不修改原对象，避免 Pydantic 字段限制报错。"""

    def __init__(
        self,
        raw_client: Any,
        *,
        provider_base_url: str,
        model_name: str,
        thinking_mode_enabled: bool = False,
    ):
        self._raw_client = raw_client
        self._provider_base_url = provider_base_url
        self._model_name = model_name
        self._thinking_mode_enabled = thinking_mode_enabled

    def __getattr__(self, item: str) -> Any:
        return getattr(self._raw_client, item)

    def bind(self, *args: Any, **kwargs: Any) -> Any:
        bind_fn = getattr(self._raw_client, "bind")
        return _instrument_llm_client(
            bind_fn(*args, **kwargs),
            provider_base_url=self._provider_base_url,
            model_name=self._model_name,
            thinking_mode_enabled=self._thinking_mode_enabled,
        )

    def bind_tools(self, *args: Any, **kwargs: Any) -> Any:
        bind_tools_fn = getattr(self._raw_client, "bind_tools")
        bound = bind_tools_fn(*args, **kwargs)
        if not any(hasattr(bound, attr) for attr in ("ainvoke", "invoke", "astream", "bind_tools")):
            return bound
        return _instrument_llm_client(
            bound,
            provider_base_url=self._provider_base_url,
            model_name=self._model_name,
            thinking_mode_enabled=self._thinking_mode_enabled,
        )

    async def ainvoke(self, inp: Any, *args: Any, **kwargs: Any) -> Any:
        self._log_prompt("ainvoke", inp)
        return await self._raw_client.ainvoke(inp, *args, **kwargs)

    def invoke(self, inp: Any, *args: Any, **kwargs: Any) -> Any:
        self._log_prompt("invoke", inp)
        return self._raw_client.invoke(inp, *args, **kwargs)

    async def astream(self, inp: Any, *args: Any, **kwargs: Any):
        self._log_prompt("astream", inp)
        async for chunk in self._raw_client.astream(inp, *args, **kwargs):
            yield chunk

    def stream(self, inp: Any, *args: Any, **kwargs: Any):
        self._log_prompt("stream", inp)
        yield from self._raw_client.stream(inp, *args, **kwargs)

    def _log_prompt(self, method: str, inp: Any) -> None:
        mode = prompt_log_mode()
        if mode == "off":
            return
        if mode == "full":
            logger.info(
                "[Prompt] mode=full method=%s model=%s base_url=%s\n%s",
                method,
                self._model_name,
                self._provider_base_url,
                _serialize_prompt_payload(inp),
            )
            return
        stats = _prompt_payload_stats(inp)
        logger.info(
            "[Prompt] mode=summary method=%s model=%s base_url=%s input_messages=%s prompt_chars=%s tool_call_count=%s",
            method,
            self._model_name,
            self._provider_base_url,
            stats["input_messages"],
            stats["prompt_chars"],
            stats["tool_call_count"],
        )


def _prompt_payload_stats(value: Any) -> Dict[str, int]:
    payload = _prompt_to_jsonable(value)

    def _content_chars(item: Any) -> int:
        if isinstance(item, dict):
            total = 0
            if "content" in item:
                total += len(str(item.get("content") or ""))
            for key, val in item.items():
                if key == "content":
                    continue
                total += _content_chars(val)
            return total
        if isinstance(item, list):
            return sum(_content_chars(x) for x in item)
        if isinstance(item, (str, int, float, bool)) or item is None:
            return len(str(item or ""))
        return len(str(item))

    def _tool_call_count(item: Any) -> int:
        if isinstance(item, dict):
            count = 0
            tool_calls = item.get("tool_calls")
            if isinstance(tool_calls, list):
                count += len(tool_calls)
            return count + sum(_tool_call_count(v) for k, v in item.items() if k != "tool_calls")
        if isinstance(item, list):
            return sum(_tool_call_count(x) for x in item)
        return 0

    return {
        "input_messages": len(payload) if isinstance(payload, list) else (0 if payload is None else 1),
        "prompt_chars": _content_chars(payload),
        "tool_call_count": _tool_call_count(payload),
    }


def _serialize_prompt_payload(value: Any) -> str:
    try:
        return json.dumps(_prompt_to_jsonable(value), ensure_ascii=False, indent=2, default=str)
    except Exception:  # noqa: BLE001
        return str(value)


def _prompt_to_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_prompt_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _prompt_to_jsonable(v) for k, v in value.items()}

    content_marker = object()
    content = getattr(value, "content", content_marker)
    if content is not content_marker:
        row: Dict[str, Any] = {
            "type": str(getattr(value, "type", "") or value.__class__.__name__),
            "content": _prompt_to_jsonable(content),
        }
        for attr in ("name", "id", "tool_call_id"):
            attr_value = getattr(value, attr, None)
            if attr_value:
                row[attr] = _prompt_to_jsonable(attr_value)
        additional_kwargs = getattr(value, "additional_kwargs", None)
        if additional_kwargs:
            row["additional_kwargs"] = _prompt_to_jsonable(additional_kwargs)
        tool_calls = getattr(value, "tool_calls", None)
        if tool_calls:
            row["tool_calls"] = _prompt_to_jsonable(tool_calls)
        return row

    if hasattr(value, "model_dump"):
        try:
            return _prompt_to_jsonable(value.model_dump())
        except Exception:  # noqa: BLE001
            pass
    return str(value)


def _instrument_llm_client(
    client: Any,
    *,
    provider_base_url: str,
    model_name: str,
    thinking_mode_enabled: bool = False,
) -> Any:
    if isinstance(client, _TracedLLMClient):
        return client
    return _TracedLLMClient(
        client,
        provider_base_url=provider_base_url,
        model_name=model_name,
        thinking_mode_enabled=thinking_mode_enabled,
    )
