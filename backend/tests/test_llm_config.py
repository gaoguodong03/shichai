"""测试 LLM 配置化（get_llm_from_config）"""
import json
import os
import zipfile
from io import BytesIO
import pytest

# 测试前设置 env，避免 LLM 客户端初始化报错
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


def test_traced_llm_client_logs_prompt_summary_by_default(caplog, monkeypatch):
    import asyncio
    import logging

    from app.agent.messages import HumanMessage, SystemMessage

    from app.agent.llm_client import _instrument_llm_client
    monkeypatch.delenv("PROMPT_LOG_MODE", raising=False)

    class RawClient:
        async def ainvoke(self, inp, *args, **kwargs):
            return "async-ok"

        def invoke(self, inp, *args, **kwargs):
            return "sync-ok"

        async def astream(self, inp, *args, **kwargs):
            yield "stream-ok"

        def stream(self, inp, *args, **kwargs):
            yield "sync-stream-ok"

    async def collect_stream(stream):
        return [item async for item in stream]

    client = _instrument_llm_client(
        RawClient(),
        provider_base_url="https://example.test/v1",
        model_name="test-model",
    )

    with caplog.at_level(logging.INFO, logger="app.agent.llm_client"):
        assert asyncio.run(
            client.ainvoke(
                [
                    SystemMessage(content="系统提示词全文"),
                    HumanMessage(content="用户提示词全文"),
                ]
            )
        ) == "async-ok"
        assert client.invoke("直接字符串提示词全文") == "sync-ok"
        assert asyncio.run(collect_stream(client.astream([HumanMessage(content="流式提示词全文")]))) == ["stream-ok"]
        assert list(client.stream([HumanMessage(content="同步流式提示词全文")])) == ["sync-stream-ok"]

    assert caplog.text.count("[Prompt]") == 4
    assert "method=ainvoke" in caplog.text
    assert "method=invoke" in caplog.text
    assert "method=astream" in caplog.text
    assert "method=stream" in caplog.text
    assert "model=test-model" in caplog.text
    assert "input_messages=" in caplog.text
    assert "prompt_chars=" in caplog.text
    assert "系统提示词全文" not in caplog.text
    assert "用户提示词全文" not in caplog.text
    assert "直接字符串提示词全文" not in caplog.text
    assert "流式提示词全文" not in caplog.text
    assert "同步流式提示词全文" not in caplog.text


def test_traced_llm_client_logs_full_prompt_when_enabled(caplog, monkeypatch):
    import asyncio
    import logging

    from app.agent.messages import HumanMessage, SystemMessage

    from app.agent.llm_client import _instrument_llm_client
    monkeypatch.setenv("PROMPT_LOG_MODE", "full")

    class RawClient:
        async def ainvoke(self, inp, *args, **kwargs):
            return "async-ok"

    client = _instrument_llm_client(
        RawClient(),
        provider_base_url="https://example.test/v1",
        model_name="test-model",
    )

    with caplog.at_level(logging.INFO, logger="app.agent.llm_client"):
        assert asyncio.run(
            client.ainvoke(
                [
                    SystemMessage(content="系统提示词全文"),
                    HumanMessage(content="用户提示词全文"),
                ]
            )
        ) == "async-ok"

    assert "[Prompt]" in caplog.text
    assert "mode=full" in caplog.text
    assert "系统提示词全文" in caplog.text
    assert "用户提示词全文" in caplog.text


