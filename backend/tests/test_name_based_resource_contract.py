import json
from pathlib import Path

import pytest

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


def test_normalize_tool_row_keeps_workspace_file_upload_mapping():
    row = normalize_tool_row(
        {
            "name": "资源共享-上传文件",
            "type": "http_api",
            "config": {
                "type": "POST",
                "base_url": "https://files.example.test",
                "path": "/api/write/file",
                "file_upload": {
                    "content_base64_field": "contentBase64",
                    "filename_field": "filename",
                    "mime_type_field": "mimeType",
                    "max_bytes": 10485760,
                },
            },
        }
    )

    assert row["config"]["file_upload"] == {
        "content_base64_field": "contentBase64",
        "filename_field": "filename",
        "mime_type_field": "mimeType",
        "max_bytes": 10485760,
    }


def test_normalize_tool_row_keeps_workspace_text_mapping():
    row = normalize_tool_row(
        {
            "name": "资源共享-发布 Markdown",
            "type": "http_api",
            "config": {
                "type": "POST",
                "base_url": "https://files.example.test",
                "workspace_text": {
                    "content_field": "body",
                    "title_field": "title",
                    "allowed_extensions": [".md"],
                    "max_bytes": 10485760,
                    "encoding": "utf-8",
                },
            },
        }
    )

    assert row["config"]["workspace_text"] == {
        "content_field": "body",
        "title_field": "title",
        "allowed_extensions": [".md"],
        "max_bytes": 10485760,
        "encoding": "utf-8",
    }


def test_normalize_tool_row_rejects_conflicting_workspace_payload_modes():
    with pytest.raises(ValueError, match="不能同时配置"):
        normalize_tool_row(
            {
                "name": "冲突工具",
                "type": "http_api",
                "config": {"file_upload": {}, "workspace_text": {}},
            }
        )


def test_saved_http_api_tool_executes_with_configured_fields(monkeypatch):
    from app.tools import call_api as call_api_mod
    from app.tools.http_api_tool import create_http_api_tool

    called = {}

    def fake_call_api(**kwargs):
        called.update(kwargs)
        return "ok"

    monkeypatch.setattr(call_api_mod, "_call_api_response_impl", fake_call_api)
    import app.tools.http_api_tool as http_api_tool_mod

    monkeypatch.setattr(http_api_tool_mod, "_call_api_response_impl", fake_call_api)
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


def test_saved_http_api_tool_substitutes_encoded_path_params(monkeypatch):
    from app.tools.http_api_tool import create_http_api_tool
    import app.tools.http_api_tool as http_api_tool_mod

    called = {}

    def fake_call_api(**kwargs):
        called.update(kwargs)
        return "ok"

    monkeypatch.setattr(http_api_tool_mod, "_call_api_response_impl", fake_call_api)
    tool = create_http_api_tool(
        {
            "name": "资源管理-查询详情",
            "type": "http_api",
            "config": {
                "type": "GET",
                "base_url": "https://files.example.test",
                "path": "/api/query/detail/{contentId}",
            },
        }
    )

    assert tool.invoke({"path_params": {"contentId": "中文/../?x=1#fragment"}}) == "ok"
    assert called["url"] == "https://files.example.test/api/query/detail/%E4%B8%AD%E6%96%87%2F..%2F%3Fx%3D1%23fragment"
    path_params_schema = tool.args_schema["properties"]["path_params"]
    assert path_params_schema["required"] == ["contentId"]
    assert set(path_params_schema["properties"]) == {"contentId"}
    assert path_params_schema["additionalProperties"] is False


@pytest.mark.parametrize(
    ("path_params", "error"),
    [
        ({}, "缺少路径参数"),
        ({"contentId": "content-1", "extra": "value"}, "未声明的路径参数"),
        ({"contentId": ""}, "不能为空"),
        ({"contentId": ".."}, "不能是相对路径段"),
        ({"contentId": ["content-1"]}, "必须是字符串、数字或布尔值"),
    ],
)
def test_saved_http_api_tool_rejects_invalid_path_params(path_params, error):
    from app.tools.http_api_tool import create_http_api_tool

    tool = create_http_api_tool(
        {
            "name": "资源管理-查询详情",
            "type": "http_api",
            "config": {
                "type": "GET",
                "base_url": "https://files.example.test",
                "path": "/api/query/detail/{contentId}",
            },
        }
    )

    with pytest.raises(ValueError, match=error):
        tool.invoke({"path_params": path_params})


def test_saved_http_api_tool_encodes_current_workspace_file_for_upload(tmp_path, monkeypatch):
    from app.tools.http_api_tool import create_http_api_tool
    import app.tools.http_api_tool as http_api_tool_mod

    (tmp_path / "report.pdf").write_bytes(b"%PDF-test")
    called = {}

    def fake_call_api(**kwargs):
        called.update(kwargs)
        return "ok"

    monkeypatch.setattr(http_api_tool_mod, "_call_api_response_impl", fake_call_api)
    monkeypatch.setattr(http_api_tool_mod, "get_workspace_root_path", lambda _workspace_id: tmp_path)
    tool = create_http_api_tool(
        {
            "name": "资源共享-上传文件",
            "type": "http_api",
            "config": {
                "type": "POST",
                "base_url": "https://files.example.test",
                "path": "/api/write/file",
                "file_upload": {
                    "content_base64_field": "contentBase64",
                    "filename_field": "filename",
                    "mime_type_field": "mimeType",
                    "max_bytes": 1024,
                },
            },
        },
        workspace_id="session-1",
    )

    assert tool.invoke({"body": {"title": "测试报告"}, "workspace_file": {"path": "report.pdf"}}) == "ok"
    assert json.loads(called["body"]) == {
        "title": "测试报告",
        "contentBase64": "JVBERi10ZXN0",
        "filename": "report.pdf",
        "mimeType": "application/pdf",
    }


