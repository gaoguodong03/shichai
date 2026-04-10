import shutil
import tempfile
from pathlib import Path

from app.core.expert_bundle import build_expert_bundle_zip_bytes, merge_single_expert_into_instances
from app.core.scenario_bundle import extract_scenario_bundle_dir
from app.core.expert_bundle import read_expert_bundle_manifest


def test_merge_single_expert_new_id_on_conflict():
    user = [{"agent_id": "a1", "name": "Old", "role": "", "system_prompt": "", "skill_ids": [], "mcp_server_ids": [], "is_leader": False, "llm_provider_id": "", "avatar_url": ""}]
    # minimal fields strip_dha may need file_capabilities - merge uses strip from scenario
    bundle_row = {
        "agent_id": "a1",
        "name": "New",
        "role": "",
        "system_prompt": "",
        "skill_ids": [],
        "mcp_server_ids": [],
        "is_leader": False,
        "llm_provider_id": "",
        "avatar_url": "",
    }
    merged, fid = merge_single_expert_into_instances(user, bundle_row, id_conflict="new_id")
    ids = [x["agent_id"] for x in merged]
    assert "a1" in ids
    assert fid != "a1"
    assert fid in ids


def test_expert_bundle_zip_roundtrip():
    expert = {
        "agent_id": "e1",
        "name": "E",
        "role": "",
        "system_prompt": "",
        "skill_ids": [],
        "mcp_server_ids": [],
        "is_leader": False,
        "llm_provider_id": "",
        "avatar_url": "",
    }
    root = Path(tempfile.mkdtemp())
    try:
        raw = build_expert_bundle_zip_bytes(expert, [], root, [])
        ext = extract_scenario_bundle_dir(raw)
        try:
            _m, ex = read_expert_bundle_manifest(ext)
            assert ex["name"] == "E"
        finally:
            shutil.rmtree(ext, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)