def test_builtin_llm_provider_presets_use_compatible_base_urls():
    """后端运行时默认 provider 与设置页默认 provider 地址必须同步且可被 OpenAI 兼容客户端调用。"""
    from app.agent.llm_client import _DEFAULT_LLM_PROVIDERS as runtime_defaults
    from app.api.settings_app import _DEFAULT_LLM_PROVIDERS as settings_defaults

    expected = {
        "qwen3-max": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "QWEN_API_KEY"),
        "gpt-4o": ("https://jeniya.top/v1", "JENIYA_API_KEY"),
        "gemini-3-pro-preview": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
        "claude-sonnet-4-6": ("https://jeniya.top/v1", "JENIYA_API_KEY"),
        "glm-4.7": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPUAI_API_KEY"),
        "deepseek-chat": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
        "moonshot-v1-128k": ("https://api.moonshot.cn/v1", "MOONSHOT_API_KEY"),
    }

    for provider_id, (base_url, api_key_env) in expected.items():
        assert runtime_defaults[provider_id]["base_url"] == base_url
        assert runtime_defaults[provider_id]["api_key_env"] == api_key_env
        assert settings_defaults[provider_id]["base_url"] == base_url
        assert settings_defaults[provider_id]["api_key_env"] == api_key_env


def test_builtin_llm_provider_names_are_model_names():
    from app.api.settings_app import _refresh_builtin_llm_provider_presets

    out = _refresh_builtin_llm_provider_presets({})

    assert sorted(out) == sorted(row["model"] for row in out.values())


def test_app_settings_preserves_top_level_system_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("ALLOW_ANONYMOUS_API", "1")

    from app.core.user_context import reset_current_user_identity, set_current_user_identity
    from app.api.settings_app import load_app_settings, save_app_settings

    token = set_current_user_identity(user_id="u-settings", username="u-settings")
    try:
        save_app_settings({"system_prompt": "全局项目规则"})

        assert load_app_settings()["system_prompt"] == "全局项目规则"
    finally:
        reset_current_user_identity(token)


def test_app_settings_does_not_inject_project_prompt_when_registration_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("ALLOW_ANONYMOUS_API", "1")

    from app.core.user_context import reset_current_user_identity, set_current_user_identity
    from app.api.settings_app import load_app_settings

    token = set_current_user_identity(user_id="u-settings-default", username="u-settings-default")
    try:
        assert load_app_settings()["system_prompt"] == ""
    finally:
        reset_current_user_identity(token)


def test_app_settings_preserves_explicit_empty_system_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("ALLOW_ANONYMOUS_API", "1")

    from app.core.user_context import reset_current_user_identity, set_current_user_identity
    from app.api.settings_app import load_app_settings, save_app_settings

    token = set_current_user_identity(user_id="u-settings-empty", username="u-settings-empty")
    try:
        save_app_settings({"system_prompt": ""})

        assert load_app_settings()["system_prompt"] == ""
    finally:
        reset_current_user_identity(token)


def test_llm_bundle_zip_roundtrip_keeps_env_reference_without_plaintext_api_key():
    """模型包使用资源包镜像结构，保留环境变量引用但不导出 API Key 明文。"""
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
        "api_key_set": True,
        "label": "Example Chat",
        "temperature": 0.2,
        "max_tokens": 128,
        "top_p": 0.9,
        "extra_body": {"enable_thinking": False},
    }

    raw = build_llm_bundle_zip_bytes("example", provider, default_llm="example")
    with zipfile.ZipFile(BytesIO(raw)) as zf:
        names = set(zf.namelist())
        assert LLM_MANIFEST_NAME in zf.namelist()
        assert "llm_bundle.json" not in names
        manifest = json.loads(zf.read(LLM_MANIFEST_NAME).decode("utf-8"))
        assert manifest["bundle_type"] == "model"
        assert "bundle_version" not in manifest
        manifest_text = zf.read("resources/models/example/model.json").decode("utf-8")
    manifest = json.loads(manifest_text)
    manifest_provider = manifest
    assert manifest_provider["name"] == "example"
    assert "plain-secret" not in manifest_text
    assert "api_key" not in manifest_provider
    assert manifest_provider["api_key_env"] == "EXAMPLE_API_KEY"
    assert "label" not in manifest_provider

    bundle_dir = extract_scenario_bundle_dir(raw)
    try:
        _manifest, provider_id, bundled = read_llm_bundle_manifest(bundle_dir)
    finally:
        import shutil

        shutil.rmtree(bundle_dir, ignore_errors=True)

    assert provider_id == "example"
    assert bundled["base_url"] == "https://example.test/v1"
    assert bundled["model"] == "example-chat"
    assert "api_key" not in bundled
    assert bundled["api_key_env"] == "EXAMPLE_API_KEY"
    assert "label" not in bundled
    assert "api_key_set" not in bundled
    assert bundled["temperature"] == 0.2
    assert bundled["max_tokens"] == 128
    assert bundled["top_p"] == 0.9
    assert bundled["extra_body"] == {"enable_thinking": False}


