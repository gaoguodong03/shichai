import pytest
import asyncio
import logging
from app.agent.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.group_chat_streaming import iter_with_keepalive
from app.agent.simple_agent import SimpleAgent
from app.agent.tool_spec import ToolSpec


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
    async for ev in iter_with_keepalive(_slow_source(), interval_sec=0.01):
        events.append(ev)

    assert events[0]["type"] == "agent_step"
    assert any(ev.get("type") == "keepalive" for ev in events)
    assert events[-1]["type"] == "final_step"


@pytest.mark.asyncio
async def test_runtime_state_clears_finished_active_run(monkeypatch):
    from app.api import group_chat_state

    task = asyncio.create_task(asyncio.sleep(0))
    await task
    writes = []
    group_chat_state.ACTIVE_GROUP_RUNS["session-done"] = {
        "task": task,
        "run_id": "run-done",
        "agent_id": "agent-qa",
        "skill_id": "skill-qa",
        "phase": "tool_running",
        "started_at": "2026-05-15T00:00:00+00:00",
    }
    monkeypatch.setattr(
        group_chat_state,
        "write_group_runtime_state",
        lambda session_id, state: writes.append((session_id, state)),
    )
    try:
        session_item = {"runtime_state": {"running": True, "phase": "tool_running"}}
        state = group_chat_state.runtime_state_for_session("session-done", session_item)
    finally:
        group_chat_state.ACTIVE_GROUP_RUNS.pop("session-done", None)

    assert state == {"running": False}
    assert "runtime_state" not in session_item
    assert writes == [("session-done", None)]


@pytest.mark.asyncio
async def test_group_session_event_publisher_notifies_subscriber():
    from app.api import group_chat_state

    queue = asyncio.Queue(maxsize=4)
    async with group_chat_state.GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
        group_chat_state.GROUP_SESSION_EVENT_SUBSCRIBERS["session-push"] = [queue]
    try:
        await group_chat_state.publish_group_session_event(
            "session-push",
            "messages_updated",
            {"message_count": 3},
        )
        event = await asyncio.wait_for(queue.get(), timeout=1)
    finally:
        async with group_chat_state.GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK:
            group_chat_state.GROUP_SESSION_EVENT_SUBSCRIBERS.pop("session-push", None)

    assert event["type"] == "messages_updated"
    assert event["session_id"] == "session-push"
    assert event["message_count"] == 3


def test_expert_prompt_log_uses_summary_by_default(caplog, monkeypatch):
    from app.agent import group_chat_runtime

    monkeypatch.delenv("PROMPT_LOG_MODE", raising=False)
    prompt = "【群聊讨论目标】\n写周报\n\n【本轮用户输入】\n请总结风险"

    with caplog.at_level(logging.INFO, logger="app.agent.group_chat_runtime"):
        group_chat_runtime._log_expert_prompt(
            session_id="group-test",
            run_id="run-test",
            agent_name="写作专家",
            skill="weekly-report",
            user_content=prompt,
        )

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "[Prompt]" in messages
    assert "group_chat_expert_prompt code=expert_prompt" in messages
    assert "session=group-test" in messages
    assert "run_id=run-test" in messages
    assert "agent_name=写作专家" in messages
    assert "skill=weekly-report" in messages
    assert "prompt_len=" in messages
    assert "mode=summary" in messages
    assert prompt not in messages


def test_expert_prompt_log_includes_full_prompt_when_enabled(caplog, monkeypatch):
    from app.agent import group_chat_runtime

    monkeypatch.setenv("PROMPT_LOG_MODE", "full")
    prompt = "【群聊讨论目标】\n写周报\n\n【本轮用户输入】\n请总结风险"

    with caplog.at_level(logging.INFO, logger="app.agent.group_chat_runtime"):
        group_chat_runtime._log_expert_prompt(
            session_id="group-test",
            run_id="run-test",
            agent_name="写作专家",
            skill="weekly-report",
            user_content=prompt,
        )

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "[Prompt]" in messages
    assert "group_chat_expert_prompt code=expert_prompt" in messages
    assert "mode=full" in messages
    assert prompt in messages


