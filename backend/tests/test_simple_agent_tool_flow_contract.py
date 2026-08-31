from app.agent.simple_agent_tool_flow import read_file_should_synthesize_after_result


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
