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
        "message_id": "msg-search",
        "speaker": {
            "type": "expert",
            "agent_name": "信息检索专家",
            "skill": "web-search",
        },
        "content": '[{"name":"条目 A","url":"https://example.com"}]',
        "created_at": "2026070712000000",
        "tool_results": [
            {
                "tool_call": {
                    "id": "tool-search",
                    "name": "web_search",
                    "kind": "api",
                    "arguments": {"query": "条目 A"},
                },
                "execution_status": "succeeded",
                "result_code": "ok",
                "message": "检索完成",
                "output": {"json_data": [{"name": "条目 A", "url": "https://example.com"}]},
            }
        ],
    }

    display = await rewrite_assistant_message_for_display(
        assistant_msg=original,
        llm=llm,
        expert_system_prompt="你是信息检索专家。",
    )

    assert display is not original
    assert display["content"] == "## 检索结果\n\n- 条目 A"
    assert original["content"] == '[{"name":"条目 A","url":"https://example.com"}]'
    assert display["tool_results"] == original["tool_results"]
    assert len(client.calls) == 1
    human_prompt = client.calls[0][1].content
    assert "你是信息检索专家。" in human_prompt
    assert original["content"] in human_prompt


@pytest.mark.asyncio
async def test_rewrite_assistant_message_for_display_falls_back_to_raw_on_llm_error():
    class FailingClient:
        async def ainvoke(self, messages):
            raise RuntimeError("upstream failed")

    original = {
        "message_id": "msg-fallback",
        "speaker": {"type": "expert", "agent_name": "信息检索专家", "skill": "web-search"},
        "content": "原始回复",
        "created_at": "2026070712000000",
    }

    display = await rewrite_assistant_message_for_display(
        assistant_msg=original,
        llm=_FakeLLM(FailingClient()),
        expert_system_prompt="",
    )

    assert display is not original
    assert display["content"] == "原始回复"
    assert original["content"] == "原始回复"
