import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.simple_agent import SimpleAgent


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        r = self._responses[self._idx]
        self._idx = min(self._idx + 1, len(self._responses) - 1)
        return r


class _FakeLLM:
    def __init__(self, responses):
        self._client = _FakeClient(responses)

    def get_client(self):
        return self._client


@pytest.mark.asyncio
async def test_simple_agent_calls_tool_runner_for_content_tool_json():
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc1",
                "name": "run_skill_script",
                "args": {"script_path": "generate_image.py"},
            }
        ],
    )
    called = {"n": 0}

    async def _tool_runner(state, tools):
        called["n"] += 1
        return {"messages": [HumanMessage(content="tool ok")], "tool_attempt_debug": [{"matched": True}]}

    agent = SimpleAgent(
        llm=_FakeLLM([response]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=1,
    )
    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})
    assert called["n"] == 1
    assert isinstance(out, dict)
    assert out.get("tool_attempt_debug")


@pytest.mark.asyncio
async def test_simple_agent_records_no_tool_detected_debug():
    response = AIMessage(content="普通文本，没有工具调用")

    async def _tool_runner(state, tools):
        return {"messages": []}

    agent = SimpleAgent(
        llm=_FakeLLM([response]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=1,
    )
    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})
    debug = out.get("tool_attempt_debug") or []
    assert debug
    assert debug[0].get("source") == "no_tool_detected"


