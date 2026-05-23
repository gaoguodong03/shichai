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
    """workspace 内创建文件后能列出"""
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
            tool_call_id,
            turn_id="workspace-fs",
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


def test_read_file_hides_internal_diagnostic_memory_files(temp_user_data_root):
    """read_file 不应把内部排障 JSONL 暴露给专家。"""
    from app.api.files import get_workspace_root
    from app.tools.read_file import create_read_file_tool

    ws = get_workspace_root("sess-r")
    (ws / "memory").mkdir(parents=True, exist_ok=True)
    (ws / "memory" / "llm_roundtrips.jsonl").write_text('{"secret": true}\n', encoding="utf-8")

    tool = create_read_file_tool("sess-r")
    out = asyncio.run(tool.ainvoke({"path": "memory/llm_roundtrips.jsonl"}))

    assert "内部排障日志" in out
    assert "secret" not in out


def test_list_workspace_directory_hides_internal_diagnostic_memory_files(temp_user_data_root, monkeypatch):
    """list_workspace_directory 只暴露用户/任务可用文件，不列出内部 JSONL 日志。"""
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
    assert "llm_roundtrips" not in out
    assert "orchestrator_audit" not in out