def test_saved_http_api_tool_injects_current_workspace_markdown_without_model_content(tmp_path, monkeypatch):
    from app.tools.http_api_tool import create_http_api_tool
    import app.tools.http_api_tool as http_api_tool_mod

    inline_image = "A" * 100_000
    markdown = f"# 展示\n\n![内嵌图片](data:image/png;base64,{inline_image})"
    (tmp_path / "演示文档.md").write_text(markdown, encoding="utf-8")
    called = {}

    def fake_call_api(**kwargs):
        called.update(kwargs)
        return "ok"

    monkeypatch.setattr(http_api_tool_mod, "_call_api_response_impl", fake_call_api)
    monkeypatch.setattr(http_api_tool_mod, "get_workspace_root_path", lambda _workspace_id: tmp_path)
    tool = create_http_api_tool(
        {
            "name": "资源共享-发布文字",
            "type": "http_api",
            "config": {
                "type": "POST",
                "base_url": "https://files.example.test",
                "body": {"bodyFormat": "markdown", "accessMode": "public"},
                "workspace_text": {
                    "content_field": "body",
                    "title_field": "title",
                    "allowed_extensions": [".md"],
                    "max_bytes": 10485760,
                    "encoding": "utf-8",
                },
            },
        },
        workspace_id="session-1",
    )

    assert tool.invoke({"workspace_file": {"path": "演示文档.md"}}) == "ok"
    assert json.loads(called["body"]) == {
        "title": "演示文档",
        "body": markdown,
        "bodyFormat": "markdown",
        "accessMode": "public",
    }
    assert len(json.loads(called["body"])["body"]) > 100_000


@pytest.mark.parametrize(
    ("workspace_file", "file_bytes", "error"),
    [
        ({"path": "../outside.md"}, None, "文件路径无效"),
        ({"path": "missing.md"}, None, "工作区文件不存在"),
        ({"path": "note.txt"}, b"text", "不允许的文件类型"),
        ({"path": "large.md"}, b"too-large", "文件超过工具允许的大小上限"),
        ({"path": "invalid.md"}, b"\xff", "无法按 utf-8 解码"),
    ],
)
def test_saved_http_api_tool_rejects_invalid_workspace_text_inputs(tmp_path, monkeypatch, workspace_file, file_bytes, error):
    from app.tools.http_api_tool import create_http_api_tool
    import app.tools.http_api_tool as http_api_tool_mod

    if file_bytes is not None:
        (tmp_path / workspace_file["path"]).write_bytes(file_bytes)
    monkeypatch.setattr(http_api_tool_mod, "get_workspace_root_path", lambda _workspace_id: tmp_path)
    tool = create_http_api_tool(
        {
            "name": "发布 Markdown",
            "type": "http_api",
            "config": {
                "type": "POST",
                "base_url": "https://files.example.test",
                "workspace_text": {
                    "allowed_extensions": [".md"],
                    "max_bytes": 4,
                    "encoding": "utf-8",
                },
            },
        },
        workspace_id="session-1",
    )

    with pytest.raises(ValueError, match=error):
        tool.invoke({"workspace_file": workspace_file})


@pytest.mark.parametrize(
    ("workspace_file", "file_bytes", "error"),
    [
        ({"path": "../outside.pdf"}, None, "文件路径无效"),
        ({"path": "missing.pdf"}, None, "工作区文件不存在"),
        ({"path": "large.pdf"}, b"too-large", "文件超过工具允许的大小上限"),
    ],
)
def test_saved_http_api_tool_rejects_invalid_workspace_file_uploads(tmp_path, monkeypatch, workspace_file, file_bytes, error):
    from app.tools.http_api_tool import create_http_api_tool
    import app.tools.http_api_tool as http_api_tool_mod

    if file_bytes is not None:
        (tmp_path / workspace_file["path"]).write_bytes(file_bytes)
    monkeypatch.setattr(http_api_tool_mod, "get_workspace_root_path", lambda _workspace_id: tmp_path)
    tool = create_http_api_tool(
        {
            "name": "文件上传",
            "type": "http_api",
            "config": {
                "type": "POST",
                "base_url": "https://files.example.test",
                "file_upload": {"max_bytes": 4},
            },
        },
        workspace_id="session-1",
    )

    with pytest.raises(ValueError, match=error):
        tool.invoke({"body": {}, "workspace_file": workspace_file})


def test_saved_http_api_tool_only_resolves_platform_env_syntax(monkeypatch):
    from app.tools import call_api as call_api_mod
    from app.tools.http_api_tool import create_http_api_tool

    called = {}

    def fake_call_api(**kwargs):
        called.update(kwargs)
        return "ok"

    monkeypatch.setenv("EXA_API_KEY", "host-secret")
    monkeypatch.setattr(call_api_mod, "_call_api_response_impl", fake_call_api)
    import app.tools.http_api_tool as http_api_tool_mod

    monkeypatch.setattr(http_api_tool_mod, "_call_api_response_impl", fake_call_api)
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
        "allow_agent_recruitment": True,
    }


def test_normalize_scenario_row_preserves_closed_scene_recruitment_setting():
    row = normalize_scenario_row(
        {
            "name": "封闭场景",
            "agent_names": ["专家A"],
            "allow_agent_recruitment": False,
        }
    )

    assert row["allow_agent_recruitment"] is False


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
