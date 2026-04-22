from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def _dha_env():
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
def client(_dha_env):
    from app.main import app

    return TestClient(app)


def test_dha_instances_crud(client: TestClient):
    create = client.post(
        "/api/dha/instances",
        json={
            "agent_id": "agent-ut-dha",
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
    assert created["agent_id"] == "agent-ut-dha"
    assert created["expert_id"] == "agent-ut-dha"
    assert created["url_capability"] is False
    assert created["file_capabilities"]["read"] is True
    assert created["file_capabilities"]["write"] is False

    listed = client.get("/api/dha/instances")
    assert listed.status_code == 200
    rows = listed.json()["data"]["instances"]
    assert any(r["agent_id"] == "agent-ut-dha" for r in rows)

    update = client.put(
        "/api/dha/instances/agent-ut-dha",
        json={"name": "单测专家2", "url_capability": True},
    )
    assert update.status_code == 200
    assert update.json()["data"]["name"] == "单测专家2"
    assert update.json()["data"]["url_capability"] is True

    delete = client.delete("/api/dha/instances/agent-ut-dha")
    assert delete.status_code == 200
    assert delete.json()["data"]["deleted"] is True

    missing = client.put("/api/dha/instances/agent-ut-dha", json={"name": "x"})
    assert missing.status_code == 404


def test_agents_and_experts_alias_routes(client: TestClient):
    c = client.post("/api/agents", json={"expert_id": "agent-alias", "name": "别名专家"})
    assert c.status_code == 200
    assert c.json()["data"]["agent_id"] == "agent-alias"

    l = client.get("/api/experts")
    assert l.status_code == 200
    assert any(x["expert_id"] == "agent-alias" for x in l.json()["data"]["instances"])

    u = client.put("/api/experts/agent-alias", json={"role": "更新后的角色"})
    assert u.status_code == 200
    assert u.json()["data"]["role"] == "更新后的角色"

    d = client.delete("/api/agents/agent-alias")
    assert d.status_code == 200
