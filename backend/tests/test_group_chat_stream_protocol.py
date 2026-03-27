import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.simple_agent import SimpleAgent


class _SeqClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.idx = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        if self.idx >= len(self.responses):
            return self.responses[-1]
        r = self.responses[self.idx]
        self.idx += 1
        return r


class _FakeLLM:
    def __init__(self, responses):
        self._c = _SeqClient(responses)

    def get_client(self):
        return self._c


@pytest.mark.asyncio
async def test_astream_emits_unified_protocol_events():
    first = AIMessage(
        content="",
        tool_calls=[{"id": "tc1", "name": "run_skill_script", "args": {"script_path": "generate_image.py"}}],
    )
    second = AIMessage(content="done")

    async def _tool_runner(state, tools):
        return {
            "messages": [HumanMessage(content="工具 run_skill_script 的执行结果: ok")],
            "tool_attempt_debug": [{"matched": True}],
            "tool_calls": [{"tool": "run_skill_script", "arguments": {"script_path": "generate_image.py"}}],
            "tool_raw_outputs": ["ok"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([first, second]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=2,
    )
    events = []
    async for ev in agent.astream({"messages": [HumanMessage(content="go")]}, stream_mode=["updates"]):
        events.append(ev)

    assert any(isinstance(e, dict) and e.get("type") == "agent_step" for e in events)
    assert any(isinstance(e, dict) and e.get("type") == "tool_step" for e in events)
    assert any(isinstance(e, dict) and e.get("type") == "final_step" for e in events)

