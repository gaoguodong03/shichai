import json
from pathlib import Path

from app.core.name_based_resources import (
    normalize_agent_row,
    normalize_scenario_row,
    normalize_skill_refs,
    normalize_tool_row,
    strip_resource_ids,
)


def test_strip_resource_ids_removes_all_resource_id_keys():
    raw = {
        "id": "scenario-1",
        "name": "协同写作",
        "agent_id": "agent-a",
        "agent_ids": ["agent-a"],
        "host": {
            "skill_id": "skill-a",
            "skill_ids": ["skill-a"],
            "mcp_server_id": "mcp-a",
            "mcp_server_ids": ["mcp-a"],
            "llm_provider_id": "deepseek",
            "llm_name": "deepseek-v4-flash",
        },
        "agents": [{"id": "x", "name": "写作专家"}],
    }

    stripped = strip_resource_ids(raw)

    assert "id" not in json.dumps(stripped, ensure_ascii=False)
    assert stripped["name"] == "协同写作"
    assert stripped["host"]["llm_name"] == "deepseek-v4-flash"


def test_normalize_tool_row_preserves_mcp_server_config_string_and_lowercases_type():
    server_config = json.dumps(
        {
            "mcpServers": {
                "MiniMax": {
                    "command": "uvx",
                    "args": ["minimax-mcp"],
                    "env": {"MINIMAX_API_KEY": "<insert-your-api-key-here>"},
                }
            }
        },
        ensure_ascii=False,
    )

    row = normalize_tool_row(
        {
            "id": "mcp-minimax",
            "name": "MiniMax",
            "type": "MCP",
            "description": "MiniMax MCP",
            "server_config": server_config,
        }
    )

    assert row == {
        "name": "MiniMax",
        "type": "mcp",
        "description": "MiniMax MCP",
        "server_config": server_config,
    }
    assert json.loads(row["server_config"])["mcpServers"]["MiniMax"]["command"] == "uvx"


def test_normalize_tool_row_completes_http_api_executable_config():
    row = normalize_tool_row(
        {
            "name": "Exa 搜索",
            "type": "HTTP API",
            "description": "Exa search",
            "config": {
                "type": "GET",
                "base_url": "https://api.exa.ai",
                "header": {"Authorization": "<insert-your-api-key-here>"},
                "body": "",
            },
        }
    )

    assert row["type"] == "http_api"
    assert row["config"] == {
        "type": "GET",
        "base_url": "https://api.exa.ai",
        "path": "",
        "header": {"Authorization": "<insert-your-api-key-here>"},
        "query": {},
        "body": "",
        "timeout_seconds": 60,
    }
    assert "id" not in row


def test_saved_http_api_tool_executes_with_configured_fields(monkeypatch):
    from app.tools import call_api as call_api_mod
    from app.tools.http_api_tool import create_http_api_tool

    called = {}

    def fake_call_api(**kwargs):
        called.update(kwargs)
        return "ok"

    monkeypatch.setattr(call_api_mod, "_call_api_impl", fake_call_api)
    import app.tools.http_api_tool as http_api_tool_mod

    monkeypatch.setattr(http_api_tool_mod, "_call_api_impl", fake_call_api)
    tool = create_http_api_tool(
        {
            "name": "Exa 搜索",
            "type": "http_api",
            "config": {
                "type": "POST",
                "base_url": "https://api.example.com",
                "path": "/v1/search",
                "header": {"Authorization": "Bearer ${env:EXA_API_KEY}"},
                "query": {"source": "local"},
                "body": {"q": "default"},
                "timeout_seconds": 12,
            },
        },
        env_vars={"EXA_API_KEY": "secret-token"},
    )

    out = tool.invoke({"query": {"q": "codex"}, "body": {"q": "override"}})

    assert out == "ok"
    assert tool.name.startswith("http_api_")
    assert called["url"] == "https://api.example.com/v1/search?source=local&q=codex"
    assert called["method"] == "POST"
    assert json.loads(called["headers_json"]) == {"Authorization": "Bearer secret-token"}
    assert json.loads(called["body"]) == {"q": "override"}
    assert called["timeout_seconds"] == 12


