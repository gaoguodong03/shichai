import pytest
import json
from app.agent.messages import AIMessage

from app.agent.skill_agent_runtime import _call_tool_impl
from app.agent.skill_tool_naming import build_skill_script_tool_name


class _DummyTool:
    def __init__(self, name: str):
        self.name = name
        self.description = "dummy"

    def func(self, **kwargs):
        return f"ok:{self.name}:{kwargs.get('prompt', '')}"

class _AsyncOnlyDummyTool:
    def __init__(self, name: str):
        self.name = name
        self.description = "dummy"
        self.func = None

    async def coroutine(self, **kwargs):
        return f"ok:{self.name}:{kwargs.get('prompt', '')}"


class _ScriptJsonTool:
    def __init__(self, name: str, raw_result: str):
        self.name = name
        self.description = "script"
        self._raw_result = raw_result
        self.calls = 0

    def func(self, **kwargs):
        self.calls += 1
        return self._raw_result


def _v2_stdout_payload(
    *,
    execution_status="succeeded",
    instruction="处理完成。",
    artifacts=None,
    handoff="host",
    resume="none",
    reason="stage_completed",
):
    return {
        "schema_version": "expert_final_state.v2",
        "execution_status": execution_status,
        "artifacts": artifacts or [],
        "next_action": {
            "handoff": handoff,
            "resume": resume,
            "reason": reason,
            "instruction": instruction,
        },
    }


@pytest.mark.asyncio
async def test_skill_tool_rejects_generic_run_skill_script_alias():
    tool = _DummyTool("run_skill_script_app-icon-generator")
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc1",
                        "name": "run_skill_script",
                        "args": {"prompt": "generate image"},
                    }
                ],
            )
        ],
        "tools": [tool],
    }
    out = await _call_tool_impl(state, [tool])
    assert isinstance(out, dict)
    debug = out.get("tool_attempt_debug") or []
    assert debug and debug[0].get("resolved_tool") == "run_skill_script"
    assert debug[0].get("matched") is False
    assert "工具 run_skill_script 不存在" in str((out.get("messages") or [])[0].content)


@pytest.mark.asyncio
async def test_skill_tool_rejects_mangled_script_tool_name():
    tool = _DummyTool("run_skill_script_app-icon-generator")
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc2",
                        "name": "run_skill_script_app-icon-generator_extra",
                        "args": {"prompt": "generate image"},
                    }
                ],
            )
        ],
        "tools": [tool],
    }
    out = await _call_tool_impl(state, [tool])
    debug = out.get("tool_attempt_debug") or []
    assert debug and debug[0].get("resolved_tool") == "run_skill_script_app-icon-generator_extra"
    assert debug[0].get("matched") is False
    assert "工具 run_skill_script_app-icon-generator_extra 不存在" in str((out.get("messages") or [])[0].content)


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
                        "args": {"prompt": "generate image"},
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


@pytest.mark.asyncio
async def test_skill_script_tool_message_exposes_only_standard_stdout_summary():
    stdout_payload = _v2_stdout_payload(
        instruction="请继续写入报告。",
        artifacts=[{"type": "file", "name": "报告", "path": "outputs/report.md"}],
        handoff="user",
        resume="same_skill",
        reason="stage_gate",
    )
    raw_result = json.dumps(
        {
            "ok": True,
            "returncode": 0,
            "stdout": json.dumps(stdout_payload, ensure_ascii=False),
            "stderr": "internal stderr must stay out of prompt",
            "sandbox_trace": {"sandbox_id": "sb-secret"},
            "message": "脚本执行成功。",
        },
        ensure_ascii=False,
    )
    tool = _ScriptJsonTool("run_skill_script_report-builder", raw_result)
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-script",
                        "name": "run_skill_script_report-builder",
                        "args": {"topic": "contract"},
                    }
                ],
            )
        ],
        "tools": [tool],
    }

    out = await _call_tool_impl(state, [tool])
    msgs = out.get("messages") or []
    assert msgs
    text = str(msgs[0].content)

    assert "请继续写入报告。" in text
    assert "outputs/report.md" in text
    assert "handoff" in text
    assert "agent_turn" not in text
    assert '"stdout"' not in text
    assert '"stderr"' not in text
    assert "returncode" not in text
    assert "sandbox_trace" not in text
    assert "internal stderr" not in text
    assert "sb-secret" not in text


@pytest.mark.asyncio
async def test_failed_standard_skill_script_stdout_is_not_cached():
    stdout_payload = _v2_stdout_payload(
        execution_status="failed",
        instruction="脚本参数无效，请修正后重试。",
        reason="failure",
    )
    raw_result = json.dumps(
        {
            "ok": True,
            "returncode": 0,
            "stdout": json.dumps(stdout_payload, ensure_ascii=False),
            "stderr": "",
            "message": "脚本执行成功。",
        },
        ensure_ascii=False,
    )
    tool = _ScriptJsonTool("run_skill_script_validator", raw_result)
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-script",
                        "name": "run_skill_script_validator",
                        "args": {"input_path": "bad.txt"},
                    }
                ],
            )
        ],
        "tools": [tool],
        "tool_result_cache": {},
    }

    await _call_tool_impl(state, [tool])
    await _call_tool_impl(state, [tool])

    assert tool.calls == 2


def test_build_skill_script_tool_name_sanitizes_non_ascii():
    tool_name = build_skill_script_tool_name("新-skill")
    assert tool_name.startswith("run_skill_script_")
    assert "新" not in tool_name
    assert "-" in tool_name or "_" in tool_name


@pytest.mark.asyncio
async def test_skill_tool_rejects_non_visible_non_ascii_requested_name():
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
                        "args": {"prompt": "generate image"},
                    }
                ],
            )
        ],
        "tools": [tool],
    }
    out = await _call_tool_impl(state, [tool])
    debug = out.get("tool_attempt_debug") or []
    assert debug and debug[0].get("resolved_tool") == "run_skill_script_新-skill"
    assert debug[0].get("matched") is False
    assert "工具 run_skill_script_新-skill 不存在" in str((out.get("messages") or [])[0].content)
