from __future__ import annotations

from app.session_state.markdown import format_session_chat_markdown, parse_session_chat_markdown


def test_session_chat_markdown_preserves_agent_name_roundtrip():
    markdown = format_session_chat_markdown(
        [
            {
                "role": "assistant",
                "agent_name": "写作专家",
                "content": "已整理初稿",
                "message_id": "msg-agent-name",
                "timestamp": "2026-06-30T00:00:00Z",
            }
        ]
    )

    assert '"agent_name": "写作专家"' in markdown
    assert parse_session_chat_markdown(markdown)[0]["agent_name"] == "写作专家"