@pytest.mark.asyncio
async def test_display_message_uses_raw_assistant_content_without_presentation_rewrite(monkeypatch):
    from app.agent import group_chat_runtime

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("presentation rewriter should not be called")

    monkeypatch.setattr(
        group_chat_runtime,
        "rewrite_assistant_message_for_display",
        _fail_if_called,
        raising=False,
    )
    assistant_msg = {
        "role": "assistant",
        "agent_name": "写作专家",
        "content": "原始专家回复",
    }

    display_msg = await group_chat_runtime._prepare_display_assistant_message(
        assistant_msg=assistant_msg,
        llm=object(),
        expert_system_prompt="不应使用",
    )

    assert display_msg is not assistant_msg
    assert display_msg["content"] == "原始专家回复"
    assert "presentation_content" not in display_msg
    assert "presentation_content" not in assistant_msg


@pytest.mark.asyncio
async def test_background_stream_keeps_source_running_after_client_close():
    from app.agent.group_chat_streaming import stream_background_events

    source_finished = asyncio.Event()

    async def source():
        yield "event: content\ndata: {}\n\n"
        await asyncio.sleep(0.01)
        source_finished.set()

    stream = stream_background_events(source())
    first = await stream.__anext__()
    assert first.startswith("event: content")

    await stream.aclose()

    await asyncio.wait_for(source_finished.wait(), timeout=1)


def test_clears_completed_audio_skill_lock_from_history():
    from app.agent.group_chat_skill_session import _clear_completed_skill_session_lock_from_history

    session_item = {
        "skill_session_owner_name": "转写专家",
        "skill_session_skill": "audio-transcription",
    }
    messages = [
        {
            "role": "assistant",
            "agent_name": "转写专家",
            "skill": "audio-transcription",
            "content": "转写文本",
            "tool_raw_results": [
                '{"ok": true, "stdout": "{\\"ok\\": true, \\"code\\": \\"transcribed\\", \\"done\\": true, \\"final\\": true, \\"text\\": \\"转写文本\\"}"}'
            ],
            "tool_debug": {
                "tool_calls": [
                    {"tool": "run_skill_script_audio-transcription", "arguments": {"script_path": "transcribe_audio.py"}}
                ]
            },
        }
    ]

    assert _clear_completed_skill_session_lock_from_history(session_item, messages) is True
    assert "skill_session_owner_name" not in session_item
    assert "skill_session_skill" not in session_item


def test_clears_implicit_skill_lock_from_history():
    from app.agent.group_chat_skill_session import _clear_completed_skill_session_lock_from_history

    session_item = {
        "skill_session_owner_name": "研讨教师",
        "skill_session_skill": "seminar-teacher",
    }
    messages = [
        {
            "role": "assistant",
            "agent_name": "研讨教师",
            "skill": "seminar-teacher",
            "content": "大家先围绕这个问题说说自己的判断。",
            "tool_debug": {
                "skill_session_state": {
                    "over": None,
                    "source": "none",
                },
            },
        }
    ]

    assert _clear_completed_skill_session_lock_from_history(session_item, messages) is True
    assert "skill_session_owner_name" not in session_item
    assert "skill_session_skill" not in session_item


def test_keeps_explicit_continue_skill_lock_from_history():
    from app.agent.group_chat_skill_session import _clear_completed_skill_session_lock_from_history

    session_item = {
        "skill_session_owner_name": "研讨教师",
        "skill_session_skill": "seminar-teacher",
    }
    messages = [
        {
            "role": "assistant",
            "agent_name": "研讨教师",
            "skill": "seminar-teacher",
            "content": "请先补充一个例子。",
            "tool_debug": {
                "skill_session_state": {
                    "over": False,
                    "source": "assistant_state_block",
                },
            },
        }
    ]

    assert _clear_completed_skill_session_lock_from_history(session_item, messages) is False
    assert session_item["skill_session_owner_name"] == "研讨教师"
    assert session_item["skill_session_skill"] == "seminar-teacher"


