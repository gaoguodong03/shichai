"""Unit tests for llm_parameter_mapper — no network, no API keys required."""
import os

import pytest


# ---------------------------------------------------------------------------
# resolve_extra_body — legacy flat-field migration
# ---------------------------------------------------------------------------


class TestResolveExtraBody:
    def test_empty_config(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({}) == {}

    def test_extra_body_passthrough(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        cfg = {"extra_body": {"top_k": 50, "thinking": {"type": "enabled"}}}
        assert resolve_extra_body(cfg) == {"top_k": 50, "thinking": {"type": "enabled"}}

    def test_extra_body_wins_over_legacy_flat(self):
        """When extra_body already has a key, legacy flat value is ignored."""
        from app.agent.llm_parameter_mapper import resolve_extra_body

        cfg = {
            "extra_body": {"enable_thinking": True},
            "enable_thinking": False,
        }
        assert resolve_extra_body(cfg) == {"enable_thinking": True}

    # -- legacy enable_thinking migration --

    def test_legacy_enable_thinking_true(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"enable_thinking": True}) == {"enable_thinking": True}

    def test_legacy_enable_thinking_false(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"enable_thinking": False}) == {"enable_thinking": False}

    def test_legacy_enable_thinking_non_bool_ignored(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"enable_thinking": "yes"}) == {}

    # -- legacy thinking_budget migration --

    def test_legacy_thinking_budget_int(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"thinking_budget": 100}) == {"thinking_budget": 100}

    def test_legacy_thinking_budget_string_int(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"thinking_budget": "50"}) == {"thinking_budget": 50}

    def test_legacy_thinking_budget_empty_ignored(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"thinking_budget": ""}) == {}

    def test_legacy_thinking_budget_none_ignored(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"thinking_budget": None}) == {}

    # -- legacy thinking (DeepSeek / GLM) migration --

    def test_legacy_thinking_bool_true(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"thinking": True}) == {"thinking": {"type": "enabled"}}

    def test_legacy_thinking_bool_false(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"thinking": False}) == {"thinking": {"type": "disabled"}}

    def test_legacy_thinking_dict_passthrough(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"thinking": {"type": "enabled", "budget": 100}}) == {
            "thinking": {"type": "enabled", "budget": 100}
        }

    # -- legacy do_sample (GLM) migration --

    def test_legacy_do_sample_true(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"do_sample": True}) == {"do_sample": True}

    def test_legacy_do_sample_false(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"do_sample": False}) == {"do_sample": False}

    def test_legacy_do_sample_non_bool_ignored(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"do_sample": "true"}) == {}

    # -- legacy top_k (Gemini / Claude) migration --

    def test_legacy_top_k(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"top_k": 20}) == {"top_k": 20}

    def test_legacy_top_k_ignored_when_topK_in_extra_body(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        cfg = {"extra_body": {"topK": 40}, "top_k": 20}
        assert resolve_extra_body(cfg) == {"topK": 40}

    # -- legacy gemini_thinking_level migration --

    def test_legacy_gemini_thinking_level_low(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        assert resolve_extra_body({"gemini_thinking_level": "low"}) == {
            "thinkingConfig": {"thinkingLevel": "low"}
        }

    def test_legacy_gemini_thinking_level_ignored_when_thinkingConfig_present(self):
        from app.agent.llm_parameter_mapper import resolve_extra_body

        cfg = {
            "extra_body": {"thinkingConfig": {"thinkingLevel": "high"}},
            "gemini_thinking_level": "low",
        }
        assert resolve_extra_body(cfg) == {"thinkingConfig": {"thinkingLevel": "high"}}


# ---------------------------------------------------------------------------
# thinking_mode_enabled
# ---------------------------------------------------------------------------


class TestThinkingModeEnabled:
    def test_empty_config(self):
        from app.agent.llm_parameter_mapper import thinking_mode_enabled

        assert thinking_mode_enabled({}) is False

    def test_enable_thinking_true(self):
        from app.agent.llm_parameter_mapper import thinking_mode_enabled

        assert thinking_mode_enabled({"enable_thinking": True}) is True

    def test_enable_thinking_false(self):
        from app.agent.llm_parameter_mapper import thinking_mode_enabled

        assert thinking_mode_enabled({"enable_thinking": False}) is False

    def test_thinking_dict_enabled(self):
        from app.agent.llm_parameter_mapper import thinking_mode_enabled

        assert thinking_mode_enabled({"thinking": True}) is True

    def test_thinking_dict_disabled(self):
        from app.agent.llm_parameter_mapper import thinking_mode_enabled

        assert thinking_mode_enabled({"thinking": False}) is False

    def test_thinking_config_present(self):
        from app.agent.llm_parameter_mapper import thinking_mode_enabled

        assert thinking_mode_enabled({"gemini_thinking_level": "low"}) is True

    def test_deepseek_thinking_enabled_via_extra_body(self):
        from app.agent.llm_parameter_mapper import thinking_mode_enabled

        assert (
            thinking_mode_enabled({"extra_body": {"thinking": {"type": "enabled"}}}) is True
        )

    def test_deepseek_thinking_disabled_via_extra_body(self):
        from app.agent.llm_parameter_mapper import thinking_mode_enabled

        assert (
            thinking_mode_enabled({"extra_body": {"thinking": {"type": "disabled"}}}) is False
        )


# ---------------------------------------------------------------------------
# resolve_litellm_model_id
# ---------------------------------------------------------------------------


class TestResolveLitellmModelId:
    def test_explicit_litellm_model_wins(self):
        from app.agent.llm_parameter_mapper import resolve_litellm_model_id

        cfg = {"litellm_model": "bedrock/anthropic.claude-sonnet", "provider": "openai", "model": "gpt-4o"}
        assert resolve_litellm_model_id(cfg) == "bedrock/anthropic.claude-sonnet"

    def test_provider_model_composed(self):
        from app.agent.llm_parameter_mapper import resolve_litellm_model_id

        assert resolve_litellm_model_id({"provider": "deepseek", "model": "deepseek-chat"}) == "deepseek/deepseek-chat"

    def test_already_slash_delimited(self):
        from app.agent.llm_parameter_mapper import resolve_litellm_model_id

        assert resolve_litellm_model_id({"model": "openai/gpt-4o"}) == "openai/gpt-4o"

    def test_no_provider_defaults_to_openai(self):
        from app.agent.llm_parameter_mapper import resolve_litellm_model_id

        assert resolve_litellm_model_id({"model": "qwen3-max"}) == "openai/qwen3-max"

    def test_missing_model_returns_unknown_openai(self):
        from app.agent.llm_parameter_mapper import resolve_litellm_model_id

        assert resolve_litellm_model_id({}) == "openai/unknown"


# ---------------------------------------------------------------------------
# map_model_config_to_litellm_kwargs — end-to-end vendor config shapes
# ---------------------------------------------------------------------------


class TestMapModelConfigToLiteLLM:
    """Parameterised config → kwarg snapshot tests for each major vendor."""

    @staticmethod
    def _map(cfg: dict, **overrides) -> dict:
        from app.agent.llm_parameter_mapper import map_model_config_to_litellm_kwargs

        return map_model_config_to_litellm_kwargs(
            cfg,
            api_key="fake-key",
            messages=[{"role": "user", "content": "hi"}],
            **overrides,
        )

    # -- OpenAI-like (Qwen / GPT / Moonshot / Claude via jeniya) --

    def test_qwen_openai_shape(self):
        kwargs = self._map(
            {
                "provider": "openai",
                "model": "qwen3-max",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "temperature": 0.3,
                "max_tokens": 2048,
                "extra_body": {"enable_thinking": False},
            }
        )
        assert kwargs["model"] == "openai/qwen3-max"
        assert kwargs["api_base"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert kwargs["temperature"] == 0.3
        assert kwargs["max_tokens"] == 2048
        assert kwargs["extra_body"] == {"enable_thinking": False}
        assert "top_p" not in kwargs

    def test_qwen_default_temperature(self):
        kwargs = self._map({"provider": "openai", "model": "qwen3-max"})
        assert kwargs["temperature"] == 0.7

    # -- DeepSeek --

    def test_deepseek_thinking_disabled(self):
        kwargs = self._map(
            {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com",
                "extra_body": {"thinking": {"type": "disabled"}},
            }
        )
        assert kwargs["model"] == "deepseek/deepseek-chat"
        assert kwargs["api_base"] == "https://api.deepseek.com"
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}

    def test_deepseek_thinking_enabled(self):
        kwargs = self._map(
            {
                "provider": "deepseek",
                "model": "deepseek-reasoner",
                "extra_body": {"thinking": {"type": "enabled"}},
            }
        )
        assert kwargs["model"] == "deepseek/deepseek-reasoner"
        assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}

    # -- Gemini --

    def test_gemini_shape(self):
        kwargs = self._map(
            {
                "provider": "openai",
                "model": "gemini-3-pro-preview",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                "extra_body": {"thinkingConfig": {"thinkingLevel": "low"}, "topK": 40},
            }
        )
        assert kwargs["model"] == "openai/gemini-3-pro-preview"
        assert kwargs["api_base"] == "https://generativelanguage.googleapis.com/v1beta/openai"
        assert kwargs["extra_body"] == {"thinkingConfig": {"thinkingLevel": "low"}, "topK": 40}

    # -- GLM / Zhipu --

    def test_glm_shape(self):
        kwargs = self._map(
            {
                "provider": "openai",
                "model": "glm-4.7",
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "temperature": 0.8,
                "extra_body": {"do_sample": True},
            }
        )
        assert kwargs["model"] == "openai/glm-4.7"
        assert kwargs["api_base"] == "https://open.bigmodel.cn/api/paas/v4"
        assert kwargs["temperature"] == 0.8
        assert kwargs["extra_body"] == {"do_sample": True}

    # -- tools / tool_choice --

    def test_tools_appended(self):
        tools = [{"type": "function", "function": {"name": "search"}}]
        kwargs = self._map({"provider": "openai", "model": "gpt-4o"}, tools=tools, tool_choice="auto")
        assert kwargs["tools"] == tools
        assert kwargs["tool_choice"] == "auto"

    def test_tools_none_omitted(self):
        kwargs = self._map({"provider": "openai", "model": "gpt-4o"})
        assert "tools" not in kwargs
        assert "tool_choice" not in kwargs

    # -- runtime_overrides --

    def test_runtime_overrides_merge(self):
        kwargs = self._map(
            {"provider": "openai", "model": "gpt-4o", "temperature": 0.2},
            runtime_overrides={"temperature": 0.9, "top_p": 0.5},
        )
        assert kwargs["temperature"] == 0.9
        assert kwargs["top_p"] == 0.5

    def test_runtime_overrides_config_popped(self):
        kwargs = self._map(
            {"provider": "openai", "model": "gpt-4o"},
            runtime_overrides={"config": {"callbacks": []}},
        )
        assert "config" not in kwargs

    # -- env-based timeout / retries fallback --

    def test_timeout_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "120")
        kwargs = self._map({"provider": "openai", "model": "gpt-4o"})
        assert kwargs["timeout"] == 120

    def test_timeout_fallback_to_qwen_env(self, monkeypatch):
        monkeypatch.delenv("LLM_REQUEST_TIMEOUT", raising=False)
        monkeypatch.setenv("QWEN_REQUEST_TIMEOUT", "90")
        kwargs = self._map({"provider": "openai", "model": "gpt-4o"})
        assert kwargs["timeout"] == 90

    def test_timeout_default(self, monkeypatch):
        monkeypatch.delenv("LLM_REQUEST_TIMEOUT", raising=False)
        monkeypatch.delenv("QWEN_REQUEST_TIMEOUT", raising=False)
        kwargs = self._map({"provider": "openai", "model": "gpt-4o"})
        assert kwargs["timeout"] == 60

    def test_max_retries_from_config(self):
        kwargs = self._map({"provider": "openai", "model": "gpt-4o", "max_retries": 3})
        assert kwargs["num_retries"] == 3

    def test_max_retries_default_zero(self, monkeypatch):
        monkeypatch.delenv("LLM_MAX_RETRIES", raising=False)
        monkeypatch.delenv("QWEN_MAX_RETRIES", raising=False)
        kwargs = self._map({"provider": "openai", "model": "gpt-4o"})
        assert kwargs["num_retries"] == 0

    # -- max_tokens env fallback --

    def test_max_tokens_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
        kwargs = self._map({"provider": "openai", "model": "gpt-4o"})
        assert kwargs["max_tokens"] == 4096

    def test_max_tokens_qwen_env_fallback(self, monkeypatch):
        monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
        monkeypatch.setenv("QWEN_MAX_TOKENS", "8192")
        kwargs = self._map({"provider": "openai", "model": "gpt-4o"})
        assert kwargs["max_tokens"] == 8192

    # -- edge cases --

    def test_none_values_stripped(self):
        kwargs = self._map({"provider": "openai", "model": "gpt-4o"})
        assert "top_p" not in kwargs
        assert "seed" not in kwargs

    def test_common_params_typed_correctly(self):
        kwargs = self._map(
            {
                "provider": "openai",
                "model": "gpt-4o",
                "temperature": "0.6",
                "top_p": "0.95",
                "seed": "42",
                "presence_penalty": "-0.5",
            }
        )
        assert kwargs["temperature"] == 0.6
        assert kwargs["top_p"] == 0.95
        assert kwargs["seed"] == 42
        assert kwargs["presence_penalty"] == -0.5


