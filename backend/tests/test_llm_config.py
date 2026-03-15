"""测试 LLM 配置化（get_llm_from_config）"""
import os
import pytest

# 测试前设置 env，避免 QwenLLM 初始化报错
os.environ.setdefault("QWEN_API_KEY", "test-key")
os.environ.setdefault("JENIYA_API_KEY", "test-jeniya-key")


def test_get_llm_from_config_qwen():
    """使用 qwen provider 创建 LLM"""
    os.environ["QWEN_API_KEY"] = "test-key"  # 隔离：避免被 test_chat_memory 等先设置的 setdefault 覆盖
    from app.agent.llm_client import get_llm_from_config

    llm = get_llm_from_config("qwen", {
        "qwen": {
            "base_url": "https://dashscope.aliyuncs.com/v1",
            "model": "qwen-turbo",
            "api_key_env": "QWEN_API_KEY",
        },
    })
    assert llm.base_url == "https://dashscope.aliyuncs.com/v1"
    assert llm.model == "qwen-turbo"
    assert llm.api_key == "test-key"


def test_get_llm_from_config_jeniya():
    """使用 jeniya provider 创建 LLM"""
    from app.agent.llm_client import get_llm_from_config

    llm = get_llm_from_config("jeniya", {
        "jeniya": {
            "base_url": "http://jeniya.top/v1",
            "model": "gpt-4o",
            "api_key_env": "JENIYA_API_KEY",
        },
    })
    assert llm.base_url == "http://jeniya.top/v1"
    assert llm.model == "gpt-4o"
    assert llm.api_key == "test-jeniya-key"


def test_get_llm_from_config_unknown_fallback():
    """未知 provider 回退到 qwen"""
    from app.agent.llm_client import get_llm_from_config

    llm = get_llm_from_config("unknown", {
        "qwen": {
            "base_url": "https://fallback/v1",
            "model": "qwen",
            "api_key_env": "QWEN_API_KEY",
        },
    })
    assert llm.base_url == "https://fallback/v1"


def test_get_llm_from_config_empty_uses_default():
    """空配置使用默认 provider"""
    from app.agent.llm_client import get_llm_from_config

    llm = get_llm_from_config("qwen", None)
    assert llm.model is not None
    assert llm.base_url is not None
