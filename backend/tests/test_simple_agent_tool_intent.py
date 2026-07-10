import json

import pytest
from app.agent.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.simple_agent_finalization import (
    _deterministic_tool_summary_message,
    _final_synthesis_instruction,
    _post_tool_synthesis_instruction,
)
from app.agent.simple_agent_mcp_tools import _mcp_tool_result_direct_final_message
from app.agent.simple_agent import SimpleAgent, _is_run_skill_script_workflow_step
from app.agent.tool_spec import ToolSpec


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0

    def bind_tools(self, tools, *args, **kwargs):
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


class _BindingSensitiveState:
    def __init__(self, *, search_call: AIMessage, write_call: AIMessage, final_message: AIMessage):
        self.search_call = search_call
        self.write_call = write_call
        self.final_message = final_message
        self.bound_calls = 0
        self.unbound_calls = 0


class _BindingSensitiveClient:
    def __init__(self, state: _BindingSensitiveState, *, bound: bool = False):
        self._state = state
        self._bound = bound

    def bind_tools(self, tools, *args, **kwargs):
        return _BindingSensitiveClient(self._state, bound=True)

    async def ainvoke(self, messages):
        if not self._bound:
            self._state.unbound_calls += 1
            return AIMessage(
                content=(
                    'write_workspace_file(path="web-crawler/候选清单-2026062816200000.md", '
                    'content="# Web 信息检索候选清单")'
                )
            )
        self._state.bound_calls += 1
        if self._state.bound_calls == 1:
            return self._state.search_call
        if self._state.bound_calls == 2:
            return self._state.write_call
        return self._state.final_message


class _BindingSensitiveLLM:
    def __init__(self, state: _BindingSensitiveState):
        self._client = _BindingSensitiveClient(state)

    def get_client(self):
        return self._client


def test_deterministic_tool_summary_wraps_markdown_like_raw_output_in_code_block():
    raw = (
        "---\n"
        "name: toutiao-summary\n"
        "description: 当用户需要[TODO: 任务类型]时使用，输入为[TODO: 文件/参数/链接]，产出[TODO: 结果形式]。\n"
        "allowed-tools:\n"
        "  mcp: []\n"
        "  python: ''\n"
        "---\n\n"
        "# Toutiao Summary\n"
    )

    message = _deterministic_tool_summary_message([raw])
    text = str(message.content)

    assert "以下是本轮工具返回摘要：" in text
    assert "```text\n---\nname: toutiao-summary" in text
    assert text.rstrip().endswith("```")


def test_post_tool_synthesis_instruction_does_not_embed_raw_tool_outputs():
    raw_outputs = [
        json.dumps(
            {
                "stdout": "internal stdout should stay in runtime logs",
                "stderr": "internal stderr should stay in runtime logs",
                "result": {"secret": "structured return should not be prompt text"},
            },
            ensure_ascii=False,
        )
    ]

    message = _post_tool_synthesis_instruction(raw_outputs)
    text = str(message.content)

    assert "工具已经执行完成" in text
    assert "internal stdout" not in text
    assert "internal stderr" not in text
    assert "structured return" not in text
    assert "工具返回摘要" not in text


def test_final_synthesis_instruction_does_not_embed_stdout_or_stderr():
    tool_out = {
        "tool_raw_outputs": [
            json.dumps(
                {
                    "ok": True,
                    "message": "script ok",
                    "stdout": "private stdout should stay in runtime logs",
                    "stderr": "private stderr should stay in runtime logs",
                },
                ensure_ascii=False,
            )
        ]
    }

    message = _final_synthesis_instruction("system", tool_out)
    text = str(message.content)

    assert "工具已经执行成功" in text
    assert "script ok" in text
    assert "private stdout" not in text
    assert "private stderr" not in text
    assert "\nstdout:" not in text
    assert "\nstderr:" not in text


def test_deterministic_tool_summary_returns_semantic_summary_as_markdown():
    raw = json.dumps(
        {
            "ok": True,
            "summary": (
                "# 第二章 技术范式转移：从手写代码到 Agent 编排\n\n"
                "## 2.1 生产效率的指数级提升\n\n"
                "Thoughtworks 的案例说明，工具返回的本轮摘要应该作为 Markdown 正文展示。"
            ),
        },
        ensure_ascii=False,
    )

    message = _deterministic_tool_summary_message([raw])
    text = str(message.content)

    assert text.startswith("# 第二章 技术范式转移")
    assert "## 2.1 生产效率的指数级提升" in text
    assert "```text" not in text
    assert "工具已执行完成" not in text


def test_deterministic_tool_summary_does_not_expose_missing_llm_summary_state():
    raw = (
        "Title: ISEF: International Rules for Pre-College Science Research - Society for Science\n"
        "URL: https://www.societyforscience.org/isef/international-rules/\n"
        "Published: 2019-08-26T03:28:43.000Z\n"
        "Highlights:\n"
        "The International Rules are the official rules of the Regeneron ISEF.\n"
    )

    message = _deterministic_tool_summary_message([raw])
    text = str(message.content)

    assert "工具已执行完成" in text
    assert "ISEF: International Rules" in text
    assert "模型没有生成最终文字总结" not in text


def test_mcp_direct_final_does_not_treat_artifact_ref_as_message_content():
    raw = json.dumps(
        {
            "execution_status": "succeeded",
            "content": "",
            "artifacts": [{"type": "markdown", "name": "报告", "path": "reports/report.md"}],
            "next_action": {"agent_turn": "respond", "skill_session": "release"},
        },
        ensure_ascii=False,
    )

    message = _mcp_tool_result_direct_final_message(
        {
            "tool_calls": [{"tool": "audio-asr_transcribe_audio_file", "arguments": {}}],
            "tool_raw_outputs": [raw],
        }
    )

    assert message is None


