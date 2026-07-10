"""测试 workspace 文件 API（按会话隔离、无全局 /api/files）"""
import asyncio
import os
import tempfile

import pytest

# 测试前将 SHUTONG_USER_DATA_ROOT 指向临时目录，避免写入仓库 data/users
@pytest.fixture(scope="module")
def temp_user_data_root():
    with tempfile.TemporaryDirectory() as d:
        old = os.environ.get("SHUTONG_USER_DATA_ROOT")
        old_anon = os.environ.get("ALLOW_ANONYMOUS_API")
        os.environ["SHUTONG_USER_DATA_ROOT"] = d
        os.environ["ALLOW_ANONYMOUS_API"] = "1"
        try:
            yield d
        finally:
            if old is not None:
                os.environ["SHUTONG_USER_DATA_ROOT"] = old
            else:
                os.environ.pop("SHUTONG_USER_DATA_ROOT", None)
            if old_anon is not None:
                os.environ["ALLOW_ANONYMOUS_API"] = old_anon
            else:
                os.environ.pop("ALLOW_ANONYMOUS_API", None)


@pytest.fixture
def client(temp_user_data_root):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_global_files_removed(client):
    """全局 /api/files 已下线，应 404"""
    r = client.get("/api/files")
    assert r.status_code == 404
    r = client.get("/api/files/download", params={"path": "x.txt"})
    assert r.status_code == 404


def test_workspace_list_empty(client):
    """空 workspace 列表返回空 entries"""
    r = client.get("/api/workspaces/test-session-1/files")
    assert r.status_code == 200
    j = r.json()
    assert j.get("status") == "ok"
    assert j.get("data", {}).get("entries") == []


def test_workspace_create_and_list(client):
    """workspace 内新建文件后能列出"""
    r = client.post(
        "/api/workspaces/ws1/files",
        json={"filename": "hello.md", "content": "# Hello"},
    )
    assert r.status_code == 200
    assert r.json().get("data", {}).get("path") == "hello.md"
    r = client.get("/api/workspaces/ws1/files")
    assert r.status_code == 200
    entries = r.json().get("data", {}).get("entries", [])
    by_name = {e["name"]: e for e in entries}
    assert "hello.md" in by_name
    assert by_name["hello.md"]["path"] == "hello.md"


def test_sessions_with_workspace_files_lists_sessions_that_have_files(client):
    """资源中心文件页应列出每个有 workspace 文件的会话。"""
    create_resp = client.post("/api/sessions", json={"title": "带文件会话"})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["data"]["id"]

    file_resp = client.post(
        f"/api/workspaces/{session_id}/files",
        json={"filename": "brief.md", "content": "# Brief"},
    )
    assert file_resp.status_code == 200

    list_resp = client.get("/api/workspaces/sessions-with-files")

    assert list_resp.status_code == 200
    sessions = list_resp.json()["data"]["sessions"]
    row = next((item for item in sessions if item["id"] == session_id), None)
    assert row is not None
    assert row["title"] == "带文件会话"
    assert row["file_count"] == 1


def test_sessions_with_workspace_files_includes_unindexed_session_dirs(client):
    """迁移前的 session 目录没有 session.json 时，文件页也应能发现 workspace 文件。"""
    from app.core.security import get_current_user

    session_id = "legacy-workspace-session"
    user = get_current_user()
    legacy_workspace = user.ctx.sessions_dir / session_id / "workspace"
    legacy_workspace.mkdir(parents=True, exist_ok=True)
    (legacy_workspace / "legacy.md").write_text("# Legacy", encoding="utf-8")

    list_resp = client.get("/api/workspaces/sessions-with-files")

    assert list_resp.status_code == 200
    sessions = list_resp.json()["data"]["sessions"]
    row = next((item for item in sessions if item["id"] == session_id), None)
    assert row is not None
    assert row["title"] == session_id
    assert row["file_count"] == 1


def test_workspace_download(client):
    """workspace 内文件可下载"""
    client.post(
        "/api/workspaces/ws2/files",
        json={"filename": "a.txt", "content": "content"},
    )
    r = client.get("/api/workspaces/ws2/files/download", params={"path": "a.txt"})
    assert r.status_code == 200
    assert r.text == "content"


