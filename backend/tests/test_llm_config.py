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


def _capture_chat_kwargs(monkeypatch, llm):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.bound_calls = []

        def bind_tools(self, tools, **kwargs):
            self.bound_calls.append(kwargs)
            return kwargs

    fake_module = types.SimpleNamespace(ChatOpenAI=FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    client = llm.get_client()
    return captured, client


def test_get_client_common_whitelisted_params(monkeypatch):
    """通用官网参数会被传给 ChatOpenAI，且不会开放任意 kwargs。"""
    from app.agent.llm_client import QwenLLM

    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(
            api_key="test-key",
            base_url="https://jeniya.top/v1",
            model="gpt-4o",
            provider_config={
                "temperature": 0.2,
                "top_p": 0.8,
                "max_tokens": 32,
                "presence_penalty": 0.1,
                "frequency_penalty": 0.2,
                "seed": 42,
                "client_kwargs": {"danger": True},
                "disabled_params": ["max_tokens"],
            },
        ),
    )

    assert captured["temperature"] == 0.2
    assert captured["top_p"] == 0.8
    assert captured["max_tokens"] == 32
    assert captured["presence_penalty"] == 0.1
    assert captured["frequency_penalty"] == 0.2
    assert captured["seed"] == 42
    assert "danger" not in captured
    assert captured["max_tokens"] == 32


def test_get_client_default_omits_max_tokens(monkeypatch):
    """默认不主动传 max_tokens，交给具体模型/网关默认值处理。"""
    from app.agent.llm_client import QwenLLM

    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(api_key="test-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="qwen3-max"),
    )

    assert "max_tokens" not in captured


def test_traced_client_preserves_wrapper_after_bind_tools(monkeypatch):
    """工具绑定后仍保留 trace/thinking 包装。"""
    from app.agent.llm_client import QwenLLM

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def bind_tools(self, tools, **kwargs):
            return self

    fake_module = types.SimpleNamespace(ChatOpenAI=FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)

    client = QwenLLM(api_key="test-key", base_url="https://example.com/v1", model="gpt-4o").get_client()
    bound = client.bind_tools([object()])

    assert hasattr(bound, "_raw_client")


def test_get_client_qwen_thinking_params_and_tool_choice(monkeypatch):
    """Qwen thinking 开启时走 extra_body，工具绑定不传 required。"""
    from app.agent.llm_client import QwenLLM, bind_tools_compat

    captured, client = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(
            api_key="test-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3-max",
            provider_config={"enable_thinking": True, "thinking_budget": 64},
        ),
    )

    assert captured["model_kwargs"] == {"extra_body": {"enable_thinking": True, "thinking_budget": 64}}
    assert bind_tools_compat(client, [object()]) == {}


def test_get_client_qwen_thinking_disabled_keeps_required_tools(monkeypatch):
    """Qwen thinking 显式关闭时仍允许 required tool_choice。"""
    from app.agent.llm_client import QwenLLM, bind_tools_compat

    captured, client = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(
            api_key="test-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3-max",
            provider_config={"enable_thinking": False},
        ),
    )

    assert captured["model_kwargs"] == {"extra_body": {"enable_thinking": False}}
    assert bind_tools_compat(client, [object()]) == {"tool_choice": "required"}


def test_get_client_gemini_params(monkeypatch):
    """Gemini 专属 topK/thinkingConfig 映射到请求体扩展。"""
    from app.agent.llm_client import QwenLLM

    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(
            api_key="test-key",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            model="gemini-2.5-flash",
            provider_config={"top_k": 20, "gemini_thinking_level": "low"},
        ),
    )

    assert captured["model_kwargs"] == {"extra_body": {"topK": 20, "thinkingConfig": {"thinkingLevel": "low"}}}


def test_get_client_claude_top_k(monkeypatch):
    """Claude 专属 top_k 映射到请求体扩展。"""
    from app.agent.llm_client import QwenLLM

    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(
            api_key="test-key",
            base_url="https://api.anthropic.com/v1",
            model="claude-sonnet-4-6",
            provider_config={"top_k": 30},
        ),
    )

    assert captured["model_kwargs"] == {"extra_body": {"top_k": 30}}


def test_get_client_glm_params(monkeypatch):
    """GLM thinking/do_sample 映射到请求体扩展。"""
    from app.agent.llm_client import QwenLLM

    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(
            api_key="test-key",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            model="glm-4.7",
            provider_config={"thinking": False, "do_sample": False},
        ),
    )

    assert captured["model_kwargs"] == {"extra_body": {"thinking": {"type": "disabled"}, "do_sample": False}}


def test_get_client_deepseek_thinking_enabled_disables_required_tools(monkeypatch):
    """DeepSeek thinking 开启时同样不强制 required tool_choice。"""
    from app.agent.llm_client import QwenLLM, bind_tools_compat

    captured, client = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(
            api_key="test-key",
            base_url="https://api.deepseek.com/v1",
            model="deepseek-reasoner",
            provider_config={"thinking": True},
        ),
    )

    assert captured["model_kwargs"] == {"extra_body": {"thinking": {"type": "enabled"}}}
    assert bind_tools_compat(client, [object()]) == {}
