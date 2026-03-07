"""测试 workspace 文件 API（按会话隔离、无全局 /api/files）"""
import os
import tempfile

import pytest

# 测试前设置环境变量，使 files 模块使用临时目录
@pytest.fixture(scope="module")
def temp_agent_outputs():
    with tempfile.TemporaryDirectory() as d:
        old = os.environ.get("AGENT_OUTPUTS_DIR")
        os.environ["AGENT_OUTPUTS_DIR"] = d
        try:
            yield d
        finally:
            if old is not None:
                os.environ["AGENT_OUTPUTS_DIR"] = old
            else:
                os.environ.pop("AGENT_OUTPUTS_DIR", None)


@pytest.fixture
def client(temp_agent_outputs):
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
    assert len(entries) == 1
    assert entries[0]["name"] == "hello.md" and entries[0]["path"] == "hello.md"


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


def test_workspace_path_traversal_blocked(client):
    """禁止 path 穿越到 workspace 外"""
    r = client.get(
        "/api/workspaces/ws4/files/download",
        params={"path": "../../../etc/passwd"},
    )
    assert r.status_code in (400, 404)


def test_write_workspace_file_tool(temp_agent_outputs):
    """write_workspace_file 写入当前 workspace"""
    from app.api.files import get_workspace_root
    from app.tools.write_workspace_file import create_write_workspace_file_tool

    tool = create_write_workspace_file_tool("sess-w")
    out = tool.func("written.md", "written content")
    assert "已写入" in out
    ws = get_workspace_root("sess-w")
    assert (ws / "written.md").read_text(encoding="utf-8") == "written content"
