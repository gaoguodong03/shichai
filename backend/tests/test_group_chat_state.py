import asyncio
import json

import pytest

from app.api import group_chat_state as state


LEGACY_SCENARIO_NAME = "scenario" + "_name"
LEGACY_LEADER_AGENT_NAME = "leader_agent" + "_name"
LEGACY_HOST_CONFIG = "host_" + "config"


def _body(content: str) -> dict:
    return {"content": content}


def test_session_definitions_history_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    sessions = {"s1": {"title": "会话", "agent_names": ["专家A"], "created_at": "t", "updated_at": "t"}}

    state.save_session_definitions(sessions)
    state.save_group_history(
        "s1",
        [
            {
                "message_id": "u1",
                "speaker": {"type": "user"},
                "message": _body("你好"),
                "created_at": "2026062908104800",
            }
        ],
    )

    assert state.load_session_definitions()["s1"]["title"] == "会话"
    assert (tmp_path / "s1" / "session.json").exists()
    assert not (tmp_path / "s1" / "meta.json").exists()
    assert state.load_group_history("s1")[0]["message"]["content"] == "你好"


def test_session_definitions_read_session_json_only(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "索引标题", "updated_at": "t1"}})
    (tmp_path / "s1" / "meta.json").write_text(
        '{"title": "旧会话目录标题", "updated_at": "t2"}',
        encoding="utf-8",
    )
    (tmp_path / "s1" / "session.json").write_text(
        '{"title": "新会话目录标题", "updated_at": "t3"}',
        encoding="utf-8",
    )

    assert state.load_session_definitions()["s1"]["title"] == "新会话目录标题"


