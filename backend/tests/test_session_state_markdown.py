from __future__ import annotations

from app.session_state.markdown import format_session_chat_markdown, parse_session_chat_markdown


def test_session_chat_markdown_preserves_agent_name_roundtrip():
    markdown = format_session_chat_markdown(
        [
            {
                "speaker": {"type": "expert", "agent_name": "写作专家", "skill": "writer"},
                "content": "已整理初稿",
                "message_id": "msg-agent-name",
                "created_at": "2026063000000000",
            }
        ]
    )

    assert '"agent_name": "写作专家"' in markdown
    assert parse_session_chat_markdown(markdown)[0]["speaker"]["agent_name"] == "写作专家"
    assert parse_session_chat_markdown(markdown)[0]["created_at"] == "2026063000000000"