@pytest.mark.asyncio
async def test_simple_agent_calls_tool_runner_for_content_tool_json():
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc1",
                "name": "run_skill_script",
                "args": {"prompt": "generate image"},
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
async def test_simple_agent_ignores_dsml_text_tool_calls():
    response = AIMessage(
        content=(
            '<｜｜DSML｜｜tool_calls>\n'
            '<｜｜DSML｜｜invoke name="image-generation_generate_image">\n'
            '<｜｜DSML｜｜parameter name="description" string="true">河南胡辣汤封面</｜｜DSML｜｜parameter>\n'
            '<｜｜DSML｜｜parameter name="pic_size" string="true">1792x1024</｜｜DSML｜｜parameter>\n'
            '</｜｜DSML｜｜invoke>\n'
            '</｜｜DSML｜｜tool_calls>'
        )
    )
    called = {"n": 0}

    async def _tool_runner(state, tools):
        called["n"] += 1
        return {"messages": [], "tool_calls": [], "tool_raw_outputs": []}

    agent = SimpleAgent(
        llm=_FakeLLM([response]),
        tools=[ToolSpec(name="image-generation_generate_image", description="生成图片")],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=1,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="生成图片")]})

    assert called["n"] == 0
    assert "<｜｜DSML｜｜tool_calls>" not in str(out["messages"][-1].content)
    assert any(
        item.get("source") == "text_tool_call_protocol_retry"
        for item in (out.get("tool_attempt_debug") or [])
    )
    assert any(
        item.get("source") == "text_tool_call_protocol_failed"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_ignores_plain_write_workspace_file_text_call():
    response = AIMessage(
        content=(
            'write_workspace_file(path="web-crawler/候选清单-2026062816200000.md", '
            'content="# Web 信息检索候选清单\\n\\n| 编号 | 标题 | URL | 摘要 | 来源工具 |")'
        )
    )
    called = {"n": 0}

    async def _tool_runner(state, tools):
        called["n"] += 1
        return {"messages": [], "tool_calls": [], "tool_raw_outputs": []}

    agent = SimpleAgent(
        llm=_FakeLLM([response]),
        tools=[ToolSpec(name="write_workspace_file", description="write workspace file")],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=1,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="搜索资料")]})

    assert called["n"] == 0
    assert "write_workspace_file(" not in str(out["messages"][-1].content)
    assert any(
        item.get("source") == "text_tool_call_protocol_retry"
        for item in (out.get("tool_attempt_debug") or [])
    )
    assert any(
        item.get("source") == "text_tool_call_protocol_failed"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_retries_text_tool_call_protocol_once_then_executes_structured_call():
    text_protocol = AIMessage(
        content=(
            'write_workspace_file(path="web-crawler/候选清单-2026062816200000.md", '
            'content="# Web 信息检索候选清单")'
        )
    )
    structured_write = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {
                    "path": "web-crawler/候选清单-2026062816200000.md",
                    "content": "# Web 信息检索候选清单",
                },
            }
        ],
    )
    final = AIMessage(content="已保存：web-crawler/候选清单-2026062816200000.md")
    called = {"n": 0}

    async def _tool_runner(state, tools):
        called["n"] += 1
        last = state["messages"][-1]
        assert last.tool_calls[0]["name"] == "write_workspace_file"
        return {
            "messages": [
                ToolMessage(
                    content="已写入当前 Chat 工作区文件：web-crawler/候选清单-2026062816200000.md",
                    tool_call_id="tc-write",
                )
            ],
            "tool_calls": [{"tool": "write_workspace_file", "arguments": last.tool_calls[0]["args"]}],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：web-crawler/候选清单-2026062816200000.md"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([text_protocol, structured_write, final]),
        tools=[ToolSpec(name="write_workspace_file", description="write workspace file")],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=3,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="搜索资料并保存")]})

    assert called["n"] == 1
    assert "write_workspace_file(" not in str(out["messages"][-1].content)
    assert any(
        item.get("source") == "text_tool_call_protocol_retry"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_retries_post_tool_text_protocol_before_falling_back_to_summary():
    search_call = AIMessage(
        content="",
        tool_calls=[{"id": "tc-search", "name": "mcp_web_search", "args": {"query": "智能软件工程伦理"}}],
    )
    text_protocol = AIMessage(
        content=(
            'write_workspace_file(path="web-crawler/候选清单-2026062816200000.md", '
            'content="# Web 信息检索候选清单")'
        )
    )
    structured_write = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {
                    "path": "web-crawler/候选清单-2026062816200000.md",
                    "content": "# Web 信息检索候选清单",
                },
            }
        ],
    )
    final = AIMessage(content="已保存：web-crawler/候选清单-2026062816200000.md")
    calls: list[str] = []

    async def _tool_runner(state, tools):
        last = state["messages"][-1]
        tool_name = last.tool_calls[0]["name"]
        calls.append(tool_name)
        if tool_name == "mcp_web_search":
            return {
                "messages": [ToolMessage(content="检索摘要", tool_call_id="tc-search")],
                "tool_calls": [{"tool": "mcp_web_search", "arguments": {"query": "智能软件工程伦理"}}],
                "tool_raw_outputs": ["检索摘要"],
            }
        return {
            "messages": [
                ToolMessage(
                    content="已写入当前 Chat 工作区文件：web-crawler/候选清单-2026062816200000.md",
                    tool_call_id="tc-write",
                )
            ],
            "tool_calls": [{"tool": "write_workspace_file", "arguments": last.tool_calls[0]["args"]}],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：web-crawler/候选清单-2026062816200000.md"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([search_call, text_protocol, structured_write, final]),
        tools=[
            ToolSpec(name="mcp_web_search", description="search"),
            ToolSpec(name="write_workspace_file", description="write workspace file"),
        ],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="搜索资料并保存")]})

    assert calls == ["mcp_web_search", "write_workspace_file"]
    final_text = str(out["messages"][-1].content)
    assert "已保存：web-crawler/候选清单-2026062816200000.md" in final_text
    assert "工具已执行完成。以下是本轮工具返回摘要" not in final_text
    assert any(
        item.get("source") == "text_tool_call_protocol_retry"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_uses_bound_tools_when_synthesizing_after_search_result():
    search_call = AIMessage(
        content="",
        tool_calls=[{"id": "tc-search", "name": "mcp_web_search", "args": {"query": "智能软件工程伦理"}}],
    )
    write_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {
                    "path": "web-crawler/候选清单-2026062816200000.md",
                    "content": "# Web 信息检索候选清单",
                },
            }
        ],
    )
    final = AIMessage(content="已保存：web-crawler/候选清单-2026062816200000.md")
    state = _BindingSensitiveState(
        search_call=search_call,
        write_call=write_call,
        final_message=final,
    )
    calls: list[str] = []

    async def _tool_runner(tool_state, tools):
        last = tool_state["messages"][-1]
        tool_name = last.tool_calls[0]["name"]
        calls.append(tool_name)
        if tool_name == "mcp_web_search":
            return {
                "messages": [ToolMessage(content="检索摘要", tool_call_id="tc-search")],
                "tool_calls": [{"tool": "mcp_web_search", "arguments": {"query": "智能软件工程伦理"}}],
                "tool_raw_outputs": ["检索摘要"],
            }
        return {
            "messages": [
                ToolMessage(
                    content="已写入当前 Chat 工作区文件：web-crawler/候选清单-2026062816200000.md",
                    tool_call_id="tc-write",
                )
            ],
            "tool_calls": [{"tool": "write_workspace_file", "arguments": last.tool_calls[0]["args"]}],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：web-crawler/候选清单-2026062816200000.md"],
        }

    agent = SimpleAgent(
        llm=_BindingSensitiveLLM(state),
        tools=[
            ToolSpec(name="mcp_web_search", description="search"),
            ToolSpec(name="write_workspace_file", description="write workspace file"),
        ],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="搜索资料并保存")]})

    assert calls == ["mcp_web_search", "write_workspace_file"]
    assert state.unbound_calls == 0
    assert state.bound_calls >= 3
    assert "已保存：web-crawler/候选清单-2026062816200000.md" in str(out["messages"][-1].content)