def test_keeps_skill_lock_from_new_history_skill_result():
    from app.agent.group_chat_skill_session import _clear_completed_skill_session_lock_from_history

    session_item = {
        "skill_session_owner_name": "研讨教师",
        "skill_session_skill": "seminar-teacher",
    }
    messages = [
        {
            "role": "assistant",
            "agent_name": "研讨教师",
            "skill": "seminar-teacher",
            "content": "旧消息已完成。",
            "tool_debug": {
                "skill_session_state": {
                    "skill_session": "release",
                }
            },
        },
        {
            "message_id": "msg-keep",
            "speaker": {
                "type": "expert",
                "agent_name": "研讨教师",
                "skill": "seminar-teacher",
            },
            "content": "请先补充一个例子。",
            "skill_result": {
                "execution_status": "blocked",
                "next_action": {
                    "agent_turn": "respond",
                    "skill_session": "keep",
                },
            },
        }
    ]

    assert _clear_completed_skill_session_lock_from_history(session_item, messages) is False
    assert session_item["skill_session_owner_name"] == "研讨教师"
    assert session_item["skill_session_skill"] == "seminar-teacher"


def test_clears_skill_lock_from_new_history_skill_result_release():
    from app.agent.group_chat_skill_session import _clear_completed_skill_session_lock_from_history

    session_item = {
        "skill_session_owner_name": "研讨教师",
        "skill_session_skill": "seminar-teacher",
    }
    messages = [
        {
            "message_id": "msg-release",
            "speaker": {
                "type": "expert",
                "agent_name": "研讨教师",
                "skill": "seminar-teacher",
            },
            "content": "处理完成。",
            "skill_result": {
                "execution_status": "succeeded",
                "next_action": {
                    "agent_turn": "respond",
                    "skill_session": "release",
                },
            },
        }
    ]

    assert _clear_completed_skill_session_lock_from_history(session_item, messages) is True
    assert "skill_session_owner_name" not in session_item
    assert "skill_session_skill" not in session_item


def test_clears_bound_skill_introspection_lock_from_history():
    from app.agent.group_chat_skill_session import _clear_completed_skill_session_lock_from_history

    session_item = {
        "skill_session_owner_name": "Skill 专家",
        "skill_session_skill": "skill-builder",
    }
    messages = [
        {
            "role": "assistant",
            "agent_name": "Skill 专家",
            "skill": "skill-builder",
            "content": "我当前绑定的 Skill 有：\n\n- **check-dev-env**（标识：`check-dev-env`）",
            "tool_debug": {
                "tool_attempt_debug": [
                    {
                        "source": "bound_skill_introspection_direct_final",
                        "matched": True,
                    }
                ],
                "skill_session_state": {
                    "over": None,
                    "source": "none",
                },
            },
        }
    ]

    assert _clear_completed_skill_session_lock_from_history(session_item, messages) is True
    assert "skill_session_owner_name" not in session_item
    assert "skill_session_skill" not in session_item


def test_store_skill_session_lock_only_for_explicit_continue_or_forced_wait():
    from app.agent.group_chat_skill_session import _store_skill_session_lock_for_turn

    session_item = {"skill_session_owner_name": "旧专家", "skill_session_skill": "old"}
    _store_skill_session_lock_for_turn(
        session_item,
        owner_agent_name="研讨教师",
        skill="seminar-teacher",
        skill_session_over=None,
    )
    assert "skill_session_owner_name" not in session_item
    assert "skill_session_skill" not in session_item

    _store_skill_session_lock_for_turn(
        session_item,
        owner_agent_name="研讨教师",
        skill="seminar-teacher",
        skill_session_over=False,
    )
    assert session_item["skill_session_owner_name"] == "研讨教师"
    assert session_item["skill_session_skill"] == "seminar-teacher"

    _store_skill_session_lock_for_turn(
        session_item,
        owner_agent_name="研讨教师",
        skill="seminar-teacher",
        skill_session_over=True,
    )
    assert "skill_session_owner_name" not in session_item
    assert "skill_session_skill" not in session_item

    _store_skill_session_lock_for_turn(
        session_item,
        owner_agent_name="研讨教师",
        skill="seminar-teacher",
        skill_session_over=None,
        force_keep=True,
    )
    assert session_item["skill_session_owner_name"] == "研讨教师"
    assert session_item["skill_session_skill"] == "seminar-teacher"


