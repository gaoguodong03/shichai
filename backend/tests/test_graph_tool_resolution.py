import pytest
from langchain_core.messages import AIMessage

from app.agent.graph import _call_tool_impl
from app.agent.tools_for_skill import build_skill_script_tool_name


class _DummyTool:
    def __init__(self, name: str):
        self.name = name
        self.description = "dummy"

    def func(self, **kwargs):
        return f"ok:{self.name}:{kwargs.get('script_path', '')}"

class _AsyncOnlyDummyTool:
    def __init__(self, name: str):
        self.name = name
        self.description = "dummy"
        self.func = None

    async def coroutine(self, **kwargs):
        return f"ok:{self.name}:{kwargs.get('script_path', '')}"


@pytest.mark.asyncio
async def test_skill_tool_alias_run_skill_script_resolved():
    tool = _DummyTool("run_skill_script_app-icon-generator")
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc1",
                        "name": "run_skill_script",
                        "args": {"script_path": "generate_image.py"},
                    }
                ],
            )
        ],
        "tools": [tool],
    }
    out = await _call_tool_impl(state, [tool])
    assert isinstance(out, dict)
    assert out.get("messages")
    debug = out.get("tool_attempt_debug") or []
    assert debug and debug[0].get("resolved_tool") == "run_skill_script_app-icon-generator"
    assert debug[0].get("matched") is True


@pytest.mark.asyncio
async def test_skill_tool_mangled_name_resolved():
    tool = _DummyTool("run_skill_script_app-icon-generator")
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc2",
                        "name": "run_skill_script_app-icon-generator_extra",
                        "args": {"script_path": "generate_image.py"},
                    }
                ],
            )
        ],
        "tools": [tool],
    }
    out = await _call_tool_impl(state, [tool])
    debug = out.get("tool_attempt_debug") or []
    assert debug and debug[0].get("resolved_tool") == "run_skill_script_app-icon-generator"
    assert debug[0].get("matched") is True


@pytest.mark.asyncio
async def test_skill_tool_exec_supports_async_only_tool():
    tool = _AsyncOnlyDummyTool("run_skill_script_app-icon-generator")
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc3",
                        "name": "run_skill_script_app-icon-generator",
                        "args": {"script_path": "generate_image.py"},
                    }
                ],
            )
        ],
        "tools": [tool],
    }
    out = await _call_tool_impl(state, [tool])
    msgs = out.get("messages") or []
    assert msgs
    assert "执行结果" in str(msgs[0].content)


def test_build_skill_script_tool_name_sanitizes_non_ascii():
    tool_name = build_skill_script_tool_name("新-skill")
    assert tool_name.startswith("run_skill_script_")
    assert "新" not in tool_name
    assert "-" in tool_name or "_" in tool_name


@pytest.mark.asyncio
async def test_skill_tool_non_ascii_requested_name_resolved():
    safe_name = build_skill_script_tool_name("新-skill")
    tool = _DummyTool(safe_name)
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc4",
                        "name": "run_skill_script_新-skill",
                        "args": {"script_path": "generate_image.py"},
                    }
                ],
            )
        ],
        "tools": [tool],
    }
    out = await _call_tool_impl(state, [tool])
    debug = out.get("tool_attempt_debug") or []
    assert debug and debug[0].get("resolved_tool") == safe_name
    assert debug[0].get("matched") is True