@pytest.mark.asyncio
async def test_simple_agent_stream_ignores_plain_write_workspace_file_text_call_without_visible_protocol():
    response = AIMessage(
        content=(
            'write_workspace_file(path="web-crawler/候选清单-2026062816200000.md", '
            'content="# Web 信息检索候选清单")'
        )
    )
    calls: list[str] = []

    async def _tool_runner(state, tools):
        calls.append("called")
        return {"messages": [], "tool_calls": [], "tool_raw_outputs": []}

    agent = SimpleAgent(
        llm=_FakeLLM([response]),
        tools=[ToolSpec(name="write_workspace_file", description="write workspace file")],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=1,
    )

    visible_texts: list[str] = []
    final_debug: list[dict] = []
    async for ev in agent.astream({"messages": [HumanMessage(content="搜索资料")]}, stream_mode=["updates"]):
        if ev.get("type") == "agent_step" and isinstance(ev.get("message"), AIMessage):
            text = str(ev["message"].content or "").strip()
            if text:
                visible_texts.append(text)
        if ev.get("type") == "final_step":
            final_debug = ev.get("tool_attempt_debug") or []

    assert calls == []
    assert all("write_workspace_file(" not in text for text in visible_texts)
    assert any(item.get("source") == "text_tool_call_protocol_retry" for item in final_debug)
    assert any(item.get("source") == "text_tool_call_protocol_failed" for item in final_debug)


@pytest.mark.asyncio
async def test_simple_agent_final_reply_uses_actual_written_workspace_path():
    write_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {
                    "path": "web-crawler/候选清单-20250401133000.md",
                    "content": "# 候选清单",
                },
            }
        ],
    )
    stale_final = AIMessage(content="候选清单已保存：`web-crawler/候选清单-20250401133000.md`")

    async def _tool_runner(state, tools):
        return {
            "messages": [
                ToolMessage(
                    content="已写入当前 Chat 工作区文件：web-crawler/候选清单-2026062816284700.md",
                    tool_call_id="tc-write",
                )
            ],
            "tool_calls": [
                {
                    "tool": "write_workspace_file",
                    "arguments": {
                        "path": "web-crawler/候选清单-20250401133000.md",
                        "content": "# 候选清单",
                    },
                }
            ],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：web-crawler/候选清单-2026062816284700.md"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([write_call, stale_final]),
        tools=[ToolSpec(name="write_workspace_file", description="write workspace file")],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=1,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="搜索资料")]})

    final_text = str(out["messages"][-1].content)
    assert "web-crawler/候选清单-2026062816284700.md" in final_text
    assert "web-crawler/候选清单-20250401133000.md" not in final_text


