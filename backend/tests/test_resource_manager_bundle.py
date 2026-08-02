import asyncio
import io
import json
import re
import zipfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT = ROOT / "examples" / "resource-manager-test"
PUBLISHER_BUNDLE_PATH = ROOT / "examples" / "resource-publisher-test" / "resource-publisher-test.zip"
TOOL_NAMES = {
    "资源共享-创建富文本",
    "资源共享-管理上传文件",
    "资源共享-查询列表",
    "资源共享-搜索资源",
    "资源共享-查询详情",
    "资源共享-管理开启分享",
    "资源共享-撤销分享",
    "资源共享-更新富文本",
    "资源共享-删除资源",
}


def test_resource_manager_zip_is_a_gitignored_generated_artifact():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "/examples/resource-manager-test/*.zip" in gitignore


def _tool_path(name: str) -> str:
    return f"resources/tools/{name}/tool.json"


def _bundle_source_files() -> dict[str, Path]:
    return {
        path.relative_to(BUNDLE_ROOT).as_posix(): path
        for path in BUNDLE_ROOT.rglob("*")
        if path.is_file() and path.suffix != ".zip" and path.name != ".DS_Store"
    }


def _build_bundle_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, source_path in sorted(_bundle_source_files().items()):
            archive.writestr(name, source_path.read_bytes())
    return output.getvalue()