def test_workspace_text_responses_disable_browser_cache(client):
    """工作区文本预览/下载不能被浏览器缓存成旧内容。"""
    client.post(
        "/api/workspaces/ws-cache/files",
        json={"filename": "facts.md", "content": "before"},
    )
    client.put(
        "/api/workspaces/ws-cache/files/content",
        params={"path": "facts.md"},
        json={"content": "after"},
    )

    content = client.get("/api/workspaces/ws-cache/files/content", params={"path": "facts.md"})
    assert content.status_code == 200
    assert content.headers.get("Cache-Control") == "no-store"
    assert content.json()["data"]["content"] == "after"

    download = client.get("/api/workspaces/ws-cache/files/download", params={"path": "facts.md"})
    assert download.status_code == 200
    assert download.headers.get("Cache-Control") == "no-store"
    assert download.text == "after"


def test_workspace_upload_and_rename(client):
    """workspace 上传、重命名"""
    r = client.post(
        "/api/workspaces/ws3/files/upload",
        files={"file": ("b.txt", b"uploaded")},
    )
    assert r.status_code == 200
    assert r.json().get("data", {}).get("path") == "b.txt"
    r = client.put(
        "/api/workspaces/ws3/files/rename",
        params={"path": "b.txt"},
        json={"new_name": "c.txt"},
    )
    assert r.status_code == 200
    assert r.json().get("data", {}).get("path") == "c.txt"
    r = client.get("/api/workspaces/ws3/files/download", params={"path": "c.txt"})
    assert r.status_code == 200
    assert r.text == "uploaded"


def test_workspace_upload_large_file(client):
    """大文件上传应分块落盘并保持内容完整"""
    payload = (b"audio-data-" * 130000) + b"tail"
    r = client.post(
        "/api/workspaces/ws-large/files/upload",
        files={"file": ("recording.wav", payload)},
    )
    assert r.status_code == 200
    assert r.json().get("data", {}).get("path") == "recording.wav"
    r = client.get("/api/workspaces/ws-large/files/download", params={"path": "recording.wav"})
    assert r.status_code == 200
    assert r.content == payload


def test_workspace_path_traversal_blocked(client):
    """禁止 path 穿越到 workspace 外"""
    r = client.get(
        "/api/workspaces/ws4/files/download",
        params={"path": "../../../etc/passwd"},
    )
    assert r.status_code == 400


def test_workspace_file_api_rejects_internal_system_paths(client):
    """文件 API 不允许访问 memory、checkpoints 或绝对路径。"""
    for path in ("memory/facts.md", "checkpoints/HEAD.json", "/tmp/secret.txt"):
        r = client.get("/api/workspaces/ws-internal/files/content", params={"path": path})
        assert r.status_code == 400


def test_workspace_id_traversal_blocked(temp_user_data_root):
    """workspace_id 不能逃逸当前用户的 workspaces 根目录。"""
    from fastapi import HTTPException

    from app.api.files import get_workspace_root_path
    from app.core.security import get_current_user

    user = get_current_user()

    with pytest.raises(HTTPException) as exc:
        get_workspace_root_path("..", user=user)

    assert exc.value.status_code == 400


