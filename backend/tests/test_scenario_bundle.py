import shutil
import tempfile
import json
import zipfile
import io
from pathlib import Path

from app.core.scenario_bundle import (
    build_scenario_bundle_zip_bytes,
    copy_bundle_skills_to_user,
    extract_scenario_bundle_dir,
    merge_agent_instances_for_bundle,
    merge_mcp_servers_for_bundle,
    read_bundle_manifest_and_lists,
    strip_agent_row_for_disk,
)


def test_merge_agent_upsert_and_append():
    user = [{"agent_id": "a1", "name": "Old"}]
    bundle = [{"agent_id": "a1", "name": "New"}, {"agent_id": "a2", "name": "B"}]
    out = merge_agent_instances_for_bundle(user, bundle)
    assert [r["name"] for r in out] == ["Old", "New", "B"]
    assert all("agent_id" not in r for r in out)


def test_merge_agent_overwrites_same_name_with_new_id():
    user = [{"agent_id": "local-a", "name": "Expert A"}, {"agent_id": "keep", "name": "Keep"}]
    bundle = [{"agent_id": "shared-a", "name": "Expert A"}]
    out = merge_agent_instances_for_bundle(user, bundle)
    assert [r["name"] for r in out] == ["Keep", "Expert A"]
    assert all("agent_id" not in r for r in out)


def test_merge_agent_always_overwrites_same_name():
    user = [{"agent_id": "a1", "name": "Keep"}]
    bundle = [{"agent_id": "a2", "name": "Keep", "description": "new"}]
    out = merge_agent_instances_for_bundle(user, bundle)
    assert out == [{"name": "Keep", "description": "new"}]


def test_merge_mcp_always_overwrites_same_name_and_appends_new():
    user = [{"name": "U", "type": "mcp", "server_config": '{"mcpServers":{"U":{"command":"old"}}}'}]
    bundle = [
        {"name": "U", "type": "mcp", "server_config": '{"mcpServers":{"U":{"command":"new"}}}'},
        {"name": "N", "type": "mcp", "server_config": '{"mcpServers":{"N":{"command":"n"}}}'},
    ]
    merged, added, updated = merge_mcp_servers_for_bundle(user, bundle)
    names = [s["name"] for s in merged]
    assert names == ["U", "N"]
    assert all("id" not in s for s in merged)
    assert "new" in merged[0]["server_config"]
    assert added == 1 and updated == 1


def test_merge_mcp_overwrites_same_name():
    user = [
        {"name": "Tool A", "type": "mcp", "server_config": '{"mcpServers":{"Tool A":{"command":"old"}}}'},
        {"name": "Keep", "type": "mcp", "server_config": '{"mcpServers":{"Keep":{"command":"keep"}}}'},
    ]
    bundle = [{"name": "Tool A", "type": "mcp", "server_config": '{"mcpServers":{"Tool A":{"command":"new"}}}'}]
    merged, added, updated = merge_mcp_servers_for_bundle(user, bundle)
    by = {r["name"]: r["server_config"] for r in merged}
    assert "new" in by["Tool A"]
    assert "keep" in by["Keep"]
    assert added == 0 and updated == 1


def test_copy_bundle_skills_to_user_always_overwrites_without_skip_branch():
    import inspect

    params = inspect.signature(copy_bundle_skills_to_user).parameters
    assert "overwrite" not in params

    text = inspect.getsource(copy_bundle_skills_to_user)
    assert "skipped" not in text
    assert "if not overwrite" not in text


def test_roundtrip_zip_manifest():
    preset = {"id": "p1", "name": "P", "agent_ids": ["a1"], "leader_agent_id": "a1"}
    experts = [{"agent_id": "a1", "name": "E"}]
    mcps = [{"id": "x1", "name": "M"}]
    skills_root = Path(tempfile.mkdtemp())
    try:
        raw = build_scenario_bundle_zip_bytes(preset, experts, mcps, skills_root, [])
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = set(zf.namelist())
            assert "bundle.json" in names
            assert "scenario_bundle.json" not in names
            assert "agents.json" not in names
            assert "mcp_servers.json" not in names
            manifest = json.loads(zf.read("bundle.json").decode("utf-8"))
            assert manifest["bundle_type"] == "scenario"
            assert "bundle_version" not in manifest
            assert "resources/scenarios/P/scenario.json" in names
            assert "resources/agents/E/agent.json" in names
            assert "resources/tools/M/tool.json" in names
        ext = extract_scenario_bundle_dir(raw)
        try:
            man, p, agents, mcp = read_bundle_manifest_and_lists(ext)
            assert man["bundle_type"] == "scenario"
            assert p["name"] == "P"
            assert "id" not in p
            assert len(agents) == 1
            assert "agent_id" not in agents[0]
            assert len(mcp) == 1
            assert mcp[0]["type"] == "mcp"
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
                    "ENV_API_KEY": "${env:SCENARIO_API_KEY}",
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
            server_config = __import__("json").loads(mcp[0]["server_config"])
            env = server_config["mcpServers"]["M"]["env"]
            assert env["PLAIN_API_KEY"] == ""
            assert env["ENV_API_KEY"] == "${env:SCENARIO_API_KEY}"
            assert env["MODEL"] == "qwen3-asr-1.7b"
            assert "sk-live-secret" not in raw.decode("latin-1")
        finally:
            shutil.rmtree(ext, ignore_errors=True)
    finally:
        shutil.rmtree(skills_root, ignore_errors=True)


def test_scenario_bundle_sanitizes_mcp_url_headers_and_nested_secrets():
    preset = {"id": "p1", "name": "P", "agent_ids": []}
    mcps = [
        {
            "id": "x1",
            "name": "Remote",
            "transport": {
                "type": "http",
                "base_url": "https://mcp.example.test/mcp?apiKey=plain-secret&mode=web&token=${env:REMOTE_TOKEN}",
                "headers": {
                    "Authorization": "Bearer plain-secret",
                    "X-Trace": "keep",
                    "X-Api-Key": "${env:HEADER_KEY}",
                },
                "nested": {
                    "callback": "https://callback.example.test/run?access_token=plain-token&ok=1",
                    "authType": "bearer",
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
            server_config = __import__("json").loads(mcp[0]["server_config"])
            transport = server_config["mcpServers"]["Remote"]
            assert transport["base_url"] == "https://mcp.example.test/mcp?apiKey=&mode=web&token=${env:REMOTE_TOKEN}"
            assert transport["headers"]["Authorization"] == ""
            assert transport["headers"]["X-Trace"] == "keep"
            assert transport["headers"]["X-Api-Key"] == "${env:HEADER_KEY}"
            assert transport["nested"]["callback"] == "https://callback.example.test/run?access_token=&ok=1"
            assert transport["nested"]["authType"] == "bearer"
            assert "plain-secret" not in raw.decode("latin-1")
            assert "plain-token" not in raw.decode("latin-1")
        finally:
            shutil.rmtree(ext, ignore_errors=True)
    finally:
        shutil.rmtree(skills_root, ignore_errors=True)


def test_strip_agent():
    row = {"agent_id": "a", "expert_id": "a", "file_capability_labels": []}
    s = strip_agent_row_for_disk(row)
    assert "expert_id" not in s
    assert "agent_id" not in s