def test_scene_expert_turn_hands_back_to_host_before_next_target():
    from app.agent.group_chat_skill_session import _should_handoff_to_host_after_expert

    assert _should_handoff_to_host_after_expert(
        orchestration_profile="scene",
        skill_session_over=None,
        has_auto_continue_signal=False,
    ) is True
    assert _should_handoff_to_host_after_expert(
        orchestration_profile="scene",
        skill_session_over=True,
        has_auto_continue_signal=False,
    ) is True
    assert _should_handoff_to_host_after_expert(
        orchestration_profile="scene",
        skill_session_over=False,
        has_auto_continue_signal=True,
    ) is False


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
async def test_astream_forces_audio_asr_tool_for_audio_file_ref_before_llm_reply():
    stale_reply = AIMessage(content="我会直接复述旧内容，但不应该显示")
    transcript = "流式完整音频转写"
    called = {"tool": 0}

    async def _tool_runner(state, tools):
        called["tool"] += 1
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        assert tool_calls[0]["name"] == "audio-asr_transcribe_audio_file"
        assert tool_calls[0]["args"]["path"] == "interview.m4a"
        import json

        raw = json.dumps(
            {
                "execution_status": "succeeded",
                "result_code": "audio_asr.transcribed",
                "message": "音频转写完成。",
                "artifacts": {"text": transcript, "segment_count": 1},
                "next_action": {"agent_turn": "respond", "skill_session": "release"},
            },
            ensure_ascii=False,
        )
        return {
            "messages": [ToolMessage(content=raw, tool_call_id=tool_calls[0]["id"])],
            "tool_attempt_debug": [],
            "tool_calls": [{"tool": "audio-asr_transcribe_audio_file", "arguments": tool_calls[0]["args"]}],
            "tool_raw_outputs": [raw],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([stale_reply]),
        tools=[ToolSpec(name="audio-asr_transcribe_audio_file", description="转写音频")],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=2,
    )
    events = []
    async for ev in agent.astream(
        {"messages": [HumanMessage(content="请转写【文件引用：面试录音｜interview.m4a】")]},
        stream_mode=["updates"],
    ):
        events.append(ev)

    assert called["tool"] == 1
    assert any(
        isinstance(ev.get("message"), AIMessage)
        and getattr(ev["message"], "tool_calls", None)
        and ev["message"].tool_calls[0]["name"] == "audio-asr_transcribe_audio_file"
        for ev in events
        if isinstance(ev, dict) and ev.get("type") == "agent_step"
    )
    assert any(
        isinstance(ev.get("message"), AIMessage) and str(ev["message"].content) == transcript
        for ev in events
        if isinstance(ev, dict) and ev.get("type") == "agent_step"
    )
    final = next(ev for ev in events if isinstance(ev, dict) and ev.get("type") == "final_step")
    assert any(
        item.get("source") == "forced_mcp_file_ref_tool_call"
        for item in final.get("tool_attempt_debug", [])
    )


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
async def test_astream_shortens_long_tool_call_ids_before_followup_llm_call():
    long_call_id = "run_skill_script:" + ("nested/path/" * 18) + "main.py:abcdef1234567890"
    assert len(long_call_id) > 64

    class _RejectLongToolCallClient:
        def __init__(self):
            self.calls = 0
            self.seen_followup_ids = []

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{"id": long_call_id, "name": "run_skill_script", "args": {"script_path": "main.py"}}],
                )
            ai_call_id = messages[-2].tool_calls[0]["id"]
            tool_call_id = messages[-1].tool_call_id
            self.seen_followup_ids.append((ai_call_id, tool_call_id))
            if len(tool_call_id) > 64:
                raise RuntimeError(f"call_id too long: {len(tool_call_id)}")
            return AIMessage(content="工具结果已总结")

    class _RejectLongToolCallLLM:
        def __init__(self):
            self.client = _RejectLongToolCallClient()

        def get_client(self):
            return self.client

    llm = _RejectLongToolCallLLM()

    async def _tool_runner(state, tools):
        tool_call_id = state["messages"][-1].tool_calls[0]["id"]
        return {
            "messages": [ToolMessage(content="ok", tool_call_id=tool_call_id)],
            "tool_attempt_debug": [{"matched": True}],
            "tool_calls": [{"tool": "run_skill_script", "arguments": {"script_path": "main.py"}}],
            "tool_raw_outputs": ["ok"],
        }

    agent = SimpleAgent(
        llm=llm,
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=2,
    )
    agent_texts = []
    async for ev in agent.astream({"messages": [HumanMessage(content="go")]}, stream_mode=["updates"]):
        if isinstance(ev, dict) and ev.get("type") == "agent_step":
            msg = ev.get("message")
            if isinstance(msg, AIMessage) and str(msg.content or "").strip():
                agent_texts.append(str(msg.content))

    assert agent_texts[-1] == "工具结果已总结"
    assert llm.client.seen_followup_ids
    ai_call_id, tool_call_id = llm.client.seen_followup_ids[-1]
    assert ai_call_id == tool_call_id
    assert len(tool_call_id) <= 64


