import asyncio
import json

from app.api import group_chat_state as state


def test_group_meta_history_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    meta = {"s1": {"title": "会话", "agent_names": ["专家A"], "created_at": "t", "updated_at": "t"}}

    state.save_group_meta(meta)
    state.save_group_history("s1", [{"role": "user", "content": "你好"}])

    assert state.load_group_meta()["s1"]["title"] == "会话"
    assert (tmp_path / "s1" / "session.json").exists()
    assert not (tmp_path / "s1" / "meta.json").exists()
    assert state.load_group_history("s1")[0]["content"] == "你好"


def test_group_meta_prefers_session_json_over_legacy_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_group_meta({"s1": {"title": "索引标题", "updated_at": "t1"}})
    (tmp_path / "s1" / "meta.json").write_text(
        '{"title": "旧会话目录标题", "updated_at": "t2"}',
        encoding="utf-8",
    )
    (tmp_path / "s1" / "session.json").write_text(
        '{"title": "新会话目录标题", "updated_at": "t3"}',
        encoding="utf-8",
    )

    assert state.load_group_meta()["s1"]["title"] == "新会话目录标题"


def test_group_meta_reads_legacy_meta_when_session_json_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    (tmp_path / "s1").mkdir(parents=True)
    (tmp_path / "s1" / "meta.json").write_text(
        '{"title": "旧会话目录标题", "updated_at": "t2"}',
        encoding="utf-8",
    )

    assert state.load_group_meta()["s1"]["title"] == "旧会话目录标题"


