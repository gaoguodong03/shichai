import shutil
import tempfile
from pathlib import Path

from app.core.scenario_bundle import (
    BUNDLE_VERSION,
    build_scenario_bundle_zip_bytes,
    extract_scenario_bundle_dir,
    merge_agent_instances_for_bundle,
    merge_mcp_servers_for_bundle,
    read_bundle_manifest_and_lists,
    strip_agent_row_for_disk,
)


def test_merge_agent_upsert_and_append():
    user = [{"agent_id": "a1", "name": "Old"}]
    bundle = [{"agent_id": "a1", "name": "New"}, {"agent_id": "a2", "name": "B"}]
    out = merge_agent_instances_for_bundle(user, bundle, overwrite=True)
    by = {r["agent_id"]: r["name"] for r in out}
    assert by["a1"] == "New"
    assert by["a2"] == "B"


def test_merge_agent_overwrites_same_name_with_new_id():
    user = [{"agent_id": "local-a", "name": "Expert A"}, {"agent_id": "keep", "name": "Keep"}]
    bundle = [{"agent_id": "shared-a", "name": "Expert A"}]
    out = merge_agent_instances_for_bundle(user, bundle, overwrite=True)
    by = {r["agent_id"]: r["name"] for r in out}
    assert "local-a" not in by
    assert by["shared-a"] == "Expert A"
    assert by["keep"] == "Keep"


def test_merge_agent_skip_overwrite():
    user = [{"agent_id": "a1", "name": "Keep"}]
    bundle = [{"agent_id": "a1", "name": "New"}]
    out = merge_agent_instances_for_bundle(user, bundle, overwrite=False)
    assert out[0]["name"] == "Keep"


def test_merge_mcp_skip_existing():
    user = [{"id": "m1", "name": "U"}]
    bundle = [{"id": "m1", "name": "B"}, {"id": "m2", "name": "N"}]
    merged, added, skipped, updated = merge_mcp_servers_for_bundle(user, bundle, skip_existing=True)
    ids = {s["id"]: s["name"] for s in merged}
    assert ids["m1"] == "U"
    assert ids["m2"] == "N"
    assert added == 1 and skipped == 1 and updated == 0


def test_merge_mcp_overwrites_same_name_with_new_id():
    user = [{"id": "local-m", "name": "Tool A"}, {"id": "keep", "name": "Keep"}]
    bundle = [{"id": "shared-m", "name": "Tool A"}]
    merged, added, skipped, updated = merge_mcp_servers_for_bundle(user, bundle, skip_existing=False)
    by = {r["id"]: r["name"] for r in merged}
    assert "local-m" not in by
    assert by["shared-m"] == "Tool A"
    assert by["keep"] == "Keep"
    assert added == 0 and skipped == 0 and updated == 1


def test_roundtrip_zip_manifest():
    preset = {"id": "p1", "name": "P", "agent_ids": ["a1"], "leader_agent_id": "a1"}
    experts = [{"agent_id": "a1", "name": "E"}]
    mcps = [{"id": "x1", "name": "M"}]
    skills_root = Path(tempfile.mkdtemp())
    try:
        raw = build_scenario_bundle_zip_bytes(preset, experts, mcps, skills_root, [])
        ext = extract_scenario_bundle_dir(raw)
        try:
            man, p, agents, mcp = read_bundle_manifest_and_lists(ext)
            assert man.get("bundle_version") == BUNDLE_VERSION
            assert p["id"] == "p1"
            assert len(agents) == 1
            assert len(mcp) == 1
        finally:
            shutil.rmtree(ext, ignore_errors=True)
    finally:
        shutil.rmtree(skills_root, ignore_errors=True)


