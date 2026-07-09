from __future__ import annotations

import os
import json
import tempfile
import zipfile
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from app.agent.messages import AIMessage


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
        monkeypatch.setattr(
            sandbox_settings,
            "resolve_dependency_status",
            lambda **_kwargs: {
                "resolver": {"ok": True, "message": ""},
                "requirements": [
                    {
                        "requirement": "pandas==2.2.0",
                        "name": "pandas",
                        "status": "satisfied",
                        "message": "",
                        "missing_packages": [],
                    }
                ],
            },
        )

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


def test_mcp_zip_export_and_import_preserves_stdio_env(frontend_flow_client: TestClient):
    client = frontend_flow_client
    headers = _headers("frontend-mcp@example.test")

    created = client.post(
        "/api/settings/mcp",
        json={
            "name": "音频转写 MCP",
            "transport": {
                "type": "stdio",
                "command": "python",
                "args": ["app/mcp/stdio/audio_asr.py"],
                "env": {
                    "QWEN_AUDIO_API_KEY": "${vault:asr}",
                    "QWEN_AUDIO_BASE_URL": "http://10.129.50.230/v1",
                    "QWEN_AUDIO_MODEL": "qwen3-asr-1.7b",
                },
            },
            "metadata": {"description": "音频转写"},
        },
        headers=headers,
    )
    assert created.status_code == 200
    server_id = created.json()["data"]["name"]

    exported = client.get(f"/api/settings/mcp/{server_id}/export-zip", headers=headers)
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(BytesIO(exported.content)) as zf:
        rows = json.loads(zf.read("mcp_servers.json").decode("utf-8"))
    assert "enabled" not in rows[0]
    assert "${vault:asr}" in rows[0]["server_config"]
    assert "qwen3-asr-1.7b" in rows[0]["server_config"]

    deleted = client.delete(f"/api/settings/mcp/{server_id}", headers=headers)
    assert deleted.status_code == 200

    imported = client.post(
        "/api/settings/mcp/import-zip",
        files={"file": ("audio-asr.zip", exported.content, "application/zip")},
        headers=headers,
    )
    assert imported.status_code == 200
    assert imported.json()["data"]["summary"]["mcp_added"] == 1

    listed = client.get("/api/settings/mcp", headers=headers)
    assert listed.status_code == 200
    restored = next(x for x in listed.json()["data"]["servers"] if x["name"] == server_id)
    assert "${vault:asr}" in restored["server_config"]


def test_skill_and_expert_export_bundle_tools_without_plaintext_secrets(frontend_flow_client: TestClient):
    client = frontend_flow_client
    headers = _headers("frontend-export-tools@example.test")

    created_tool = client.post(
        "/api/settings/mcp",
        json={
            "name": "带密钥的工具",
            "transport": {
                "type": "stdio",
                "command": "python",
                "args": ["app/mcp/stdio/audio_asr.py"],
                "env": {
                    "QWEN_AUDIO_API_KEY": "sk-live-secret",
                    "QWEN_AUDIO_MODEL": "qwen3-asr-1.7b",
                },
            },
        },
        headers=headers,
    )
    assert created_tool.status_code == 200
    tool_id = created_tool.json()["data"]["name"]

    created_skill = client.post(
        "/api/settings/skills",
        json={"name": "导出工具技能", "description": ""},
        headers=headers,
    )
    assert created_skill.status_code == 200
    skill_id = created_skill.json()["data"]["directory_name"]
    updated_skill = client.put(
        f"/api/settings/skills/{skill_id}",
        json={"allowed_tools": {"mcp": [tool_id], "python": []}},
        headers=headers,
    )
    assert updated_skill.status_code == 200

    exported_skill = client.get(f"/api/settings/skills/{skill_id}/export-zip", headers=headers)
    assert exported_skill.status_code == 200
    with zipfile.ZipFile(BytesIO(exported_skill.content)) as zf:
        skill_tools = json.loads(zf.read("mcp_servers.json").decode("utf-8"))
    assert [row["name"] for row in skill_tools] == [tool_id]
    assert "sk-live-secret" not in json.dumps(skill_tools, ensure_ascii=False)
    assert "qwen3-asr-1.7b" in json.dumps(skill_tools, ensure_ascii=False)
    assert "sk-live-secret" not in exported_skill.content.decode("latin-1")

    created_expert = client.post(
        "/api/agents",
        json={
            "name": "带技能工具的专家",
            "skills": [{"name": "导出工具技能", "directory_name": skill_id}],
        },
        headers=headers,
    )
    assert created_expert.status_code == 200

    exported_expert = client.get("/api/agents/带技能工具的专家/export-bundle", headers=headers)
    assert exported_expert.status_code == 200
    with zipfile.ZipFile(BytesIO(exported_expert.content)) as zf:
        expert_tools = json.loads(zf.read("mcp_servers.json").decode("utf-8"))
    assert [row["name"] for row in expert_tools] == [tool_id]
    assert "sk-live-secret" not in exported_expert.content.decode("latin-1")