def test_write_workspace_file_tool(temp_user_data_root, monkeypatch):
    """write_workspace_file 写入当前 workspace"""
    from app.api.files import get_workspace_root
    from app.tools import write_workspace_file as write_tool_module
    from app.tools.write_workspace_file import create_write_workspace_file_tool

    class _FakeSandboxService:
        async def write_workspace_text(
            self,
            *,
            user_id,
            session_id,
            workspace_path,
            rel_path,
            content,
        ):
            target = (workspace_path / rel_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    monkeypatch.setattr(write_tool_module, "get_shared_sandbox_service", lambda: _FakeSandboxService())

    tool = create_write_workspace_file_tool("sess-w")
    # 当前工具仅提供异步 coroutine（不支持 sync invoke）
    out = asyncio.run(tool.ainvoke({"path": "written.md", "content": "written content"}))
    assert "已写入" in out
    ws = get_workspace_root("sess-w")
    assert (ws / "written.md").read_text(encoding="utf-8") == "written content"


def test_write_workspace_file_tool_keeps_model_timestamp_path(temp_user_data_root, monkeypatch):
    """write_workspace_file 不再改写模型传入的时间戳路径。"""
    from app.api.files import get_workspace_root
    from app.tools import write_workspace_file as write_tool_module
    from app.tools.write_workspace_file import create_write_workspace_file_tool

    class _FakeSandboxService:
        async def write_workspace_text(
            self,
            *,
            user_id,
            session_id,
            workspace_path,
            rel_path,
            content,
        ):
            target = (workspace_path / rel_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    monkeypatch.setattr(write_tool_module, "get_shared_sandbox_service", lambda: _FakeSandboxService())

    tool = create_write_workspace_file_tool("sess-timestamp")
    out = asyncio.run(
        tool.ainvoke(
            {
                "path": "web-crawler/候选清单-2026082509304500.md",
                "content": "candidate list",
            }
        )
    )

    assert "web-crawler/候选清单-2026082509304500.md" in out
    ws = get_workspace_root("sess-timestamp")
    assert (ws / "web-crawler/候选清单-2026082509304500.md").read_text(encoding="utf-8") == "candidate list"


def test_write_workspace_file_tool_keeps_timestamp_placeholder_path(temp_user_data_root, monkeypatch):
    """write_workspace_file 原样使用 path，不再把 <时间戳> 当作工具层占位符。"""
    from app.api.files import get_workspace_root
    from app.tools import write_workspace_file as write_tool_module
    from app.tools.write_workspace_file import create_write_workspace_file_tool

    class _FakeSandboxService:
        async def write_workspace_text(
            self,
            *,
            user_id,
            session_id,
            workspace_path,
            rel_path,
            content,
        ):
            target = (workspace_path / rel_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    monkeypatch.setattr(write_tool_module, "get_shared_sandbox_service", lambda: _FakeSandboxService())

    tool = create_write_workspace_file_tool("sess-placeholder")
    out = asyncio.run(
        tool.ainvoke(
            {
                "path": "image/配图方案-<时间戳>.md",
                "content": "image plan",
            }
        )
    )

    assert "image/配图方案-<时间戳>.md" in out
    ws = get_workspace_root("sess-placeholder")
    assert (ws / "image/配图方案-<时间戳>.md").read_text(encoding="utf-8") == "image plan"


def test_write_workspace_file_tool_advertises_project_filename_contract():
    from app.tools.write_workspace_file import WriteWorkspaceFileInput, create_write_workspace_file_tool

    tool = create_write_workspace_file_tool("sess-contract")
    path_description = WriteWorkspaceFileInput.model_fields["path"].description or ""

    assert "文件名-当前文件时间戳.扩展名" in path_description
    assert "不替换或校验时间戳" in path_description
    assert "不替换或校验时间戳" in tool.description


def test_write_workspace_file_refuses_implicit_overwrite(temp_user_data_root, monkeypatch):
    """write_workspace_file 默认不覆盖已有文件，避免最终产物被后续摘要误写覆盖。"""
    from app.api.files import get_workspace_root
    from app.tools import write_workspace_file as write_tool_module
    from app.tools.write_workspace_file import create_write_workspace_file_tool

    class _FakeSandboxService:
        async def write_workspace_text(
            self,
            *,
            user_id,
            session_id,
            workspace_path,
            rel_path,
            content,
        ):
            target = (workspace_path / rel_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    monkeypatch.setattr(write_tool_module, "get_shared_sandbox_service", lambda: _FakeSandboxService())

    tool = create_write_workspace_file_tool("sess-no-overwrite")
    out = asyncio.run(tool.ainvoke({"path": "article.md", "content": "full article"}))
    assert "已写入" in out

    overwrite_out = asyncio.run(tool.ainvoke({"path": "article.md", "content": "summary only"}))

    assert "错误：文件已存在" in overwrite_out
    ws = get_workspace_root("sess-no-overwrite")
    assert (ws / "article.md").read_text(encoding="utf-8") == "full article"


def test_write_workspace_file_allows_explicit_overwrite(temp_user_data_root, monkeypatch):
    """调用方明确传 overwrite=true 时仍可覆盖文件。"""
    from app.api.files import get_workspace_root
    from app.tools import write_workspace_file as write_tool_module
    from app.tools.write_workspace_file import create_write_workspace_file_tool

    class _FakeSandboxService:
        async def write_workspace_text(
            self,
            *,
            user_id,
            session_id,
            workspace_path,
            rel_path,
            content,
        ):
            target = (workspace_path / rel_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    monkeypatch.setattr(write_tool_module, "get_shared_sandbox_service", lambda: _FakeSandboxService())

    tool = create_write_workspace_file_tool("sess-explicit-overwrite")
    assert "已写入" in asyncio.run(tool.ainvoke({"path": "article.md", "content": "first"}))

    out = asyncio.run(tool.ainvoke({"path": "article.md", "content": "second", "overwrite": True}))

    assert "已写入" in out
    ws = get_workspace_root("sess-explicit-overwrite")
    assert (ws / "article.md").read_text(encoding="utf-8") == "second"


def test_write_workspace_file_rejects_dsml_tool_call_payload(temp_user_data_root, monkeypatch):
    """write_workspace_file 不应把模型工具调用协议当作正文写入工作区。"""
    from app.api.files import get_workspace_root
    from app.tools import write_workspace_file as write_tool_module
    from app.tools.write_workspace_file import create_write_workspace_file_tool

    class _FakeSandboxService:
        async def write_workspace_text(
            self,
            *,
            user_id,
            session_id,
            workspace_path,
            rel_path,
            content,
        ):
            target = (workspace_path / rel_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    monkeypatch.setattr(write_tool_module, "get_shared_sandbox_service", lambda: _FakeSandboxService())

    payload = (
        "<｜｜DSML｜｜tool_calls>\n"
        '<｜｜DSML｜｜invoke name="write_workspace_file">\n'
        '<｜｜DSML｜｜parameter name="path" string="true">notes/real.md</｜｜DSML｜｜parameter>\n'
        '<｜｜DSML｜｜parameter name="content" string="true"># 正文</｜｜DSML｜｜parameter>\n'
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>"
    )
    tool = create_write_workspace_file_tool("sess-dsml-payload")

    out = asyncio.run(tool.ainvoke({"path": "leaked.md", "content": payload}))

    assert "错误：content 不是可保存的最终正文" in out
    ws = get_workspace_root("sess-dsml-payload")
    assert not (ws / "leaked.md").exists()


def test_read_file_rejects_internal_memory_paths(temp_user_data_root):
    """memory/ 是内部运行态目录，不能通过工作区读取工具暴露。"""
    from app.api.files import get_workspace_root
    from app.tools.read_file import create_read_file_tool

    ws = get_workspace_root("sess-r")
    (ws / "memory").mkdir(parents=True, exist_ok=True)
    (ws / "memory" / "llm_roundtrips.jsonl").write_text('{"secret": true}\n', encoding="utf-8")

    tool = create_read_file_tool("sess-r")
    out = asyncio.run(tool.ainvoke({"path": "memory/llm_roundtrips.jsonl"}))

    assert "内部系统目录" in out
    assert "secret" not in out


def test_workspace_read_tool_is_named_read_workspace_file():
    from app.tools.read_file import create_read_file_tool

    tool = create_read_file_tool("sess-r")

    assert tool.name == "read_workspace_file"


def test_read_file_pseudo_field_error_does_not_teach_raw_tool_stream_fields():
    """read_workspace_file errors must not reintroduce raw stdout/stderr prompt instructions."""
    from app.tools.read_file import create_read_file_tool

    tool = create_read_file_tool("sess-r")
    out = asyncio.run(tool.ainvoke({"path": "stdout"}))

    assert "工具返回字段" in out
    assert "stdout/stderr/returncode" not in out


def test_read_file_reads_current_layout_workspace_relative_path(temp_user_data_root, monkeypatch):
    """read_file 应按当前 sessions/{id}/workspace 布局读取工作区相对路径。"""
    from app.api.files import get_workspace_root
    from app.tools import read_file as read_file_module
    from app.tools.read_file import create_read_file_tool

    class _FakeSandboxService:
        async def read_workspace_text(self, *, workspace_path, rel_path, **_kwargs):
            return (workspace_path / rel_path).read_text(encoding="utf-8")

    ws = get_workspace_root("sess-current-layout")
    target = ws / "web-crawler" / "候选清单-2026070415122700.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("候选清单正文", encoding="utf-8")
    monkeypatch.setattr(read_file_module, "get_shared_sandbox_service", lambda: _FakeSandboxService())

    tool = create_read_file_tool("sess-current-layout")
    out = asyncio.run(tool.ainvoke({"path": "web-crawler/候选清单-2026070415122700.md"}))

    assert out == "候选清单正文"


def test_read_file_missing_path_does_not_search_for_candidates(temp_user_data_root, monkeypatch):
    """read_file 只按调用方给出的工作区相对路径读取；缺失时不再遍历工作区猜路径。"""
    from app.api.files import get_workspace_root
    from app.tools import read_file as read_file_module
    from app.tools.read_file import create_read_file_tool

    class _MissingSandboxService:
        async def read_workspace_text(self, **_kwargs):
            raise FileNotFoundError("missing")

    ws = get_workspace_root("sess-missing")
    (ws / "nested").mkdir(parents=True, exist_ok=True)
    (ws / "nested" / "report.md").write_text("real file", encoding="utf-8")
    monkeypatch.setattr(read_file_module, "get_shared_sandbox_service", lambda: _MissingSandboxService())

    tool = create_read_file_tool("sess-missing")
    out = asyncio.run(tool.ainvoke({"path": "report.md"}))

    assert "错误：文件不存在：report.md" in out
    assert "nested/report.md" not in out
    assert "list_workspace_directory" in out


def test_read_file_allows_script_generated_workspace_outputs(temp_user_data_root):
    """Skill 生成在 workspace/scripts 下的结果文件仍然是工作区文件。"""
    from app.tools.read_file import _workspace_relative_for_session

    rel, err = _workspace_relative_for_session(
        session_id="sess-script-output",
        path="scripts/saved_data/result_20260523_123036/analysis_report.txt",
    )

    assert err is None
    assert rel == "scripts/saved_data/result_20260523_123036/analysis_report.txt"


def test_list_workspace_directory_filters_internal_memory_paths(temp_user_data_root, monkeypatch):
    """memory/ 是内部运行态目录，不进入工作区列表工具结果。"""
    from app.agent import tools_for_skill as tool_module
    from app.agent.session_workspace_policy import sandbox_session_dir
    from app.agent.tools_for_skill import _create_builtin_workspace_tools

    class _FakeSandboxService:
        async def list_workspace_files_flat(
            self,
            *,
            user_id,
            session_id,
            workspace_path,
            rel_prefix="",
            turn_id="workspace-fs",
        ):
            root = sandbox_session_dir(session_id).rstrip("/")
            return [
                {"path": f"{root}/handoff-note.txt", "name": "handoff-note.txt", "size": 5},
                {"path": f"{root}/memory/facts.md", "name": "facts.md", "size": 5},
                {"path": f"{root}/memory/llm_roundtrips.jsonl", "name": "llm_roundtrips.jsonl", "size": 5},
                {"path": f"{root}/memory/orchestrator_audit.jsonl", "name": "orchestrator_audit.jsonl", "size": 5},
            ]

    monkeypatch.setattr(tool_module, "get_shared_sandbox_service", lambda: _FakeSandboxService())
    tools = _create_builtin_workspace_tools("sess-l")
    list_tool = next(t for t in tools if t.name == "list_workspace_directory")

    out = asyncio.run(list_tool.ainvoke({"path": ""}))

    assert "handoff-note.txt" in out
    assert "memory/facts.md" not in out
    assert "llm_roundtrips" not in out
    assert "orchestrator_audit" not in out


def test_rename_workspace_file_recovers_single_timestamped_source(temp_user_data_root, monkeypatch):
    """模型传入猜测时间戳时，rename 可在唯一同前缀文件上恢复。"""
    from app.api.files import get_workspace_root
    from app.agent import tools_for_skill as tool_module
    from app.agent.sandbox_workspace_fs import exec_workspace_shell_on_host, list_workspace_files_on_host
    from app.agent.tools_for_skill import _create_builtin_workspace_tools

    class _FakeSandboxService:
        async def exec_workspace_shell(
            self,
            *,
            session_id,
            workspace_path,
            argv,
            **_kwargs,
        ):
            return exec_workspace_shell_on_host(session_id=session_id, workspace_path=workspace_path, argv=argv)

        async def list_workspace_files_flat(
            self,
            *,
            session_id,
            workspace_path,
            rel_prefix="",
            **_kwargs,
        ):
            return list_workspace_files_on_host(
                session_id=session_id,
                workspace_path=workspace_path,
                rel_prefix=rel_prefix,
            )

    workspace_id = "sess-rename-timestamp"
    ws = get_workspace_root(workspace_id)
    real_file = ws / "image" / "配图方案-2026062602135500.md"
    real_file.parent.mkdir(parents=True, exist_ok=True)
    real_file.write_text("plan", encoding="utf-8")

    monkeypatch.setattr(tool_module, "get_shared_sandbox_service", lambda: _FakeSandboxService())
    tools = _create_builtin_workspace_tools(workspace_id)
    rename_tool = next(t for t in tools if t.name == "rename_workspace_file")

    out = asyncio.run(
        rename_tool.ainvoke(
            {
                "path": "image/配图方案-2026062602140000.md",
                "new_name": "配图方案-最终版.md",
            }
        )
    )

    assert "已重命名文件：image/配图方案-最终版.md" in out
    assert not real_file.exists()
    assert (ws / "image" / "配图方案-最终版.md").read_text(encoding="utf-8") == "plan"


def test_rename_workspace_file_does_not_guess_multiple_timestamped_sources(temp_user_data_root, monkeypatch):
    """同前缀同扩展名有多个候选时，rename 不自动猜源文件。"""
    from app.api.files import get_workspace_root
    from app.agent import tools_for_skill as tool_module
    from app.agent.sandbox_workspace_fs import exec_workspace_shell_on_host, list_workspace_files_on_host
    from app.agent.tools_for_skill import _create_builtin_workspace_tools

    class _FakeSandboxService:
        async def exec_workspace_shell(
            self,
            *,
            session_id,
            workspace_path,
            argv,
            **_kwargs,
        ):
            return exec_workspace_shell_on_host(session_id=session_id, workspace_path=workspace_path, argv=argv)

        async def list_workspace_files_flat(
            self,
            *,
            session_id,
            workspace_path,
            rel_prefix="",
            **_kwargs,
        ):
            return list_workspace_files_on_host(
                session_id=session_id,
                workspace_path=workspace_path,
                rel_prefix=rel_prefix,
            )

    workspace_id = "sess-rename-multiple"
    ws = get_workspace_root(workspace_id)
    first = ws / "image" / "配图方案-2026062602135500.md"
    second = ws / "image" / "配图方案-2026062602135600.md"
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    monkeypatch.setattr(tool_module, "get_shared_sandbox_service", lambda: _FakeSandboxService())
    tools = _create_builtin_workspace_tools(workspace_id)
    rename_tool = next(t for t in tools if t.name == "rename_workspace_file")

    out = asyncio.run(
        rename_tool.ainvoke(
            {
                "path": "image/配图方案-2026062602140000.md",
                "new_name": "配图方案-最终版.md",
            }
        )
    )

    assert "错误：重命名失败" in out
    assert first.read_text(encoding="utf-8") == "first"
    assert second.read_text(encoding="utf-8") == "second"