@pytest.mark.asyncio
async def test_simple_agent_ignores_second_write_workspace_file_call_after_successful_write():
    first_write = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {
                    "path": "web-crawler/候选清单-20250401133000.md",
                    "content": "# 候选清单",
                },
            }
        ],
    )
    duplicate_write = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-duplicate-write",
                "name": "write_workspace_file",
                "args": {
                    "path": "web-crawler/候选清单-20250401133000.md",
                    "content": "# 候选清单",
                },
            }
        ],
    )
    call_count = 0

    async def _tool_runner(state, tools):
        nonlocal call_count
        call_count += 1
        return {
            "messages": [
                ToolMessage(
                    content="已写入当前 Chat 工作区文件：web-crawler/候选清单-2026062816284700.md",
                    tool_call_id=state["messages"][-1].tool_calls[0]["id"],
                )
            ],
            "tool_calls": [
                {
                    "tool": "write_workspace_file",
                    "arguments": state["messages"][-1].tool_calls[0]["args"],
                }
            ],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：web-crawler/候选清单-2026062816284700.md"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([first_write, duplicate_write]),
        tools=[ToolSpec(name="write_workspace_file", description="write workspace file")],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=1,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="搜索资料")]})

    assert call_count == 1
    assert any(
        item.get("source") == "post_tool_synthesis_repeated_tool_calls_ignored"
        for item in (out.get("tool_attempt_debug") or [])
    )


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
    write_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {"path": "notes/task.txt", "content": "任务"},
            }
        ],
    )
    should_not_call = AIMessage(content="不应该为了工具后总结再次调用模型")
    tool_round = {"n": 0}

    async def _tool_runner(state, tools):
        tool_round["n"] += 1
        return {
            "messages": [HumanMessage(content="written")],
            "tool_calls": [
                {
                    "tool": "write_workspace_file",
                    "arguments": {"path": "notes/task.txt", "content": "任务"},
                }
            ],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：notes/task.txt"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([write_call, should_not_call]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=6,
        stop_after_tool_names=("write_workspace_file",),
        synthesize_after_tools=False,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    assert tool_round["n"] == 1
    assert all("不应该" not in str(getattr(msg, "content", "")) for msg in out["messages"])
    assert any(
        item.get("source") == "stop_after_tool_result"
        and item.get("tool") == "write_workspace_file"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_continues_after_script_next_action_to_write_workspace():
    script_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-script",
                "name": "run_skill_script_skill-builder",
                "args": {"skill_name": "demo"},
            }
        ],
    )
    write_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {"path": "skills/demo/SKILL.md", "content": "# Demo"},
            }
        ],
    )
    final_summary = AIMessage(content="已新建并写入 skills/demo/SKILL.md")
    calls: list[str] = []

    async def _tool_runner(state, tools):
        tool_call = state["messages"][-1].tool_calls[0]
        tool_name = tool_call["name"]
        calls.append(tool_name)
        if tool_name.startswith("run_skill_script"):
            raw = json.dumps(
                {
                    "execution_status": "succeeded",
                    "content": "Skill 模板目录已新建，请继续写入 SKILL.md。",
                    "artifacts": [{"type": "directory", "name": "demo", "path": "skills/demo"}],
                    "next_action": {"agent_turn": "continue", "skill_session": "keep"},
                },
                ensure_ascii=False,
            )
            return {
                "messages": [ToolMessage(content=raw, tool_call_id="tc-script")],
                "tool_calls": [{"tool": tool_name, "arguments": {"skill_name": "demo"}}],
                "tool_raw_outputs": [raw],
            }
        return {
            "messages": [ToolMessage(content="已写入当前 Chat 工作区文件：skills/demo/SKILL.md", tool_call_id="tc-write")],
            "tool_calls": [
                {
                    "tool": "write_workspace_file",
                    "arguments": {"path": "skills/demo/SKILL.md", "content": "# Demo"},
                }
            ],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：skills/demo/SKILL.md"],
            "tool_attempt_debug": [{"source": "write_workspace_file", "matched": True}],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([script_call, write_call, final_summary]),
        tools=[
            ToolSpec.from_function(
                name="run_skill_script_skill-builder",
                description="run skill script",
                func=lambda: None,
            ),
            ToolSpec.from_function(
                name="write_workspace_file",
                description="write workspace file",
                func=lambda: None,
            ),
        ],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
        synthesize_after_tools=True,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="新建 demo skill")]})

    assert calls == ["run_skill_script_skill-builder", "write_workspace_file"]
    assert str(out["messages"][-1].content) == "已新建并写入 skills/demo/SKILL.md"
    assert any(
        item.get("source") == "script_workflow_step_continue"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_continues_after_skill_builder_init_to_edit_skill():
    init_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-init",
                "name": "run_skill_script_skill-builder",
                "args": {"skill_name": "toutiao-summary"},
            }
        ],
    )
    write_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {
                    "path": "skills/toutiao-summary/SKILL.md",
                    "content": "# Toutiao Summary",
                },
            }
        ],
    )
    final_summary = AIMessage(content="已新建并完善 skills/toutiao-summary/SKILL.md")
    calls: list[str] = []

    async def _tool_runner(state, tools):
        tool_call = state["messages"][-1].tool_calls[0]
        tool_name = tool_call["name"]
        calls.append(tool_name)
        if tool_name.startswith("run_skill_script"):
            raw = json.dumps(
                {
                    "ok": True,
                    "code": "script_executed",
                    "message": "脚本执行成功。",
                    "stdout": json.dumps(
                        {
                            "execution_status": "succeeded",
                            "content": "Skill 模板目录已新建，请继续编辑 SKILL.md。",
                            "artifacts": [{"type": "directory", "name": "toutiao-summary", "path": "skills/toutiao-summary"}],
                            "next_action": {"agent_turn": "continue", "skill_session": "keep"},
                        },
                        ensure_ascii=False,
                    ),
                },
                ensure_ascii=False,
            )
            return {
                "messages": [ToolMessage(content=raw, tool_call_id="tc-init")],
                "tool_calls": [
                    {
                        "tool": tool_name,
                        "arguments": {"skill_name": "toutiao-summary"},
                    }
                ],
                "tool_raw_outputs": [raw],
            }
        return {
            "messages": [ToolMessage(content="已写入当前 Chat 工作区文件：skills/toutiao-summary/SKILL.md", tool_call_id="tc-write")],
            "tool_calls": [
                {
                    "tool": "write_workspace_file",
                    "arguments": {"path": "skills/toutiao-summary/SKILL.md"},
                }
            ],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：skills/toutiao-summary/SKILL.md"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([init_call, write_call, final_summary]),
        tools=[
            ToolSpec.from_function(
                name="run_skill_script_skill-builder",
                description="run skill script",
                func=lambda: None,
            ),
            ToolSpec.from_function(
                name="write_workspace_file",
                description="write workspace file",
                func=lambda: None,
            ),
        ],
        system_prompt="完成单次测试任务后按当前 Skill 会话协议输出。",
        tool_runner=_tool_runner,
        max_steps=4,
        synthesize_after_tools=True,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="新建 toutiao-summary skill")]})

    assert calls == ["run_skill_script_skill-builder", "write_workspace_file"]
    assert str(out["messages"][-1].content) == "已新建并完善 skills/toutiao-summary/SKILL.md"
    assert any(
        item.get("source") == "script_workflow_step_continue"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_continues_after_script_next_action_payload_without_tool_trace():
    init_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-init",
                "name": "run_skill_script_skill-builder",
                "args": {"skill_name": "toutiao-news-summary"},
            }
        ],
    )
    write_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {
                    "path": "skills/toutiao-news-summary/SKILL.md",
                    "content": "# Toutiao News Summary",
                },
            }
        ],
    )
    final_summary = AIMessage(content="已新建并完善 skills/toutiao-news-summary/SKILL.md")
    raw = json.dumps(
        {
            "execution_status": "succeeded",
            "content": "Skill 模板目录已新建，请继续编辑 SKILL.md 并运行必要验证。",
            "artifacts": [{"type": "directory", "name": "toutiao-news-summary", "path": "skills/toutiao-news-summary"}],
            "next_action": {"agent_turn": "continue", "skill_session": "keep"},
        },
        ensure_ascii=False,
    )
    calls: list[str] = []

    async def _tool_runner(state, tools):
        tool_call = state["messages"][-1].tool_calls[0]
        tool_name = tool_call["name"]
        calls.append(tool_name)
        if tool_name.startswith("run_skill_script"):
            return {
                "messages": [ToolMessage(content=raw, tool_call_id="tc-init")],
                "tool_raw_outputs": [raw],
            }
        return {
            "messages": [ToolMessage(content="已写入当前 Chat 工作区文件：skills/toutiao-news-summary/SKILL.md", tool_call_id="tc-write")],
            "tool_calls": [
                {
                    "tool": "write_workspace_file",
                    "arguments": {"path": "skills/toutiao-news-summary/SKILL.md"},
                }
            ],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：skills/toutiao-news-summary/SKILL.md"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([init_call, write_call, final_summary]),
        tools=[
            ToolSpec.from_function(
                name="run_skill_script_skill-builder",
                description="run skill script",
                func=lambda: None,
            ),
            ToolSpec.from_function(
                name="write_workspace_file",
                description="write workspace file",
                func=lambda: None,
            ),
        ],
        system_prompt="完成单次测试任务后按当前 Skill 会话协议输出。",
        tool_runner=_tool_runner,
        max_steps=4,
        synthesize_after_tools=True,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="新建 toutiao-news-summary skill")]})

    assert _is_run_skill_script_workflow_step({"tool_raw_outputs": [raw]}) is True
    assert calls == ["run_skill_script_skill-builder", "write_workspace_file"]
    final_text = str(out["messages"][-1].content)
    assert final_text == "已新建并完善 skills/toutiao-news-summary/SKILL.md"
    assert "工具已执行完成" not in final_text
    assert any(
        item.get("source") == "script_workflow_step_continue"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_continues_after_next_action_agent_turn_continue():
    init_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-init",
                "name": "run_skill_script_skill-builder",
                "args": {"template_name": "toutiao-news-summary"},
            }
        ],
    )
    write_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {
                    "path": "skills/toutiao-news-summary/SKILL.md",
                    "content": "# Toutiao News Summary",
                },
            }
        ],
    )
    final_summary = AIMessage(content="已新建并完善 skills/toutiao-news-summary/SKILL.md")
    raw = json.dumps(
        {
            "execution_status": "succeeded",
            "content": "Skill 模板目录已新建，请继续编辑 SKILL.md。",
            "artifacts": [{"type": "directory", "name": "toutiao-news-summary", "path": "skills/toutiao-news-summary"}],
            "next_action": {"agent_turn": "continue", "skill_session": "keep"},
        },
        ensure_ascii=False,
    )
    calls: list[str] = []

    async def _tool_runner(state, tools):
        tool_call = state["messages"][-1].tool_calls[0]
        tool_name = tool_call["name"]
        calls.append(tool_name)
        if tool_name.startswith("run_skill_script"):
            return {
                "messages": [ToolMessage(content=raw, tool_call_id="tc-init")],
                "tool_raw_outputs": [raw],
            }
        return {
            "messages": [ToolMessage(content="已写入当前 Chat 工作区文件：skills/toutiao-news-summary/SKILL.md", tool_call_id="tc-write")],
            "tool_calls": [
                {
                    "tool": "write_workspace_file",
                    "arguments": {"path": "skills/toutiao-news-summary/SKILL.md"},
                }
            ],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：skills/toutiao-news-summary/SKILL.md"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([init_call, write_call, final_summary]),
        tools=[
            ToolSpec.from_function(
                name="run_skill_script_skill-builder",
                description="run skill script",
                func=lambda: None,
            ),
            ToolSpec.from_function(
                name="write_workspace_file",
                description="write workspace file",
                func=lambda: None,
            ),
        ],
        system_prompt="新建 Skill。",
        tool_runner=_tool_runner,
        max_steps=4,
        synthesize_after_tools=True,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="新建 toutiao-news-summary skill")]})

    assert _is_run_skill_script_workflow_step({"tool_raw_outputs": [raw]}) is True
    assert calls == ["run_skill_script_skill-builder", "write_workspace_file"]
    assert str(out["messages"][-1].content) == "已新建并完善 skills/toutiao-news-summary/SKILL.md"
    assert "工具已执行完成" not in str(out["messages"][-1].content)