@pytest.mark.asyncio
async def test_simple_agent_stops_after_terminal_sandbox_environment_failure():
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc1",
                "name": "run_skill_script_demo",
                "args": {},
            }
        ],
    )
    fallback_response = AIMessage(content="不应该再次调用模型综合这个工具错误")
    calls = {"n": 0}

    async def _tool_runner(state, tools):
        calls["n"] += 1
        return {
            "messages": [HumanMessage(content="tool failed")],
            "tool_raw_outputs": [
                '{"ok": false, "error": "OpenSandbox lifecycle API 连接失败：当前应用进程无法连接 OpenSandbox 服务。"}'
            ],
            "tool_attempt_debug": [{"matched": True}],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([response, fallback_response]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=2,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    assert calls["n"] == 1
    final_text = str(out["messages"][-1].content)
    assert "工具运行环境不可用" in final_text
    assert "OpenSandbox" in final_text
    assert "不应该再次调用" not in final_text
    assert any(
        item.get("source") == "terminal_tool_failure_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_can_stop_after_configured_write_tool_without_final_llm():
    read_call = AIMessage(
        content="",
        tool_calls=[{"id": "tc-read", "name": "read_file", "args": {"path": "speaker_task.txt"}}],
    )
    write_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {"path": "speaker_task.txt", "content": "任务"},
            }
        ],
    )
    should_not_call = AIMessage(content="不应该为了工具后总结再次调用模型")
    tool_round = {"n": 0}

    async def _tool_runner(state, tools):
        tool_round["n"] += 1
        if tool_round["n"] == 1:
            return {
                "messages": [HumanMessage(content="missing")],
                "tool_calls": [{"tool": "read_file", "arguments": {"path": "speaker_task.txt"}}],
                "tool_raw_outputs": ["错误：文件不存在：speaker_task.txt"],
            }
        return {
            "messages": [HumanMessage(content="written")],
            "tool_calls": [
                {
                    "tool": "write_workspace_file",
                    "arguments": {"path": "speaker_task.txt", "content": "任务"},
                }
            ],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：speaker_task.txt"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([read_call, write_call, should_not_call]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=6,
        stop_after_tool_names=("write_workspace_file",),
        synthesize_after_tools=False,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    assert tool_round["n"] == 2
    assert all("不应该" not in str(getattr(msg, "content", "")) for msg in out["messages"])
    assert any(
        item.get("source") == "stop_after_tool_result"
        and item.get("tool") == "write_workspace_file"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_synthesizes_immediately_after_configured_read_file_path():
    read_call = AIMessage(
        content="",
        tool_calls=[{"id": "tc-read", "name": "read_file", "args": {"path": "speaker_task.txt"}}],
    )
    final_answer = AIMessage(content="按任务文件直接完成发言")
    repeated_read_call = AIMessage(
        content="",
        tool_calls=[{"id": "tc-repeat", "name": "read_file", "args": {"path": "speaker_task.txt"}}],
    )
    tool_round = {"n": 0}

    async def _tool_runner(state, tools):
        tool_round["n"] += 1
        return {
            "messages": [ToolMessage(content="本轮任务：直接给出教师选题。", tool_call_id="tc-read")],
            "tool_calls": [{"tool": "read_file", "arguments": {"path": "speaker_task.txt"}}],
            "tool_raw_outputs": ["本轮任务：直接给出教师选题。"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([read_call, final_answer, repeated_read_call]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
        synthesize_after_read_file_paths=("speaker_task.txt",),
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    assert tool_round["n"] == 1
    assert str(out["messages"][-1].content) == "按任务文件直接完成发言"
    assert all("tc-repeat" not in str(getattr(msg, "tool_calls", "")) for msg in out["messages"])
    assert any(
        item.get("source") == "synthesize_after_read_file"
        and item.get("path") == "speaker_task.txt"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_direct_final_for_large_script_success_without_second_llm():
    script_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-script",
                "name": "run_skill_script_shixiseng_dedicated_crawler",
                "args": {"script_path": "main.py"},
            }
        ],
    )
    should_not_call = AIMessage(content="不应该为了大体积脚本日志再次调用模型")
    raw_payload = {
        "ok": True,
        "code": "script_executed",
        "script": "main.py",
        "returncode": 0,
        "stdout": (
            "All tasks finished. Check results in: scripts/saved_data/result_20260523_123036\n"
            "实习僧本轮爬取分析反馈\n"
            "本轮岗位数：55 个。\n"
            "成功写入/导出岗位数：55 个。"
        ),
        "stderr": "fetch log\n" + ("x" * 9000),
    }

    async def _tool_runner(state, tools):
        return {
            "messages": [ToolMessage(content=json.dumps(raw_payload, ensure_ascii=False), tool_call_id="tc-script")],
            "tool_calls": [{"tool": "run_skill_script_shixiseng_dedicated_crawler", "arguments": {"script_path": "main.py"}}],
            "tool_raw_outputs": [json.dumps(raw_payload, ensure_ascii=False)],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([script_call, should_not_call]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    final_text = str(out["messages"][-1].content)
    assert "本轮岗位数：55 个" in final_text
    assert "不应该" not in final_text
    assert "fetch log" not in final_text
    assert any(
        item.get("source") == "large_run_skill_script_success_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_falls_back_to_tool_summary_when_final_llm_fails():
    read_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-read",
                "name": "read_file",
                "args": {"path": "scripts/saved_data/result_20260523_123036/analysis_report.txt"},
            }
        ],
    )
    llm_failure = AIMessage(content="抱歉，模型响应失败：Connection error.")

    async def _tool_runner(state, tools):
        return {
            "messages": [
                ToolMessage(
                    content="实习僧本轮爬取分析反馈\n本轮岗位数：55 个。\n成功写入/导出岗位数：55 个。",
                    tool_call_id="tc-read",
                )
            ],
            "tool_calls": [
                {
                    "tool": "read_file",
                    "arguments": {"path": "scripts/saved_data/result_20260523_123036/analysis_report.txt"},
                }
            ],
            "tool_raw_outputs": ["实习僧本轮爬取分析反馈\n本轮岗位数：55 个。\n成功写入/导出岗位数：55 个。"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([read_call, llm_failure]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    final_text = str(out["messages"][-1].content)
    assert "本轮岗位数：55 个" in final_text
    assert "模型响应失败" not in final_text
    assert any(
        item.get("source") == "llm_failure_after_tool_outputs_fallback"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_reports_tool_error_without_more_llm_calls():
    read_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-read",
                "name": "read_file",
                "args": {"path": "scripts/saved_data/result_20260523_123036/analysis_report.txt"},
            }
        ],
    )
    should_not_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-list",
                "name": "run_skill_script_shixiseng_dedicated_crawler",
                "args": {"script_path": "__list__"},
            }
        ],
    )
    tool_round = {"n": 0}

    async def _tool_runner(state, tools):
        tool_round["n"] += 1
        return {
            "messages": [
                ToolMessage(
                    content="错误：文件不存在：scripts/saved_data/result_20260523_123036/analysis_report.txt",
                    tool_call_id="tc-read",
                )
            ],
            "tool_calls": [
                {
                    "tool": "read_file",
                    "arguments": {"path": "scripts/saved_data/result_20260523_123036/analysis_report.txt"},
                }
            ],
            "tool_raw_outputs": [
                "错误：文件不存在：scripts/saved_data/result_20260523_123036/analysis_report.txt"
            ],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([read_call, should_not_call]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    final_text = str(out["messages"][-1].content)
    assert tool_round["n"] == 1
    assert "当前步骤失败" in final_text
    assert "analysis_report.txt" in final_text
    assert "tc-list" not in str(getattr(out["messages"][-1], "tool_calls", ""))
    assert any(
        item.get("source") == "tool_error_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )
