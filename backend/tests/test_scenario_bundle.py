import shutil
import tempfile
from pathlib import Path

from app.core.scenario_bundle import (
    BUNDLE_VERSION,
    build_scenario_bundle_zip_bytes,
    extract_scenario_bundle_dir,
    merge_dha_instances_for_bundle,
    merge_mcp_servers_for_bundle,
    read_bundle_manifest_and_lists,
    strip_dha_row_for_disk,
)


def test_merge_dha_upsert_and_append():
    user = [{"agent_id": "a1", "name": "Old"}]
    bundle = [{"agent_id": "a1", "name": "New"}, {"agent_id": "a2", "name": "B"}]
    out = merge_dha_instances_for_bundle(user, bundle, overwrite=True)
    by = {r["agent_id"]: r["name"] for r in out}
    assert by["a1"] == "New"
    assert by["a2"] == "B"


def test_merge_dha_skip_overwrite():
    user = [{"agent_id": "a1", "name": "Keep"}]
    bundle = [{"agent_id": "a1", "name": "New"}]
    out = merge_dha_instances_for_bundle(user, bundle, overwrite=False)
    assert out[0]["name"] == "Keep"


def test_merge_mcp_skip_existing():
    user = [{"id": "m1", "name": "U"}]
    bundle = [{"id": "m1", "name": "B"}, {"id": "m2", "name": "N"}]
    merged, added, skipped, updated = merge_mcp_servers_for_bundle(user, bundle, skip_existing=True)
    ids = {s["id"]: s["name"] for s in merged}
    assert ids["m1"] == "U"
    assert ids["m2"] == "N"
    assert added == 1 and skipped == 1 and updated == 0


def test_roundtrip_zip_manifest():
    preset = {"id": "p1", "name": "P", "agent_ids": ["a1"], "leader_agent_id": "a1"}
    experts = [{"agent_id": "a1", "name": "E"}]
    mcps = [{"id": "x1", "name": "M"}]
    skills_root = Path(tempfile.mkdtemp())
    try:
        raw = build_scenario_bundle_zip_bytes(preset, experts, mcps, skills_root, [])
        ext = extract_scenario_bundle_dir(raw)
        try:
            man, p, dha, mcp = read_bundle_manifest_and_lists(ext)
            assert man.get("bundle_version") == BUNDLE_VERSION
            assert p["id"] == "p1"
            assert len(dha) == 1
            assert len(mcp) == 1
        finally:
            shutil.rmtree(ext, ignore_errors=True)
    finally:
        shutil.rmtree(skills_root, ignore_errors=True)


def test_strip_dha():
    row = {"agent_id": "a", "expert_id": "a", "file_capability_labels": []}
    s = strip_dha_row_for_disk(row)
    assert "expert_id" not in s
