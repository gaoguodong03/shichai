"""测试 LLM 配置化（get_llm_from_config）"""
import os
import sys
import types
import pytest

# 测试前设置 env，避免 QwenLLM 初始化报错
os.environ.setdefault("QWEN_API_KEY", "test-key")
os.environ.setdefault("JENIYA_API_KEY", "test-jeniya-key")


def test_get_llm_from_config_qwen():
    """使用 qwen provider 创建 LLM"""
    os.environ["QWEN_API_KEY"] = "test-key"  # 隔离：避免被其他测试先设置的 setdefault 覆盖
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
            "base_url": "https://jeniya.top/v1",
            "model": "gpt-4o",
            "api_key_env": "JENIYA_API_KEY",
        },
    })
    assert llm.base_url == "https://jeniya.top/v1"
    assert llm.model == "gpt-4o"
    assert llm.api_key == "test-jeniya-key"


def test_get_llm_from_config_api_key_ref():
    """api_key_ref 优先于环境变量与内联 api_key"""
    from app.agent.llm_client import get_llm_from_config

    llm = get_llm_from_config(
        "jeniya",
        {
            "jeniya": {
                "base_url": "https://jeniya.top/v1",
                "model": "gpt-4o",
                "api_key_env": "JENIYA_API_KEY",
                "api_key": "inline-should-not-win",
                "api_key_ref": "vault-a",
            },
        },
        api_secrets={"vault-a": "from-vault"},
    )
    assert llm.api_key == "from-vault"


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


def test_get_llm_from_config_normalizes_chat_completions_url():
    """误填完整 chat/completions endpoint 时自动裁剪为 API base。"""
    from app.agent.llm_client import get_llm_from_config

    llm = get_llm_from_config("jeniya", {
        "jeniya": {
            "base_url": "https://jeniya.top/v1/chat/completions",
            "model": "gpt-4o",
            "api_key_env": "JENIYA_API_KEY",
        },
    })
    assert llm.base_url == "https://jeniya.top/v1"


def test_get_llm_from_config_upgrades_jeniya_http_to_https():
    """历史 Jeniya http 配置自动升级为 https，避免 301 将 POST 改成 GET。"""
    from app.agent.llm_client import get_llm_from_config

    llm = get_llm_from_config("jeniya", {
        "jeniya": {
            "base_url": "http://jeniya.top/v1",
            "model": "gpt-4o",
            "api_key_env": "JENIYA_API_KEY",
        },
    })
    assert llm.base_url == "https://jeniya.top/v1"


def test_get_llm_from_config_rejects_relative_base_url():
    """只填 /v1 这类相对地址时给出明确配置错误。"""
    from app.agent.llm_client import get_llm_from_config

    with pytest.raises(ValueError, match="完整的 http"):
        get_llm_from_config("bad", {
            "bad": {
                "base_url": "/v1",
                "model": "gpt-4o",
                "api_key_env": "JENIYA_API_KEY",
            },
        })


def test_get_client_adds_qwen_chat_template_kwargs(monkeypatch):
    """Qwen 模型请求附加禁用 thinking 的专属参数。"""
    from app.agent.llm_client import QwenLLM

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_module = types.SimpleNamespace(ChatOpenAI=FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)

    QwenLLM(api_key="test-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="qwen3-max").get_client()

    assert captured["model_kwargs"] == {"extra_body": {"enable_thinking": False}}


def test_get_client_adds_qwen_chat_template_kwargs_for_non_dashscope(monkeypatch):
    """非 DashScope 的 Qwen 兼容服务使用 chat_template_kwargs。"""
    from app.agent.llm_client import QwenLLM

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_module = types.SimpleNamespace(ChatOpenAI=FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)

    QwenLLM(api_key="test-key", base_url="https://example.com/v1", model="qwen3-max").get_client()

    assert captured["model_kwargs"] == {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}


def test_get_client_skips_qwen_chat_template_kwargs_for_other_models(monkeypatch):
    """非 Qwen 模型不传 DashScope/Qwen 专属参数。"""
    from app.agent.llm_client import QwenLLM

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_module = types.SimpleNamespace(ChatOpenAI=FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)

    QwenLLM(api_key="test-key", base_url="https://jeniya.top/v1", model="gpt-4o").get_client()

    assert "model_kwargs" not in captured
