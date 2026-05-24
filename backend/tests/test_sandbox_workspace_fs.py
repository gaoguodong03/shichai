import pytest

from app.agent import sandbox_workspace_fs as fs


def test_workspace_host_file_blocks_parent_escape(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ValueError):
        fs.workspace_host_file(workspace_path=workspace, rel_path="../escape.txt")


def test_workspace_shell_mv_uses_session_scoped_workspace_path(tmp_path):
    workspace = tmp_path / "sessions" / "workspaces" / "sess-1"
    source = workspace / "notes" / "a.txt"
    source.parent.mkdir(parents=True)
    source.write_text("hello", encoding="utf-8")

    result = fs.exec_workspace_shell_on_host(
        session_id="sess-1",
        workspace_path=workspace,
        argv=["mv", "/workspace/sess-1/notes/a.txt", "/workspace/sess-1/archive/a.txt"],
    )

    assert result == {"exit_code": 0, "stdout": "", "stderr": "", "complete": True}
    assert (workspace / "archive" / "a.txt").read_text(encoding="utf-8") == "hello"


def test_workspace_listing_reports_sandbox_session_paths(tmp_path):
    workspace = tmp_path / "sessions" / "workspaces" / "sess-1"
    (workspace / "archive").mkdir(parents=True)
    (workspace / "archive" / "a.txt").write_text("hello", encoding="utf-8")

    items = fs.list_workspace_files_on_host(workspace_path=workspace, session_id="sess-1")

    assert any(item["path"] == "/workspace/sess-1/archive/a.txt" for item in items)
