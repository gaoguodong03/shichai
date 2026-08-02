import asyncio
from types import SimpleNamespace


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
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls")])

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)

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
