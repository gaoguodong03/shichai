import asyncio

from app.api import group_chat_state as state


def test_group_meta_history_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    meta = {"s1": {"title": "会话", "agent_ids": ["agent-a"], "created_at": "t", "updated_at": "t"}}

    state.save_group_meta(meta)
    state.save_group_history("s1", [{"role": "user", "content": "你好"}])

    assert state.load_group_meta()["s1"]["title"] == "会话"
    assert state.load_group_history("s1")[0]["content"] == "你好"


def test_build_archive_segments_ignores_host_messages():
    messages = [
        {"role": "user", "message_id": "u1", "content": "目标", "timestamp": "t1"},
        {"role": "host", "message_id": "h1", "content": "下面请 A"},
        {"role": "assistant", "agent_id": "agent-a", "message_id": "a1", "content": "回答", "timestamp": "t2", "skill_id": "skill-a"},
    ]

    segments = state.build_archive_segments(messages)

    assert len(segments) == 1
    assert segments[0]["user"]["content"] == "目标"
    assert segments[0]["experts"][0]["agent_id"] == "agent-a"
    assert segments[0]["experts"][0]["messages"][0]["skill_id"] == "skill-a"


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
