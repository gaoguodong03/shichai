from app.core.mcp_skill_resolution import resolve_skill_mcp_declarations


def test_resolve_skill_mcp_declarations_by_id():
    servers = [{"id": "mcp-a", "name": "Tool A"}]
    resolved, missing = resolve_skill_mcp_declarations(["mcp-a"], [], servers)
    assert resolved == ["mcp-a"]
    assert missing == []


def test_resolve_skill_mcp_declarations_by_declared_name():
    servers = [{"id": "mcp-local", "name": "Exa"}]
    resolved, missing = resolve_skill_mcp_declarations(["exa"], [], servers)
    assert resolved == ["mcp-local"]
    assert missing == []


def test_resolve_skill_mcp_declarations_by_ref_name():
    servers = [{"id": "mcp-local", "name": "Linkup Search"}]
    refs = [{"id": "stale-id", "name": "Linkup Search"}]
    resolved, missing = resolve_skill_mcp_declarations(["stale-id"], refs, servers)
    assert resolved == ["mcp-local"]
    assert missing == []


def test_resolve_skill_mcp_declarations_unresolved():
    servers = [{"id": "mcp-local", "name": "Exa"}]
    resolved, missing = resolve_skill_mcp_declarations(["mcp-missing"], [], servers)
    assert resolved == []
    assert missing == ["mcp-missing"]
