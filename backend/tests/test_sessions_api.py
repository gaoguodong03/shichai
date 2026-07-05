from __future__ import annotations

import os
import re
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
    assert "speak_mode" not in created
    assert re.fullmatch(r"\d{16}", created["created_at"])
    assert re.fullmatch(r"\d{16}", created["updated_at"])

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
    assert "leader_agent_name" not in created
    assert "host_config" not in created
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


@pytest.mark.asyncio
async def test_session_detail_uses_presentation_content_without_mutating_history(monkeypatch, tmp_path):
    from app.api import group_chat_state as state
    from app.agent import group_session_service

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(group_session_service, "load_agent_instances", lambda: [])
    monkeypatch.setattr(group_session_service, "load_app_settings", lambda: {})

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
                "role": "assistant",
                "agent_name": "信息检索专家",
                "content": "工具已执行完成。以下是本轮工具返回摘要：\nTitle: Raw",
                "presentation_content": "## 检索结果\n\n- Raw",
                "timestamp": "2026062908104900",
            }
        ],
    )

    detail = await group_session_service.get_group_session(session_id)
    detail_msg = detail["data"]["messages"][0]
    assert detail_msg["content"] == "## 检索结果\n\n- Raw"

    stored_msg = state.load_group_history(session_id)[0]
    assert stored_msg["content"].startswith("工具已执行完成")
    assert stored_msg["presentation_content"] == "## 检索结果\n\n- Raw"


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
        [{"role": "user", "content": "请导出这段对话", "timestamp": "t1"}],
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
    assert updated["orchestration_profile"] == "scene"

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
            "speaker_task": "建议您先邀请【网页爬取专家】和【文字创作专家】加入会话。",
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
        json={"leader_agent_name": "全局主持"},
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
                    "host_config": {"leader_agent_name": "场景主持"},
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
            "scenario_name": "场景主持名称回归",
            "orchestration_profile": "scene",
        },
    )
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    detail_resp = client.get(f"/api/sessions/{session_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["agent_map"]["agent-scene-host"]["name"] == "场景主持"
    assert detail["scenario_name"] == "场景主持名称回归"
    assert "host_config" not in detail


def test_scene_session_preserves_scene_system_prompt(client: TestClient):
    agent_resp = client.post("/api/agents", json={"name": "场景规则专家"})
    assert agent_resp.status_code == 200

    create_resp = client.post(
        "/api/sessions",
        json={
            "title": "场景规则会话",
            "agent_names": ["场景规则专家"],
            "system_prompt": "场景级项目规则",
            "orchestration_profile": "scene",
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()["data"]
    assert created["system_prompt"] == "场景级项目规则"

    detail_resp = client.get(f"/api/sessions/{created['id']}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["data"]["system_prompt"] == "场景级项目规则"


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
                    "host_config": {"leader_agent_name": "规则主持"},
                }
            ]
        },
    )
    assert save_resp.status_code == 200

    list_resp = client.get("/api/settings/session-presets")
    assert list_resp.status_code == 200
    preset = list_resp.json()["data"]["presets"][0]
    assert preset["system_prompt"] == "场景预设规则"
    assert preset["host_config"]["system_prompt"] is None


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


def test_new_regular_session_uses_latest_default_host_profile(client: TestClient):
    host_resp = client.put(
        "/api/settings/host-profile",
        json={"leader_agent_name": "上线默认主持"},
    )
    assert host_resp.status_code == 200

    create_resp = client.post("/api/sessions", json={"title": "默认主持链路"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    detail_resp = client.get(f"/api/sessions/{session_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert "leader_agent_name" not in detail
    assert detail["agent_map"]["agent-scene-host"]["name"] == "上线默认主持"
    assert "host_config" not in detail or detail["host_config"] in ({}, None)


def test_sessions_get_returns_404_for_missing_id(client: TestClient):
    resp = client.get("/api/sessions/group-not-exist-123456")
    assert resp.status_code == 404
