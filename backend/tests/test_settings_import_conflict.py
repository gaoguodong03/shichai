from app.api import settings_presets as settings_presets_api
from app.core.user_context import reset_current_user_identity, set_current_user_identity


def test_merge_session_presets_skip_by_name(tmp_path, monkeypatch):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-conflict", username="conflict@example.com")
    try:
        settings_presets_api._mirror_session_presets_to_resources(
            [
                {"name": "同名场景", "agent_names": ["专家1"], "host": {"name": "主持人"}},
                {"name": "其他场景", "agent_names": ["专家2"], "host": {"name": "主持人"}},
            ],
        )

        merged, imported_names, skipped_by_name, overwritten_names = settings_presets_api._merge_session_presets_into_file(
            [{"name": "同名场景", "agent_names": ["新专家"], "host": {"name": "主持人"}}],
            "skip",
        )
    finally:
        reset_current_user_identity(token)

    assert imported_names == []
    assert skipped_by_name == ["同名场景"]
    assert overwritten_names == []
    assert [x["name"] for x in merged] == ["其他场景", "同名场景"]


def test_merge_session_presets_overwrites_same_name_resource(tmp_path, monkeypatch):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-conflict", username="conflict@example.com")
    try:
        settings_presets_api._mirror_session_presets_to_resources(
            [
                {"name": "同名场景", "agent_names": ["专家1"], "host": {"name": "主持人"}},
                {"name": "保留", "agent_names": ["专家3"], "host": {"name": "主持人"}},
            ],
        )

        merged, imported_names, skipped_by_name, overwritten_names = settings_presets_api._merge_session_presets_into_file(
            [{"name": "同名场景", "agent_names": ["新专家"], "host": {"name": "主持人"}}],
            "overwrite",
        )
    finally:
        reset_current_user_identity(token)

    assert skipped_by_name == []
    assert overwritten_names == ["同名场景"]
    assert imported_names == ["同名场景"]
    assert [x["name"] for x in merged] == ["保留", "同名场景"]
    assert next(x for x in merged if x["name"] == "同名场景")["agent_names"] == ["新专家"]