def test_llm_provider_row_sanitizer_drops_inline_api_key_fields():
    from app.api.settings_app import _sanitize_llm_provider_row

    row = _sanitize_llm_provider_row(
        {
            "model": "qwen3-max",
            "api_key_env": "QWEN_API_KEY",
            "api_key": "inline-secret",
            "api_key_set": True,
            "label": "旧展示名",
        }
    )

    assert row == {"model": "qwen3-max", "api_key_env": "QWEN_API_KEY"}


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


def test_resolve_llm_api_key_prefers_user_env_var_store(monkeypatch):
    from app.agent.llm_client import resolve_llm_api_key

    monkeypatch.setenv("JENIYA_API_KEY", "from-host-env")
    cfg = {
        "api_key_env": "JENIYA_API_KEY",
        "api_key": "inline-should-not-win",
    }
    assert resolve_llm_api_key(cfg, {"JENIYA_API_KEY": "from-user-env"}) == "from-user-env"


def test_resolve_llm_api_key_ignores_inline_api_key_without_env_reference(monkeypatch):
    from app.agent.llm_client import resolve_llm_api_key

    monkeypatch.delenv("JENIYA_API_KEY", raising=False)

    assert resolve_llm_api_key({"api_key": "inline-secret"}) is None


def test_build_llm_credential_notice_mentions_model():
    from app.agent.llm_client import build_llm_credential_notice

    notice = build_llm_credential_notice(
        "qwen",
        {"model": "qwen3-max", "label": "通义千问"},
    )
    assert "qwen3-max" in notice
    assert "通义千问" not in notice
    assert "没有配置密钥或密钥错误" in notice
    assert "设置 → 环境变量" in notice
    assert "api_key_env" in notice
    assert "设置 → 密钥" not in notice
    assert "选择密钥" not in notice


def test_llm_credential_notice_for_agent_when_key_missing(monkeypatch):
    from app.agent.group_chat_expert_resolution import _llm_credential_notice_for_agent

    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    notice = _llm_credential_notice_for_agent(
        None,
        {
            "default_llm": "qwen3-max",
            "llm_providers": {
                "qwen3-max": {
                    "model": "qwen3-max",
                    "api_key_env": "QWEN_API_KEY",
                }
            },
        },
    )
    assert notice is not None
    assert "qwen3-max" in notice


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


def test_get_llm_from_config_api_key_env_uses_user_env_var_store(monkeypatch):
    """api_key_env 优先读取平台内用户级环境变量，其次才读宿主机环境变量。"""
    from app.agent.llm_client import get_llm_from_config

    monkeypatch.setenv("JENIYA_API_KEY", "from-host-env")
    llm = get_llm_from_config(
        "jeniya",
        {
            "jeniya": {
                "base_url": "https://jeniya.top/v1",
                "model": "gpt-4o",
                "api_key_env": "JENIYA_API_KEY",
                "api_key": "inline-should-not-win",
            },
        },
        env_vars={"JENIYA_API_KEY": "from-user-env"},
    )
    assert llm.api_key == "from-user-env"