def test_saved_http_api_tool_only_resolves_platform_env_syntax(monkeypatch):
    from app.tools import call_api as call_api_mod
    from app.tools.http_api_tool import create_http_api_tool

    called = {}

    def fake_call_api(**kwargs):
        called.update(kwargs)
        return "ok"

    monkeypatch.setenv("EXA_API_KEY", "host-secret")
    monkeypatch.setattr(call_api_mod, "_call_api_impl", fake_call_api)
    import app.tools.http_api_tool as http_api_tool_mod

    monkeypatch.setattr(http_api_tool_mod, "_call_api_impl", fake_call_api)
    tool = create_http_api_tool(
        {
            "name": "Exa 搜索",
            "type": "http_api",
            "config": {
                "type": "GET",
                "base_url": "https://api.example.com/${EXA_API_KEY}",
                "header": {"Authorization": "Bearer ${EXA_API_KEY}"},
            },
        },
        env_vars={"EXA_API_KEY": "user-secret"},
    )

    assert tool.invoke({}) == "ok"
    assert called["url"] == "https://api.example.com/${EXA_API_KEY}"
    assert json.loads(called["headers_json"]) == {"Authorization": "Bearer ${EXA_API_KEY}"}


def test_normalize_skill_refs_keep_name_and_directory_name_only():
    refs = normalize_skill_refs(
        [
            {"id": "old", "name": "文档合著v1.1", "directory_name": "\\skill_fasfasdf"},
            {"skill_id": "another", "name": "检索", "folder_name": "skill-search"},
        ]
    )

    assert refs == [
        {"name": "文档合著v1.1", "directory_name": "skill_fasfasdf"},
    ]


def test_normalize_skill_refs_dedupes_by_directory_name_not_display_name():
    refs = normalize_skill_refs(
        [
            {"name": "同名 Skill", "directory_name": "skill-alpha"},
            {"name": "同名 Skill", "directory_name": "skill-beta"},
            {"name": "改名后的 Skill", "directory_name": "skill-alpha"},
        ]
    )

    assert refs == [
        {"name": "同名 Skill", "directory_name": "skill-alpha"},
        {"name": "同名 Skill", "directory_name": "skill-beta"},
    ]


def test_normalize_skill_refs_preserves_directory_name_identity():
    refs = normalize_skill_refs(
        [
            {"name": "大小写敏感 Skill", "directory_name": "Skill-ABC_01"},
            {"name": "嵌套路径旧输入", "directory_name": "/nested/skill"},
        ]
    )

    assert refs == [{"name": "大小写敏感 Skill", "directory_name": "Skill-ABC_01"}]


def test_normalize_skill_refs_preserves_missing_skill_directory_without_display_name():
    refs = normalize_skill_refs(
        [
            {"directory_name": "deleted-skill"},
        ]
    )

    assert refs == [{"name": "", "directory_name": "deleted-skill"}]


def test_normalize_skill_refs_dedupes_by_exact_directory_name_identity():
    refs = normalize_skill_refs(
        [
            {"name": "大写目录 Skill", "directory_name": "Skill-ABC_01"},
            {"name": "小写目录 Skill", "directory_name": "skill-abc_01"},
            {"name": "重复目录 Skill", "directory_name": "Skill-ABC_01"},
        ]
    )

    assert refs == [
        {"name": "大写目录 Skill", "directory_name": "Skill-ABC_01"},
        {"name": "小写目录 Skill", "directory_name": "skill-abc_01"},
    ]


def test_skill_bundle_import_plan_uses_directory_name_identity(tmp_path: Path):
    from app.core.settings_bundle_import import skill_directory_identity_import_plan

    bundle_dir = tmp_path / "bundle"
    incoming = bundle_dir / "resources" / "skills" / "skill-incoming"
    incoming.mkdir(parents=True)
    incoming.joinpath("SKILL.md").write_text("---\nname: Same Display\n---\nincoming\n", encoding="utf-8")

    user_skills = tmp_path / "user-skills"
    local = user_skills / "skill-local"
    local.mkdir(parents=True)
    local.joinpath("SKILL.md").write_text("---\nname: Same Display\n---\nlocal\n", encoding="utf-8")

    directory_map, copy_pairs, overwritten = skill_directory_identity_import_plan(bundle_dir, user_skills)

    assert directory_map == {"skill-incoming": "skill-incoming"}
    assert copy_pairs == [("skill-incoming", "skill-incoming")]
    assert overwritten == []


