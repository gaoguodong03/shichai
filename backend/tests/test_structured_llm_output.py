"""Tests for the shared structured LLM output gateway."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from app.agent.expert_completion_contract import ExpertFinalStatePayload
from app.agent.llm_client import LiteLLMChatClient
from app.agent.messages import HumanMessage
from app.agent.llm_prompt_trace import instrument_llm_client
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
async def test_invoke_pydantic_llm_output_forwards_json_mode_through_traced_litellm(monkeypatch):
    pytest.importorskip("litellm")
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content='{"selected_skill":"research"}', tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    client = instrument_llm_client(
        LiteLLMChatClient(
            model_config={
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "base_url": "https://api.deepseek.com",
            },
            api_key="test-key",
        ),
        provider_base_url="https://api.deepseek.com",
        model_name="deepseek-v4-flash",
    )

    out = await invoke_pydantic_llm_output(
        client,
        [HumanMessage(content="select")],
        ExpertSkillSelectionPayload,
    )

    assert out.selected_skill == "research"
    assert captured["response_format"] == {"type": "json_object"}


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
async def test_invoke_pydantic_llm_output_supplies_exact_schema_on_first_and_retry_calls():
    invalid_artifacts = {
        "execution_status": "succeeded",
        "message": {
            "content": "资料已保存。",
            "artifacts": ["web-crawler/report.md"],
        },
        "next_action": {"agent_turn": "respond", "skill_session": "release"},
    }
    valid_final = {
        "execution_status": "succeeded",
        "message": {
            "content": "资料已保存。",
            "artifacts": [
                {
                    "type": "markdown",
                    "name": "report.md",
                    "path": "web-crawler/report.md",
                }
            ],
        },
        "next_action": {"agent_turn": "respond", "skill_session": "release"},
    }
    client = _Client(
        json.dumps(invalid_artifacts, ensure_ascii=False),
        json.dumps(valid_final, ensure_ascii=False),
    )

    out = await invoke_pydantic_llm_output(
        client,
        [HumanMessage(content="finalize")],
        ExpertFinalStatePayload,
        retry_messages=[HumanMessage(content="retry with strict JSON")],
    )

    assert out.message.artifacts[0].path == "web-crawler/report.md"
    assert len(client.calls) == 2
    for call in client.calls:
        schema_message = call[-1]
        assert isinstance(schema_message, HumanMessage)
        assert "Pydantic JSON Schema" in str(schema_message.content)
        assert '"ArtifactRef"' in str(schema_message.content)
        assert '"path"' in str(schema_message.content)


@pytest.mark.asyncio
async def test_invoke_pydantic_llm_output_keeps_traced_client_without_bind_compatible():
    raw_client = _Client('{"selected_skill":"research"}')
    traced_client = instrument_llm_client(
        raw_client,
        provider_base_url="https://example.test/v1",
        model_name="test-model",
    )

    out = await invoke_pydantic_llm_output(
        traced_client,
        [HumanMessage(content="select")],
        ExpertSkillSelectionPayload,
    )

    assert out.selected_skill == "research"
    assert len(raw_client.calls) == 1


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


@pytest.mark.asyncio
async def test_invoke_pydantic_llm_output_logs_each_protocol_failure_with_context(caplog):
    client = _Client(
        '```json\n{"selected_skill":"research"}\n```',
        '{"selected_skill":"research","unexpected":true}',
    )

    with caplog.at_level(logging.WARNING, logger="app.agent.structured_llm_output"):
        with pytest.raises(StructuredOutputProtocolError):
            await invoke_pydantic_llm_output(
                client,
                [HumanMessage(content="select")],
                ExpertSkillSelectionPayload,
                retry_messages=[HumanMessage(content="retry with strict JSON")],
                protocol_log_context={
                    "operation": "host_scheduler",
                    "group_session_id": "group-1",
                    "host_name": "四九",
                },
            )

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2
    assert "attempt=initial" in messages[0]
    assert "structured output must be a single JSON object" in messages[0]
    assert 'raw_output=\'```json\\n{"selected_skill":"research"}\\n```\'' in messages[0]
    assert "attempt=retry" in messages[1]
    assert "structured output failed schema validation" in messages[1]
    assert "extra_forbidden" in messages[1]
    assert '"group_session_id":"group-1"' in messages[1]
    assert '"host_name":"四九"' in messages[1]


@pytest.mark.asyncio
async def test_invoke_pydantic_llm_output_adds_raw_response_to_post_validation_error(caplog):
    raw = '{"selected_skill":"missing-member"}'
    client = _Client(raw)

    def reject_payload(_payload):
        raise StructuredOutputProtocolError(
            "selected skill is not available",
            schema_name="ExpertSkillSelectionPayload",
        )

    with caplog.at_level(logging.WARNING, logger="app.agent.structured_llm_output"):
        with pytest.raises(StructuredOutputProtocolError) as exc_info:
            await invoke_pydantic_llm_output(
                client,
                [HumanMessage(content="select")],
                ExpertSkillSelectionPayload,
                post_validate=reject_payload,
            )

    assert exc_info.value.raw_output == raw
    assert f"raw_output={raw!r}" in caplog.text
