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
            {"id": "s1", "name": "同名场景", "agent_ids": ["a1"]},
            {"id": "s2", "name": "其他场景", "agent_ids": ["a2"]},
        ],
    )

    merged, imported_ids, skipped_by_name, overwritten_ids = settings_presets_api._merge_session_presets_into_file(
        [{"id": "incoming", "name": "同名场景", "agent_ids": ["x1"]}],
        "skip",
    )
    assert imported_ids == []
    assert skipped_by_name == ["同名场景"]
    assert overwritten_ids == []
    assert [x["id"] for x in merged] == ["s1", "s2"]


def test_merge_session_presets_overwrite_all_same_name(tmp_path, monkeypatch):
    presets_path = tmp_path / "session_presets.json"
    monkeypatch.setattr(settings_presets_api, "_get_session_presets_path", lambda: presets_path)
    _write_presets(
        presets_path,
        [
            {"id": "s1", "name": "同名场景", "agent_ids": ["a1"]},
            {"id": "s2", "name": "同名场景", "agent_ids": ["a2"]},
            {"id": "s3", "name": "保留", "agent_ids": ["a3"]},
        ],
    )

    merged, imported_ids, skipped_by_name, overwritten_ids = settings_presets_api._merge_session_presets_into_file(
        [{"id": "s3", "name": "同名场景", "agent_ids": ["x1"]}],
        "overwrite",
    )
    assert skipped_by_name == []
    assert overwritten_ids == ["s1", "s2"]
    assert len(imported_ids) == 1
    merged_ids = [x["id"] for x in merged]
    assert "s3" in merged_ids
    assert imported_ids[0] != "s3"
