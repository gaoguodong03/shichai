"""LLM 客户端 - 支持 Qwen 及 OpenAI 兼容 API，可配置化切换"""
import json
import logging
import os
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from app.agent.tool_spec import tools_to_openai_tools

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
    """Resolve model name to its config row, falling back to qwen3-max defaults."""
    providers = providers_config or _DEFAULT_LLM_PROVIDERS
    llm_key = str(llm_name or "").strip()
    providers_by_lower = {str(k).strip().lower(): v for k, v in providers.items()}
    resolved_name = llm_key
    cfg = providers.get(llm_key) or providers_by_lower.get(llm_key.lower())
    if not cfg:
        resolved_name = "qwen3-max"
        cfg = providers.get("qwen3-max") or providers_by_lower.get("qwen3-max") or {}
    return resolved_name, dict(cfg or {})


def resolve_llm_api_key(
    cfg: Dict[str, Any],
    api_secrets: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Resolve API key without constructing an LLM client."""
    api_key = None
    ref = (cfg.get("api_key_ref") or "").strip()
    if ref and api_secrets and ref in api_secrets:
        api_key = api_secrets[ref]
    if not api_key:
        api_key = (cfg.get("api_key") or "").strip() or None
    if not api_key:
        api_key_env = cfg.get("api_key_env", "QWEN_API_KEY")
        api_key = os.getenv(api_key_env)
    return (str(api_key).strip() or None) if api_key else None


def describe_llm_provider(llm_name: str, cfg: Dict[str, Any]) -> str:
    """Human-readable model label for user-facing notices."""
    model = str(cfg.get("model") or llm_name or "").strip() or str(llm_name or "").strip() or "unknown"
    label = str(cfg.get("label") or "").strip()
    if label and label != model:
        return f"{label}（{model}）"
    return model


def build_llm_credential_notice(llm_name: str, cfg: Dict[str, Any]) -> str:
    """User-facing notice when an LLM provider has no usable API key."""
    model_desc = describe_llm_provider(llm_name, cfg)
    return (
        f"模型型号为 {model_desc}，此时没有配置密钥或密钥错误。"
        "请前往「设置 → 密钥」添加密钥，并在「资源中心 → 配置模型」中为该模型选择密钥后重试。"
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
    api_secrets: Optional[Dict[str, str]] = None,
) -> "QwenLLM":
    """
    根据 llm_name 从配置新建 LLM 客户端。
    解析顺序：api_key_ref（密钥库）> 配置中的 api_key > api_key_env 环境变量。
    """
    resolved_name, cfg = resolve_llm_provider_entry(llm_name, providers_config)
    if not cfg:
        return QwenLLM()

    api_key = resolve_llm_api_key(cfg, api_secrets)
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

    # UI/API users sometimes paste the full Chat Completions endpoint.  LangChain
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
        """获取 LangChain ChatOpenAI 客户端"""
        try:
            from langchain_openai import ChatOpenAI
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"langchain_openai is required for LLM client: {e}") from e
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
        kwargs = {
            "model": self.model,
            "openai_api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "streaming": _coerce_bool(self.provider_config.get("streaming"), True),
            "request_timeout": request_timeout,
            "max_retries": max_retries,
        }
        # 只接收官方常见 Chat/Message API 明确支持的白名单字段；不要透传任意用户字段。
        _set_if_present(kwargs, "top_p", _coerce_optional_float(self.provider_config.get("top_p")))
        _set_if_present(kwargs, "presence_penalty", _coerce_optional_float(self.provider_config.get("presence_penalty")))
        _set_if_present(kwargs, "frequency_penalty", _coerce_optional_float(self.provider_config.get("frequency_penalty")))
        _set_if_present(kwargs, "seed", _coerce_optional_int(self.provider_config.get("seed")))

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
            kwargs.setdefault("model_kwargs", {})["extra_body"] = extra_body
        elif _is_qwen_model(self.model):
            kwargs.setdefault("model_kwargs", {})["extra_body"] = _qwen_no_thinking_extra_body(self.base_url)
        thinking_mode_enabled = bool(
            extra_body.get("enable_thinking") is True
            or (isinstance(extra_body.get("thinking"), dict) and extra_body["thinking"].get("type") == "enabled")
            or extra_body.get("thinkingConfig")
        )
        kwargs = _clean_client_kwargs(kwargs)
        try:
            client = ChatOpenAI(**kwargs)
        except Exception as e:  # noqa: BLE001
            # Older langchain-openai versions used openai_api_base instead of base_url.
            if "base_url" not in str(e):
                raise
            kwargs["openai_api_base"] = kwargs.pop("base_url")
            client = ChatOpenAI(**kwargs)
        try:
            object.__setattr__(client, "_thinking_mode_enabled", thinking_mode_enabled)
        except Exception:
            pass
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
        logger.info(
            "[Prompt] method=%s model=%s base_url=%s\n%s",
            method,
            self._model_name,
            self._provider_base_url,
            _serialize_prompt_payload(inp),
        )


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
