"""Tests for the shared structured LLM output gateway."""
from __future__ import annotations

import pytest

from app.agent.messages import HumanMessage
from app.agent.structured_llm_output import invoke_pydantic_llm_output
from app.agent.structured_output_contracts import (
    ExpertSkillSelectionPayload,
    StructuredOutputProtocolError,
)


class _Response:
    def __init__(self, content):
        self.content = content


class _Client:
    def __init__(self, *contents):
        self._contents = list(contents)
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return _Response(self._contents.pop(0))


class _BindableClientState:
    def __init__(self, *contents):
        self.contents = list(contents)
        self.bind_calls = []
        self.calls = []


class _BindableClient:
    def __init__(self, state: _BindableClientState, *, json_mode: bool = False):
        self.state = state
        self.json_mode = json_mode

    def bind(self, **kwargs):
        self.state.bind_calls.append(kwargs)
        response_format = kwargs.get("response_format")
        return _BindableClient(
            self.state,
            json_mode=isinstance(response_format, dict) and response_format.get("type") == "json_object",
        )

    async def ainvoke(self, messages):
        self.state.calls.append({"messages": messages, "json_mode": self.json_mode})
        return _Response(self.state.contents.pop(0))


@pytest.mark.asyncio
async def test_invoke_pydantic_llm_output_binds_json_object_mode():
    state = _BindableClientState('{"selected_skill":"research"}')

    out = await invoke_pydantic_llm_output(
        _BindableClient(state),
        [HumanMessage(content="select")],
        ExpertSkillSelectionPayload,
    )

    assert out.selected_skill == "research"
    assert state.bind_calls == [{"response_format": {"type": "json_object"}}]
    assert [call["json_mode"] for call in state.calls] == [True]


@pytest.mark.asyncio
async def test_invoke_pydantic_llm_output_reuses_json_mode_for_retry():
    state = _BindableClientState(
        '说明：{"selected_skill":"writer"}',
        '{"selected_skill":"research"}',
    )

    out = await invoke_pydantic_llm_output(
        _BindableClient(state),
        [HumanMessage(content="select")],
        ExpertSkillSelectionPayload,
        retry_messages=[HumanMessage(content="retry with strict JSON")],
    )

    assert out.selected_skill == "research"
    assert state.bind_calls == [{"response_format": {"type": "json_object"}}]
    assert [call["json_mode"] for call in state.calls] == [True, True]


@pytest.mark.asyncio
async def test_invoke_pydantic_llm_output_validates_first_response():
    client = _Client('{"selected_skill":"research"}')

    out = await invoke_pydantic_llm_output(
        client,
        [HumanMessage(content="select")],
        ExpertSkillSelectionPayload,
    )

    assert out.selected_skill == "research"
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_invoke_pydantic_llm_output_retries_with_same_pydantic_schema():
    client = _Client(
        '说明：{"selected_skill":"writer"}',
        '{"selected_skill":"research"}',
    )

    out = await invoke_pydantic_llm_output(
        client,
        [HumanMessage(content="select")],
        ExpertSkillSelectionPayload,
        retry_messages=[HumanMessage(content="retry with strict JSON")],
    )

    assert out.selected_skill == "research"
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_invoke_pydantic_llm_output_rejects_markdown_fenced_json():
    client = _Client('```json\n{"selected_skill":"research"}\n```')

    with pytest.raises(StructuredOutputProtocolError):
        await invoke_pydantic_llm_output(
            client,
            [HumanMessage(content="select")],
            ExpertSkillSelectionPayload,
        )

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_invoke_pydantic_llm_output_raises_after_retry_protocol_failure():
    client = _Client("not json", "still not json")

    with pytest.raises(StructuredOutputProtocolError):
        await invoke_pydantic_llm_output(
            client,
            [HumanMessage(content="select")],
            ExpertSkillSelectionPayload,
            retry_messages=[HumanMessage(content="retry with strict JSON")],
        )

    assert len(client.calls) == 2