def _skill_parts(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, frontmatter, body = text.split("---", 2)
    return yaml.safe_load(frontmatter) or {}, body.strip()


def _assert_imported_resource_matches_source(source_path: Path, imported_path: Path) -> None:
    assert imported_path.is_file(), source_path.as_posix()
    if source_path.name == "SKILL.md":
        assert _skill_parts(imported_path) == _skill_parts(source_path)
    elif source_path.suffix == ".json":
        assert json.loads(imported_path.read_text(encoding="utf-8")) == json.loads(
            source_path.read_text(encoding="utf-8")
        )
    else:
        assert imported_path.read_bytes() == source_path.read_bytes()


def test_resource_manager_bundle_contract_is_complete_and_secret_free():
    assert not list(BUNDLE_ROOT.rglob(".DS_Store"))
    source_files = _bundle_source_files()

    with zipfile.ZipFile(io.BytesIO(_build_bundle_bytes())) as archive:
        names = set(archive.namelist())
        assert names == set(source_files)
        for name, source_path in source_files.items():
            assert archive.read(name) == source_path.read_bytes()
        manifest = json.loads(archive.read("bundle.json"))
        scenario = json.loads(archive.read("resources/scenarios/资源管理测试/scenario.json"))
        agent = json.loads(archive.read("resources/agents/资源管理专家/agent.json"))
        skill = archive.read("resources/skills/resource-manager/SKILL.md").decode("utf-8")
        tools = {
            name: json.loads(archive.read(_tool_path(name)))
            for name in TOOL_NAMES
        }
        all_text = "\n".join(
            archive.read(name).decode("utf-8")
            for name in names
            if name.endswith((".json", ".md"))
        )

    assert manifest["bundle_type"] == "scenario"
    assert "resources/scenarios/资源管理测试/scenario.json" in names
    assert "resources/agents/资源管理专家/agent.json" in names
    assert "resources/skills/resource-manager/SKILL.md" in names
    assert "resources/skills/resource-manager-host/SKILL.md" in names
    assert {_tool_path(name) for name in TOOL_NAMES} <= names
    assert "${env:STATIC_CONTENT_API_KEY}" in all_text
    assert "sk-" not in all_text

    scenario_prompt = scenario["system_prompt"]
    host_prompt = scenario["host"]["system_prompt"]
    assert scenario["allow_agent_recruitment"] is False
    assert scenario["agent_names"] == ["资源管理专家"]
    assert scenario["host"]["skill_directory"] == "resource-manager-host"
    for heading in ["场景目标：", "适用范围：", "共同要求：", "工作区约定：", "完成标准："]:
        assert heading in scenario_prompt
    assert "默认私密" in scenario_prompt
    assert "不得从 URL" in scenario_prompt
    assert "workspace_text" in scenario_prompt
    assert "主持人" not in scenario_prompt
    assert "target_agent_name" not in scenario_prompt
    assert "JSON" not in scenario_prompt

    assert "你是会话主持人，只负责调度" in host_prompt
    assert "业务信息是否充分由该专家判断并向用户提问" in host_prompt
    assert "只有满足场景任务契约的完成标准时，才能结束" in host_prompt
    assert "工作区：" in host_prompt
    assert "阶段表使用规则：" in host_prompt
    assert "任务单应包含本轮目标" in host_prompt
    assert "业务信息是否充分仍由资源管理专家判断" in host_prompt
    assert "current_phase 为“等待资源信息”时" in host_prompt
    assert "回答是否充分仅由资源管理专家判断" in host_prompt
    assert "按表格从上到下判断“判定条件”列，执行第一条已经满足的规则" in host_prompt
    assert "没有任何条件能够确认时，保持原阶段并把控制权交给用户" in host_prompt
    assert '"current_phase"' in host_prompt
    assert '"target_agent_name"' in host_prompt
    assert '"attachments"' in host_prompt
    assert '"artifacts"' in host_prompt
    assert '"suggested_add_agent_names"' in host_prompt
    assert "发布、创建、上传" in agent["description"]
    assert "公开分享" in agent["description"]
    assert "不选择下一位专家" in agent["system_prompt"]
    assert '"execution_status"' in agent["system_prompt"]
    assert '"next_action"' in agent["system_prompt"]
    assert "succeeded、blocked 或 failed" in agent["system_prompt"]
    assert "continue 或 respond" in agent["system_prompt"]
    assert "keep 或 release" in agent["system_prompt"]

    assert tools["资源共享-创建富文本"]["config"]["body"] == {"bodyFormat": "markdown"}
    assert tools["资源共享-管理上传文件"]["config"]["body"] == {}
    assert tools["资源共享-查询详情"]["config"]["path"] == "/api/query/detail/{contentId}"
    assert "标题、资源 ID、类型、公开状态和实际返回的 `ownerUrl`" in tools["资源共享-查询详情"]["description"]
    assert "不展示正文、`accessUrl` 或 `shareUrl`" in tools["资源共享-查询详情"]["description"]
    assert "只通过 `body.contentId`" in tools["资源共享-删除资源"]["description"]
    assert "不得传 `path_params`" in tools["资源共享-删除资源"]["description"]
    assert tools["资源共享-更新富文本"]["config"]["workspace_text"]["allowed_extensions"] == [".md"]
    assert tools["资源共享-更新富文本"]["config"]["workspace_text"]["max_bytes"] == 10485760

    for phrase in [
        "默认私密",
        "资源 ID",
        "不得从任何 URL",
        "先查询",
        "二次确认",
        "完整正文",
        "不得重新创建",
        "私密资源只展示",
        "逐条列出 `items` 中的全部资源",
        "不得将部分结果称为全部资源",
    ]:
        assert phrase in skill

    host_skill = (
        BUNDLE_ROOT / "resources" / "skills" / "resource-manager-host" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "| 决策前阶段 | 判定条件 | 本轮动作 | 决策后阶段 |" in host_skill
    assert "调度`资源管理专家`" in host_skill
    assert "转述资源管理专家上一条消息中的必要问题" in host_skill
    assert "| 资源管理 | 最近一条对话消息来自资源管理专家" in host_skill
    assert "| 等待资源信息 | 最近一条对话消息来自用户" in host_skill
    assert "不判断回答内容是否充分" in host_skill
    assert "| 等待资源信息 |" in host_skill
    assert "用户已回答资源管理专家的必要问题" not in host_skill
    assert "最近一条对话消息来自资源管理专家" in host_skill
    assert "execution_status=" not in host_skill
    assert "不得把专家自己的提问视为用户回答" in host_skill
    assert "用户当前明确资源任务已经真实完成" in host_skill
    assert "不可恢复失败" in host_skill
    assert "message.target_agent_name" not in host_skill
    assert "JSON" not in host_skill
    assert re.findall(r"^## (.+)$", host_skill, flags=re.MULTILINE) == []

    assert re.findall(r"^## (.+)$", skill, flags=re.MULTILINE) == ["执行规则", "结束条件"]
    assert "Markdown 文件且只模糊要求“发布”" in skill
    assert "execution_status=blocked" in skill
    assert "agent_turn=respond" in skill
    assert "skill_session=keep" in skill
    assert "execution_status=succeeded" in skill
    assert "skill_session=release" in skill
    assert "agent_turn=continue" in skill
    assert "execution_status=failed" in skill
    assert "搜索结果继续按页调用“资源共享-搜索资源”并始终携带原 `query.q`" in skill
    assert "可通过重新调用同一工具恢复" in skill
    assert "同时处理最新回复中新增的明确资源操作" in host_skill

def test_resource_manager_bundle_imports_through_frontend_http_contract(monkeypatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username
    from app.main import app

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    monkeypatch.setattr("app.core.security.decode_access_token", lambda _token: "u1")
    client = TestClient(app)
    bundle_bytes = _build_bundle_bytes()
    request_kwargs = {
        "files": {
            "file": (
                "resource-manager-test.zip",
                bundle_bytes,
                "application/zip",
            )
        },
        "headers": {"Authorization": "Bearer test-token"},
    }

    preview = client.post(
        "/api/settings/session-presets/import-bundle",
        data={"dry_run": "true"},
        **request_kwargs,
    )
    assert preview.status_code == 200
    preview_data = preview.json()["data"]["bundle_preview"]
    assert preview_data["preset_name"] == "资源管理测试"
    assert preview_data["missing_references"] == {
        "experts": [],
        "skills": [],
        "tools": [],
    }

    committed = client.post(
        "/api/settings/session-presets/import-bundle",
        data={"dry_run": "false"},
        **request_kwargs,
    )
    assert committed.status_code == 200
    assert committed.json()["data"]["summary"]["preset_imported_names"] == ["资源管理测试"]

    token = set_current_username("u1")
    try:
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
        for source_path in (BUNDLE_ROOT / "resources").rglob("*"):
            if not source_path.is_file() or source_path.name == ".DS_Store":
                continue
            relative = source_path.relative_to(BUNDLE_ROOT / "resources")
            imported_path = ctx.resources_dir / relative
            _assert_imported_resource_matches_source(source_path, imported_path)
    finally:
        reset_current_username(token)


def test_resource_manager_agent_uses_existing_long_paste_staging_boundary():
    composer = (
        ROOT / "frontend/src/features/workspace/composables/useGroupComposerActions.ts"
    ).read_text(encoding="utf-8")

    assert "'资源发布专家'" in composer
    assert "'资源管理专家'" in composer
    assert "PASTE_TO_WORKSPACE_THRESHOLD = 1024" in composer
    assert "/发布|共享|上传|保存|公开/" in composer
    assert "STAGED_RESOURCE_REQUEST_LIMIT = 140" in composer
    assert "完整内容已暂存为附带 Markdown 文件。用户原始请求摘要：" in composer
    assert "请依据该请求处理附件；未明确时先询问。" not in composer
    assert "请将附带的 Markdown 渲染为网页正文发布。" not in composer


def test_resource_manager_skill_locks_management_call_order_contract():
    skill = (
        BUNDLE_ROOT / "resources" / "skills" / "resource-manager" / "SKILL.md"
    ).read_text(encoding="utf-8")

    for rule in [
        "只创建或上传，不开启分享",
        "仅调用一次“资源共享-管理开启分享”",
        "详情显示已分享且包含 `shareUrl` 时直接返回原链接",
        "分享或撤销失败后停止，不得重新创建资源",
        "不得对同一动作再次要求确认",
        "不得再要求用户确认公开",
        "核对成功后直接调用“资源共享-删除资源”",
        "仅修改标题且资源 ID 可靠时",
        "不得调用“资源共享-查询详情”",
        "查询详情只展示标题、资源 ID、类型、公开状态和实际返回的 `ownerUrl`",
        "不展示正文、`accessUrl` 或 `shareUrl`",
        "链接必须逐字符复制工具响应 JSON 中对应字段的完整字符串",
        "端口、路径或分隔符",
        "最终回复中的链接必须与本轮工具结果逐字符一致",
        "删除调用只传 `body: {\"contentId\": \"...\"}`，不得传 `path_params`",
        "设置密码不通过本场景 HTTP API 执行",
        "请前往 Owner 管理详情页自行设置访问密码",
        "不得建议改为公开分享",
        "不得再次询问资源对象",
        "execution_status=blocked",
        "next_action.agent_turn=respond",
    ]:
        assert rule in skill


def test_resource_manager_bundle_imports_without_overwriting_publisher_resources(monkeypatch, tmp_path: Path):
    from app.api import settings_presets as api
    from app.api.settings_mcp import load_mcp_config
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    bundle_bytes = _build_bundle_bytes()
    token = set_current_username("resource-manager-test")
    try:
        asyncio.run(api._import_scene_from_bundle_bytes(PUBLISHER_BUNDLE_PATH.read_bytes(), dry_run=False))
        preview = asyncio.run(api._import_scene_from_bundle_bytes(bundle_bytes, dry_run=True))
        result = asyncio.run(api._import_scene_from_bundle_bytes(bundle_bytes, dry_run=False))
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
        imported_skill = ctx.skills_dir / "resource-manager" / "SKILL.md"
        imported_tools = {row["name"] for row in load_mcp_config()}
        imported_agents = {
            path.parent.name
            for path in ctx.agents_dir.glob("*/agent.json")
        }
        imported_scenarios = {
            path.parent.name
            for path in ctx.scenarios_dir.glob("*/scenario.json")
        }
    finally:
        reset_current_username(token)

    assert preview["preview"]["preset_name"] == "资源管理测试"
    assert result["summary"]["agent_imported_names"] == ["资源管理专家"]
    assert result["summary"]["skills_imported"] == ["resource-manager", "resource-manager-host"]
    assert result["summary"]["mcp_added"] == 9
    assert imported_skill.is_file()
    assert TOOL_NAMES <= imported_tools
    assert {"资源共享-上传文件", "资源共享-开启分享"} <= imported_tools
    assert preview["preview"]["would_overwrite_tools"] == []
    assert {"资源发布专家", "资源管理专家"} <= imported_agents
    assert {"资源发布测试", "资源管理测试"} <= imported_scenarios


def test_resource_manager_tools_cover_private_create_query_and_management(monkeypatch, tmp_path: Path):
    from app.tools.http_api_tool import create_http_api_tool
    import app.tools.http_api_tool as http_api_tool_mod

    tool_rows = {
        path.parent.name: json.loads(path.read_text(encoding="utf-8"))
        for path in (BUNDLE_ROOT / "resources" / "tools").glob("*/tool.json")
    }
    (tmp_path / "new-body.md").write_text("# 新正文", encoding="utf-8")
    calls = []

    def fake_call_api(**kwargs):
        calls.append((kwargs["method"], kwargs["url"], json.loads(kwargs["body"])))
        return "ok"

    monkeypatch.setattr(http_api_tool_mod, "_call_api_response_impl", fake_call_api)
    monkeypatch.setattr(http_api_tool_mod, "get_workspace_root_path", lambda _workspace_id: tmp_path)

    tools = {
        name: create_http_api_tool(row, workspace_id="resource-session")
        for name, row in tool_rows.items()
    }
    tools["资源共享-创建富文本"].invoke({"body": {"title": "私密正文", "body": "正文"}})
    tools["资源共享-查询列表"].invoke({"query": {"page": 1, "perPage": 10}})
    tools["资源共享-搜索资源"].invoke({"query": {"q": "私密正文"}})
    tools["资源共享-查询详情"].invoke({"path_params": {"contentId": "content/1"}})
    tools["资源共享-管理开启分享"].invoke({"body": {"contentId": "content-1"}})
    tools["资源共享-撤销分享"].invoke({"body": {"contentId": "content-1"}})
    tools["资源共享-更新富文本"].invoke(
        {
            "body": {
                "contentId": "content-1",
                "title": "私密正文",
                "bodyFormat": "markdown",
            },
            "workspace_file": {"path": "new-body.md"},
        }
    )
    tools["资源共享-删除资源"].invoke({"body": {"contentId": "content-1"}})

    assert [call[1] for call in calls] == [
        "http://10.129.236.188:8787/api/write/content",
        "http://10.129.236.188:8787/api/query/list?page=1&perPage=10",
        "http://10.129.236.188:8787/api/query/search?q=%E7%A7%81%E5%AF%86%E6%AD%A3%E6%96%87",
        "http://10.129.236.188:8787/api/query/detail/content%2F1",
        "http://10.129.236.188:8787/api/write/share",
        "http://10.129.236.188:8787/api/write/share/revoke",
        "http://10.129.236.188:8787/api/write/update",
        "http://10.129.236.188:8787/api/write/delete",
    ]
    assert calls[0][2] == {"title": "私密正文", "body": "正文"}
    assert "accessMode" not in calls[0][2]
    assert calls[6][2] == {
        "contentId": "content-1",
        "title": "私密正文",
        "bodyFormat": "markdown",
        "body": "# 新正文",
    }
