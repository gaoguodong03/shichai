import shutil
import tempfile
from pathlib import Path

from app.core.expert_bundle import build_expert_bundle_zip_bytes, merge_single_expert_into_instances
from app.core.scenario_bundle import extract_scenario_bundle_dir
from app.core.expert_bundle import read_expert_bundle_manifest


def test_merge_single_expert_skip_on_same_name():
    user = [{"name": "Old", "role": "", "system_prompt": "", "skills": [], "tool_names": [], "is_leader": False, "llm_name": "", "avatar_url": ""}]
    bundle_row = {
        "name": "Old",
        "role": "",
        "system_prompt": "",
        "skills": [],
        "tool_names": [],
        "is_leader": False,
        "llm_name": "",
        "avatar_url": "",
    }
    merged, fid, skipped, overwritten = merge_single_expert_into_instances(user, bundle_row, name_conflict="skip")
    assert skipped is True
    assert fid is None
    assert overwritten == []
    assert len(merged) == 1
    assert merged[0]["name"] == "Old"


def test_merge_single_expert_overwrite_all_same_name_and_keep_import():
    user = [
        {"name": "Same", "role": "", "system_prompt": "", "skills": [], "tool_names": [], "is_leader": False, "llm_name": "", "avatar_url": ""},
        {"name": "Same", "role": "", "system_prompt": "", "skills": [], "tool_names": [], "is_leader": False, "llm_name": "", "avatar_url": ""},
    ]
    bundle_row = {
        "name": "Same",
        "role": "r",
        "system_prompt": "p",
        "skills": [],
        "tool_names": [],
        "is_leader": False,
        "llm_name": "",
        "avatar_url": "",
    }
    merged, fid, skipped, overwritten = merge_single_expert_into_instances(user, bundle_row, name_conflict="overwrite")
    assert skipped is False
    assert fid == "Same"
    assert overwritten == ["Same"]
    assert [x["name"] for x in merged] == ["Same"]
    assert merged[0]["role"] == "r"


def test_expert_bundle_zip_roundtrip():
    expert = {
        "name": "E",
        "role": "",
        "system_prompt": "",
        "skills": [],
        "tool_names": [],
        "is_leader": False,
        "llm_name": "",
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
