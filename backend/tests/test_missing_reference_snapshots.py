from __future__ import annotations

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    monkeypatch.setenv("ALLOW_ANONYMOUS_API", "1")
    from app.main import app

    return TestClient(app)


def test_updating_skill_display_name_does_not_rename_directory(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        created = client.post(
            "/api/settings/skills",
            json={"name": "Original Skill", "description": "original"},
        )
        assert created.status_code == 200
        directory_name = created.json()["data"]["directory_name"]

        updated = client.put(
            f"/api/settings/skills/{directory_name}",
            json={"name": "Renamed Skill", "description": "renamed", "body": "body"},
        )

        assert updated.status_code == 200
        assert updated.json()["data"]["directory_name"] == directory_name
        assert updated.json()["data"]["renamed"] is False
        assert client.get(f"/api/settings/skills/{directory_name}/content").status_code == 200


def test_deleting_skill_keeps_agent_reference_for_missing_reference_display(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        created = client.post(
            "/api/settings/skills",
            json={"name": "Referenced Skill", "description": "referenced"},
        )
        assert created.status_code == 200
        directory_name = created.json()["data"]["directory_name"]

        agent = client.post(
            "/api/agents",
            json={
                "name": "引用专家",
                "skills": [{"name": "专家保留的技能快照名", "directory_name": directory_name}],
            },
        )
        assert agent.status_code == 200

        deleted = client.delete(f"/api/settings/skills/{directory_name}")

        assert deleted.status_code == 200
        listed = client.get("/api/agents")
        assert listed.status_code == 200
        row = next(item for item in listed.json()["data"]["instances"] if item["name"] == "引用专家")
        assert row["skills"] == [{"name": "专家保留的技能快照名", "directory_name": directory_name}]
