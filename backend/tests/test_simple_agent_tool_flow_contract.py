from app.agent.simple_agent_tool_errors import _tool_call_display_path
from app.agent.simple_agent_tool_flow import read_file_should_synthesize_after_result, workspace_write_call_key


def test_workspace_write_call_key_ignores_removed_arg_placeholders():
    key = workspace_write_call_key(
        {
            "name": "write_workspace_file",
            "args": {"__arg1": "notes/a.md", "__arg2": "正文"},
        }
    )

    assert key == ""


def test_read_file_synthesis_ignores_removed_arg_placeholder_path():
    debug: list[dict] = []
    matched = read_file_should_synthesize_after_result(
        {
            "tool_calls": [
                {
                    "tool": "read_workspace_file",
                    "arguments": {"__arg1": "notes/a.md"},
                }
            ]
        },
        ("notes/a.md",),
        debug,
    )

    assert matched is False
    assert debug == []


def test_tool_error_labels_ignore_removed_arg_placeholder_path():
    label = _tool_call_display_path({"tool": "read_workspace_file", "arguments": {"__arg1": "notes/a.md"}})

    assert label == ""
