from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def _agents_env():
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
def client(_agents_env):
    from app.main import app

    return TestClient(app)


def test_agents_crud(client: TestClient):
    create = client.post(
        "/api/agents",
        json={
            "name": "单测专家",
            "description": "测试描述",
            "system_prompt": "测试提示",
            "skills": [{"name": "Skill 1", "directory_name": "skill-one"}],
            "llm_name": "deepseek-v4-flash",
        },
    )
    assert create.status_code == 200
    created = create.json()["data"]
    assert "agent_id" not in created
    assert created["name"] == "单测专家"
    assert created["description"] == "测试描述"
    assert created["system_prompt"] == "测试提示"
    assert created["llm_name"] == "deepseek-v4-flash"
    assert created["skills"] == [{"name": "Skill 1", "directory_name": "skill-one"}]
    assert "role" not in created
    assert "tool_names" not in created
    assert "url_capability" not in created
    assert "file_capabilities" not in created
    assert "avatar_url" not in created

    listed = client.get("/api/agents")
    assert listed.status_code == 200
    rows = listed.json()["data"]["instances"]
    assert any(r["name"] == "单测专家" for r in rows)

    update = client.put(
        "/api/agents/单测专家",
        json={"name": "单测专家2", "description": "更新描述"},
    )
    assert update.status_code == 200
    assert update.json()["data"]["name"] == "单测专家2"
    assert update.json()["data"]["description"] == "更新描述"

    delete = client.delete("/api/agents/单测专家2")
    assert delete.status_code == 200
    assert delete.json()["data"]["deleted"] is True

    missing = client.put("/api/agents/单测专家2", json={"name": "x"})
    assert missing.status_code == 404

    old_crud = client.get("/api/dha/instances")
    assert old_crud.status_code == 404


def test_agents_routes_use_name_identity(client: TestClient):
    c = client.post("/api/agents", json={"name": "Agent 专家"})
    assert c.status_code == 200
    assert "agent_id" not in c.json()["data"]

    l = client.get("/api/agents")
    assert l.status_code == 200
    assert any(x["name"] == "Agent 专家" for x in l.json()["data"]["instances"])

    u = client.put("/api/agents/Agent 专家", json={"description": "更新后的描述"})
    assert u.status_code == 200
    assert u.json()["data"]["description"] == "更新后的描述"

    d = client.delete("/api/agents/Agent 专家")
    assert d.status_code == 200
