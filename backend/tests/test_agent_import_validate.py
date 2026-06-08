from app.core.agent_import_validate import (
    extract_expert_from_import_body,
    validate_agent_instance_row,
    agent_validation_to_api_dict,
)


def test_extract_expert_wrapped():
    body = {"expert": {"name": "N", "agent_id": "a1"}}
    assert len(extract_expert_from_import_body(body)) == 1


def test_extract_expert_bare():
    body = {"name": "N", "agent_id": "a1"}
    assert extract_expert_from_import_body(body)[0]["name"] == "N"


def test_validate_skills_mcp():
    row = {"skill_ids": ["s1", "missing"], "mcp_server_ids": ["m1", "gone"]}
    v = validate_agent_instance_row(
        row,
        skill_has_content=lambda s: s == "s1",
        mcp_servers=[{"id": "m1", "enabled": True}],
    )
    d = agent_validation_to_api_dict(v)
    assert d["valid"] is False
    assert any(x["skill_id"] == "missing" for x in d["missing_skills"])
