"""测试 LLM 配置化（get_llm_from_config）"""
import os
import sys
import types
import zipfile
from io import BytesIO
import pytest

# 测试前设置 env，避免 QwenLLM 初始化报错
os.environ.setdefault("QWEN_API_KEY", "test-key")
os.environ.setdefault("JENIYA_API_KEY", "test-jeniya-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-key")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("ZHIPUAI_API_KEY", "test-zhipu-key")
os.environ.setdefault("MOONSHOT_API_KEY", "test-moonshot-key")


@pytest.fixture(autouse=True)
def _llm_test_keys(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "test-key")
    monkeypatch.setenv("JENIYA_API_KEY", "test-jeniya-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("ZHIPUAI_API_KEY", "test-zhipu-key")
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-moonshot-key")


def test_builtin_llm_provider_presets_use_compatible_base_urls():
    """后端运行时兜底与设置页默认 provider 地址必须同步且可被当前 ChatOpenAI 客户端调用。"""
    from app.agent.llm_client import _DEFAULT_LLM_PROVIDERS as runtime_defaults
    from app.api.settings_app import _DEFAULT_LLM_PROVIDERS as settings_defaults

    expected = {
        "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "QWEN_API_KEY"),
        "jeniya": ("https://jeniya.top/v1", "JENIYA_API_KEY"),
        "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
        "claude": ("https://jeniya.top/v1", "JENIYA_API_KEY"),
        "glm": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPUAI_API_KEY"),
        "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
        "kimi": ("https://api.moonshot.cn/v1", "MOONSHOT_API_KEY"),
    }

    for provider_id, (base_url, api_key_env) in expected.items():
        assert runtime_defaults[provider_id]["base_url"] == base_url
        assert runtime_defaults[provider_id]["api_key_env"] == api_key_env
        assert settings_defaults[provider_id]["base_url"] == base_url
        assert settings_defaults[provider_id]["api_key_env"] == api_key_env


def test_settings_refreshes_old_jeniya_builtin_provider_presets():
    """旧版本保存下来的内置 Jeniya 中转默认行，应在加载设置时刷新为 provider 原生预设。"""
    from app.api.settings_app import _refresh_builtin_llm_provider_presets

    providers = {
        "deepseek": {
            "base_url": "https://jeniya.top/v1",
            "model": "deepseek-chat",
            "api_key_env": "JENIYA_API_KEY",
        },
        "custom-jeniya-deepseek": {
            "base_url": "https://jeniya.top/v1",
            "model": "deepseek-chat",
            "api_key_env": "JENIYA_API_KEY",
            "api_key_ref": "user-vault",
        },
    }

    out = _refresh_builtin_llm_provider_presets(providers)

    assert out["deepseek"]["base_url"] == "https://api.deepseek.com"
    assert out["deepseek"]["api_key_env"] == "DEEPSEEK_API_KEY"
    assert out["custom-jeniya-deepseek"]["base_url"] == "https://jeniya.top/v1"


def test_llm_bundle_zip_roundtrip_omits_plaintext_api_key():
    """模型包应包含完整非密钥配置与调用参数，但不得导出 API Key 明文。"""
    from app.core.llm_bundle import (
        LLM_MANIFEST_NAME,
        build_llm_bundle_zip_bytes,
        read_llm_bundle_manifest,
    )
    from app.core.scenario_bundle import extract_scenario_bundle_dir

    provider = {
        "base_url": "https://example.test/v1",
        "model": "example-chat",
        "api_key": "plain-secret",
        "api_key_env": "EXAMPLE_API_KEY",
        "api_key_ref": "vault-example",
        "api_key_set": True,
        "temperature": 0.2,
        "max_tokens": 128,
        "top_p": 0.9,
        "extra_body": {"enable_thinking": False},
    }

    raw = build_llm_bundle_zip_bytes("example", provider, default_llm="example")
    with zipfile.ZipFile(BytesIO(raw)) as zf:
        assert LLM_MANIFEST_NAME in zf.namelist()
        manifest_text = zf.read(LLM_MANIFEST_NAME).decode("utf-8")
    assert "plain-secret" not in manifest_text

    bundle_dir = extract_scenario_bundle_dir(raw)
    try:
        _manifest, provider_id, bundled = read_llm_bundle_manifest(bundle_dir)
    finally:
        import shutil

        shutil.rmtree(bundle_dir, ignore_errors=True)

    assert provider_id == "example"
    assert bundled["base_url"] == "https://example.test/v1"
    assert bundled["model"] == "example-chat"
    assert bundled["api_key_env"] == "EXAMPLE_API_KEY"
    assert bundled["api_key_ref"] == "vault-example"
    assert bundled["api_key_set"] is True
    assert bundled["temperature"] == 0.2
    assert bundled["max_tokens"] == 128
    assert bundled["top_p"] == 0.9
    assert bundled["extra_body"] == {"enable_thinking": False}
    assert "api_key" not in bundled


def test_get_llm_from_config_qwen():
    """使用 qwen provider 新建 LLM"""
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
    """使用 jeniya provider 新建 LLM"""
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


def test_get_llm_from_config_provider_id_is_case_insensitive():
    """provider id 大小写不应导致误回退到 qwen。"""
    from app.agent.llm_client import get_llm_from_config

    llm = get_llm_from_config("JENIYA", {
        "jeniya": {
            "base_url": "https://jeniya.top/v1",
            "model": "gpt-4o",
            "api_key_env": "JENIYA_API_KEY",
        },
        "qwen": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen3-max",
            "api_key_env": "QWEN_API_KEY",
        },
    })
    assert llm.base_url == "https://jeniya.top/v1"
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