def test_script_stdout_without_next_action_does_not_continue_workflow():
    raw = json.dumps(
        {
            "execution_status": "succeeded",
            "content": "Skill 模板目录已新建。",
            "artifacts": [{"type": "directory", "name": "toutiao-news-summary", "path": "skills/toutiao-news-summary"}],
        },
        ensure_ascii=False,
    )

    assert _is_run_skill_script_workflow_step({"tool_raw_outputs": [raw]}) is False




@pytest.mark.asyncio
async def test_simple_agent_stream_ignores_duplicate_structured_write_after_successful_write():
    search_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-search",
                "name": "mcp_Exa_web_search",
                "args": {"query": "智能软件工程及伦理"},
            }
        ],
    )
    write_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {
                    "path": "web-crawler/候选清单-20250228143200.md",
                    "content": "# Web 信息检索候选清单",
                },
            }
        ],
    )
    duplicate_structured_write = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-dup-write",
                "name": "write_workspace_file",
                "args": {
                    "path": "web-crawler/候选清单-20250228143200.md",
                    "content": "# Web 信息检索候选清单",
                    "overwrite": True,
                },
            }
        ],
    )
    final_summary = AIMessage(content="候选清单已保存：`web-crawler/候选清单-2026070420444600.md`")
    calls: list[str] = []

    async def _tool_runner(state, tools):
        tool_call = state["messages"][-1].tool_calls[0]
        tool_name = tool_call["name"]
        calls.append(tool_name)
        if tool_name == "mcp_Exa_web_search":
            return {
                "messages": [ToolMessage(content="Title: A\nURL: https://example.com/a", tool_call_id="tc-search")],
                "tool_calls": [{"tool": tool_name, "arguments": {"query": "智能软件工程及伦理"}}],
                "tool_raw_outputs": ["Title: A\nURL: https://example.com/a"],
            }
        return {
            "messages": [
                ToolMessage(
                    content="已写入当前 Chat 工作区文件：web-crawler/候选清单-2026070420444600.md",
                    tool_call_id=tool_call["id"],
                )
            ],
            "tool_calls": [{"tool": "write_workspace_file", "arguments": tool_call["args"]}],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：web-crawler/候选清单-2026070420444600.md"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([search_call, write_call, duplicate_structured_write, final_summary]),
        tools=[
            ToolSpec.from_function(name="mcp_Exa_web_search", description="search", func=lambda: None),
            ToolSpec.from_function(name="write_workspace_file", description="write workspace file", func=lambda: None),
        ],
        system_prompt="搜索资料。",
        tool_runner=_tool_runner,
        max_steps=5,
        synthesize_after_tools=True,
    )

    final_debug: list[dict] = []
    async for ev in agent.astream({"messages": [HumanMessage(content="搜索智能软件工程及伦理")]}, stream_mode=["updates"]):
        if ev.get("type") == "final_step":
            final_debug = ev.get("tool_attempt_debug") or []

    assert calls == ["mcp_Exa_web_search", "write_workspace_file"]
    assert any(item.get("source") == "structured_duplicate_workspace_write_ignored" for item in final_debug)


