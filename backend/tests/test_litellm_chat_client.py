import asyncio
import re
import sys
from types import SimpleNamespace


def test_traced_llm_client_collects_call_usage():
    from app.agent.llm_prompt_trace import instrument_llm_client
    from app.agent.llm_runtime_diagnostics import collect_llm_calls
    from app.agent.messages import AIMessage, HumanMessage

    class FakeClient:
        async def ainvoke(self, _messages):
            return AIMessage(
                content="完成",
                response_metadata={
                    "finish_reason": "stop",
                    "token_usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                },
            )

    client = instrument_llm_client(
        FakeClient(),
        provider_base_url="https://example.test/v1",
        model_name="test-model",
    )

    async def run():
        with collect_llm_calls("expert_turn") as calls:
            await client.ainvoke([HumanMessage(content="你好")])
        return calls

    calls = asyncio.run(run())

    assert len(calls) == 1
    assert calls[0]["operation"] == "expert_turn"
    assert calls[0]["status"] == "succeeded"
    assert calls[0]["response_metadata"]["token_usage"]["total_tokens"] == 12
    assert calls[0]["input_metrics"]["input_messages"] == 1
    assert calls[0]["output_metrics"]["output_chars"] == 2
    assert calls[0]["output_content"] == "完成"
    assert re.fullmatch(r"\d{16}", calls[0]["created_at"])


def test_llm_failure_classifier_uses_stable_fault_codes():
    from app.agent.llm_runtime_diagnostics import classify_llm_failure
    from app.agent.structured_output_contracts import StructuredOutputProtocolError

    assert classify_llm_failure(ValueError("模型配置不存在：missing-model")) == "LLM_SERVICE_NOT_CONFIGURED"
    assert classify_llm_failure(RuntimeError("AuthenticationError: invalid api key")) == "LLM_SERVICE_CONFIG_INVALID"
    assert classify_llm_failure(TimeoutError("upstream timed out")) == "LLM_SERVICE_UNREACHABLE"
    assert (
        classify_llm_failure(StructuredOutputProtocolError("missing required field"))
        == "LLM_RESPONSE_INVALID"
    )


def test_project_messages_cover_agent_runtime_shape():
    from app.agent.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    system = SystemMessage(content="system")
    user = HumanMessage(content="hello")
    first = AIMessage(content="hel", response_metadata={"finish_reason": "length"})
    second = AIMessage(content="lo", tool_calls=[{"id": "tc1", "name": "write_file", "args": {"path": "a.md"}}])
    tool = ToolMessage(content="ok", tool_call_id="tc1")

    combined = first + second

    assert system.type == "system"
    assert user.type == "human"
    assert combined.type == "ai"
    assert combined.content == "hello"
    assert combined.tool_calls == [{"id": "tc1", "name": "write_file", "args": {"path": "a.md"}}]
    assert combined.response_metadata["finish_reason"] == "length"
    assert tool.type == "tool"
    assert tool.tool_call_id == "tc1"
    assert combined.model_dump()["tool_calls"][0]["name"] == "write_file"


def test_litellm_chat_client_roundtrips_tool_calls(monkeypatch):
    from app.agent.llm_client import LiteLLMChatClient
    from app.agent.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        raw_tool_call = SimpleNamespace(
            id="tc1",
            type="function",
            function=SimpleNamespace(name="write_file", arguments='{"path":"a.md"}'),
        )
        message = SimpleNamespace(content="", tool_calls=[raw_tool_call])
        return SimpleNamespace(
            model="test-model-2026",
            choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
            usage=SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=18,
                total_tokens=138,
                prompt_tokens_details=SimpleNamespace(cached_tokens=64),
                completion_tokens_details=SimpleNamespace(reasoning_tokens=7),
                cache_creation_input_tokens=12,
                cache_read_input_tokens=64,
            ),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=fake_acompletion))

    client = LiteLLMChatClient(
        model_config={
            "provider": "openai",
            "model": "test-model",
            "base_url": "https://example.test/v1",
            "temperature": 0.2,
        },
        api_key="test-key",
    ).bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "write",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                },
            }
        ],
        tool_choice="required",
    )

    result = asyncio.run(
        client.ainvoke(
            [
                SystemMessage(content="system"),
                HumanMessage(content="hello"),
                AIMessage(
                    content="",
                    tool_calls=[{"id": "old", "name": "read_file", "args": {"path": "in.md"}}],
                ),
                ToolMessage(content="file content", tool_call_id="old"),
            ]
        )
    )

    assert captured["model"] == "openai/test-model"
    assert captured["temperature"] == 0.2
    assert captured["tool_choice"] == "required"
    assert captured["tools"][0]["function"]["name"] == "write_file"
    assert captured["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "old",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"in.md"}'},
                }
            ],
        },
        {"role": "tool", "content": "file content", "tool_call_id": "old"},
    ]
    assert result.tool_calls == [{"id": "tc1", "name": "write_file", "args": {"path": "a.md"}}]
    assert result.additional_kwargs["tool_calls"][0]["function"]["name"] == "write_file"
    assert result.response_metadata == {
        "finish_reason": "tool_calls",
        "token_usage": {
            "input_tokens": 120,
            "output_tokens": 18,
            "total_tokens": 138,
            "cached_tokens": 64,
            "reasoning_tokens": 7,
            "cache_creation_tokens": 12,
            "cache_read_tokens": 64,
        },
        "model": "test-model-2026",
    }