def test_normalize_scenario_host_preserves_skill_directory_identity():
    row = normalize_scenario_row(
        {
            "name": "主持人 Skill 场景",
            "agent_names": ["专家A"],
            "host": {"skill_name": "主持 Skill", "skill_directory": "Host-Skill_01"},
        }
    )

    assert row["host"]["skill_directory"] == "Host-Skill_01"


def test_normalize_agent_row_keeps_only_name_llm_prompt_description_and_skills():
    row = normalize_agent_row(
        {
            "id": "agent-old",
            "name": "文档合著专家v1.1",
            "role": "旧角色",
            "llm_name": "deepseek-v4-flash",
            "description": "负责文档合著",
            "system_prompt": "按 Skill 工作",
            "tool_names": ["旧工具"],
            "is_leader": True,
            "avatar_url": "data:image/png;base64,abc",
            "file_capabilities": {"read": False},
            "url_capability": False,
            "skills": [
                {"name": "文档合著v1.1", "directory_name": "/skill_fasfasdf"},
                {"name": "文档检索v1.0", "directory_name": "\\skill_tywretmy"},
            ],
        }
    )

    assert row == {
        "name": "文档合著专家v1.1",
        "llm_name": "deepseek-v4-flash",
        "description": "负责文档合著",
        "system_prompt": "按 Skill 工作",
        "skills": [
            {"name": "文档合著v1.1", "directory_name": "skill_fasfasdf"},
            {"name": "文档检索v1.0", "directory_name": "skill_tywretmy"},
        ],
    }


def test_normalize_scenario_row_keeps_minimal_prompt_host_and_agent_names():
    row = normalize_scenario_row(
        {
            "id": "scenario-old",
            "name": "协同写作v1.1",
            "description": "",
            "system_prompt": "场景级项目规则",
            "discussion_goal_example": "旧字段",
            "agents": ["文档合著专家v1.1"],
            "agent_names": ["图片生成专家v1.0", "信息检索专家v1.0"],
            "host": {
                "name": "协同写作场景主持人",
                "llm_name": "deepseek-v4-flash",
                "system_prompt": None,
                "skills": [{"name": "旧列表", "directory_name": "skill-old"}],
                "skill_name": "协同写作主持人v1.2",
                "skill_directory": "\\skill_tywretmy",
                "tool_names": ["旧工具"],
                "file_capabilities": {"read": False},
                "url_capability": False,
            },
        }
    )

    assert row == {
        "name": "协同写作v1.1",
        "description": "",
        "system_prompt": "场景级项目规则",
        "host": {
            "name": "协同写作场景主持人",
            "llm_name": "deepseek-v4-flash",
            "system_prompt": "",
            "skill_name": "协同写作主持人v1.2",
            "skill_directory": "skill_tywretmy",
        },
        "agent_names": ["图片生成专家v1.0", "信息检索专家v1.0"],
    }


def test_skill_frontmatter_keeps_allowed_tools_mcp_http_api_and_python_only():
    from app.api.settings_skill_frontmatter import sanitize_skill_frontmatter_for_write

    fm = {
        "name": "文档合著v1.1",
        "description": "合著",
        "auto-tools": {"mcp": ["旧"], "python": "requests"},
        "allowed-tools": {"mcp": ["MiniMax"], "http-api": ["旧HTTP"], "http_api": ["Exa"], "python": "pandas"},
        "reference-labels": {"mcp": [{"name": "MiniMax"}]},
        "enabled": True,
    }

    sanitize_skill_frontmatter_for_write(fm)

    assert fm == {
        "name": "文档合著v1.1",
        "description": "合著",
        "allowed-tools": {
            "mcp": ["MiniMax"],
            "http_api": ["Exa"],
            "python": [],
        },
    }
