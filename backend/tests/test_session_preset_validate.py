"""session_preset_validate 单元测试"""
from app.core.session_preset_validate import (
    extract_presets_from_import_body,
    normalize_preset_dict_for_validation,
    validate_session_preset,
    validation_to_api_dict,
)
from app.core.host_config import normalize_host_config_dict


def test_extract_presets_wrapped():
    body = {"export_version": 1, "preset": {"id": "a", "name": "N", "agent_ids": ["x"]}}
    assert len(extract_presets_from_import_body(body)) == 1


def test_extract_presets_bare():
    body = {"id": "a", "name": "N", "agent_ids": ["x"]}
    assert extract_presets_from_import_body(body)[0]["id"] == "a"


def test_normalize_invalid():
    assert normalize_preset_dict_for_validation({}) is None
    assert normalize_preset_dict_for_validation({"id": "a", "name": "", "agent_ids": ["x"]}) is None


def test_validate_missing_agent():
    preset = {"id": "p", "name": "P", "agent_ids": ["missing"], "host_config": {"skill_ids": ["s1"]}}
    v = validate_session_preset(
        preset,
        agent_by_id={},
        skill_has_content=lambda sid: sid == "s1",
        mcp_servers=[{"id": "m1", "enabled": True}],
    )
    assert "missing" in v.missing_agent_ids
    d = validation_to_api_dict(v)
    assert d["valid"] is False


def test_validate_host_skill_and_mcp():
    preset = {
        "id": "p",
        "name": "P",
        "agent_ids": ["a1"],
        "host_config": {"skill_ids": ["hs"], "mcp_server_ids": ["hm"]},
    }
    agents = {"a1": {"skill_ids": ["es"], "mcp_server_ids": ["em"]}}
    v = validate_session_preset(
        preset,
        agent_by_id=agents,
        skill_has_content=lambda sid: sid in ("hs", "es"),
        mcp_servers=[{"id": "hm", "enabled": True}, {"id": "em", "enabled": True}],
    )
    assert v.valid


def test_validate_empty_host_skill_ids_do_not_create_missing_group_host():
    preset = {
        "id": "p",
        "name": "P",
        "agent_ids": ["a1"],
        "host_config": {"skill_ids": []},
    }
    agents = {"a1": {"skill_ids": [], "mcp_server_ids": []}}
    v = validate_session_preset(
        preset,
        agent_by_id=agents,
        skill_has_content=lambda _: False,
        mcp_servers=[],
    )

    assert v.valid
    assert v.missing_skills == []


def test_legacy_group_host_placeholder_is_not_a_default_dependency():
    cfg = normalize_host_config_dict({"skill_ids": ["group-host"]})

    assert cfg["skill_ids"] == []


def test_validate_host_mcp_ignores_legacy_enabled_false():
    preset = {
        "id": "p",
        "name": "P",
        "agent_ids": ["a1"],
        "host_config": {"mcp_server_ids": ["off"]},
    }
    agents = {"a1": {"skill_ids": [], "mcp_server_ids": []}}
    v = validate_session_preset(
        preset,
        agent_by_id=agents,
        skill_has_content=lambda _: True,
        mcp_servers=[{"id": "off", "enabled": False}],
    )
    assert v.valid
    assert v.disabled_mcp_servers == []


def test_skip_agent_skills_when_agent_missing():
    preset = {"id": "p", "name": "P", "agent_ids": ["ghost"]}
    v = validate_session_preset(
        preset,
        agent_by_id={},
        skill_has_content=lambda _: False,
        mcp_servers=[],
    )
    assert v.missing_agent_ids == ["ghost"]
    assert not v.missing_skills
