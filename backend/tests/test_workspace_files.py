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
    assert r.status_code in (400, 404)


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


def test_read_file_allows_memory_jsonl_as_regular_workspace_files(temp_user_data_root):
    """废弃诊断 JSONL 不再是平台保留文件，存在时按普通工作区文件读取。"""
    from app.api.files import get_workspace_root
    from app.tools.read_file import create_read_file_tool

    ws = get_workspace_root("sess-r")
    (ws / "memory").mkdir(parents=True, exist_ok=True)
    (ws / "memory" / "llm_roundtrips.jsonl").write_text('{"secret": true}\n', encoding="utf-8")

    tool = create_read_file_tool("sess-r")
    out = asyncio.run(tool.ainvoke({"path": "memory/llm_roundtrips.jsonl"}))

    assert "secret" in out


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


def test_list_workspace_directory_allows_memory_jsonl_as_regular_files(temp_user_data_root, monkeypatch):
    """废弃诊断 JSONL 不再被工具层隐藏。"""
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
                {"path": f"{root}/speaker_task.txt", "name": "speaker_task.txt", "size": 5},
                {"path": f"{root}/memory/facts.md", "name": "facts.md", "size": 5},
                {"path": f"{root}/memory/llm_roundtrips.jsonl", "name": "llm_roundtrips.jsonl", "size": 5},
                {"path": f"{root}/memory/orchestrator_audit.jsonl", "name": "orchestrator_audit.jsonl", "size": 5},
            ]

    monkeypatch.setattr(tool_module, "get_shared_sandbox_service", lambda: _FakeSandboxService())
    tools = _create_builtin_workspace_tools("sess-l")
    list_tool = next(t for t in tools if t.name == "list_workspace_directory")

    out = asyncio.run(list_tool.ainvoke({"path": ""}))

    assert "speaker_task.txt" in out
    assert "memory/facts.md" in out
    assert "llm_roundtrips" in out
    assert "orchestrator_audit" in out