def test_session_definitions_load_filters_legacy_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    (tmp_path / "s1").mkdir(parents=True)
    (tmp_path / "s1" / "session.json").write_text(
        json.dumps(
            {
                "title": "会话",
                "title_auto_generated": True,
                "agent_names": ["专家A"],
                "host": {
                    "name": "四九",
                    "skill_directory": "group-host",
                    "skill_name": "展示名",
                    LEGACY_LEADER_AGENT_NAME: "旧主持",
                },
                "created_at": "2026062908104800",
                "updated_at": "2026062908104900",
                LEGACY_SCENARIO_NAME: "旧场景",
                LEGACY_LEADER_AGENT_NAME: "旧主持",
                "runtime_state": {"running": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = state.load_session_definitions()["s1"]

    assert loaded == {
        "title": "会话",
        "title_auto_generated": True,
        "agent_names": ["专家A"],
        "host": {
            "name": "四九",
            "skill_directory": "group-host",
        },
        "created_at": "2026062908104800",
        "updated_at": "2026062908104900",
    }


def test_session_definitions_ignore_legacy_meta_json(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    (tmp_path / "s1").mkdir(parents=True)
    (tmp_path / "s1" / "meta.json").write_text(
        '{"title": "旧会话目录标题", "updated_at": "t2"}',
        encoding="utf-8",
    )

    assert "s1" not in state.load_session_definitions()


def test_runtime_writes_runtime_json_not_session_json(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions(
        {
            "s1": {
                "title": "会话",
                "created_at": "2026062908104800",
                "updated_at": "2026062908104800",
            }
        }
    )

    state.write_group_runtime(
        "s1",
        {
            "running": True,
            "run_id": "r1",
            "phase": "routing",
            "started_at": "2999123123595900",
        },
    )

    assert (tmp_path / "s1" / "runtime.json").exists()
    loaded = state.load_session_definitions()["s1"]
    assert "runtime_state" not in loaded
    assert state.runtime_for_session("s1", loaded)["run_id"] == "r1"


def test_runtime_json_keeps_only_contract_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": "2026062908104800"}})

    state.write_group_runtime(
        "s1",
        {
            "running": True,
            "run_id": "r1",
            "agent_name": "专家A",
            "skill": "skill-a",
            "phase": "routing",
            "started_at": "2999123123595900",
            "updated_at": "2999123123595999",
            "user_id": "u1",
            "debug": {"trace": True},
        },
    )

    raw = json.loads((tmp_path / "s1" / "runtime.json").read_text(encoding="utf-8"))

    assert raw == {
        "running": True,
        "run_id": "r1",
        "agent_name": "专家A",
        "skill": "skill-a",
        "phase": "routing",
        "started_at": "2999123123595900",
    }


def test_runtime_for_session_filters_stored_runtime_json_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": "2026062908104800"}})
    (tmp_path / "s1" / "runtime.json").write_text(
        json.dumps(
            {
                "running": True,
                "run_id": "r1",
                "agent_name": "专家A",
                "skill": "skill-a",
                "phase": "tool_running",
                "started_at": "2999123123595900",
                "updated_at": "2999123123595999",
                "user_id": "u1",
                "continuation": {"owner_agent_name": "专家A"},
                "host_scheduler": {"next_speaker": "专家A"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runtime = state.runtime_for_session("s1", {})

    assert runtime == {
        "running": True,
        "run_id": "r1",
        "agent_name": "专家A",
        "skill": "skill-a",
        "phase": "tool_running",
        "started_at": "2999123123595900",
    }


def test_session_definition_persists_only_contract_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    state.save_session_definitions(
        {
            "s1": {
                "id": "s1",
                "title": "会话",
                "title_auto_generated": True,
                "agent_names": ["专家A"],
                "host": {
                    "name": "四九",
                    "llm_name": "qwen3-max",
                    "system_prompt": "只做调度",
                    "skill_name": "主持人 Skill 展示名",
                    "skill_directory": "group-host",
                    LEGACY_HOST_CONFIG: {"name": "旧主持人"},
                    LEGACY_LEADER_AGENT_NAME: "旧主持人",
                },
                "created_at": "2026062908104800",
                "updated_at": "2026062908104900",
                "add_agent_names": ["专家B"],
                "remove_agent_names": ["专家C"],
                "runtime_state": {"running": True},
                "pending_owner_agent_name": "专家A",
                "speaker_task": "旧任务",
                "instruction": "旧指令",
                "next_prompt": "旧提示",
            }
        }
    )

    raw = json.loads((tmp_path / "s1" / "session.json").read_text(encoding="utf-8"))

    assert raw == {
        "title": "会话",
        "title_auto_generated": True,
        "agent_names": ["专家A"],
        "host": {
            "name": "四九",
            "llm_name": "qwen3-max",
            "system_prompt": "只做调度",
            "skill_directory": "group-host",
        },
        "created_at": "2026062908104800",
        "updated_at": "2026062908104900",
    }


def test_orchestration_state_writes_short_term_state_not_session_json(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions(
        {
            "s1": {
                "title": "会话",
                "created_at": "2026062908104800",
                "updated_at": "2026062908104800",
            }
        }
    )

    state.write_group_orchestration_state(
        "s1",
        {
            "host_scheduler": {
                "current_phase": "阶段2",
                "next_speaker": "写作专家",
                "next_action": "请写大纲",
            },
            "continuation": {
                "owner_agent_name": "写作专家",
                "skill_policy": "keep",
                "skill": "article-writer",
                "next_action": "继续补全正文",
            },
            "speaker_task": "旧字段",
        },
    )

    loaded = state.load_group_orchestration_state("s1")
    assert loaded == {
        "continuation": {
            "owner_agent_name": "写作专家",
            "skill_policy": "keep",
            "skill": "article-writer",
            "next_action": "继续补全正文",
        },
        "host_scheduler": {
            "current_phase": "阶段2",
            "next_speaker": "写作专家",
            "next_action": "请写大纲",
        },
    }
    assert (tmp_path / "s1" / "orchestration_state.json").exists()
    assert "scheduler_state" not in state.load_session_definitions()["s1"]


def test_orchestration_state_drops_invite_scheduler_branch(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions(
        {
            "s1": {
                "title": "会话",
                "created_at": "2026062908104800",
                "updated_at": "2026062908104800",
            }
        }
    )

    state.write_group_orchestration_state(
        "s1",
        {
            "host_scheduler": {
                "current_phase": "招募",
                "next_speaker": "invite",
                "next_action": "建议邀请专家",
                "announcement": "旧字段",
                "suggested_order": ["写作专家"],
            }
        },
    )

    assert state.load_group_orchestration_state("s1") == {}


def test_group_history_writes_canonical_speaker_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    state.save_group_history(
        "s1",
        [
            {
                "message_id": "u1",
                "speaker": {"type": "user"},
                "message": _body("你好"),
                "created_at": "2026062908104800",
                "client_message_id": "c1",
            },
            {
                "message_id": "a1",
                "speaker": {"type": "expert", "agent_name": "专家A", "skill": "skill-a"},
                "message": _body("回答"),
                "created_at": "2026062908104900",
            },
        ],
    )

    raw = json.loads((tmp_path / "s1" / "history.json").read_text(encoding="utf-8"))
    assert raw[0] == {
        "message_id": "u1",
        "speaker": {"type": "user"},
        "message": {"content": "你好"},
        "created_at": "2026062908104800",
        "client_message_id": "c1",
    }
    assert raw[1]["speaker"] == {"type": "expert", "agent_name": "专家A", "skill": "skill-a"}
    assert raw[1]["created_at"] == "2026062908104900"
    assert "skill_result" not in raw[1]
    assert "role" not in raw[1]
    assert "agent_name" not in raw[1]
    assert "timestamp" not in raw[1]


def test_group_history_accepts_host_message_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    state.save_group_history(
        "s1",
        [
            {
                "message_id": "h1",
                "speaker": {"type": "host", "agent_name": "四九"},
                "message": _body("请确认资料是否满足需求。"),
                "created_at": "2026062908104800",
            }
        ],
    )

    raw = json.loads((tmp_path / "s1" / "history.json").read_text(encoding="utf-8"))
    assert raw[0]["speaker"] == {"type": "host", "agent_name": "四九"}
    assert raw[0]["message"]["content"] == "请确认资料是否满足需求。"

    loaded = state.load_group_history("s1")
    assert loaded[0]["message"]["content"] == "请确认资料是否满足需求。"


def test_group_history_loads_canonical_messages_without_runtime_compat(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    (tmp_path / "s1").mkdir(parents=True)
    (tmp_path / "s1" / "history.json").write_text(
        json.dumps(
            [
                {
                    "message_id": "a1",
                    "speaker": {"type": "expert", "agent_name": "专家A", "skill": "skill-a"},
                    "message": {"content": "回答"},
                    "created_at": "2026062908104900",
                    "skill_result": {
                        "execution_status": "succeeded",
                        "content": "回答",
                        "artifacts": [],
                        "next_action": {"agent_turn": "respond", "skill_session": "keep"},
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = state.load_group_history("s1")

    assert loaded[0]["speaker"]["type"] == "expert"
    assert loaded[0]["speaker"]["agent_name"] == "专家A"
    assert loaded[0]["speaker"]["skill"] == "skill-a"
    assert loaded[0]["created_at"] == "2026062908104900"
    assert "role" not in loaded[0]
    assert "agent_name" not in loaded[0]
    assert "skill" not in loaded[0]
    assert "timestamp" not in loaded[0]


def test_group_history_load_drops_invalid_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    (tmp_path / "s1").mkdir(parents=True)
    valid_message = {
        "message_id": "u1",
        "speaker": {"type": "user"},
        "message": {"content": "新消息"},
        "created_at": "2026062908104800",
    }
    invalid_message = {
        "message_id": "h1",
        "speaker": {"type": "host"},
        "message": {"content": "缺少主持人名称"},
        "created_at": "2026062908104700",
    }
    history_path = tmp_path / "s1" / "history.json"
    history_path.write_text(json.dumps([invalid_message, valid_message], ensure_ascii=False), encoding="utf-8")

    loaded = state.load_group_history("s1")

    assert loaded == [
        {
            **valid_message,
            "message": {"content": "新消息"},
        }
    ]
    assert json.loads(history_path.read_text(encoding="utf-8")) == loaded


@pytest.mark.parametrize(
    "old_key, value",
    [
        ("role", "assistant"),
        ("timestamp", "2026062908104900"),
        ("agent_name", "信息检索专家"),
        ("skill", "skill-a"),
        ("tool_raw_results", []),
        ("tool_debug", {}),
        ("presentation_content", "## 检索结果"),
        ("meta", {}),
        ("schema_version", "chat.message.v1"),
        ("diagnostics", {}),
        ("raw", {}),
    ],
)
def test_group_history_rejects_old_top_level_fields_on_save(tmp_path, monkeypatch, old_key, value):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    message = {
        "message_id": "a1",
        "speaker": {"type": "expert", "agent_name": "信息检索专家"},
        "message": _body("回答"),
        "created_at": "2026062908104900",
        old_key: value,
    }

    with pytest.raises(ValueError):
        state.save_group_history("s1", [message])


def test_frontend_history_message_keeps_canonical_content(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    msg = {
        "message_id": "a1",
        "speaker": {"type": "expert", "agent_name": "信息检索专家"},
        "message": _body("最终展示内容"),
        "created_at": "2026062908104900",
    }

    assert state.frontend_history_message(msg) == {
        **msg,
        "message": {"content": "最终展示内容"},
    }


def test_stale_session_definition_save_preserves_sessions_created_later(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"long": {"title": "长对话", "updated_at": "t1"}})

    stale_snapshot = state.load_session_definitions()
    state.save_session_definitions(
        {
            "long": {"title": "长对话", "updated_at": "t1"},
            "new": {"title": "期间新建", "updated_at": "t2"},
        }
    )

    stale_snapshot["long"]["updated_at"] = "t3"
    state.save_session_definitions(stale_snapshot)

    saved = state.load_session_definitions()
    assert saved["long"]["updated_at"] == "t3"
    assert saved["new"]["title"] == "期间新建"


def test_stale_session_definition_save_does_not_revert_newer_session_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions(
        {
            "long": {"title": "长对话", "updated_at": "2026-05-24T10:00:00+00:00"},
            "other": {"title": "旧标题", "updated_at": "2026-05-24T10:00:00+00:00"},
        }
    )

    stale_snapshot = state.load_session_definitions()
    state.save_session_definitions(
        {
            "long": {"title": "长对话", "updated_at": "2026-05-24T10:00:00+00:00"},
            "other": {"title": "新标题", "updated_at": "2026-05-24T10:01:00+00:00"},
        }
    )

    stale_snapshot["long"]["updated_at"] = "2026-05-24T10:02:00+00:00"
    state.save_session_definitions(stale_snapshot)

    saved = state.load_session_definitions()
    assert saved["long"]["updated_at"] == "2026-05-24T10:02:00+00:00"
    assert saved["other"]["title"] == "新标题"


def test_build_archive_segments_ignores_host_messages():
    messages = [
        {"speaker": {"type": "user"}, "message_id": "u1", "message": _body("目标"), "created_at": "t1"},
        {"speaker": {"type": "host", "agent_name": "四九"}, "message_id": "h1", "message": _body("下面请 A"), "created_at": "t1"},
        {
            "speaker": {"type": "expert", "agent_name": "专家A", "skill": "skill-a"},
            "message_id": "a1",
            "message": _body("回答"),
            "created_at": "t2",
        },
    ]

    segments = state.build_archive_segments(messages)

    assert len(segments) == 1
    assert segments[0]["user"]["content"] == "目标"
    assert segments[0]["experts"][0]["agent_name"] == "专家A"
    assert segments[0]["experts"][0]["messages"][0]["skill"] == "skill-a"


def test_runtime_clears_done_task(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    async def done():
        return None

    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(done())
        loop.run_until_complete(task)
        state.ACTIVE_GROUP_RUNS["s1"] = {"run_id": "r1", "task": task, "phase": "running"}
        session_item = {}

        runtime = state.runtime_for_session("s1", session_item)

        assert runtime == {"running": False}
        assert "runtime_state" not in session_item
    finally:
        state.ACTIVE_GROUP_RUNS.clear()
        loop.close()


def test_runtime_clears_stale_stored_run_without_active_task(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    monkeypatch.setenv("GROUP_RUNTIME_STATE_STALE_SECONDS", "60")
    state.ACTIVE_GROUP_RUNS.clear()
    published: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        state,
        "schedule_group_session_event",
        lambda session_id, event_type, payload=None: published.append((session_id, event_type, payload or {})),
    )
    state.save_session_definitions({"s1": {"title": "运行态会话", "updated_at": "t1"}})

    session_item = {}
    (tmp_path / "s1" / "runtime.json").write_text(
        json.dumps(
            {
                "running": True,
                "run_id": "old-run",
                "phase": "tool_running",
                "started_at": "2026-05-24T00:00:00+00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runtime = state.runtime_for_session("s1", session_item)

    assert runtime == {"running": False, "phase": "failed"}
    assert published[-1] == ("s1", "runtime", {"runtime": {"running": False, "phase": "failed"}})
    assert "runtime_state" not in session_item
