from app.core.agent_import_validate import (
    extract_expert_from_import_body,
    validate_agent_instance_row,
    agent_validation_to_api_dict,
)


def test_extract_expert_wrapped():
    body = {"expert": {"name": "N"}}
    assert len(extract_expert_from_import_body(body)) == 1


def test_extract_expert_bare():
    body = {"name": "N"}
    assert extract_expert_from_import_body(body)[0]["name"] == "N"


def test_validate_skills_mcp():
    row = {
        "skills": [
            {"name": "技能1", "directory_name": "s1"},
            {"name": "缺失技能", "directory_name": "missing"},
        ]
    }
    v = validate_agent_instance_row(
        row,
        skill_has_content=lambda s: s == "s1",
        mcp_servers=[{"name": "m1", "type": "mcp"}],
    )
    d = agent_validation_to_api_dict(v)
    assert d["valid"] is False
    assert any(x["skill"] == "missing" for x in d["missing_skills"])
