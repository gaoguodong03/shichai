from app.core.mcp_skill_resolution import resolve_skill_mcp_declarations


def test_resolve_skill_mcp_declarations_by_declared_name():
    servers = [{"name": "Exa"}]
    resolved, missing = resolve_skill_mcp_declarations(["Exa"], servers)
    assert resolved == ["Exa"]
    assert missing == []


def test_resolve_skill_mcp_declarations_rejects_case_mismatch():
    servers = [{"name": "Exa"}]
    resolved, missing = resolve_skill_mcp_declarations(["exa"], servers)
    assert resolved == []
    assert missing == ["exa"]


def test_resolve_skill_mcp_declarations_by_display_name():
    servers = [{"name": "Exa 搜索"}]
    resolved, missing = resolve_skill_mcp_declarations(["Exa 搜索"], servers)
    assert resolved == ["Exa 搜索"]
    assert missing == []


def test_resolve_skill_mcp_declarations_rejects_resource_id():
    servers = [{"id": "mcp-fb19dbb1", "name": "Exa 搜索"}]
    resolved, missing = resolve_skill_mcp_declarations(["mcp-fb19dbb1"], servers)
    assert resolved == []
    assert missing == ["mcp-fb19dbb1"]


def test_resolve_skill_mcp_declarations_rejects_short_name_guess():
    servers = [{"name": "Exa 搜索"}]
    resolved, missing = resolve_skill_mcp_declarations(["exa"], servers)
    assert resolved == []
    assert missing == ["exa"]


def test_resolve_skill_mcp_declarations_unresolved():
    servers = [{"name": "Exa"}]
    resolved, missing = resolve_skill_mcp_declarations(["mcp-missing"], servers)
    assert resolved == []
    assert missing == ["mcp-missing"]


def test_resolve_skill_mcp_declarations_does_not_guess_ambiguous_short_name():
    servers = [
        {"name": "Exa 搜索"},
        {"name": "Exa 抓取"},
    ]
    resolved, missing = resolve_skill_mcp_declarations(["exa"], servers)
    assert resolved == []
    assert missing == ["exa"]
