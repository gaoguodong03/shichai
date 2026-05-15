import pytest
import asyncio
from langchain_core.messages import AIMessage, HumanMessage

from app.api.group_chat import _iter_with_keepalive
from app.agent.simple_agent import SimpleAgent


class _SeqClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.idx = 0

    def bind_tools(self, tools, **kwargs):
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
async def test_keepalive_iter_emits_marker_while_agent_is_idle():
    async def _slow_source():
        yield {"type": "agent_step", "message": AIMessage(content="start")}
        import asyncio

        await asyncio.sleep(0.03)
        yield {"type": "final_step"}

    events = []
    async for ev in _iter_with_keepalive(_slow_source(), interval_sec=0.01):
        events.append(ev)

    assert events[0]["type"] == "agent_step"
    assert any(ev.get("type") == "keepalive" for ev in events)
    assert events[-1]["type"] == "final_step"


@pytest.mark.asyncio
async def test_runtime_state_clears_finished_active_run(monkeypatch):
    from app.api import group_chat

    task = asyncio.create_task(asyncio.sleep(0))
    await task
    writes = []
    group_chat._ACTIVE_GROUP_RUNS["session-done"] = {
        "task": task,
        "run_id": "run-done",
        "agent_id": "agent-qa",
        "skill_id": "skill-qa",
        "phase": "tool_running",
        "started_at": "2026-05-15T00:00:00+00:00",
    }
    monkeypatch.setattr(
        group_chat,
        "_write_group_runtime_state",
        lambda session_id, state: writes.append((session_id, state)),
    )
    try:
        meta_item = {"runtime_state": {"running": True, "phase": "tool_running"}}
        state = group_chat._runtime_state_for_session("session-done", meta_item)
    finally:
        group_chat._ACTIVE_GROUP_RUNS.pop("session-done", None)

    assert state == {"running": False}
    assert "runtime_state" not in meta_item
    assert writes == [("session-done", None)]


@pytest.mark.asyncio
async def test_group_session_event_publisher_notifies_subscriber():
    from app.api import group_chat

    queue = asyncio.Queue(maxsize=4)
    async with group_chat._GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
        group_chat._GROUP_SESSION_EVENT_SUBSCRIBERS["session-push"] = [queue]
    try:
        await group_chat._publish_group_session_event(
            "session-push",
            "messages_updated",
            {"message_count": 3},
        )
        event = await asyncio.wait_for(queue.get(), timeout=1)
    finally:
        async with group_chat._GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
            group_chat._GROUP_SESSION_EVENT_SUBSCRIBERS.pop("session-push", None)

    assert event["type"] == "messages_updated"
    assert event["session_id"] == "session-push"
    assert event["message_count"] == 3


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


@pytest.mark.asyncio
async def test_astream_synthesizes_visible_answer_after_tool_output():
    first = AIMessage(
        content="",
        tool_calls=[{"id": "tc1", "name": "exa_web_fetch_exa", "args": {"url": "https://example.com"}}],
    )
    empty_after_tool = AIMessage(content="")

    async def _tool_runner(state, tools):
        return {
            "messages": [HumanMessage(content="工具 exa_web_fetch_exa 的执行结果: ok")],
            "tool_attempt_debug": [{"matched": True}],
            "tool_calls": [{"tool": "exa_web_fetch_exa", "arguments": {"url": "https://example.com"}}],
            "tool_raw_outputs": ['{"ok": true, "stdout": "页面标题：Example Domain\\n页面正文：用于示例的网页。"}'],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([first, empty_after_tool]),
        tools=[object()],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=1,
    )
    agent_texts = []
    async for ev in agent.astream({"messages": [HumanMessage(content="抓取网页")]}, stream_mode=["updates"]):
        if isinstance(ev, dict) and ev.get("type") == "agent_step":
            msg = ev.get("message")
            if isinstance(msg, AIMessage) and str(msg.content or "").strip():
                agent_texts.append(str(msg.content))

    assert any("工具已执行完成" in text for text in agent_texts)
    assert any("Example Domain" in text for text in agent_texts)


@pytest.mark.asyncio
async def test_astream_continues_when_model_hits_output_length_limit():
    first = AIMessage(content="第一段到然而", response_metadata={"finish_reason": "length"})
    second = AIMessage(content="，后面继续写完。", response_metadata={"finish_reason": "stop"})

    async def _tool_runner(state, tools):
        return {"messages": []}

    agent = SimpleAgent(
        llm=_FakeLLM([first, second]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=3,
    )
    texts = []
    debug = []
    async for ev in agent.astream({"messages": [HumanMessage(content="写长文")]}, stream_mode=["updates"]):
        if isinstance(ev, dict) and ev.get("type") == "agent_step":
            msg = ev.get("message")
            if isinstance(msg, AIMessage):
                texts.append(str(msg.content or ""))
        if isinstance(ev, dict) and ev.get("type") == "final_step":
            debug = ev.get("tool_attempt_debug") or []

    assert texts == ["第一段到然而", "，后面继续写完。"]
    assert any(item.get("source") == "output_limit_continuation" for item in debug)
