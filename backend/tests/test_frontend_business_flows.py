from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage


class _SeqClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0

    def bind_tools(self, tools, *args, **kwargs):
        return self

    async def ainvoke(self, messages):
        if self._idx >= len(self._responses):
            return self._responses[-1]
        response = self._responses[self._idx]
        self._idx += 1
        return response


class _FakeLLM:
    def __init__(self, responses):
        self._client = _SeqClient(responses)

    def get_client(self):
        return self._client


@pytest.fixture
def frontend_flow_client(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        old_root = os.environ.get("SHUTONG_USER_DATA_ROOT")
        old_anon = os.environ.get("ALLOW_ANONYMOUS_API")
        monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", d)
        monkeypatch.setenv("ALLOW_ANONYMOUS_API", "1")

        from app.api import sandbox_settings, settings_mcp
        from app.main import app

        async def fake_prewarm_current_user(*args, **kwargs):
            return {"status": "ok", "sandbox_id": "sb-test"}

        async def fake_ensure_user_mcp_config_loaded(_username):
            return SimpleNamespace(server_configs=[], sessions={}, tools={})

        async def fake_dispose_mcp_runtime_for_user(_username):
            return None

        monkeypatch.setattr(sandbox_settings, "_prewarm_current_user", fake_prewarm_current_user)
        monkeypatch.setattr(settings_mcp, "ensure_user_mcp_config_loaded", fake_ensure_user_mcp_config_loaded)
        monkeypatch.setattr(settings_mcp, "dispose_mcp_runtime_for_user", fake_dispose_mcp_runtime_for_user)

        try:
            with TestClient(app) as client:
                yield client
        finally:
            if old_root is None:
                os.environ.pop("SHUTONG_USER_DATA_ROOT", None)
            else:
                os.environ["SHUTONG_USER_DATA_ROOT"] = old_root
            if old_anon is None:
                os.environ.pop("ALLOW_ANONYMOUS_API", None)
            else:
                os.environ["ALLOW_ANONYMOUS_API"] = old_anon


def _headers(user: str = "frontend-flow@example.test") -> dict[str, str]:
    return {"X-User-Name": user}


def test_frontend_workspace_session_and_file_flow(frontend_flow_client: TestClient):
    client = frontend_flow_client
    headers = _headers()

    create = client.post("/api/sessions", json={"title": "前端全流程会话"}, headers=headers)
    assert create.status_code == 200
    session_id = create.json()["data"]["id"]

    listed = client.get("/api/sessions", headers=headers)
    assert listed.status_code == 200
    assert any(x["id"] == session_id for x in listed.json()["data"]["sessions"])

    updated = client.put(
        f"/api/sessions/{session_id}",
        json={"title": "前端全流程会话-已更新", "agent_ids": []},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "前端全流程会话-已更新"

    stop = client.post(f"/api/sessions/{session_id}/chat/stop", headers=headers)
    assert stop.status_code == 200

    mkdir = client.post(
        f"/api/workspaces/{session_id}/files/mkdir",
        json={"dirname": "docs"},
        headers=headers,
    )
    assert mkdir.status_code == 200

    created_file = client.post(
        f"/api/workspaces/{session_id}/files",
        params={"path": "docs"},
        json={"filename": "brief.md", "content": "# Brief\n"},
        headers=headers,
    )
    assert created_file.status_code == 200
    assert created_file.json()["data"]["path"] == "docs/brief.md"

    content = client.get(
        f"/api/workspaces/{session_id}/files/content",
        params={"path": "docs/brief.md"},
        headers=headers,
    )
    assert content.status_code == 200
    assert content.json()["data"]["content"] == "# Brief\n"

    saved = client.put(
        f"/api/workspaces/{session_id}/files/content",
        params={"path": "docs/brief.md"},
        json={"content": "# Brief\nupdated\n"},
        headers=headers,
    )
    assert saved.status_code == 200

    uploaded = client.post(
        f"/api/workspaces/{session_id}/files/upload",
        files={"file": ("recording.wav", b"audio-bytes")},
        headers=headers,
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["data"]["path"] == "recording.wav"

    media_dir = client.post(
        f"/api/workspaces/{session_id}/files/mkdir",
        json={"dirname": "media"},
        headers=headers,
    )
    assert media_dir.status_code == 200

    renamed = client.put(
        f"/api/workspaces/{session_id}/files/rename",
        params={"path": "recording.wav"},
        json={"new_name": "media/recording.wav"},
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["path"] == "media/recording.wav"

    files = client.get(f"/api/workspaces/{session_id}/files", headers=headers)
    assert files.status_code == 200
    paths = {x["path"] for x in files.json()["data"]["entries"]}
    assert "docs" in paths
    assert "media" in paths

    exported = client.post(f"/api/sessions/{session_id}/export", headers=headers)
    assert exported.status_code == 400
    assert "会话无消息" in exported.json()["detail"]

    deleted_file = client.delete(
        f"/api/workspaces/{session_id}/files/content",
        params={"path": "docs/brief.md"},
        headers=headers,
    )
    assert deleted_file.status_code == 200

    deleted_session = client.delete(f"/api/sessions/{session_id}", headers=headers)
    assert deleted_session.status_code == 200
    assert deleted_session.json()["data"]["deleted"] is True


def test_frontend_session_question_answer_flow(frontend_flow_client: TestClient, monkeypatch):
    from app.api import group_chat

    client = frontend_flow_client
    headers = _headers("frontend-chat@example.test")
    answer = "2+2 等于 4。"
    monkeypatch.setattr(group_chat, "_get_llm_for_dha", lambda dha, app_settings: _FakeLLM([AIMessage(content=answer)]))

    skill = client.post(
        "/api/settings/skills",
        json={"name": "QA Flow Skill", "description": "回答用户在会话中提出的问题"},
        headers=headers,
    )
    assert skill.status_code == 200
    skill_id = skill.json()["data"]["id"]

    dha = client.post(
        "/api/dha/instances",
        json={
            "agent_id": "agent-qa-flow",
            "name": "问答专家",
            "role": "回答用户提出的问题",
            "system_prompt": "直接回答用户问题。",
            "skill_ids": [skill_id],
            "mcp_server_ids": [],
            "file_capabilities": {"read": False, "write": False},
        },
        headers=headers,
    )
    assert dha.status_code == 200

    create = client.post(
        "/api/sessions",
        json={"title": "问答检查会话", "agent_ids": ["agent-qa-flow"]},
        headers=headers,
    )
    assert create.status_code == 200
    session_id = create.json()["data"]["id"]

    chat = client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "@问答专家 你好，2+2 等于几？"},
        headers=headers,
    )
    assert chat.status_code == 200
    data = chat.json()["data"]
    assert data["route"]["agent_id"] == "agent-qa-flow"
    assert data["message"]["content"] == answer
    assert data["end"]["waiting_for_user"] is True
    assert data["interrupted"] is False

    detail = client.get(f"/api/sessions/{session_id}", headers=headers)
    assert detail.status_code == 200
    messages = detail.json()["data"]["messages"]
    assert any(m["role"] == "user" and "2+2" in m["content"] for m in messages)
    assert any(m["role"] == "assistant" and m.get("agent_id") == "agent-qa-flow" and m["content"] == answer for m in messages)

    exported = client.post(f"/api/sessions/{session_id}/export", headers=headers)
    assert exported.status_code == 200
    assert exported.json()["data"]["download_url"].startswith(f"/api/workspaces/{session_id}/files/download")

    assert client.delete(f"/api/settings/skills/{skill_id}", headers=headers).status_code == 200


def test_frontend_resource_center_and_settings_flow(frontend_flow_client: TestClient):
    client = frontend_flow_client
    headers = _headers()

    app_settings = client.get("/api/settings/app", headers=headers)
    assert app_settings.status_code == 200
    put_settings = client.put(
        "/api/settings/app",
        json={"default_llm": "qwen", "llm_providers": {"qwen": {"model": "qwen3-max"}}},
        headers=headers,
    )
    assert put_settings.status_code == 200
    assert put_settings.json()["data"]["default_llm"] == "qwen"

    host_profile = client.put(
        "/api/settings/host-profile",
        json={"display_name": "测试主持人", "skill_ids": [], "mcp_server_ids": []},
        headers=headers,
    )
    assert host_profile.status_code == 200
    assert host_profile.json()["data"]["display_name"] == "测试主持人"

    secret = client.post(
        "/api/settings/api-secrets",
        json={"id": "TEST_KEY", "label": "测试密钥", "api_key": "sk-test"},
        headers=headers,
    )
    assert secret.status_code == 200
    secret_update = client.put(
        "/api/settings/api-secrets/TEST_KEY",
        json={"label": "测试密钥2"},
        headers=headers,
    )
    assert secret_update.status_code == 200
    assert secret_update.json()["data"]["label"] == "测试密钥2"

    dha = client.post(
        "/api/dha/instances",
        json={
            "agent_id": "agent-front-flow",
            "name": "前端流程专家",
            "role": "验证资源中心专家 CRUD",
            "skill_ids": [],
            "mcp_server_ids": [],
            "file_capabilities": {"read": True, "write": True},
        },
        headers=headers,
    )
    assert dha.status_code == 200
    dha_update = client.put(
        "/api/dha/instances/agent-front-flow",
        json={"role": "已更新角色"},
        headers=headers,
    )
    assert dha_update.status_code == 200
    assert dha_update.json()["data"]["role"] == "已更新角色"

    presets = client.put(
        "/api/settings/session-presets",
        json={
            "presets": [
                {
                    "id": "scenario-front-flow",
                    "name": "前端流程场景",
                    "agent_ids": ["agent-front-flow"],
                    "description": "覆盖场景保存",
                    "discussion_goal_example": "验证场景",
                    "leader_agent_id": "agent-front-flow",
                }
            ]
        },
        headers=headers,
    )
    assert presets.status_code == 200
    preset_list = client.get("/api/settings/session-presets", headers=headers)
    assert preset_list.status_code == 200
    assert any(x["id"] == "scenario-front-flow" for x in preset_list.json()["data"]["presets"])

    skill = client.post(
        "/api/settings/skills",
        json={"name": "Front Flow Skill", "description": "资源中心技能 CRUD"},
        headers=headers,
    )
    assert skill.status_code == 200
    skill_id = skill.json()["data"]["id"]
    skill_update = client.put(
        f"/api/settings/skills/{skill_id}",
        json={
            "name": "Front Flow Skill",
            "description": "已更新技能",
            "body": "## 用途\n\n验证技能编辑。\n",
            "allowed_tools": {"mcp": [], "python": "requests==2.31.0"},
        },
        headers=headers,
    )
    assert skill_update.status_code == 200

    skill_content = client.get(f"/api/settings/skills/{skill_id}/content", headers=headers)
    assert skill_content.status_code == 200
    assert skill_content.json()["data"]["description"] == "已更新技能"

    part_dir = client.post(
        f"/api/settings/skills/{skill_id}/parts/references/mkdir",
        json={"path": "notes"},
        headers=headers,
    )
    assert part_dir.status_code == 200
    part_file = client.post(
        f"/api/settings/skills/{skill_id}/parts/references",
        json={"path": "notes/readme.md", "content": "v1"},
        headers=headers,
    )
    assert part_file.status_code == 200
    part_update = client.put(
        f"/api/settings/skills/{skill_id}/parts/references/notes/readme.md",
        json={"content": "v2"},
        headers=headers,
    )
    assert part_update.status_code == 200
    part_get = client.get(
        f"/api/settings/skills/{skill_id}/parts/references/notes/readme.md",
        headers=headers,
    )
    assert part_get.status_code == 200
    assert part_get.json()["data"]["content"] == "v2"
    part_delete = client.delete(
        f"/api/settings/skills/{skill_id}/parts/references/notes/readme.md",
        headers=headers,
    )
    assert part_delete.status_code == 200

    mcp = client.post(
        "/api/settings/mcp",
        json={
            "name": "前端流程 MCP",
            "enabled": False,
            "transport": {"type": "stdio", "command": "python", "args": ["-m", "noop"]},
            "metadata": {"purpose": "test"},
        },
        headers=headers,
    )
    assert mcp.status_code == 200
    mcp_id = mcp.json()["data"]["id"]
    assert client.post(f"/api/settings/mcp/{mcp_id}/enable", headers=headers).status_code == 200
    assert client.post(f"/api/settings/mcp/{mcp_id}/disable", headers=headers).status_code == 200
    mcp_update = client.put(
        f"/api/settings/mcp/{mcp_id}",
        json={"name": "前端流程 MCP 2", "enabled": False},
        headers=headers,
    )
    assert mcp_update.status_code == 200
    assert mcp_update.json()["data"]["name"] == "前端流程 MCP 2"

    sandbox = client.put("/api/settings/sandbox", json={"image_variant": "standard"}, headers=headers)
    assert sandbox.status_code == 200
    requirements = client.put(
        "/api/settings/sandbox/requirements",
        json={"content": "requests==2.31.0\n"},
        headers=headers,
    )
    assert requirements.status_code == 200
    requirements_merge = client.post(
        "/api/settings/sandbox/requirements/merge",
        json={"requirements": ["pandas==2.2.0", "requests>=2"]},
        headers=headers,
    )
    assert requirements_merge.status_code == 200
    assert "pandas==2.2.0" in requirements_merge.json()["data"]["content"]

    assert client.delete(f"/api/settings/mcp/{mcp_id}", headers=headers).status_code == 200
    assert client.delete(f"/api/settings/skills/{skill_id}", headers=headers).status_code == 200
    assert client.delete("/api/dha/instances/agent-front-flow", headers=headers).status_code == 200
    assert client.delete("/api/settings/api-secrets/TEST_KEY", headers=headers).status_code == 200
