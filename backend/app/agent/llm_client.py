"""LLM 客户端 - 支持 Qwen 模型"""
import os
from typing import Optional

from langchain_openai import ChatOpenAI


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
        self.api_key = api_key or os.getenv("QWEN_API_KEY")
        self.base_url = base_url or os.getenv(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        # 可通过 QWEN_MODEL 覆盖，默认 qwen3-max（阿里云最新旗舰，替代已弃用的 turbo）
        self.model = model or os.getenv("QWEN_MODEL", "qwen3-max")
        self.temperature = temperature
        self.max_tokens = max_tokens

        if not self.api_key:
            raise ValueError("QWEN_API_KEY is required")

    def get_client(self):
        """获取 LangChain ChatOpenAI 客户端"""
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
