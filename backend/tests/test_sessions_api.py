from __future__ import annotations

import os
import tempfile

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


def test_sessions_create_list_get_delete_flow(client: TestClient):
    create_resp = client.post("/api/sessions", json={"title": "回归测试会话"})
    assert create_resp.status_code == 200
    created = create_resp.json()["data"]
    session_id = created["id"]
    assert created["title"] == "回归测试会话"
    assert created["speak_mode"] == "auto"

    list_resp = client.get("/api/sessions")
    assert list_resp.status_code == 200
    sessions = list_resp.json()["data"]["sessions"]
    assert any(row["id"] == session_id for row in sessions)

    get_resp = client.get(f"/api/sessions/{session_id}")
    assert get_resp.status_code == 200
    detail = get_resp.json()["data"]
    assert detail["id"] == session_id
    assert detail["messages"] == []

    del_resp = client.delete(f"/api/sessions/{session_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "ok"

    get_after_delete = client.get(f"/api/sessions/{session_id}")
    assert get_after_delete.status_code == 404


def test_update_empty_session_can_become_scene_without_join_messages(client: TestClient):
    agent_resp = client.post("/api/agents", json={"agent_id": "agent-scene-flow", "name": "场景专家"})
    assert agent_resp.status_code == 200

    create_resp = client.post("/api/sessions", json={"title": "新对话", "agent_ids": []})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    update_resp = client.put(
        f"/api/sessions/{session_id}",
        json={
            "title": "问答验收场景",
            "agent_ids": ["agent-scene-flow"],
            "leader_agent_id": "agent-scene-flow",
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()["data"]
    assert updated["id"] == session_id
    assert updated["title"] == "问答验收场景"
    assert updated["agent_ids"] == ["agent-scene-flow"]
    assert updated["orchestration_profile"] == "scene"

    detail_resp = client.get(f"/api/sessions/{session_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["data"]["messages"] == []


def test_scene_session_detail_uses_scene_host_display_name(client: TestClient):
    host_resp = client.put(
        "/api/settings/host-profile",
        json={"display_name": "全局主持", "skill_ids": [], "mcp_server_ids": []},
    )
    assert host_resp.status_code == 200

    agent_resp = client.post("/api/agents", json={"agent_id": "agent-scene-host-name", "name": "场景专家"})
    assert agent_resp.status_code == 200

    create_resp = client.post(
        "/api/sessions",
        json={
            "title": "场景主持名称回归",
            "agent_ids": ["agent-scene-host-name"],
            "leader_agent_id": "agent-scene-host",
            "host_config": {"display_name": "场景主持", "skill_ids": []},
        },
    )
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    detail_resp = client.get(f"/api/sessions/{session_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["agent_map"]["agent-scene-host"]["name"] == "场景主持"
    assert detail["host_config"]["display_name"] == "场景主持"


def test_new_regular_session_uses_latest_default_host_profile(client: TestClient):
    host_resp = client.put(
        "/api/settings/host-profile",
        json={"display_name": "上线默认主持", "skill_ids": [], "mcp_server_ids": []},
    )
    assert host_resp.status_code == 200

    create_resp = client.post("/api/sessions", json={"title": "默认主持链路"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    detail_resp = client.get(f"/api/sessions/{session_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["leader_agent_id"] == "agent-scene-host"
    assert detail["agent_map"]["agent-scene-host"]["name"] == "上线默认主持"
    assert "host_config" not in detail or detail["host_config"] in ({}, None)


def test_sessions_get_returns_404_for_missing_id(client: TestClient):
    resp = client.get("/api/sessions/group-not-exist-123456")
    assert resp.status_code == 404
