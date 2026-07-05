import pytest

from app.agent.messages import AIMessage
from app.agent.group_chat_presentation_rewriter import rewrite_assistant_message_for_display


class _FakeClient:
    def __init__(self, content: str = "整理后的 Markdown"):
        self.content = content
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.content)


class _FakeLLM:
    def __init__(self, client):
        self.client = client

    def get_client(self):
        return self.client


@pytest.mark.asyncio
async def test_rewrite_assistant_message_for_display_only_changes_frontend_copy():
    client = _FakeClient(content="## 检索结果\n\n- 条目 A")
    llm = _FakeLLM(client)
    original = {
        "role": "assistant",
        "agent_name": "信息检索专家",
        "content": '[{"name":"条目 A","url":"https://example.com"}]',
        "tool_raw_results": ['[{"name":"条目 A","url":"https://example.com"}]'],
        "tool_debug": {"raw_result_count": 1},
    }

    display = await rewrite_assistant_message_for_display(
        assistant_msg=original,
        llm=llm,
        expert_system_prompt="你是信息检索专家。",
    )

    assert display is not original
    assert display["content"] == "## 检索结果\n\n- 条目 A"
    assert original["content"] == '[{"name":"条目 A","url":"https://example.com"}]'
    assert display["tool_raw_results"] == original["tool_raw_results"]
    assert len(client.calls) == 1
    human_prompt = client.calls[0][1].content
    assert "你是信息检索专家。" in human_prompt
    assert original["content"] in human_prompt


@pytest.mark.asyncio
async def test_rewrite_assistant_message_for_display_falls_back_to_raw_on_llm_error():
    class FailingClient:
        async def ainvoke(self, messages):
            raise RuntimeError("upstream failed")

    original = {"role": "assistant", "content": "原始回复"}

    display = await rewrite_assistant_message_for_display(
        assistant_msg=original,
        llm=_FakeLLM(FailingClient()),
        expert_system_prompt="",
    )

    assert display is not original
    assert display["content"] == "原始回复"
    assert original["content"] == "原始回复"