def test_get_client_default_request_timeout_is_interactive_budget(monkeypatch):
    """默认单次 LLM HTTP 等待不要过长；慢模型可用 provider 配置单独放大。"""
    from app.agent.llm_client import QwenLLM

    monkeypatch.delenv("QWEN_REQUEST_TIMEOUT", raising=False)
    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(api_key="test-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="qwen3-max"),
    )

    assert captured["request_timeout"] == 60


def test_get_client_request_timeout_provider_config_can_extend_default(monkeypatch):
    """provider 配置中的 request_timeout 默认生效，不被隐式 10s 上限截断。"""
    from app.agent.llm_client import QwenLLM

    monkeypatch.delenv("QWEN_REQUEST_TIMEOUT", raising=False)
    monkeypatch.delenv("QWEN_REQUEST_TIMEOUT_MAX", raising=False)
    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(
            api_key="test-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3-max",
            provider_config={"request_timeout": 180},
        ),
    )

    assert captured["request_timeout"] == 180


def test_get_client_default_max_retries_is_zero(monkeypatch):
    """默认失败即失败，避免一次请求超时后继续重试拖慢前端反馈。"""
    from app.agent.llm_client import QwenLLM

    monkeypatch.delenv("QWEN_MAX_RETRIES", raising=False)
    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(api_key="test-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="qwen3-max"),
    )

    assert captured["max_retries"] == 0


def test_get_client_request_timeout_can_be_capped_by_env(monkeypatch):
    """需要快速失败时，可显式设置 QWEN_REQUEST_TIMEOUT_MAX 做上限。"""
    from app.agent.llm_client import QwenLLM

    monkeypatch.delenv("QWEN_REQUEST_TIMEOUT", raising=False)
    monkeypatch.setenv("QWEN_REQUEST_TIMEOUT_MAX", "30")
    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(
            api_key="test-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3-max",
            provider_config={"request_timeout": 180},
        ),
    )

    assert captured["request_timeout"] == 30


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
            base_url="https://api.deepseek.com",
            model="deepseek-reasoner",
            provider_config={"thinking": True},
        ),
    )

    assert captured["model_kwargs"] == {"extra_body": {"thinking": {"type": "enabled"}}}
    assert bind_tools_compat(client, [object()]) == {}


def test_get_client_deepseek_defaults_to_thinking_disabled(monkeypatch):
    """DeepSeek 未显式设置 thinking 时默认关闭，避免网关走不可用默认模式。"""
    from app.agent.llm_client import QwenLLM

    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        QwenLLM(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            provider_config={},
        ),
    )

    assert captured["model_kwargs"] == {"extra_body": {"thinking": {"type": "disabled"}}}
