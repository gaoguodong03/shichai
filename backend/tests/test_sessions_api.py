from __future__ import annotations

import asyncio
import os
import re
import tempfile
import json
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def _session_test_env():
    with tempfile.TemporaryDirectory() as d:
        old_root = os.environ.get("SHUTONG_USER_DATA_ROOT")
        old_anon = os.environ.get("ALLOW_ANONYMOUS_API")
        os.environ["SHUTONG_USER_DATA_ROOT"] = d
        os.environ["ALLOW_ANONYMOUS_API"] = "1"
        try:
            yield
        finally:
            if old_root is None:
                os.environ.pop("SHUTONG_USER_DATA_ROOT", None)
            else:
                os.environ["SHUTONG_USER_DATA_ROOT"] = old_root
            if old_anon is None:
                os.environ.pop("ALLOW_ANONYMOUS_API", None)
            else:
                os.environ["ALLOW_ANONYMOUS_API"] = old_anon


@pytest.fixture
def client(_session_test_env):
    from app.main import app

    return TestClient(app)


def _user_msg(message_id: str, content: str) -> dict:
    return {
        "message_id": message_id,
        "speaker": {"type": "user"},
        "message": {"content": content},
        "created_at": "2026062908104800",
    }


@contextmanager
def _session_running(session_id: str):
    from app.api.group_chat_state import ACTIVE_GROUP_RUNS

    loop = asyncio.new_event_loop()
    task = loop.create_task(asyncio.sleep(60))
    ACTIVE_GROUP_RUNS[session_id] = {"run_id": "run-test", "task": task, "phase": "executing"}
    try:
        yield
    finally:
        ACTIVE_GROUP_RUNS.pop(session_id, None)
        task.cancel()
        loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        loop.close()


