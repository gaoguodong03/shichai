import json
from types import SimpleNamespace

from app.agent.skill_agent_runtime import (
    _missing_tool_result_record,
    _tool_result_record_from_exception,
    _tool_result_record_from_raw,
)


def test_script_nonzero_result_becomes_failed_tool_result():
    raw = json.dumps(
        {
            "ok": False,
            "returncode": 2,
            "stdout": "partial stdout",
            "stderr": "boom",
            "message": "脚本执行失败",
        },
        ensure_ascii=False,
    )

    result = _tool_result_record_from_raw(
        tool_name="run_skill_script_report-writer",
        tool=SimpleNamespace(name="run_skill_script_report-writer", metadata={}),
        arguments={"script_path": "scripts/build.py"},
        tool_call_id="call-1",
        raw_result=raw,
    )

    assert result["execution_status"] == "failed"
    assert result["tool_call"]["name"] == "run_skill_script"
    assert result["tool_call"]["kind"] == "script"
    assert result["error_log"]["stderr"] == "boom"
    assert result["error_log"]["stdout"] == "partial stdout"
    assert result["output"]["stdout"] == "partial stdout"


def test_mcp_tool_result_keeps_provider_identity_without_wrapper_name():
    result = _tool_result_record_from_raw(
        tool_name="mcp_Linkup_linkup-fetch_3270ad4e",
        tool=SimpleNamespace(
            name="mcp_Linkup_linkup-fetch_3270ad4e",
            metadata={"mcp_server_name": "linkup", "mcp_tool_name": "linkup-fetch"},
        ),
        arguments={"url": "https://example.com"},
        tool_call_id="call-2",
        raw_result="Title: Example",
    )

    assert result["execution_status"] == "succeeded"
    assert result["tool_call"]["name"] == "linkup-fetch"
    assert result["tool_call"]["provider"] == "linkup"
    assert result["tool_call"]["provider_tool"] == "linkup-fetch"


def test_tool_exception_becomes_failed_tool_result_with_error_log():
    result = _tool_result_record_from_exception(
        tool_name="read_workspace_file",
        tool=SimpleNamespace(name="read_workspace_file", metadata={}),
        arguments={"path": "missing.md"},
        tool_call_id="call-3",
        error=RuntimeError("cannot read"),
    )

    assert result["execution_status"] == "failed"
    assert result["message"] == "cannot read"
    assert result["error_log"]["message"] == "cannot read"


def test_missing_workspace_read_tool_is_blocked_without_required_user_fields():
    result = _missing_tool_result_record(
        tool_name="read_workspace_file",
        arguments={"path": "notes/a.md"},
        tool_call_id="call-4",
        available_tools=["write_workspace_file"],
    )

    assert result["execution_status"] == "blocked"
    assert result["message"] == "当前专家未启用 read_workspace_file，无法读取工作区文件。"
    assert "required_user_fields" not in result
