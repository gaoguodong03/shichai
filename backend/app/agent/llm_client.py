"""LLM 客户端 - 支持 Qwen 及 OpenAI 兼容 API，可配置化切换"""
import os
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from app.core.llm_trace import append_llm_trace

# 默认 provider 配置（当 app_settings 无 llm_providers 时使用）；与 settings 中 _DEFAULT_LLM_PROVIDERS 保持一致
_JENIYA_BASE = "https://jeniya.top/v1"
_JENIYA_KEY = "JENIYA_API_KEY"
_DEFAULT_LLM_PROVIDERS: Dict[str, Dict[str, str]] = {
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3-max",
        "api_key_env": "QWEN_API_KEY",
    },
    "jeniya": {"base_url": _JENIYA_BASE, "model": "gpt-4o", "api_key_env": _JENIYA_KEY},
    "gemini": {"base_url": _JENIYA_BASE, "model": "gemini-3-pro-preview", "api_key_env": _JENIYA_KEY},
    "claude": {"base_url": _JENIYA_BASE, "model": "claude-sonnet-4-6", "api_key_env": _JENIYA_KEY},
    "glm": {"base_url": _JENIYA_BASE, "model": "glm-4.7", "api_key_env": _JENIYA_KEY},
    "deepseek": {"base_url": _JENIYA_BASE, "model": "deepseek-chat", "api_key_env": _JENIYA_KEY},
    "kimi": {"base_url": _JENIYA_BASE, "model": "moonshot-v1-128k", "api_key_env": _JENIYA_KEY},
}


def bind_tools_compat(client: Any, tools: list[Any]) -> Any:
    """绑定工具时默认禁用 auto tool choice，兼容未开启 auto-parser 的 OpenAI 兼容网关。"""
    if not tools:
        return client
    strategy = (os.getenv("LLM_TOOL_CHOICE_STRATEGY", "required") or "required").strip().lower()
    if strategy in ("", "default"):
        strategy = "required"
    if strategy == "auto":
        return client.bind_tools(tools)
    if strategy in ("required", "any"):
        return client.bind_tools(tools, tool_choice="required")
    if strategy == "none":
        return client.bind_tools(tools, tool_choice="none")
    return client.bind_tools(tools, tool_choice="required")


