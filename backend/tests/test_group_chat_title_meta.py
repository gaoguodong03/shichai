from app.agent import group_chat_title_meta


def test_title_meta_message_content_ignores_legacy_top_level_content():
    assert (
        group_chat_title_meta._message_content(
            {
                "message": {"content": "标准标题正文"},
                "content": "旧顶层标题正文",
            }
        )
        == "标准标题正文"
    )
    assert group_chat_title_meta._message_content({"content": "旧顶层标题正文"}) == ""
