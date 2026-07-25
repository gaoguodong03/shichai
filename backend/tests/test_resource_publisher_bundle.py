import asyncio
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUNDLE_PATH = ROOT / "examples" / "resource-publisher-test" / "resource-publisher-test.zip"


def test_resource_publisher_bundle_is_importable_and_uses_user_api_key_reference():
    assert BUNDLE_PATH.is_file()

    with zipfile.ZipFile(BUNDLE_PATH) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("bundle.json"))
        text_tool = json.loads(archive.read("resources/tools/资源共享-发布文字/tool.json"))
        upload_tool = json.loads(archive.read("resources/tools/资源共享-上传文件/tool.json"))
        skill = archive.read("resources/skills/resource-publisher/SKILL.md").decode("utf-8")

    assert manifest["bundle_type"] == "scenario"
    assert "resources/scenarios/资源发布测试/scenario.json" in names
    assert "resources/agents/资源发布专家/agent.json" in names
    assert "resources/skills/resource-publisher/SKILL.md" in names
    assert upload_tool["type"] == "http_api"
    assert upload_tool["config"]["header"]["x-shutong49-api-key"] == "${env:STATIC_CONTENT_API_KEY}"
    assert upload_tool["config"]["file_upload"]["max_bytes"] == 10485760
    assert text_tool["config"]["workspace_text"]["allowed_extensions"] == [".md"]
    assert text_tool["config"]["workspace_text"]["max_bytes"] == 10485760
    assert text_tool["config"]["body"] == {"bodyFormat": "markdown", "accessMode": "public"}
    assert "渲染为网页" in skill
    assert "调用 `read_workspace_file` 读取" not in skill
    assert "不得调用 `read_workspace_file`" in skill


def test_resource_publisher_bundle_imports_into_empty_user_resources(monkeypatch, tmp_path: Path):
    from app.api import settings_presets as api
    from app.api.settings_mcp import load_mcp_config
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("publisher-test")
    try:
        preview = asyncio.run(api._import_scene_from_bundle_bytes(BUNDLE_PATH.read_bytes(), dry_run=True))
        result = asyncio.run(api._import_scene_from_bundle_bytes(BUNDLE_PATH.read_bytes(), dry_run=False))
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
        imported_skill = ctx.skills_dir / "resource-publisher" / "SKILL.md"
        upload_tool = next(row for row in load_mcp_config() if row["name"] == "资源共享-上传文件")
    finally:
        reset_current_username(token)

    assert preview["preview"]["preset_name"] == "资源发布测试"
    assert result["summary"]["agent_imported_names"] == ["资源发布专家"]
    assert result["summary"]["skills_imported"] == ["resource-publisher"]
    assert imported_skill.is_file()
    assert upload_tool["config"]["file_upload"]["content_base64_field"] == "contentBase64"


def test_resource_publisher_tools_use_create_or_upload_before_share(tmp_path: Path, monkeypatch):
    from app.tools.http_api_tool import create_http_api_tool
    import app.tools.http_api_tool as http_api_tool_mod

    with zipfile.ZipFile(BUNDLE_PATH) as archive:
        tools = {
            name: json.loads(archive.read(path))
            for name, path in {
                "text": "resources/tools/资源共享-发布文字/tool.json",
                "file": "resources/tools/资源共享-上传文件/tool.json",
                "share": "resources/tools/资源共享-开启分享/tool.json",
            }.items()
        }
    (tmp_path / "note.md").write_text("附件内容", encoding="utf-8")
    calls = []

    def fake_call_api(**kwargs):
        calls.append((kwargs["url"], json.loads(kwargs["body"])))
        return "ok"

    monkeypatch.setattr(http_api_tool_mod, "_call_api_response_impl", fake_call_api)
    monkeypatch.setattr(http_api_tool_mod, "get_workspace_root_path", lambda _workspace_id: tmp_path)
    text_tool = create_http_api_tool(tools["text"], workspace_id="publisher-session")
    file_tool = create_http_api_tool(tools["file"], workspace_id="publisher-session")
    share_tool = create_http_api_tool(tools["share"], workspace_id="publisher-session")

    text_tool.invoke({"body": {"title": "文字", "body": "正文", "bodyFormat": "markdown", "accessMode": "public"}})
    share_tool.invoke({"body": {"contentId": "text-content"}})
    text_tool.invoke({"workspace_file": {"path": "note.md"}})
    share_tool.invoke({"body": {"contentId": "markdown-content"}})
    file_tool.invoke({"body": {"title": "附件", "accessMode": "public"}, "workspace_file": {"path": "note.md"}})
    share_tool.invoke({"body": {"contentId": "file-content"}})

    assert [url.rsplit("/", 1)[-1] for url, _body in calls] == ["content", "share", "content", "share", "file", "share"]
    assert calls[2][1]["title"] == "note"
    assert calls[2][1]["body"] == "附件内容"
    assert calls[4][1]["filename"] == "note.md"
    assert calls[5][1] == {"contentId": "file-content"}