def test_resolve_llm_provider_entry_keeps_missing_model_reference():
    """缺失模型引用是资源完整性问题，不静默回退到其他模型。"""
    from app.agent.llm_client import resolve_llm_provider_entry

    resolved_name, cfg = resolve_llm_provider_entry(
        "unknown",
        {
            "qwen3-max": {
                "base_url": "https://fallback/v1",
                "model": "qwen",
                "api_key_env": "QWEN_API_KEY",
            },
        },
    )

    assert resolved_name == "unknown"
    assert cfg == {}


def test_get_llm_from_config_rejects_missing_model_reference():
    """运行时不能把缺失模型引用兜底成 qwen3-max。"""
    from app.agent.llm_client import get_llm_from_config

    with pytest.raises(ValueError, match="模型配置不存在：unknown"):
        get_llm_from_config(
            "unknown",
            {
                "qwen3-max": {
                    "base_url": "https://fallback/v1",
                    "model": "qwen",
                    "api_key_env": "QWEN_API_KEY",
                },
            },
        )


def test_missing_llm_config_does_not_borrow_default_api_key(monkeypatch):
    """缺失模型配置不能借默认 QWEN_API_KEY 伪装成可用配置。"""
    from app.agent.llm_client import resolve_llm_api_key

    monkeypatch.setenv("QWEN_API_KEY", "host-default-key")

    assert resolve_llm_api_key({}) is None


def test_get_llm_from_config_requires_explicit_api_key_env(monkeypatch):
    """模型资源必须显式声明 api_key_env，不能从 base_url 猜宿主机变量。"""
    from app.agent.llm_client import get_llm_from_config

    monkeypatch.setenv("QWEN_API_KEY", "host-default-key")

    with pytest.raises(ValueError, match="api_key_env"):
        get_llm_from_config(
            "qwen",
            {
                "qwen": {
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "model": "qwen3-max",
                }
            },
        )


def test_llm_client_constructor_requires_resolved_api_key(monkeypatch):
    """底层客户端不能按 base_url 从宿主机环境变量推断凭据。"""
    from app.agent.llm_client import LLMClient

    monkeypatch.setenv("QWEN_API_KEY", "host-qwen-key")
    monkeypatch.setenv("JENIYA_API_KEY", "host-jeniya-key")
    monkeypatch.setenv("OPENAI_API_KEY", "host-openai-key")

    with pytest.raises(ValueError, match="缺少 API Key"):
        LLMClient(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="qwen3-max")

    with pytest.raises(ValueError, match="缺少 API Key"):
        LLMClient(base_url="https://jeniya.top/v1", model="gpt-4o")


def test_get_llm_from_config_empty_uses_default():
    """空配置使用默认 provider"""
    from app.agent.llm_client import get_llm_from_config

    llm = get_llm_from_config("qwen3-max", None)
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


def _capture_chat_kwargs(monkeypatch, llm):
    del monkeypatch
    client = llm.get_client()
    raw = client._raw_client
    captured = {
        **raw._request_options,
        "api_key": raw._client_options.get("api_key"),
        "base_url": raw._client_options.get("base_url"),
        "request_timeout": raw._client_options.get("timeout"),
        "max_retries": raw._client_options.get("max_retries"),
        "model": raw._model,
        "litellm_model": raw._litellm_model,
    }
    return captured, client


def test_get_client_does_not_auto_inject_extra_body(monkeypatch):
    """系统不会按厂商自动补专属参数；未配置 extra_body 时请求中不出现。"""
    from app.agent.llm_client import LLMClient

    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(api_key="test-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="qwen3-max"),
    )
    assert "extra_body" not in captured

    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(api_key="test-key", base_url="https://api.deepseek.com", model="deepseek-chat"),
    )
    assert "extra_body" not in captured


def test_get_client_passes_configured_extra_body_as_is(monkeypatch):
    """extra_body 完全以模型配置为准，不做 Provider 推导。"""
    from app.agent.llm_client import LLMClient

    extra = {"enable_thinking": False, "thinking_budget": 32}
    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(
            api_key="test-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3-max",
            provider_config={"extra_body": extra},
        ),
    )
    assert captured["extra_body"] == extra


