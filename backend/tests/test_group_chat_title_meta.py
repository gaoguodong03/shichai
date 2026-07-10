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


def test_title_refresh_does_not_infer_missing_auto_title_flag(monkeypatch):
    scheduled: list[tuple] = []
    saved_definitions: list[dict] = []

    monkeypatch.setattr(group_chat_title_meta, "_save_group_history", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        group_chat_title_meta,
        "_save_session_definitions",
        lambda definitions: saved_definitions.append(definitions.copy()),
    )
    monkeypatch.setattr(
        group_chat_title_meta,
        "_schedule_group_title_refresh",
        lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )
    session_definitions = {
        "s1": {
            "title": "多Agent协作 · 旧模板标题",
            "agent_names": [],
            "created_at": "2026071000000000",
            "updated_at": "2026071000000000",
        }
    }
    messages: list[dict] = []

    group_chat_title_meta._record_user_message_and_refresh_title(
        group_session_id="s1",
        session_definitions=session_definitions,
        messages=messages,
        user_message="请整理材料",
        client_message_id="client-1",
    )

    assert session_definitions["s1"]["title"] == "多Agent协作 · 旧模板标题"
    assert "title_auto_generated" not in session_definitions["s1"]
    assert scheduled == []
    assert saved_definitions


def test_record_user_message_omits_empty_optional_message_fields(monkeypatch):
    monkeypatch.setattr(group_chat_title_meta, "_save_group_history", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(group_chat_title_meta, "_save_session_definitions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(group_chat_title_meta, "_schedule_group_title_refresh", lambda *_args, **_kwargs: None)
    session_definitions = {
        "s1": {
            "title": "会话",
            "title_auto_generated": False,
            "agent_names": [],
            "created_at": "2026071000000000",
            "updated_at": "2026071000000000",
        }
    }
    messages: list[dict] = []

    group_chat_title_meta._record_user_message_and_refresh_title(
        group_session_id="s1",
        session_definitions=session_definitions,
        messages=messages,
        user_message="请整理材料",
        client_message_id="client-1",
    )

    assert messages[0]["message"] == {"content": "请整理材料"}
