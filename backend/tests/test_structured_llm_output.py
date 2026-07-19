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