def get_llm_from_config(
    provider_id: str,
    providers_config: Optional[Dict[str, Dict[str, Any]]] = None,
    api_secrets: Optional[Dict[str, str]] = None,
) -> "QwenLLM":
    """
    根据 provider_id 从配置创建 LLM 客户端。
    解析顺序：api_key_ref（密钥库）> 配置中的 api_key > api_key_env 环境变量。
    """
    providers = providers_config or _DEFAULT_LLM_PROVIDERS
    cfg = providers.get(provider_id) or providers.get("qwen")
    if not cfg:
        return QwenLLM()

    api_key = None
    ref = (cfg.get("api_key_ref") or "").strip()
    if ref and api_secrets and ref in api_secrets:
        api_key = api_secrets[ref]
    if not api_key:
        api_key = (cfg.get("api_key") or "").strip() or None
    if not api_key:
        api_key_env = cfg.get("api_key_env", "QWEN_API_KEY")
        api_key = os.getenv(api_key_env)
    base_url = cfg.get("base_url")
    model = cfg.get("model")
    return QwenLLM(
        api_key=api_key,
        base_url=base_url,
        model=model,
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


def _qwen_no_thinking_extra_body(base_url: Optional[str]) -> Dict[str, Any]:
    if "dashscope" in (base_url or "").lower():
        return {"enable_thinking": False}
    return {"chat_template_kwargs": {"enable_thinking": False}}


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
        max_tokens: int = 2000,
    ):
        self.base_url = normalize_openai_base_url(
            base_url or os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        # 可通过 QWEN_MODEL 覆盖，默认 qwen3-max（阿里云最新旗舰，替代已弃用的 turbo）
        self.model = model or os.getenv("QWEN_MODEL", "qwen3-max")
        self.temperature = temperature
        self.max_tokens = max_tokens

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
        # 可通过 QWEN_REQUEST_TIMEOUT 调整（秒），默认 180
        request_timeout = _parse_int_env("QWEN_REQUEST_TIMEOUT", 180)
        # max_retries：默认 2。若每次调用都 Retrying，多为 DashScope 限流（429），可设 QWEN_MAX_RETRIES=0 先看真实错误
        max_retries = _parse_int_env("QWEN_MAX_RETRIES", 2)
        kwargs = {
            "model": self.model,
            "openai_api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "streaming": True,
            "request_timeout": request_timeout,
            "max_retries": max_retries,
        }
        if _is_qwen_model(self.model):
            kwargs["model_kwargs"] = {
                "extra_body": _qwen_no_thinking_extra_body(self.base_url)
            }
        try:
            client = ChatOpenAI(**kwargs)
        except Exception as e:  # noqa: BLE001
            # Older langchain-openai versions used openai_api_base instead of base_url.
            if "base_url" not in str(e):
                raise
            kwargs["openai_api_base"] = kwargs.pop("base_url")
            client = ChatOpenAI(**kwargs)
        return _instrument_llm_client(
            client,
            provider_base_url=self.base_url,
            model_name=self.model,
        )


def _message_content_to_text(obj: Any) -> str:
    if obj is None:
        return ""
    content = getattr(obj, "content", obj)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                t = item.get("text")
                if t is not None:
                    parts.append(str(t))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _input_to_text(inp: Any) -> str:
    if isinstance(inp, list):
        return "\n\n".join(_message_content_to_text(x) for x in inp)
    return _message_content_to_text(inp)


class _TracedLLMClient:
    """对底层 LLM client 的只读代理：不修改原对象，避免 Pydantic 字段限制报错。"""

    def __init__(self, raw_client: Any, *, provider_base_url: str, model_name: str):
        self._raw_client = raw_client
        self._provider_base_url = provider_base_url
        self._model_name = model_name

    def __getattr__(self, item: str) -> Any:
        return getattr(self._raw_client, item)

    async def ainvoke(self, inp: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            out = await self._raw_client.ainvoke(inp, *args, **kwargs)
            append_llm_trace(
                tag="global_llm_ainvoke",
                system_content="",
                user_content=_input_to_text(inp),
                model_output=_message_content_to_text(out),
                extra={
                    "base_url": self._provider_base_url,
                    "model": self._model_name,
                },
            )
            return out
        except Exception as e:
            append_llm_trace(
                tag="global_llm_ainvoke_error",
                system_content="",
                user_content=_input_to_text(inp),
                model_output=f"[ERROR] {type(e).__name__}: {e}",
                extra={
                    "base_url": self._provider_base_url,
                    "model": self._model_name,
                },
            )
            raise

    def invoke(self, inp: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            out = self._raw_client.invoke(inp, *args, **kwargs)
            append_llm_trace(
                tag="global_llm_invoke",
                system_content="",
                user_content=_input_to_text(inp),
                model_output=_message_content_to_text(out),
                extra={
                    "base_url": self._provider_base_url,
                    "model": self._model_name,
                },
            )
            return out
        except Exception as e:
            append_llm_trace(
                tag="global_llm_invoke_error",
                system_content="",
                user_content=_input_to_text(inp),
                model_output=f"[ERROR] {type(e).__name__}: {e}",
                extra={
                    "base_url": self._provider_base_url,
                    "model": self._model_name,
                },
            )
            raise


def _instrument_llm_client(client: Any, *, provider_base_url: str, model_name: str) -> Any:
    if isinstance(client, _TracedLLMClient):
        return client
    return _TracedLLMClient(
        client,
        provider_base_url=provider_base_url,
        model_name=model_name,
    )
