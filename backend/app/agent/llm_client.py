"""LLM 客户端 - 支持 Qwen 及 OpenAI 兼容 API，可配置化切换"""
import os
from typing import Optional, Dict, Any

# 默认 provider 配置（当 app_settings 无 llm_providers 时使用）；与 settings 中 _DEFAULT_LLM_PROVIDERS 保持一致
_JENIYA_BASE = "http://jeniya.top/v1"
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
        self.base_url = base_url or os.getenv(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
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
        return ChatOpenAI(
            model=self.model,
            openai_api_key=self.api_key,
            openai_api_base=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            streaming=True,
            request_timeout=request_timeout,
            max_retries=max_retries,
        )