def test_parameter_mapper_migrates_legacy_flat_fields_into_extra_body(monkeypatch):
    """旧版顶层专属字段在调用前折叠进 extra_body（兼容迁移，非厂商推断）。"""
    from app.agent.llm_client import LLMClient

    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="any-model",
            provider_config={
                "enable_thinking": True,
                "thinking_budget": 64,
                "thinking": True,
                "do_sample": False,
                "top_k": 20,
                "gemini_thinking_level": "low",
            },
        ),
    )
    assert captured["extra_body"] == {
        "enable_thinking": True,
        "thinking_budget": 64,
        "thinking": {"type": "enabled"},
        "do_sample": False,
        "top_k": 20,
        "thinkingConfig": {"thinkingLevel": "low"},
    }


def test_get_client_common_params(monkeypatch):
    """公共参数作为独立字段进入 LiteLLM kwargs；连接无关字段不透传。"""
    from app.agent.llm_client import LLMClient

    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(
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


def test_get_client_default_omits_max_tokens(monkeypatch):
    """默认不主动传 max_tokens，交给具体模型/网关默认值处理。"""
    from app.agent.llm_client import LLMClient

    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(api_key="test-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="qwen3-max"),
    )
    assert "max_tokens" not in captured


def test_get_client_default_request_timeout_is_interactive_budget(monkeypatch):
    from app.agent.llm_client import LLMClient

    monkeypatch.delenv("QWEN_REQUEST_TIMEOUT", raising=False)
    monkeypatch.delenv("LLM_REQUEST_TIMEOUT", raising=False)
    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(api_key="test-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="qwen3-max"),
    )
    assert captured["request_timeout"] == 60


def test_get_client_request_timeout_comes_from_env_not_model_config(monkeypatch):
    """超时由环境变量控制，不再作为模型公共参数读取。"""
    from app.agent.llm_client import LLMClient

    monkeypatch.delenv("QWEN_REQUEST_TIMEOUT_MAX", raising=False)
    monkeypatch.delenv("LLM_REQUEST_TIMEOUT_MAX", raising=False)
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "180")
    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(
            api_key="test-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3-max",
            provider_config={"request_timeout": 999, "timeout": 999},
        ),
    )
    assert captured["request_timeout"] == 180


def test_get_client_default_max_retries_is_zero(monkeypatch):
    from app.agent.llm_client import LLMClient

    monkeypatch.delenv("QWEN_MAX_RETRIES", raising=False)
    monkeypatch.delenv("LLM_MAX_RETRIES", raising=False)
    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(api_key="test-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="qwen3-max"),
    )
    assert captured["max_retries"] == 0


def test_get_client_request_timeout_can_be_capped_by_env(monkeypatch):
    from app.agent.llm_client import LLMClient

    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "180")
    monkeypatch.setenv("QWEN_REQUEST_TIMEOUT_MAX", "30")
    captured, _ = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(
            api_key="test-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3-max",
        ),
    )
    assert captured["request_timeout"] == 30


def test_traced_client_preserves_wrapper_after_bind_tools(monkeypatch):
    from app.agent.llm_client import LLMClient

    client = LLMClient(api_key="test-key", base_url="https://example.com/v1", model="gpt-4o").get_client()
    bound = client.bind_tools([object()])
    assert hasattr(bound, "_raw_client")


def _bound_tool_choice(bound_client):
    return bound_client._raw_client._tool_choice


def test_extra_body_thinking_disables_required_tools(monkeypatch):
    """思考模式由配置 extra_body 决定，开启时 tool_choice 不强制 required。"""
    from app.agent.llm_client import LLMClient, bind_tools_compat

    captured, client = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="any-model",
            provider_config={"extra_body": {"enable_thinking": True, "thinking_budget": 64}},
        ),
    )
    assert captured["extra_body"] == {"enable_thinking": True, "thinking_budget": 64}
    assert _bound_tool_choice(bind_tools_compat(client, [object()])) is None