def test_runtime_state_writes_runtime_json_not_session_json(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_group_meta(
        {
            "s1": {
                "title": "会话",
                "created_at": "2026062908104800",
                "updated_at": "2026062908104800",
            }
        }
    )

    state.write_group_runtime_state(
        "s1",
        {
            "running": True,
            "run_id": "r1",
            "phase": "routing",
            "started_at": "2999123123595900",
        },
    )

    assert (tmp_path / "s1" / "runtime.json").exists()
    loaded = state.load_group_meta()["s1"]
    assert "runtime_state" not in loaded
    assert state.runtime_state_for_session("s1", loaded)["run_id"] == "r1"


def test_group_history_writes_canonical_speaker_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    state.save_group_history(
        "s1",
        [
            {
                "message_id": "u1",
                "role": "user",
                "content": "你好",
                "timestamp": "2026062908104800",
                "client_message_id": "c1",
            },
            {
                "message_id": "a1",
                "role": "assistant",
                "agent_name": "专家A",
                "content": "回答",
                "timestamp": "2026062908104900",
                "skill": "skill-a",
                "tool_debug": {
                    "skill_session_state": {
                        "skill_session": "release",
                        "source": "assistant_state_block",
                    }
                },
                "required_user_fields": [{"key": "legacy"}],
            },
        ],
    )

    raw = json.loads((tmp_path / "s1" / "history.json").read_text(encoding="utf-8"))
    assert raw[0] == {
        "message_id": "u1",
        "speaker": {"type": "user"},
        "content": "你好",
        "created_at": "2026062908104800",
        "client_message_id": "c1",
    }
    assert raw[1]["speaker"] == {"type": "expert", "agent_name": "专家A", "skill": "skill-a"}
    assert raw[1]["created_at"] == "2026062908104900"
    assert raw[1]["skill_result"] == {
        "execution_status": "succeeded",
        "next_action": {"skill_session": "release"},
    }
    assert "role" not in raw[1]
    assert "agent_name" not in raw[1]
    assert "timestamp" not in raw[1]
    assert "required_user_fields" not in raw[1]


def test_group_history_loads_canonical_messages_with_runtime_compat(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    (tmp_path / "s1").mkdir(parents=True)
    (tmp_path / "s1" / "history.json").write_text(
        json.dumps(
            [
                {
                    "message_id": "a1",
                    "speaker": {"type": "expert", "agent_name": "专家A", "skill": "skill-a"},
                    "content": "回答",
                    "created_at": "2026062908104900",
                    "skill_result": {
                        "execution_status": "succeeded",
                        "next_action": {"skill_session": "keep"},
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = state.load_group_history("s1")

    assert loaded[0]["speaker"]["type"] == "expert"
    assert loaded[0]["role"] == "assistant"
    assert loaded[0]["agent_name"] == "专家A"
    assert loaded[0]["skill"] == "skill-a"
    assert loaded[0]["timestamp"] == "2026062908104900"


def test_stale_group_meta_save_preserves_sessions_created_later(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_group_meta({"long": {"title": "长对话", "updated_at": "t1"}})

    stale_snapshot = state.load_group_meta()
    state.save_group_meta(
        {
            "long": {"title": "长对话", "updated_at": "t1"},
            "new": {"title": "期间新建", "updated_at": "t2"},
        }
    )

    stale_snapshot["long"]["updated_at"] = "t3"
    state.save_group_meta(stale_snapshot)

    saved = state.load_group_meta()
    assert saved["long"]["updated_at"] == "t3"
    assert saved["new"]["title"] == "期间新建"


def test_stale_group_meta_save_does_not_revert_newer_session_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_group_meta(
        {
            "long": {"title": "长对话", "updated_at": "2026-05-24T10:00:00+00:00"},
            "other": {"title": "旧标题", "updated_at": "2026-05-24T10:00:00+00:00"},
        }
    )

    stale_snapshot = state.load_group_meta()
    state.save_group_meta(
        {
            "long": {"title": "长对话", "updated_at": "2026-05-24T10:00:00+00:00"},
            "other": {"title": "新标题", "updated_at": "2026-05-24T10:01:00+00:00"},
        }
    )

    stale_snapshot["long"]["updated_at"] = "2026-05-24T10:02:00+00:00"
    state.save_group_meta(stale_snapshot)

    saved = state.load_group_meta()
    assert saved["long"]["updated_at"] == "2026-05-24T10:02:00+00:00"
    assert saved["other"]["title"] == "新标题"


def test_build_archive_segments_ignores_host_messages():
    messages = [
        {"role": "user", "message_id": "u1", "content": "目标", "timestamp": "t1"},
        {"role": "host", "message_id": "h1", "content": "下面请 A"},
        {"role": "assistant", "agent_name": "专家A", "message_id": "a1", "content": "回答", "timestamp": "t2", "skill": "skill-a"},
    ]

    segments = state.build_archive_segments(messages)

    assert len(segments) == 1
    assert segments[0]["user"]["content"] == "目标"
    assert segments[0]["experts"][0]["agent_name"] == "专家A"
    assert segments[0]["experts"][0]["messages"][0]["skill"] == "skill-a"


def test_runtime_state_clears_done_task(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    async def done():
        return None

    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(done())
        loop.run_until_complete(task)
        state.ACTIVE_GROUP_RUNS["s1"] = {"run_id": "r1", "task": task, "phase": "running"}
        meta_item = {"runtime_state": {"running": True}}

        runtime = state.runtime_state_for_session("s1", meta_item)

        assert runtime == {"running": False}
        assert "runtime_state" not in meta_item
    finally:
        state.ACTIVE_GROUP_RUNS.clear()
        loop.close()


def test_runtime_state_clears_stale_stored_run_without_active_task(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    monkeypatch.setenv("GROUP_RUNTIME_STATE_STALE_SECONDS", "60")
    state.ACTIVE_GROUP_RUNS.clear()

    meta_item = {
        "runtime_state": {
            "running": True,
            "run_id": "old-run",
            "phase": "tool_running",
            "started_at": "2026-05-24T00:00:00+00:00",
        }
    }

    runtime = state.runtime_state_for_session("s1", meta_item)

    assert runtime == {"running": False}
    assert "runtime_state" not in meta_item
