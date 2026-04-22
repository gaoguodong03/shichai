import shutil
import tempfile
from pathlib import Path

from app.core.expert_bundle import build_expert_bundle_zip_bytes, merge_single_expert_into_instances
from app.core.scenario_bundle import extract_scenario_bundle_dir
from app.core.expert_bundle import read_expert_bundle_manifest


def test_merge_single_expert_skip_on_same_name():
    user = [{"agent_id": "a1", "name": "Old", "role": "", "system_prompt": "", "skill_ids": [], "mcp_server_ids": [], "is_leader": False, "llm_provider_id": "", "avatar_url": ""}]
    # minimal fields strip_dha may need file_capabilities - merge uses strip from scenario
    bundle_row = {
        "agent_id": "a9",
        "name": "Old",
        "role": "",
        "system_prompt": "",
        "skill_ids": [],
        "mcp_server_ids": [],
        "is_leader": False,
        "llm_provider_id": "",
        "avatar_url": "",
    }
    merged, fid, skipped, overwritten = merge_single_expert_into_instances(user, bundle_row, id_conflict="skip")
    assert skipped is True
    assert fid is None
    assert overwritten == []
    assert len(merged) == 1
    assert merged[0]["agent_id"] == "a1"


def test_merge_single_expert_overwrite_all_same_name_and_keep_import():
    user = [
        {"agent_id": "a1", "name": "Same", "role": "", "system_prompt": "", "skill_ids": [], "mcp_server_ids": [], "is_leader": False, "llm_provider_id": "", "avatar_url": ""},
        {"agent_id": "a2", "name": "Same", "role": "", "system_prompt": "", "skill_ids": [], "mcp_server_ids": [], "is_leader": False, "llm_provider_id": "", "avatar_url": ""},
    ]
    bundle_row = {
        "agent_id": "a9",
        "name": "Same",
        "role": "r",
        "system_prompt": "p",
        "skill_ids": [],
        "mcp_server_ids": [],
        "is_leader": False,
        "llm_provider_id": "",
        "avatar_url": "",
    }
    merged, fid, skipped, overwritten = merge_single_expert_into_instances(user, bundle_row, id_conflict="overwrite")
    assert skipped is False
    assert fid == "a9"
    assert overwritten == ["a1", "a2"]
    assert [x["agent_id"] for x in merged] == ["a9"]


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