# ---------------------------------------------------------------------------
# normalize_openai_base_url
# ---------------------------------------------------------------------------


class TestNormalizeOpenAIBaseURL:
    def test_trailing_slash_stripped(self):
        from app.agent.llm_parameter_mapper import normalize_openai_base_url

        assert normalize_openai_base_url("https://api.openai.com/v1/") == "https://api.openai.com/v1"

    def test_chat_completions_suffix_removed(self):
        from app.agent.llm_parameter_mapper import normalize_openai_base_url

        assert (
            normalize_openai_base_url("https://api.openai.com/v1/chat/completions")
            == "https://api.openai.com/v1"
        )

    def test_none_returns_none(self):
        from app.agent.llm_parameter_mapper import normalize_openai_base_url

        assert normalize_openai_base_url(None) is None

    def test_empty_returns_none(self):
        from app.agent.llm_parameter_mapper import normalize_openai_base_url

        assert normalize_openai_base_url("") is None

    def test_jeniya_http_upgraded(self):
        from app.agent.llm_parameter_mapper import normalize_openai_base_url

        assert (
            normalize_openai_base_url("http://jeniya.top/v1") == "https://jeniya.top/v1"
        )

    def test_invalid_scheme_raises(self):
        from app.agent.llm_parameter_mapper import normalize_openai_base_url

        with pytest.raises(ValueError, match="完整的 http"):
            normalize_openai_base_url("/v1")

    def test_no_scheme_raises(self):
        from app.agent.llm_parameter_mapper import normalize_openai_base_url

        with pytest.raises(ValueError, match="完整的 http"):
            normalize_openai_base_url("jeniya.top/v1")
