from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import init as core_init


@pytest.fixture(autouse=True)
def _reset_init_state(monkeypatch):
    monkeypatch.setattr(core_init, "_initialized", False)
    yield
    monkeypatch.setattr(core_init, "_initialized", False)


async def test_startup_init_loads_only_users_with_resources(monkeypatch, tmp_path):
    root = tmp_path / "users"
    (root / "alice" / "resources" / "skills" / "demo").mkdir(parents=True)
    (root / "alice" / "resources" / "skills" / "demo" / "SKILL.md").write_text("---\nname: Demo\n---\nbody\n", encoding="utf-8")
    (root / "bob").mkdir(parents=True)
    (root / "carol" / "resources" / "tools" / "Search").mkdir(parents=True)
    (root / "carol" / "resources" / "tools" / "Search" / "tool.json").write_text('{"name": "Search", "type": "mcp"}\n', encoding="utf-8")
    (root / ".hidden").mkdir(parents=True)
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(root))

    skills_seen: list[tuple[str, str]] = []
    mcp_seen: list[str] = []

    def fake_user_context(username: str):
        return SimpleNamespace(
            skills_dir=root / username / "resources" / "skills",
            tools_dir=root / username / "resources" / "tools",
        )

    def fake_skills_loader(username: str, skills_dir):
        skills_seen.append((username, str(skills_dir)))
        return SimpleNamespace(skills={"demo": object()})

    async def fake_mcp_config_loaded(username: str):
        mcp_seen.append(username)
        return SimpleNamespace(server_configs=[{"id": "search"}], tools={})

    monkeypatch.setattr(core_init, "get_user_context_for", fake_user_context)
    monkeypatch.setattr(core_init, "get_skills_loader_for_user", fake_skills_loader)
    monkeypatch.setattr(core_init, "ensure_user_mcp_config_loaded", fake_mcp_config_loaded)

    await core_init.ensure_mcp_and_skills_initialized()
    await core_init.ensure_mcp_and_skills_initialized()

    assert skills_seen == [
        ("alice", str(root / "alice" / "resources" / "skills")),
    ]
    assert mcp_seen == ["carol"]


async def test_startup_init_handles_empty_user_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "missing-users"))

    await core_init.ensure_mcp_and_skills_initialized()

    assert core_init._initialized is True
