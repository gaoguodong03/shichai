"""session_preset_validate 单元测试"""
from app.core.session_preset_validate import (
    extract_presets_from_import_body,
    normalize_preset_dict_for_validation,
    validate_session_preset,
    validation_to_api_dict,
)
from app.core.host_config import normalize_host_config_dict


def test_extract_presets_wrapped():
    body = {"export_version": 1, "preset": {"name": "N", "agent_names": ["专家 A"]}}
    assert len(extract_presets_from_import_body(body)) == 1


def test_extract_presets_bare():
    body = {"name": "N", "agent_names": ["专家 A"]}
    assert extract_presets_from_import_body(body)[0]["name"] == "N"


def test_normalize_invalid():
    assert normalize_preset_dict_for_validation({}) is None
    assert normalize_preset_dict_for_validation({"name": "", "agent_names": ["专家 A"]}) is None


def test_validate_missing_agent():
    preset = {
        "name": "P",
        "agent_names": ["缺失专家"],
        "host_config": {"skill_name": "主持技能", "skill_directory": "skill-host"},
    }
    v = validate_session_preset(
        preset,
        agent_by_name={},
        skill_has_content=lambda directory_name: directory_name == "skill-host",
        mcp_servers=[{"name": "检索工具", "type": "mcp"}],
    )
    assert "缺失专家" in v.missing_agents
    d = validation_to_api_dict(v)
    assert d["valid"] is False


def test_validate_host_skill_and_mcp():
    preset = {
        "name": "P",
        "agent_names": ["专家 A"],
        "host_config": {
            "skill_name": "主持技能",
            "skill_directory": "skill-host",
        },
    }
    agents = {
        "专家 A": {
            "skills": [{"name": "专家技能", "directory_name": "skill-expert"}],
        }
    }
    v = validate_session_preset(
        preset,
        agent_by_name=agents,
        skill_has_content=lambda directory_name: directory_name in ("skill-host", "skill-expert"),
        mcp_servers=[],
    )
    assert v.valid


def test_validate_empty_host_skills_do_not_create_missing_group_host():
    preset = {
        "name": "P",
        "agent_names": ["专家 A"],
        "host_config": {"skill_name": "", "skill_directory": ""},
    }
    agents = {"专家 A": {"skills": []}}
    v = validate_session_preset(
        preset,
        agent_by_name=agents,
        skill_has_content=lambda _: False,
        mcp_servers=[],
    )

    assert v.valid
    assert v.missing_skills == []


def test_group_host_without_skills_has_no_default_dependency():
    cfg = normalize_host_config_dict({"skill_name": "", "skill_directory": ""})

    assert cfg["skill_name"] == ""
    assert cfg["skill_directory"] == ""


def test_group_host_ignores_malformed_skill_refs():
    cfg = normalize_host_config_dict(
        {
            "skill_name": "",
            "skill_directory": "skill-host",
        }
    )

    assert cfg["skill_name"] == ""
    assert cfg["skill_directory"] == "skill-host"


def test_host_config_normalizes_to_single_host_skill():
    cfg = normalize_host_config_dict(
        {
            "skill_name": "主持人 A",
            "skill_directory": "/host-a",
        }
    )

    assert cfg["skill_name"] == "主持人 A"
    assert cfg["skill_directory"] == "host-a"


def test_skip_agent_skills_when_agent_missing():
    preset = {"name": "P", "agent_names": ["幽灵专家"]}
    v = validate_session_preset(
        preset,
        agent_by_name={},
        skill_has_content=lambda _: False,
        mcp_servers=[],
    )
    assert v.missing_agents == ["幽灵专家"]
    assert not v.missing_skills
