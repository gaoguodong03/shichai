"""LLM 客户端 - 支持 Qwen 模型"""
from langchain_openai import ChatOpenAI
from typing import Optional
import os

class QwenLLM:
    """Qwen LLM 客户端（兼容 OpenAI API）"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "qwen-plus",
        temperature: float = 0.7,
        max_tokens: int = 2000
    ):
        self.api_key = api_key or os.getenv("QWEN_API_KEY")
        self.base_url = base_url or os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        if not self.api_key:
            raise ValueError("QWEN_API_KEY is required")
    
    def get_client(self):
        """获取 LangChain ChatOpenAI 客户端"""
        return ChatOpenAI(
            model=self.model,
            openai_api_key=self.api_key,
            openai_api_base=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            streaming=True,
            request_timeout=90,
        )