@pytest.mark.asyncio
async def test_ainvoke_shortens_long_tool_call_ids_before_followup_llm_call():
    long_call_id = "run_skill_script:" + ("deep/path/" * 18) + "main.py:abcdef1234567890"
    assert len(long_call_id) > 64

    class _RejectLongToolCallClient:
        def __init__(self):
            self.calls = 0
            self.seen_followup_ids = []

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{"id": long_call_id, "name": "run_skill_script", "args": {"script_path": "main.py"}}],
                )
            ai_call_id = messages[-2].tool_calls[0]["id"]
            tool_call_id = messages[-1].tool_call_id
            self.seen_followup_ids.append((ai_call_id, tool_call_id))
            if len(tool_call_id) > 64:
                raise RuntimeError(f"call_id too long: {len(tool_call_id)}")
            return AIMessage(content="工具结果已总结")

    class _RejectLongToolCallLLM:
        def __init__(self):
            self.client = _RejectLongToolCallClient()

        def get_client(self):
            return self.client

    llm = _RejectLongToolCallLLM()

    async def _tool_runner(state, tools):
        tool_call_id = state["messages"][-1].tool_calls[0]["id"]
        return {
            "messages": [ToolMessage(content="ok", tool_call_id=tool_call_id)],
            "tool_attempt_debug": [{"matched": True}],
            "tool_calls": [{"tool": "run_skill_script", "arguments": {"script_path": "main.py"}}],
            "tool_raw_outputs": ["ok"],
        }

    agent = SimpleAgent(
        llm=llm,
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=2,
    )

    result = await agent.ainvoke({"messages": [HumanMessage(content="go")]})
    final = result["messages"][-1]

    assert isinstance(final, AIMessage)
    assert final.content == "工具结果已总结"
    assert llm.client.seen_followup_ids
    ai_call_id, tool_call_id = llm.client.seen_followup_ids[-1]
    assert ai_call_id == tool_call_id
    assert len(tool_call_id) <= 64


@pytest.mark.asyncio
async def test_astream_synthesizes_after_configured_task_file_read_without_repeating_tool():
    first = AIMessage(
        content="",
        tool_calls=[{"id": "tc-read", "name": "read_workspace_file", "args": {"path": "speaker_task.txt"}}],
    )
    final = AIMessage(content="根据任务文件完成本轮发言")
    repeated = AIMessage(
        content="",
        tool_calls=[{"id": "tc-repeat", "name": "read_workspace_file", "args": {"path": "speaker_task.txt"}}],
    )
    calls = {"n": 0}

    async def _tool_runner(state, tools):
        calls["n"] += 1
        return {
            "messages": [ToolMessage(content="任务：教师给出选题。", tool_call_id="tc-read")],
            "tool_attempt_debug": [{"matched": True}],
            "tool_calls": [{"tool": "read_workspace_file", "arguments": {"path": "speaker_task.txt"}}],
            "tool_raw_outputs": ["任务：教师给出选题。"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([first, final, repeated]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
        synthesize_after_read_file_paths=("speaker_task.txt",),
    )
    events = []
    async for ev in agent.astream({"messages": [HumanMessage(content="go")]}, stream_mode=["updates"]):
        events.append(ev)

    assert calls["n"] == 1
    agent_texts = [
        str(ev["message"].content)
        for ev in events
        if ev.get("type") == "agent_step" and isinstance(ev.get("message"), AIMessage)
    ]
    assert agent_texts[-1] == "根据任务文件完成本轮发言"
    final_debug = next(ev["tool_attempt_debug"] for ev in events if ev.get("type") == "final_step")
    assert any(item.get("source") == "synthesize_after_read_workspace_file" for item in final_debug)


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