def test_extra_body_thinking_disabled_keeps_required_tools(monkeypatch):
    from app.agent.llm_client import LLMClient, bind_tools_compat

    captured, client = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="any-model",
            provider_config={"extra_body": {"enable_thinking": False}},
        ),
    )
    assert captured["extra_body"] == {"enable_thinking": False}
    assert _bound_tool_choice(bind_tools_compat(client, [object()])) == "required"


def test_bind_tools_compat_allows_one_agent_turn_to_choose_tools_or_finish(monkeypatch):
    from app.agent.llm_client import LLMClient, bind_tools_compat

    _, client = _capture_chat_kwargs(
        monkeypatch,
        LLMClient(api_key="test-key", base_url="https://example.com/v1", model="gpt-4o"),
    )
    bound = bind_tools_compat(client, [object()], tool_choice_strategy="auto")
    assert _bound_tool_choice(bound) is None


def test_resolve_litellm_model_id_from_config_provider():
    from app.agent.llm_parameter_mapper import resolve_litellm_model_id

    assert resolve_litellm_model_id({"provider": "deepseek", "model": "deepseek-chat"}) == "deepseek/deepseek-chat"
    assert resolve_litellm_model_id({"provider": "openai", "model": "qwen3-max"}) == "openai/qwen3-max"
    assert resolve_litellm_model_id({"model": "gpt-4o"}) == "openai/gpt-4o"
    assert resolve_litellm_model_id({"model": "gpt-4o", "litellm_model": "openai/custom-gpt"}) == "openai/custom-gpt"
    assert resolve_litellm_model_id({"provider": "anthropic", "model": "claude-sonnet-4-6"}) == "anthropic/claude-sonnet-4-6"


def test_builtin_defaults_carry_extra_body_not_flat_vendor_fields():
    from app.agent.llm_client import _DEFAULT_LLM_PROVIDERS as runtime_defaults
    from app.api.settings_app import _DEFAULT_LLM_PROVIDERS as settings_defaults

    assert runtime_defaults == settings_defaults
    assert runtime_defaults["qwen3-max"]["extra_body"] == {"enable_thinking": False}
    assert runtime_defaults["deepseek-chat"]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "thinking" not in runtime_defaults["deepseek-chat"]
    assert runtime_defaults["deepseek-chat"]["provider"] == "deepseek"


def test_get_client_uses_litellm_completion(monkeypatch):
    """实际调用走 litellm.acompletion / completion，并经 Parameter Mapper 组装 kwargs。"""
    import asyncio
    from types import SimpleNamespace

    from app.agent.llm_client import LLMClient
    from app.agent.messages import HumanMessage

    captured = {}

    class FakeResponse:
        choices = [
            SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=None),
                finish_reason="stop",
            )
        ]

    def fake_completion(**kwargs):
        captured["sync"] = kwargs
        return FakeResponse()

    async def fake_acompletion(**kwargs):
        captured["async"] = kwargs
        return FakeResponse()

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.acompletion", fake_acompletion)

    client = LLMClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        provider_config={
            "provider": "deepseek",
            "extra_body": {"thinking": {"type": "disabled"}},
        },
    ).get_client()

    assert client.invoke([HumanMessage(content="hi")]).content == "ok"
    assert asyncio.run(client.ainvoke([HumanMessage(content="hi")])).content == "ok"

    assert captured["sync"]["model"] == "deepseek/deepseek-chat"
    assert captured["async"]["model"] == "deepseek/deepseek-chat"
    assert captured["sync"]["api_base"] == "https://api.deepseek.com"
    assert captured["sync"]["api_key"] == "test-key"
    assert captured["sync"]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert captured["sync"]["num_retries"] == 0
