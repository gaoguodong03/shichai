import json
import re
from types import SimpleNamespace

import pytest

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
    assert re.fullmatch(r"\d{16}", result["created_at"])


def test_tool_result_records_explicit_duration():
    result = _tool_result_record_from_raw(
        tool_name="read_workspace_file",
        tool=SimpleNamespace(name="read_workspace_file", metadata={}),
        arguments={"path": "demo.md"},
        tool_call_id="call-timed",
        raw_result="正文",
        duration_ms=27,
    )

    assert result["duration_ms"] == 27


def test_script_tool_result_uses_skill_directory_and_manifest_entry_identity():
    tool = SimpleNamespace(
        name="run_skill_script_report-writer",
        metadata={
            "source": "script",
            "provider": "report-writer",
            "provider_tool": "scripts/build.py",
        },
    )

    result = _tool_result_record_from_raw(
        tool_name=tool.name,
        tool=tool,
        arguments={"topic": "合同"},
        tool_call_id="call-script",
        raw_result=json.dumps({"ok": True, "stdout": "{}", "stderr": "", "returncode": 0}, ensure_ascii=False),
    )

    assert result["tool_call"]["kind"] == "script"
    assert result["tool_call"]["provider"] == "report-writer"
    assert result["tool_call"]["provider_tool"] == "scripts/build.py"
    assert result["tool_call"]["name"] == "scripts/build.py"


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


def test_http_api_tool_result_keeps_saved_tool_identity():
    from app.tools.http_api_tool import create_http_api_tool

    tool = create_http_api_tool({"name": "Exa 搜索", "type": "http_api", "config": {"base_url": "https://api.example.com"}})

    result = _tool_result_record_from_raw(
        tool_name=tool.name,
        tool=tool,
        arguments={"query": {"q": "codex"}},
        tool_call_id="call-http",
        raw_result="状态码: 200\n\n{}",
    )

    assert result["tool_call"]["kind"] == "api"
    assert result["tool_call"]["provider"] == "Exa 搜索"
    assert result["tool_call"]["provider_tool"] == tool.name


def test_mcp_like_tool_name_without_metadata_is_not_guessed_as_mcp():
    with pytest.raises(ValueError):
        _tool_result_record_from_raw(
            tool_name="mcp_Server_tool",
            tool=SimpleNamespace(name="mcp_Server_tool", metadata={}),
            arguments={},
            tool_call_id="call-missing-source",
            raw_result="ok",
        )


def test_plain_text_tool_output_does_not_infer_status_from_legacy_error_prefix():
    result = _tool_result_record_from_raw(
        tool_name="mcp_Server_tool",
        tool=SimpleNamespace(
            name="mcp_Server_tool",
            metadata={"mcp_server_name": "server", "mcp_tool_name": "tool"},
        ),
        arguments={},
        tool_call_id="call-legacy-text",
        raw_result="错误：未提供 content 参数",
    )

    assert result["execution_status"] == "succeeded"
    assert result["output"]["content"] == "错误：未提供 content 参数"
    assert "error_log" not in result


def test_tool_exception_becomes_failed_tool_result_with_error_log():
    result = _tool_result_record_from_exception(
        tool_name="read_workspace_file",
        tool=SimpleNamespace(name="read_workspace_file", metadata={}),
        arguments={"path": "missing.md"},
        tool_call_id="call-3",
        error=RuntimeError("cannot read"),
    )

    assert result["execution_status"] == "failed"
    assert "message" not in result
    assert result["output"]["content"] == "cannot read"
    assert result["error_log"]["message"] == "cannot read"


def test_missing_workspace_read_tool_is_blocked_without_required_user_fields():
    result = _missing_tool_result_record(
        tool_name="read_workspace_file",
        arguments={"path": "notes/a.md"},
        tool_call_id="call-4",
        available_tools=["write_workspace_file"],
    )

    assert result["execution_status"] == "blocked"
    assert "message" not in result
    assert result["output"]["content"] == "当前专家未启用 read_workspace_file，无法读取工作区文件。请先启用文件读取能力，或让用户提供文件内容。"
    assert "required_user_fields" not in result