def test_mcp_settings_rejects_legacy_runtime_fields(frontend_flow_client: TestClient):
    client = frontend_flow_client
    headers = _headers("frontend-mcp-legacy@example.test")

    created = client.post(
        "/api/settings/mcp",
        json={
            "name": "旧开关工具",
            "enabled": False,
            "transport": {"type": "stdio", "command": "python", "args": ["-m", "noop"]},
        },
        headers=headers,
    )
    assert created.status_code == 422
    assert "enabled" in created.text

    valid = client.post(
        "/api/settings/mcp",
        json={
            "name": "当前工具",
            "transport": {"type": "stdio", "command": "python", "args": ["-m", "noop"]},
        },
        headers=headers,
    )
    assert valid.status_code == 200
    updated = client.put(
        "/api/settings/mcp/当前工具",
        json={"status": "connected"},
        headers=headers,
    )
    assert updated.status_code == 422
    assert "status" in updated.text

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "mcp_servers.json",
            json.dumps(
                [
                    {
                        "name": "旧包工具",
                        "enabled": True,
                        "server_config": json.dumps({"mcpServers": {"旧包工具": {"type": "stdio", "command": "python"}}}),
                    }
                ],
                ensure_ascii=False,
            ),
        )
    imported = client.post(
        "/api/settings/mcp/import-zip",
        files={"file": ("legacy-mcp.zip", buf.getvalue(), "application/zip")},
        headers=headers,
    )
    assert imported.status_code == 400
    assert "旧运行字段" in imported.json()["detail"]


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
        json={"title": "前端全流程会话-已更新", "agent_names": []},
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
    from app.agent import group_chat_runtime as group_chat
    from app.agent import group_chat_expert_resolution as expert_resolution

    client = frontend_flow_client
    headers = _headers("frontend-chat@example.test")
    answer = "2+2 等于 4。"
    monkeypatch.setattr(group_chat, "_get_llm_for_agent", lambda agent_profile, app_settings: _FakeLLM([AIMessage(content=answer)]))
    monkeypatch.setattr(expert_resolution, "_llm_credential_notice_for_agent", lambda agent_profile, app_settings: None)

    skill = client.post(
        "/api/settings/skills",
        json={"name": "QA Flow Skill", "description": "回答用户在会话中提出的问题"},
        headers=headers,
    )
    assert skill.status_code == 200
    skill_id = skill.json()["data"]["directory_name"]

    agent_profile = client.post(
        "/api/agents",
        json={
            "name": "问答专家",
            "description": "回答用户提出的问题",
            "system_prompt": "直接回答用户问题。",
            "skills": [{"name": "QA Flow Skill", "directory_name": skill_id}],
        },
        headers=headers,
    )
    assert agent_profile.status_code == 200

    create = client.post(
        "/api/sessions",
        json={"title": "问答检查会话", "agent_names": ["问答专家"]},
        headers=headers,
    )
    assert create.status_code == 200
    session_id = create.json()["data"]["id"]

    chat = client.post(
        f"/api/sessions/{session_id}/chat",
        json={
            "message": "你好，2+2 等于几？",
            "client_message_id": "frontend-chat-1",
            "target_agent_name": "问答专家",
        },
        headers=headers,
    )
    assert chat.status_code == 200
    data = chat.json()["data"]
    assert data["message"]["message"]["content"] == answer
    assert set(data) == {"route", "progress", "messages", "message", "end", "error"}
    assert data["end"]["type"] == "end"
    assert data["end"]["phase"] == "awaiting_user"
    assert data["end"]["waiting_for_user"] is True

    detail = client.get(f"/api/sessions/{session_id}", headers=headers)
    assert detail.status_code == 200
    messages = detail.json()["data"]["messages"]
    assert any(m["speaker"]["type"] == "user" and "2+2" in m["message"]["content"] for m in messages)
    assert any(
        m["speaker"]["type"] == "expert"
        and m["speaker"].get("agent_name") == "问答专家"
        and m["message"]["content"] == answer
        for m in messages
    )

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
        json={"default_llm": "qwen", "llm_providers": {"qwen": {"model": "qwen3-max", "label": "通义千问"}}},
        headers=headers,
    )
    assert put_settings.status_code == 200
    assert put_settings.json()["data"]["default_llm"] == "qwen"
    assert "label" not in put_settings.json()["data"]["llm_providers"]["qwen"]
    secret_settings = client.put(
        "/api/settings/app",
        json={
            "default_llm": "qwen",
            "llm_providers": {
                "qwen": {
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "model": "qwen3-max",
                    "api_key": "sk-inline-secret",
                }
            },
        },
        headers=headers,
    )
    assert secret_settings.status_code == 200
    provider = secret_settings.json()["data"]["llm_providers"]["qwen"]
    assert provider["api_key_set"] is True
    assert "api_key" not in provider

    app_settings_after_secret = client.get("/api/settings/app", headers=headers)
    assert app_settings_after_secret.status_code == 200
    provider_after = app_settings_after_secret.json()["data"]["llm_providers"]["qwen"]
    assert provider_after["api_key_set"] is True
    assert "api_key" not in provider_after
    assert "sk-inline-secret" not in app_settings_after_secret.text

    exported_llm = client.get("/api/settings/llm-providers/qwen/export-bundle", headers=headers)
    assert exported_llm.status_code == 200
    assert exported_llm.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(BytesIO(exported_llm.content)) as zf:
        manifest_text = zf.read("llm_bundle.json").decode("utf-8")
        manifest = json.loads(manifest_text)
    assert "sk-inline-secret" not in manifest_text
    assert manifest["name"] == "qwen"
    assert manifest["provider"]["model"] == "qwen3-max"
    assert manifest["provider"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert "api_key" not in manifest["provider"]
    assert "api_key_env" not in manifest["provider"]
    assert "api_key_ref" not in manifest["provider"]

    preview_llm = client.post(
        "/api/settings/llm-providers/import-bundle",
        files={"file": ("qwen.zip", exported_llm.content, "application/zip")},
        headers=headers,
    )
    assert preview_llm.status_code == 200
    preview = preview_llm.json()["data"]["bundle_preview"]
    assert preview["name"] == "qwen"
    assert preview["would_conflict_name"] is True
    assert preview["provider"]["model"] == "qwen3-max"
    assert "api_key" not in preview["provider"]

    imported_llm = client.post(
        "/api/settings/llm-providers/import-bundle",
        data={"dry_run": "false"},
        files={"file": ("qwen.zip", exported_llm.content, "application/zip")},
        headers=headers,
    )
    assert imported_llm.status_code == 409

    remove_same_name = client.put(
        "/api/settings/app",
        json={
            "default_llm": "qwen3-max",
            "llm_providers": {"qwen3-max": {"model": "qwen3-max"}},
        },
        headers=headers,
    )
    assert remove_same_name.status_code == 200
    imported_llm = client.post(
        "/api/settings/llm-providers/import-bundle",
        data={"dry_run": "false"},
        files={"file": ("qwen.zip", exported_llm.content, "application/zip")},
        headers=headers,
    )
    assert imported_llm.status_code == 200
    assert imported_llm.json()["data"]["summary"]["imported_name"] == "qwen"

    host_profile = client.put(
        "/api/settings/host-profile",
        json={"name": "测试主持人", "skill_name": "", "skill_directory": ""},
        headers=headers,
    )
    assert host_profile.status_code == 200
    assert host_profile.json()["data"]["name"] == "测试主持人"

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

    agent_profile = client.post(
        "/api/agents",
        json={
            "name": "前端流程专家",
            "description": "验证资源中心专家 CRUD",
            "skills": [],
        },
        headers=headers,
    )
    assert agent_profile.status_code == 200
    agent_update = client.put(
        "/api/agents/前端流程专家",
        json={"description": "已更新描述"},
        headers=headers,
    )
    assert agent_update.status_code == 200
    assert agent_update.json()["data"]["description"] == "已更新描述"

    presets = client.put(
        "/api/settings/session-presets",
        json={
            "presets": [
                {
                    "name": "前端流程场景",
                    "agent_names": ["前端流程专家"],
                    "description": "覆盖场景保存",
                    "host": {"name": "主持人", "skill_name": "", "skill_directory": ""},
                }
            ]
        },
        headers=headers,
    )
    assert presets.status_code == 200
    preset_list = client.get("/api/settings/session-presets", headers=headers)
    assert preset_list.status_code == 200
    assert any(x["name"] == "前端流程场景" for x in preset_list.json()["data"]["presets"])

    skill = client.post(
        "/api/settings/skills",
        json={"name": "Front Flow Skill", "description": "资源中心技能 CRUD"},
        headers=headers,
    )
    assert skill.status_code == 200
    skill_id = skill.json()["data"]["directory_name"]
    skill_update = client.put(
        f"/api/settings/skills/{skill_id}",
        json={
            "name": "Front Flow Skill",
            "description": "已更新技能",
            "body": "## 用途\n\n验证技能编辑。\n",
            "allowed_tools": {"mcp": [], "python": ["requests==2.31.0"]},
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
            "transport": {"type": "stdio", "command": "python", "args": ["-m", "noop"]},
            "metadata": {"purpose": "test"},
        },
        headers=headers,
    )
    assert mcp.status_code == 200
    mcp_id = mcp.json()["data"]["name"]
    mcp_update = client.put(
        f"/api/settings/mcp/{mcp_id}",
        json={"name": "前端流程 MCP 2"},
        headers=headers,
    )
    assert mcp_update.status_code == 200
    assert mcp_update.json()["data"]["name"] == "前端流程 MCP 2"
    mcp_id = "前端流程 MCP 2"

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
    requirements_status = client.post(
        "/api/settings/sandbox/requirements/status",
        json={"requirements": ["pandas==2.2.0"]},
        headers=headers,
    )
    assert requirements_status.status_code == 200
    assert requirements_status.json()["data"]["requirements"][0]["status"] == "satisfied"

    assert client.delete(f"/api/settings/mcp/{mcp_id}", headers=headers).status_code == 200
    assert client.delete(f"/api/settings/skills/{skill_id}", headers=headers).status_code == 200
    assert client.delete("/api/agents/前端流程专家", headers=headers).status_code == 200
    assert client.delete("/api/settings/api-secrets/TEST_KEY", headers=headers).status_code == 200