def test_sessions_create_list_get_delete_flow(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "回归测试会话"})
    assert create_resp.status_code == 200
    created = create_resp.json()["data"]
    session_id = created["id"]
    assert created["title"] == "回归测试会话"
    assert "speak_mode" not in created
    assert re.fullmatch(r"\d{16}", created["created_at"])
    assert re.fullmatch(r"\d{16}", created["updated_at"])

    list_resp = client.get("/api/sessions")
    assert list_resp.status_code == 200
    sessions = list_resp.json()["data"]["sessions"]
    row = next(row for row in sessions if row["id"] == session_id)
    assert "runtime" in row
    assert "runtime_state" not in row

    get_resp = client.get(f"/api/sessions/{session_id}")
    assert get_resp.status_code == 200
    detail = get_resp.json()["data"]
    assert detail["id"] == session_id
    assert detail["messages"] == []
    assert "runtime" in detail
    assert "runtime_state" not in detail

    del_resp = client.delete(f"/api/sessions/{session_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "ok"

    get_after_delete = client.get(f"/api/sessions/{session_id}")
    assert get_after_delete.status_code == 404


def test_sessions_api_uses_agent_names_contract(client: TestClient):
    agent_resp = client.post("/api/agents", json={"name": "运行时专家"})
    assert agent_resp.status_code == 200

    create_resp = client.post(
        "/api/sessions",
        json={"title": "名称协议会话", "agent_names": ["运行时专家"]},
    )
    assert create_resp.status_code == 200
    created = create_resp.json()["data"]
    assert created["agent_names"] == ["运行时专家"]
    assert "host" in created
    assert "agent_ids" not in created
    assert "leader_agent_id" not in created

    session_id = created["id"]
    detail_resp = client.get(f"/api/sessions/{session_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["agent_names"] == ["运行时专家"]
    assert "agent_ids" not in detail
    assert detail["agent_map"]["运行时专家"]["name"] == "运行时专家"

    update_resp = client.put(f"/api/sessions/{session_id}", json={"agent_names": []})
    assert update_resp.status_code == 200
    updated = update_resp.json()["data"]
    assert updated["agent_names"] == []
    assert "agent_ids" not in updated


def test_chat_once_stream_error_uses_sse_error_contract(client: TestClient, monkeypatch):
    from app.api import sessions

    async def broken_body():
        raise RuntimeError("boom")
        yield b""

    class BrokenStream:
        body_iterator = broken_body()

    async def fake_group_chat_stream(session_id, request):
        return BrokenStream()

    monkeypatch.setattr(sessions, "group_chat_stream", fake_group_chat_stream)

    response = client.post(
        "/api/sessions/s-error/chat",
        json={"message": "hi", "client_message_id": "cm-error"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {"route", "progress", "messages", "message", "end", "error"}
    error = data["error"]
    assert error == {
        "type": "error",
        "run_id": None,
        "code": "chat_once_stream_error",
        "message": "boom",
    }


def test_delete_message_rejects_running_session(client: TestClient):
    from app.api.group_chat_state import load_group_history, save_group_history
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    create_resp = client.post("/api/sessions", json={"title": "运行中禁止删消息"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]
    token = set_current_user_identity(user_id="free4inno", username="free4inno")
    try:
        save_group_history(session_id, [_user_msg("msg-1", "不能删")])
    finally:
        reset_current_user_identity(token)

    with _session_running(session_id):
        delete_resp = client.delete(f"/api/sessions/{session_id}/messages/msg-1")

    assert delete_resp.status_code == 409
    token = set_current_user_identity(user_id="free4inno", username="free4inno")
    try:
        assert load_group_history(session_id)[0]["message_id"] == "msg-1"
    finally:
        reset_current_user_identity(token)


@pytest.mark.asyncio
async def test_session_detail_uses_canonical_content(monkeypatch, tmp_path):
    from app.api import group_chat_state as state
    from app.agent import group_session_service

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(group_session_service, "load_agent_instances", lambda: [])

    async def _no_enrich(instances, workspace_id=None):
        return instances

    monkeypatch.setattr(group_session_service, "enrich_agent_instances", _no_enrich)
    session_id = "s-presentation"

    state.save_session_definitions(
        {session_id: {"title": "展示内容会话", "agent_names": [], "created_at": "t1", "updated_at": "t1"}}
    )
    state.save_group_history(
        session_id,
        [
            {
                "message_id": "a1",
                "speaker": {"type": "expert", "agent_name": "信息检索专家", "skill": "skill-web"},
                "message": {"content": "## 检索结果\n\n- Raw"},
                "created_at": "2026062908104900",
            }
        ],
    )

    detail = await group_session_service.get_group_session(session_id)
    detail_msg = detail["data"]["messages"][0]
    assert detail_msg["message"]["content"] == "## 检索结果\n\n- Raw"
    assert detail_msg["speaker"]["agent_name"] == "信息检索专家"

    stored_msg = state.load_group_history(session_id)[0]
    assert stored_msg["message"]["content"] == "## 检索结果\n\n- Raw"
    assert "presentation_content" not in stored_msg


def test_export_session_default_filename_uses_workspace_timestamp_contract(monkeypatch, tmp_path):
    from app.api import files as files_api
    from app.api import group_chat_state
    from app.agent.group_session_service import _save_group_history, export_session_to_markdown

    session_id = "sess-export-contract"
    sessions_root = tmp_path / "sessions"
    workspace_root = tmp_path / "workspaces" / session_id
    monkeypatch.setattr(group_chat_state, "GROUP_SESSIONS_ROOT", sessions_root)

    def _fake_workspace_root(_session_id: str):
        workspace_root.mkdir(parents=True, exist_ok=True)
        return workspace_root

    monkeypatch.setattr(files_api, "get_workspace_root", _fake_workspace_root)

    _save_group_history(
        session_id,
        [
            {
                "message_id": "u1",
                "speaker": {"type": "user"},
                "message": {"content": "请导出这段对话"},
                "created_at": "2026062908104800",
            }
        ],
    )

    rel_path, download_url = export_session_to_markdown(session_id)

    assert re.match(rf"^session-{re.escape(session_id)}-\d{{16}}\.md$", rel_path)
    assert not re.search(r"\d{8}-\d{6}", rel_path)
    assert download_url.endswith(f"path={rel_path}")


def test_update_empty_session_can_become_scene_without_join_messages(client: TestClient):
    agent_resp = client.post("/api/agents", json={"name": "场景专家"})
    assert agent_resp.status_code == 200

    create_resp = client.post("/api/sessions", json={"title": "新对话", "agent_names": []})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    update_resp = client.put(
        f"/api/sessions/{session_id}",
        json={
            "title": "问答验收场景",
            "agent_names": ["场景专家"],
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()["data"]
    assert updated["id"] == session_id
    assert updated["title"] == "问答验收场景"
    assert updated["agent_names"] == ["场景专家"]
    assert updated["agent_names"] == ["场景专家"]

    detail_resp = client.get(f"/api/sessions/{session_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["data"]["messages"] == []


def test_update_session_clears_stale_scheduler_state(client: TestClient):
    from app.api.group_chat_state import load_session_definitions, save_session_definitions
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    agent_resp = client.post("/api/agents", json={"name": "清理专家"})
    assert agent_resp.status_code == 200

    create_resp = client.post("/api/sessions", json={"title": "旧调度状态会话", "agent_names": []})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    token = set_current_user_identity(user_id="free4inno", username="free4inno")
    try:
        session_definitions = load_session_definitions()
        session_definitions[session_id]["scheduler_state"] = {
            "current_phase": "阶段1：选题与需求确认",
            "next_speaker": "用户",
            "next_action": "建议您先邀请【网页爬取专家】和【文字创作专家】加入会话。",
        }
        save_session_definitions(session_definitions)
    finally:
        reset_current_user_identity(token)

    update_resp = client.put(
        f"/api/sessions/{session_id}",
        json={"agent_names": ["清理专家"]},
    )
    assert update_resp.status_code == 200

    token = set_current_user_identity(user_id="free4inno", username="free4inno")
    try:
        refreshed = load_session_definitions()
        assert "scheduler_state" not in refreshed[session_id]
    finally:
        reset_current_user_identity(token)


def test_scene_session_detail_uses_scene_host_display_name(client: TestClient):
    host_resp = client.put(
        "/api/settings/host-profile",
        json={"name": "全局主持"},
    )
    assert host_resp.status_code == 200

    agent_resp = client.post("/api/agents", json={"name": "场景主持名称专家"})
    assert agent_resp.status_code == 200
    preset_resp = client.put(
        "/api/settings/session-presets",
        json={
            "presets": [
                {
                    "name": "场景主持名称回归",
                    "agent_names": ["场景主持名称专家"],
                    "host": {"name": "场景主持"},
                }
            ]
        },
    )
    assert preset_resp.status_code == 200

    create_resp = client.post(
        "/api/sessions",
            json={
                "title": "场景主持名称回归",
                "agent_names": ["场景主持名称专家"],
                "host": {"name": "场景主持"},
            },
        )
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    detail_resp = client.get(f"/api/sessions/{session_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["agent_map"]["agent-scene-host"]["name"] == "场景主持"
    assert detail["host"]["name"] == "场景主持"


def test_session_presets_preserve_top_level_system_prompt(client: TestClient):
    agent_resp = client.post("/api/agents", json={"name": "场景预设规则专家"})
    assert agent_resp.status_code == 200

    save_resp = client.put(
        "/api/settings/session-presets",
        json={
            "presets": [
                {
                    "name": "规则场景",
                    "agent_names": ["场景预设规则专家"],
                    "description": "场景说明",
                    "system_prompt": "场景预设规则",
                    "host": {"name": "规则主持"},
                }
            ]
        },
    )
    assert save_resp.status_code == 200

    list_resp = client.get("/api/settings/session-presets")
    assert list_resp.status_code == 200
    preset = list_resp.json()["data"]["presets"][0]
    assert preset["system_prompt"] == "场景预设规则"
    assert preset["host"]["system_prompt"] is None


def test_app_and_host_system_prompts_are_independent(client: TestClient):
    app_resp = client.put("/api/settings/app", json={"system_prompt": "全局平台规则"})
    assert app_resp.status_code == 200
    assert app_resp.json()["data"]["system_prompt"] == "全局平台规则"

    host_resp = client.put("/api/settings/host-profile", json={"system_prompt": "主持人调度规则"})
    assert host_resp.status_code == 200
    assert host_resp.json()["data"]["system_prompt"] == "主持人调度规则"

    app_get = client.get("/api/settings/app")
    host_get = client.get("/api/settings/host-profile")
    assert app_get.json()["data"]["system_prompt"] == "全局平台规则"
    assert host_get.json()["data"]["system_prompt"] == "主持人调度规则"


def test_app_settings_store_default_host_under_host_field(client: TestClient):
    from app.api.settings_app import app_settings_path
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    host_resp = client.put(
        "/api/settings/host-profile",
        json={"name": "测试主持人", "system_prompt": "只做调度"},
    )
    assert host_resp.status_code == 200

    token = set_current_user_identity(user_id="free4inno", username="free4inno")
    try:
        raw = json.loads(app_settings_path().read_text(encoding="utf-8"))
        assert raw["host"]["name"] == "测试主持人"
        assert raw["host"]["system_prompt"] == "只做调度"
        assert "host_profile" not in raw
    finally:
        reset_current_user_identity(token)


def test_new_regular_session_uses_latest_default_host_profile(client: TestClient):
    host_resp = client.put(
        "/api/settings/host-profile",
        json={"name": "上线默认主持"},
    )
    assert host_resp.status_code == 200

    create_resp = client.post("/api/sessions", json={"title": "默认主持链路"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    detail_resp = client.get(f"/api/sessions/{session_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["agent_map"]["agent-scene-host"]["name"] == "上线默认主持"
    assert detail["host"]["name"] == "上线默认主持"


def test_sessions_get_returns_404_for_missing_id(client: TestClient):
    resp = client.get("/api/sessions/group-not-exist-123456")
    assert resp.status_code == 404
