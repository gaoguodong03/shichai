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
            "agent_id": "agent-ut-api",
            "name": "单测专家",
            "role": "测试角色",
            "skill_ids": ["s1"],
            "mcp_server_ids": ["m1"],
            "url_capability": False,
            "file_capabilities": {"read": True, "write": False},
        },
    )
    assert create.status_code == 200
    created = create.json()["data"]
    assert created["agent_id"] == "agent-ut-api"
    assert created["url_capability"] is False
    assert created["file_capabilities"]["read"] is True
    assert created["file_capabilities"]["write"] is False

    listed = client.get("/api/agents")
    assert listed.status_code == 200
    rows = listed.json()["data"]["instances"]
    assert any(r["agent_id"] == "agent-ut-api" for r in rows)

    update = client.put(
        "/api/agents/agent-ut-api",
        json={"name": "单测专家2", "url_capability": True},
    )
    assert update.status_code == 200
    assert update.json()["data"]["name"] == "单测专家2"
    assert update.json()["data"]["url_capability"] is True

    delete = client.delete("/api/agents/agent-ut-api")
    assert delete.status_code == 200
    assert delete.json()["data"]["deleted"] is True

    missing = client.put("/api/agents/agent-ut-api", json={"name": "x"})
    assert missing.status_code == 404

    old_crud = client.get("/api/dha/instances")
    assert old_crud.status_code == 404


def test_agents_routes(client: TestClient):
    c = client.post("/api/agents", json={"agent_id": "agent-route", "name": "Agent 专家"})
    assert c.status_code == 200
    assert c.json()["data"]["agent_id"] == "agent-route"

    l = client.get("/api/agents")
    assert l.status_code == 200
    assert any(x["agent_id"] == "agent-route" for x in l.json()["data"]["instances"])

    u = client.put("/api/agents/agent-route", json={"role": "更新后的角色"})
    assert u.status_code == 200
    assert u.json()["data"]["role"] == "更新后的角色"

    d = client.delete("/api/agents/agent-route")
    assert d.status_code == 200