def test_scenario_bundle_sanitizes_mcp_plaintext_secrets():
    preset = {"id": "p1", "name": "P", "agent_ids": []}
    mcps = [
        {
            "id": "x1",
            "name": "M",
            "transport": {
                "type": "stdio",
                "env": {
                    "PLAIN_API_KEY": "sk-live-secret",
                    "VAULT_API_KEY": "${vault:api-key}",
                    "MODEL": "qwen3-asr-1.7b",
                },
            },
        }
    ]
    skills_root = Path(tempfile.mkdtemp())
    try:
        raw = build_scenario_bundle_zip_bytes(preset, [], mcps, skills_root, [])
        ext = extract_scenario_bundle_dir(raw)
        try:
            _man, _p, _agents, mcp = read_bundle_manifest_and_lists(ext)
            env = mcp[0]["transport"]["env"]
            assert env["PLAIN_API_KEY"] == ""
            assert env["VAULT_API_KEY"] == "${vault:api-key}"
            assert env["MODEL"] == "qwen3-asr-1.7b"
            assert "sk-live-secret" not in raw.decode("latin-1")
        finally:
            shutil.rmtree(ext, ignore_errors=True)
    finally:
        shutil.rmtree(skills_root, ignore_errors=True)


def test_session_preset_export_resolves_skill_mcp_by_reference_label_name(monkeypatch, tmp_path: Path):
    import asyncio
    import json
    import zipfile
    from io import BytesIO

    from app.api import settings_presets as api
    from app.core.user_context import get_current_user_context, reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="source-user", username="source@example.com")
    try:
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
        ctx.config_dir.mkdir(parents=True, exist_ok=True)
        ctx.config_dir.joinpath("mcp_servers.json").write_text(
            json.dumps(
                [
                    {
                        "id": "current-exa",
                        "name": "Exa 搜索",
                        "transport": {"type": "http", "base_url": "https://mcp.exa.ai/mcp?exaApiKey=${EXA_API_KEY}"},
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        skill_dir = ctx.skills_dir / "research-skill"
        skill_dir.mkdir(parents=True)
        skill_dir.joinpath("SKILL.md").write_text(
            "---\n"
            "name: 材料搜索\n"
            "auto-tools:\n"
            "  mcp:\n"
            "    - stale-exa\n"
            "allowed-tools:\n"
            "  mcp:\n"
            "    - stale-exa\n"
            "reference-labels:\n"
            "  mcp:\n"
            "    - id: stale-exa\n"
            "      name: Exa 搜索\n"
            "---\n"
            "body\n",
            encoding="utf-8",
        )
        ctx.config_dir.joinpath("dha_instances.json").write_text(
            json.dumps([{"agent_id": "agent-a", "name": "专家A", "skill_ids": ["research-skill"]}], ensure_ascii=False),
            encoding="utf-8",
        )
        ctx.config_dir.joinpath("session_presets.json").write_text(
            json.dumps([{"id": "scene-a", "name": "场景A", "agent_ids": ["agent-a"]}], ensure_ascii=False),
            encoding="utf-8",
        )

        raw, _preset, _safe = api._session_preset_bundle_zip_for_preset("scene-a")
    finally:
        reset_current_user_identity(token)

    with zipfile.ZipFile(BytesIO(raw)) as zf:
        rows = json.loads(zf.read("mcp_servers.json").decode("utf-8"))
    assert rows[0]["id"] == "stale-exa"
    assert rows[0]["name"] == "Exa 搜索"
    assert rows[0]["transport"]["base_url"] == "https://mcp.exa.ai/mcp?exaApiKey=${EXA_API_KEY}"

    token = set_current_user_identity(user_id="target-user", username="target@example.com")
    try:
        target_ctx = get_current_user_context(default_fallback=False)
        assert target_ctx is not None
        result = asyncio.run(api._import_scene_from_bundle_bytes(raw, dry_run=False))
        imported_rows = json.loads(target_ctx.config_dir.joinpath("mcp_servers.json").read_text(encoding="utf-8"))
    finally:
        reset_current_user_identity(token)
    assert result["summary"]["mcp_added"] == 1
    assert imported_rows[0]["id"] == "stale-exa"


def test_strip_agent():
    row = {"agent_id": "a", "expert_id": "a", "file_capability_labels": []}
    s = strip_agent_row_for_disk(row)
    assert "expert_id" not in s
