import json

from app.api import settings_presets as settings_presets_api


def _write_presets(path, rows):
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def test_merge_session_presets_skip_by_name(tmp_path, monkeypatch):
    presets_path = tmp_path / "session_presets.json"
    monkeypatch.setattr(settings_presets_api, "_get_session_presets_path", lambda: presets_path)
    _write_presets(
        presets_path,
        [
            {"name": "同名场景", "agent_names": ["专家1"], "host_config": {"leader_agent_name": "主持人"}},
            {"name": "其他场景", "agent_names": ["专家2"], "host_config": {"leader_agent_name": "主持人"}},
        ],
    )

    merged, imported_names, skipped_by_name, overwritten_names = settings_presets_api._merge_session_presets_into_file(
        [{"name": "同名场景", "agent_names": ["新专家"], "host_config": {"leader_agent_name": "主持人"}}],
        "skip",
    )
    assert imported_names == []
    assert skipped_by_name == ["同名场景"]
    assert overwritten_names == []
    assert [x["name"] for x in merged] == ["同名场景", "其他场景"]


def test_merge_session_presets_overwrite_all_same_name(tmp_path, monkeypatch):
    presets_path = tmp_path / "session_presets.json"
    monkeypatch.setattr(settings_presets_api, "_get_session_presets_path", lambda: presets_path)
    _write_presets(
        presets_path,
        [
            {"name": "同名场景", "agent_names": ["专家1"], "host_config": {"leader_agent_name": "主持人"}},
            {"name": "同名场景", "agent_names": ["专家2"], "host_config": {"leader_agent_name": "主持人"}},
            {"name": "保留", "agent_names": ["专家3"], "host_config": {"leader_agent_name": "主持人"}},
        ],
    )

    merged, imported_names, skipped_by_name, overwritten_names = settings_presets_api._merge_session_presets_into_file(
        [{"name": "同名场景", "agent_names": ["新专家"], "host_config": {"leader_agent_name": "主持人"}}],
        "overwrite",
    )
    assert skipped_by_name == []
    assert overwritten_names == ["同名场景", "同名场景"]
    assert imported_names == ["同名场景"]
    assert [x["name"] for x in merged] == ["保留", "同名场景"]