@pytest.mark.asyncio
async def test_simple_agent_stream_continues_after_script_next_action_to_write_workspace():
    script_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-script",
                "name": "run_skill_script_skill-builder",
                "args": {"skill_name": "demo"},
            }
        ],
    )
    write_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {"path": "skills/demo/SKILL.md", "content": "# Demo"},
            }
        ],
    )
    calls: list[str] = []

    async def _tool_runner(state, tools):
        tool_call = state["messages"][-1].tool_calls[0]
        tool_name = tool_call["name"]
        calls.append(tool_name)
        if tool_name.startswith("run_skill_script"):
            raw = json.dumps(
                {
                    "execution_status": "succeeded",
                    "content": "Skill 模板目录已新建，请继续写入 SKILL.md。",
                    "artifacts": [{"type": "directory", "name": "demo", "path": "skills/demo"}],
                    "next_action": {"agent_turn": "continue", "skill_session": "keep"},
                },
                ensure_ascii=False,
            )
            return {
                "messages": [ToolMessage(content=raw, tool_call_id="tc-script")],
                "tool_calls": [{"tool": tool_name, "arguments": {"skill_name": "demo"}}],
                "tool_raw_outputs": [raw],
            }
        return {
            "messages": [ToolMessage(content="已写入当前 Chat 工作区文件：skills/demo/SKILL.md", tool_call_id="tc-write")],
            "tool_calls": [
                {
                    "tool": "write_workspace_file",
                    "arguments": {"path": "skills/demo/SKILL.md", "content": "# Demo"},
                }
            ],
            "tool_raw_outputs": ["已写入当前 Chat 工作区文件：skills/demo/SKILL.md"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([script_call, write_call, AIMessage(content="已新建并写入 skills/demo/SKILL.md")]),
        tools=[
            ToolSpec.from_function(
                name="run_skill_script_skill-builder",
                description="run skill script",
                func=lambda: None,
            ),
            ToolSpec.from_function(
                name="write_workspace_file",
                description="write workspace file",
                func=lambda: None,
            ),
        ],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
        synthesize_after_tools=True,
    )

    final_debug: list[dict] = []
    async for ev in agent.astream({"messages": [HumanMessage(content="新建 demo skill")]}, stream_mode=["updates"]):
        if isinstance(ev, dict) and ev.get("type") == "final_step":
            final_debug = ev.get("tool_attempt_debug") or []

    assert calls == ["run_skill_script_skill-builder", "write_workspace_file"]
    assert any(item.get("source") == "script_workflow_step_continue" for item in final_debug)


@pytest.mark.asyncio
async def test_simple_agent_answers_bound_skill_question_without_running_tools():
    bad_tool_call = AIMessage(
        content="",
        tool_calls=[{"id": "tc-read", "name": "read_workspace_file", "args": {"path": "transcribe_audio.py"}}],
    )
    called = {"n": 0}

    async def _tool_runner(state, tools):
        called["n"] += 1
        return {
            "messages": [ToolMessage(content="错误：文件不存在：transcribe_audio.py", tool_call_id="tc-read")],
            "tool_calls": [{"tool": "read_workspace_file", "arguments": {"path": "transcribe_audio.py"}}],
            "tool_raw_outputs": ["错误：文件不存在：transcribe_audio.py"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([bad_tool_call]),
        tools=[ToolSpec(name="read_workspace_file", description="读文件")],
        system_prompt=(
            "你是一个有用的 AI 助手。\n\n"
            "## 你当前绑定的 Skill\n"
            "若用户询问你有哪些 skill、能力或工具包，必须依据下列清单回答，不要编造清单外的名称；"
            "本轮实际执行时仍以上文完整技能说明为准。\n\n"
            "- **音频转写 MCP**（标识：`audio-asr-mcp`）\n"
            "  当用户希望使用本地 audio-asr MCP 转写 backend/data 下的音频文件时使用。\n\n"
            "你可以使用以下工具：\n"
            "- read_workspace_file: 读取工作区内相对路径对应的文件内容。\n\n"
            "当你需要使用工具时，必须使用模型的结构化工具调用。"
        ),
        tool_runner=_tool_runner,
        max_steps=2,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="你一共有哪些skill")]})

    assert called["n"] == 0
    final_text = str(out["messages"][-1].content)
    assert "音频转写 MCP" in final_text
    assert "audio-asr-mcp" in final_text
    assert "transcribe_audio.py" not in final_text
    assert "你可以使用以下工具" not in final_text
    assert "read_workspace_file" not in final_text
    assert "结构化工具调用" not in final_text
    assert any(
        item.get("source") == "bound_skill_introspection_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_does_not_treat_discussion_ability_terms_as_skill_introspection():
    final_answer = AIMessage(content="材料包正文")

    agent = SimpleAgent(
        llm=_FakeLLM([final_answer]),
        tools=[],
        system_prompt=(
            "你是一个有用的 AI 助手。\n\n"
            "## 你当前绑定的 Skill\n"
            "- **材料研究**（标识：`skill-material`）\n"
            "  整理材料"
        ),
        tool_runner=lambda *_args, **_kwargs: None,
        max_steps=2,
    )

    prompt = (
        "围绕教师刚细化的题目，整理材料包：聚焦“AI 在学生竞赛中是提高公平效率，"
        "还是模糊原创与能力边界”。如果两位同学都完成作品，一位大量使用 AI 做检索、"
        "生成和润色，另一位主要靠自己完成，我们该怎样判断他们的真实能力和竞赛结果的公正性？"
    )
    out = await agent.ainvoke({"messages": [HumanMessage(content=prompt)]})

    final_text = str(out["messages"][-1].content)
    assert final_text == "材料包正文"
    assert "我当前绑定的 Skill 有" not in final_text
    assert not any(
        item.get("source") == "bound_skill_introspection_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_does_not_treat_named_skill_execution_as_introspection():
    final_answer = AIMessage(content="开始检查开发环境")

    agent = SimpleAgent(
        llm=_FakeLLM([final_answer]),
        tools=[],
        system_prompt=(
            "你是一个有用的 AI 助手。\n\n"
            "## 你当前绑定的 Skill\n"
            "- **check-dev-env**（标识：`check-dev-env`）\n"
            "  检查本地开发环境。\n"
            "- **skill-builder**（标识：`skill-builder`）\n"
            "  新建 Skill。"
        ),
        tool_runner=lambda *_args, **_kwargs: None,
        max_steps=2,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="使用 check-dev-env 检查一下有没有安装好")]})

    final_text = str(out["messages"][-1].content)
    assert final_text == "开始检查开发环境"
    assert "我当前绑定的 Skill 有" not in final_text
    assert not any(
        item.get("source") == "bound_skill_introspection_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_ignores_history_sections_for_bound_skill_introspection():
    final_answer = AIMessage(content="开始检查开发环境")

    agent = SimpleAgent(
        llm=_FakeLLM([final_answer]),
        tools=[],
        system_prompt=(
            "你是一个有用的 AI 助手。\n\n"
            "## 你当前绑定的 Skill\n"
            "- **check-dev-env**（标识：`check-dev-env`）\n"
            "  检查本地开发环境。\n"
            "- **skill-builder**（标识：`skill-builder`）\n"
            "  新建 Skill。"
        ),
        tool_runner=lambda *_args, **_kwargs: None,
        max_steps=2,
    )

    wrapped = (
        "【群聊讨论目标】\n默认即可\n\n"
        "【本轮用户输入】\n检查我的开发环境\n\n"
        "【最近讨论】\n"
        "【用户】@导入 Skill 测试专家 你都有哪些技能\n"
        "【agent】我当前绑定的 Skill 有：check-dev-env、skill-builder\n\n"
        "【关键事实】\n- 用户刚才问过专家有哪些技能\n\n"
        "请紧扣讨论目标发言，不要偏离主题。"
    )
    out = await agent.ainvoke({"messages": [HumanMessage(content=wrapped)]})

    final_text = str(out["messages"][-1].content)
    assert final_text == "开始检查开发环境"
    assert "我当前绑定的 Skill 有" not in final_text
    assert not any(
        item.get("source") == "bound_skill_introspection_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_uses_current_user_section_for_bound_skill_introspection():
    agent = SimpleAgent(
        llm=_FakeLLM([AIMessage(content="不应调用模型")]),
        tools=[],
        system_prompt=(
            "你是一个有用的 AI 助手。\n\n"
            "## 你当前绑定的 Skill\n"
            "- **check-dev-env**（标识：`check-dev-env`）\n"
            "  检查本地开发环境。"
        ),
        tool_runner=lambda *_args, **_kwargs: None,
        max_steps=2,
    )

    wrapped = (
        "【群聊讨论目标】\n默认即可\n\n"
        "【本轮用户输入】\n你都有哪些技能\n\n"
        "【最近讨论】\n【用户】检查我的开发环境\n"
    )
    out = await agent.ainvoke({"messages": [HumanMessage(content=wrapped)]})

    final_text = str(out["messages"][-1].content)
    assert "我当前绑定的 Skill 有" in final_text
    assert "check-dev-env" in final_text
    assert any(
        item.get("source") == "bound_skill_introspection_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_synthesizes_immediately_after_configured_read_file_path():
    task_file = "handoff-note.txt"
    read_call = AIMessage(
        content="",
        tool_calls=[{"id": "tc-read", "name": "read_workspace_file", "args": {"path": task_file}}],
    )
    final_answer = AIMessage(content="按任务文件直接完成发言")
    repeated_read_call = AIMessage(
        content="",
        tool_calls=[{"id": "tc-repeat", "name": "read_workspace_file", "args": {"path": task_file}}],
    )
    tool_round = {"n": 0}

    async def _tool_runner(state, tools):
        tool_round["n"] += 1
        return {
            "messages": [ToolMessage(content="本轮任务：直接给出教师选题。", tool_call_id="tc-read")],
            "tool_calls": [{"tool": "read_workspace_file", "arguments": {"path": task_file}}],
            "tool_raw_outputs": ["本轮任务：直接给出教师选题。"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([read_call, final_answer, repeated_read_call]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
        synthesize_after_read_file_paths=(task_file,),
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    assert tool_round["n"] == 1
    assert str(out["messages"][-1].content) == "按任务文件直接完成发言"
    assert all("tc-repeat" not in str(getattr(msg, "tool_calls", "")) for msg in out["messages"])
    assert any(
        item.get("source") == "synthesize_after_read_workspace_file"
        and item.get("path") == task_file
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_does_not_direct_final_from_large_script_stdout():
    script_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-script",
                "name": "run_skill_script_shixiseng_dedicated_crawler",
                "args": {"query": "实习僧岗位"},
            }
        ],
    )
    final_answer = AIMessage(content="模型按协议总结脚本执行结果。")
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
            "tool_calls": [{"tool": "run_skill_script_shixiseng_dedicated_crawler", "arguments": {"query": "实习僧岗位"}}],
            "tool_raw_outputs": [json.dumps(raw_payload, ensure_ascii=False)],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([script_call, final_answer]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    final_text = str(out["messages"][-1].content)
    assert final_text == "模型按协议总结脚本执行结果。"
    assert "本轮岗位数：55 个" not in final_text
    assert "fetch log" not in final_text
    assert not any(
        item.get("source") == "large_run_skill_script_success_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_direct_final_for_audio_asr_mcp_without_truncation():
    transcript = "完整转写内容。" + ("很长的音频文本。" * 700)
    asr_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-asr",
                "name": "audio-asr_transcribe_audio_file",
                "args": {
                    "path": "backend/data/users/u/sessions/g/workspace/a.mp3",
                    "chunk_seconds": 120,
                },
            }
        ],
    )
    should_not_call = AIMessage(content="不应该为了音频转写再次调用模型")

    async def _tool_runner(state, tools):
        raw = json.dumps(
            {
                "execution_status": "succeeded",
                "content": transcript,
                "artifacts": [],
                "next_action": {"agent_turn": "respond", "skill_session": "release"},
            },
            ensure_ascii=False,
        )
        return {
            "messages": [ToolMessage(content=raw[:4000] + "\n...[工具结果已截断]", tool_call_id="tc-asr")],
            "tool_calls": [
                {
                    "tool": "audio-asr_transcribe_audio_file",
                    "arguments": {"path": "backend/data/users/u/sessions/g/workspace/a.mp3"},
                }
            ],
            "tool_raw_outputs": [raw],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([asr_call, should_not_call]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="转文字")]})

    assert str(out["messages"][-1].content) == transcript
    assert "不应该" not in str(out["messages"][-1].content)
    assert any(
        item.get("source") == "mcp_tool_result_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_does_not_force_audio_asr_tool_from_message_file_ref():
    model_reply = AIMessage(content="请通过结构化附件或明确工具参数提供音频文件。")
    called = {"tool": 0}

    async def _tool_runner(state, tools):
        called["tool"] += 1
        raise AssertionError("旧正文文件引用不能强制触发音频 ASR 工具")

    agent = SimpleAgent(
        llm=_FakeLLM([model_reply]),
        tools=[ToolSpec(name="audio-asr_transcribe_audio_file", description="转写音频")],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=3,
    )

    out = await agent.ainvoke(
        {
            "messages": [
                HumanMessage(
                    content="请转文字\n【文件引用：学生降转及研究方向调整.mp3｜学生降转及研究方向调整.mp3】"
                )
            ],
            "workspace_id": "group-audio",
        }
    )

    assert called["tool"] == 0
    assert str(out["messages"][-1].content) == "请通过结构化附件或明确工具参数提供音频文件。"
    assert not any(
        item.get("source") == "forced_mcp_file_ref_tool_call"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_falls_back_to_tool_summary_when_final_llm_fails():
    read_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-read",
                "name": "read_workspace_file",
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
                    "tool": "read_workspace_file",
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
        item.get("source") == "llm_failure_after_tool_outputs_summary"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_simple_agent_uses_unbound_client_after_tool_result():
    first = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-check",
                "name": "run_skill_script_sandbox-dep-check",
                "args": {"package": "pytest"},
            }
        ],
    )

    class _Client:
        def __init__(self, *, root, bound: bool = False):
            self.root = root
            self.bound = bound

        def bind_tools(self, tools, **kwargs):
            self.root.bind_kwargs.append(kwargs)
            return _Client(root=self.root, bound=True)

        async def ainvoke(self, messages):
            self.root.calls.append({"bound": self.bound, "message_count": len(messages)})
            if len(self.root.calls) == 1:
                return first
            if self.bound:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "tc-repeat",
                            "name": "run_skill_script_sandbox-dep-check",
                            "args": {"package": "pytest"},
                        }
                    ],
                )
            return AIMessage(content="工具结果已总结")

    class _LLM:
        def __init__(self):
            self.calls = []
            self.bind_kwargs = []

        def get_client(self):
            return _Client(root=self)

    llm = _LLM()
    tool_round = {"n": 0}

    async def _tool_runner(state, tools):
        tool_round["n"] += 1
        return {
            "messages": [ToolMessage(content="ok", tool_call_id="tc-check")],
            "tool_calls": [
                {
                    "tool": "run_skill_script_sandbox-dep-check",
                    "arguments": {"package": "pytest"},
                }
            ],
            "tool_raw_outputs": ["ok"],
        }

    agent = SimpleAgent(
        llm=llm,
        tools=[
            ToolSpec.from_function(
                name="run_skill_script_sandbox-dep-check",
                description="check dependency",
                func=lambda: None,
            )
        ],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    assert str(out["messages"][-1].content) == "工具结果已总结"
    assert tool_round["n"] == 1
    assert llm.calls[0]["bound"] is True
    assert llm.calls[1]["bound"] is False


@pytest.mark.asyncio
async def test_script_dependency_failure_fallback_when_final_llm_fails():
    script_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-check",
                "name": "run_skill_script_sandbox-dep-check",
                "args": {"package": "pytest"},
            }
        ],
    )
    llm_failure = AIMessage(content="抱歉，模型响应失败：Connection error.")
    raw = json.dumps(
        {
            "ok": False,
            "code": "script_exit_nonzero",
            "message": "脚本退出码 3",
            "returncode": 3,
            "stdout": "",
            "stderr": (
                "skill_python_requirements_bytes=96\n"
                + json.dumps(
                    {
                        "ok": False,
                        "code": "package_not_installed",
                        "package": "pytest",
                        "error": "ModuleNotFoundError: No module named 'pytest'",
                    },
                    ensure_ascii=False,
                )
            ),
        },
        ensure_ascii=False,
    )

    async def _tool_runner(state, tools):
        return {
            "messages": [ToolMessage(content=raw, tool_call_id="tc-check")],
            "tool_calls": [
                {
                    "tool": "run_skill_script_sandbox-dep-check",
                    "arguments": {"package": "pytest"},
                }
            ],
            "tool_raw_outputs": [raw],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([script_call, llm_failure]),
        tools=[],
        system_prompt="验证结束后按当前 Skill 会话协议输出。",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    final_text = str(out["messages"][-1].content)
    assert "没装这个依赖：pytest" in final_text
    assert "模型响应失败" not in final_text


@pytest.mark.asyncio
async def test_simple_agent_reports_tool_error_without_more_llm_calls():
    read_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-read",
                "name": "read_workspace_file",
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
                "args": {"query": "不应重复调用"},
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
                    "tool": "read_workspace_file",
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


@pytest.mark.asyncio
async def test_simple_agent_recovers_from_invented_group_read_file_missing_path():
    read_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-read",
                "name": "read_workspace_file",
                "args": {"path": "材料包_AI在学生竞赛中的应用.md"},
            }
        ],
    )
    final_answer = AIMessage(content="我会直接基于最近讨论中的材料包继续发言。")
    tool_round = {"n": 0}

    async def _tool_runner(state, tools):
        tool_round["n"] += 1
        return {
            "messages": [
                ToolMessage(
                    content="错误：文件不存在：材料包_AI在学生竞赛中的应用.md",
                    tool_call_id="tc-read",
                )
            ],
            "tool_calls": [
                {
                    "tool": "read_workspace_file",
                    "arguments": {"path": "材料包_AI在学生竞赛中的应用.md"},
                }
            ],
            "tool_raw_outputs": ["错误：文件不存在：材料包_AI在学生竞赛中的应用.md"],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([read_call, final_answer]),
        tools=[ToolSpec(name="read_workspace_file", description="读文件")],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    user_content = (
        "【群聊讨论目标】\n伴学研讨\n\n"
        "【本轮用户输入】\n（无）\n\n"
        "【最近讨论】\n"
        "材料包已整理：AI 在学生竞赛中的应用可以从公平、原创性和能力评估展开。\n"
        "下面由引导教学的教师发言。"
    )
    out = await agent.ainvoke({"messages": [HumanMessage(content=user_content)]})

    final_text = str(out["messages"][-1].content)
    assert tool_round["n"] == 1
    assert final_text == "我会直接基于最近讨论中的材料包继续发言。"
    assert "当前步骤失败" not in final_text
    assert any(
        item.get("source") == "recoverable_context_read_workspace_file_missing"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_run_skill_script_dependency_missing_direct_final_without_second_llm():
    script_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-check",
                "name": "run_skill_script_sandbox-dep-check",
                "args": {"package": "pytest"},
            }
        ],
    )
    should_not_call = AIMessage(content="不应该等待模型总结")
    tool_round = {"n": 0}
    raw = json.dumps(
        {
            "ok": False,
            "code": "script_exit_nonzero",
            "message": "脚本退出码 3",
            "returncode": 3,
            "stdout": "",
            "stderr": json.dumps(
                {
                    "ok": False,
                    "code": "package_not_installed",
                    "package": "pytest",
                    "error": "ModuleNotFoundError: No module named 'pytest'",
                },
                ensure_ascii=False,
            ),
        },
        ensure_ascii=False,
    )

    async def _tool_runner(state, tools):
        tool_round["n"] += 1
        return {
            "messages": [ToolMessage(content=raw, tool_call_id="tc-check")],
            "tool_calls": [
                {
                    "tool": "run_skill_script_sandbox-dep-check",
                    "arguments": {"package": "pytest"},
                }
            ],
            "tool_raw_outputs": [raw],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([script_call, should_not_call]),
        tools=[],
        system_prompt="验证结束后按当前 Skill 会话协议输出。",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    final_text = str(out["messages"][-1].content)
    assert tool_round["n"] == 1
    assert "没装这个依赖：pytest" in final_text
    assert "不应该等待模型总结" not in final_text
    assert not any(
        item.get("source") == "tool_error_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )
    assert any(
        item.get("source") == "script_dependency_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )


@pytest.mark.asyncio
async def test_run_skill_script_playwright_browser_missing_direct_final_without_success_hallucination():
    script_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-crawl",
                "name": "run_skill_script_shixiseng_dedicated_crawler",
                "args": {"query": "实习僧岗位"},
            }
        ],
    )
    hallucinated_success = AIMessage(content="爬取成功，共写入 55 条岗位。")
    tool_round = {"n": 0}
    stderr = (
        "BrowserType.launch: Executable doesn't exist at /ms-playwright/chromium-1161/chrome-linux/chrome\n"
        "Looks like Playwright was just installed or updated. Please run the following command to download new browsers:\n"
        "    playwright install"
    )
    raw = json.dumps(
        {
            "ok": False,
            "code": "script_exit_nonzero",
            "message": "脚本退出码 1",
            "returncode": 1,
            "stdout": "",
            "stderr": stderr,
        },
        ensure_ascii=False,
    )

    async def _tool_runner(state, tools):
        tool_round["n"] += 1
        return {
            "messages": [ToolMessage(content=raw, tool_call_id="tc-crawl")],
            "tool_calls": [
                {
                    "tool": "run_skill_script_shixiseng_dedicated_crawler",
                    "arguments": {"query": "实习僧岗位"},
                }
            ],
            "tool_raw_outputs": [raw],
        }

    agent = SimpleAgent(
        llm=_FakeLLM([script_call, hallucinated_success]),
        tools=[],
        system_prompt="x",
        tool_runner=_tool_runner,
        max_steps=4,
    )

    out = await agent.ainvoke({"messages": [HumanMessage(content="爬岗位")]})

    final_text = str(out["messages"][-1].content)
    assert tool_round["n"] == 1
    assert "Playwright 运行环境不可用" in final_text
    assert "本轮爬取没有成功" in final_text
    assert "爬取成功，共写入 55 条岗位" not in final_text
    assert any(
        item.get("source") == "playwright_runtime_failure_direct_final"
        for item in (out.get("tool_attempt_debug") or [])
    )
