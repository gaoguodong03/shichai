import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
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


def test_file_ref_resolver_injects_content(temp_user_data_root):
    from app.api.files import get_workspace_root_path
    from app.agent.file_ref_resolver import resolve_file_refs_in_text

    ws = get_workspace_root_path("sess-file-ref")
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "memory").mkdir(parents=True, exist_ok=True)
    (ws / "memory" / "facts.md").write_text("hello from memory", encoding="utf-8")

    text = "请参考【文件引用：facts｜memory/facts.md】后继续。"
    out = resolve_file_refs_in_text(text, "sess-file-ref")
    assert "【文件内容已解析】" in out
    assert "[文件: memory/facts.md]" in out
    assert "hello from memory" in out


def test_looks_like_url_or_remote_path():
    from app.agent.read_path_utils import looks_like_url_or_remote_path

    assert looks_like_url_or_remote_path("//github.com/OpenGithubs/x/blob/main/a.md")
    assert looks_like_url_or_remote_path("https://example.com/a.md")
    assert not looks_like_url_or_remote_path("github-weekly-snapshot.md")
    assert not looks_like_url_or_remote_path("memory/facts.md")


def test_extract_path_prefers_file_ref_tag():
    from langchain_core.messages import HumanMessage

    from app.agent import graph as g

    msgs = [HumanMessage(content="请看【文件引用：快照｜github-weekly-snapshot.md】")]
    assert g._extract_path_from_last_user_for_read(msgs) == "github-weekly-snapshot.md"


def test_apply_read_file_replaces_url_with_file_ref_path():
    from langchain_core.messages import HumanMessage

    from app.agent import graph as g

    args = {"path": "//github.com/OpenGithubs/github-weekly-rank/blob/main/2026/04/20260406.md"}
    msgs = [HumanMessage(content="【文件引用：github-weekly-snapshot.md｜github-weekly-snapshot.md】")]
    g._apply_read_file_path_from_user_message(args, msgs)
    assert args.get("path") == "github-weekly-snapshot.md"


def test_file_ref_resolver_blocks_traversal(temp_user_data_root):
    from app.agent.file_ref_resolver import resolve_file_refs_in_text

    text = "bad【文件引用：x｜../../secret.txt】"
    out = resolve_file_refs_in_text(text, "sess-file-ref")
    assert "【文件内容已解析】" in out
    assert "读取失败" in out or "不存在" in out


def test_normalize_skill_script_path_strips_scripts_prefix():
    from app.tools import run_skill_script as rss

    assert rss._normalize_skill_script_path("kb_document_store_cli.py") == "kb_document_store_cli.py"
    assert rss._normalize_skill_script_path("scripts/kb_document_store_cli.py") == "kb_document_store_cli.py"
    assert rss._normalize_skill_script_path(r"scripts\kb_document_store_cli.py") == "kb_document_store_cli.py"
    assert rss._normalize_skill_script_path("./scripts/foo.py") == "foo.py"
    assert rss._apply_script_path_normalization("scripts/__list__") == "__list__"
    assert rss._apply_script_path_normalization("__describe__:scripts/bar.py") == "__describe__:bar.py"


def test_run_skill_script_subprocess_sets_pythonpath(monkeypatch, tmp_path):
    from app.tools import run_skill_script as rss

    ws_root = tmp_path / "ws"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rss, "_get_workspace_root", lambda _wid: ws_root)

    script_root = tmp_path / "skill" / "scripts"
    script_root.mkdir(parents=True, exist_ok=True)
    script_path = script_root / "probe.py"
    script_path.write_text(
        "from app.core.feature_flags import is_feature_enabled\nprint('ok' if callable(is_feature_enabled) else 'bad')\n",
        encoding="utf-8",
    )

    out = rss._execute_script_subprocess(
        script_full_path=script_path,
        script_path="probe.py",
        skill_id="probe-skill",
        workspace_id="sess-probe",
        write_mode="workspace_all",
        input_json="",
        cli_argv=[],
        script_root=script_root,
        timeout_sec=10,
    )
    assert out.get("ok") is True
    assert "ok" in str(out.get("stdout") or "")


def test_build_sandbox_exec_request_uses_full_mount_skill_paths():
    from app.tools import run_skill_script as rss

    cmd, env, cwd = rss._build_sandbox_exec_request(
        skill_id="demo-skill",
        workspace_id="sess-1",
        script_path="tools/check.py",
        suffix=".py",
        cli_argv=["--x", "1"],
        input_json="",
    )
    shell = " ".join(cmd)
    assert "/skills/demo-skill/scripts/tools/check.py" in shell
    assert env == {}
    assert cwd == "/workspace"


def test_filesystem_wrapper_blocks_cross_session_path(monkeypatch, tmp_path):
    from app.tools.filesystem_session_wrapper import _normalize_path_for_session

    # wrapper 要求 agent_outputs 位于 backend 目录内；这里构造一个 backend 下的临时根目录
    backend_root = Path(__file__).resolve().parents[1]
    local_user_root = backend_root / ".tmp-test-user-data"
    local_user_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(local_user_root))
    monkeypatch.setenv("ALLOW_ANONYMOUS_API", "1")

    # 合法路径会被归一化到当前 session 前缀
    ok = _normalize_path_for_session("notes/a.md", "sess-a")
    assert "/workspaces/sess-a/" in ok
    # 越界路径应被拒绝
    import pytest

    with pytest.raises(ValueError):
        _normalize_path_for_session("../sess-b/secrets.txt", "sess-a")


@pytest.mark.asyncio
async def test_execute_mcp_call_via_gateway(temp_user_data_root, monkeypatch):
    from app.mcp.manager import execute_mcp_call
    from app.agent.sandbox_adapter import SandboxHandle
    from app.agent.sandbox_service import SandboxService
    from app.agent.tool_gateway import UnifiedToolGateway
    import app.mcp.manager as mcp_manager

    monkeypatch.setenv("UNIFIED_TOOL_GATEWAY_ENABLED", "1")

    class _FakeAdapter:
        async def create_session_sandbox(self, session_id, policy):
            return SandboxHandle(
                runtime="fake",
                session_id=session_id,
                root=policy.fs_root,
                metadata={"sandbox_id": f"sb-{session_id}", "policy": {"tool_allowlist": list(policy.tool_allowlist), "timeout_ms": policy.timeout_ms}},
            )

        async def run_tool_in_sandbox(self, _handle, tool_request):
            runner = tool_request["runner"]
            return await runner()

        async def read_file(self, _handle, _path):
            return b""

        async def write_file(self, _handle, _path, _data, token_version=0):
            return {"status": "ok", "token_version": token_version}

        async def list_artifacts(self, _handle, task_id=""):
            return []

        async def dispose_sandbox(self, _handle):
            return None

    fake_gateway = UnifiedToolGateway(
        sandbox_service=SandboxService(sandbox_adapter=_FakeAdapter(), session_ttl_sec=3600)
    )
    monkeypatch.setattr(mcp_manager, "_MCP_GATEWAY", fake_gateway)

    class _FakeSession:
        def __init__(self):
            self.calls = 0

        async def call_tool(self, tool_name, kwargs):
            self.calls += 1
            assert tool_name == "echo"
            return {"ok": True, "kwargs": kwargs}

    sess = _FakeSession()
    ok, result, err = await execute_mcp_call(
        server_id="server-a",
        tool_name="echo",
        kwargs={"q": "x"},
        session=sess,
        timeout_sec=2.0,
    )
    assert ok is True
    assert err == ""
    assert result == {"ok": True, "kwargs": {"q": "x"}}
    # 第二次调用不应被上一次 idempotency 结果“粘住”
    ok2, result2, err2 = await execute_mcp_call(
        server_id="server-a",
        tool_name="echo",
        kwargs={"q": "y"},
        session=sess,
        timeout_sec=2.0,
    )
    assert ok2 is True
    assert err2 == ""
    assert result2 == {"ok": True, "kwargs": {"q": "y"}}
    assert sess.calls == 2


@pytest.mark.asyncio
async def test_execute_mcp_call_serializes_same_session(temp_user_data_root, monkeypatch):
    from app.mcp.manager import execute_mcp_call

    monkeypatch.setenv("UNIFIED_TOOL_GATEWAY_ENABLED", "0")

    class _UnsafeSession:
        def __init__(self):
            self.inflight = 0
            self.max_inflight = 0

        async def call_tool(self, tool_name, kwargs):
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
            if self.inflight > 1:
                self.inflight -= 1
                raise RuntimeError("concurrent call_tool not allowed")
            try:
                await asyncio.sleep(0.05)
                return {"ok": True, "tool": tool_name, "kwargs": kwargs}
            finally:
                self.inflight -= 1

    import asyncio

    sess = _UnsafeSession()
    r1, r2 = await asyncio.gather(
        execute_mcp_call(
            server_id="s1",
            tool_name="echo",
            kwargs={"q": "a"},
            session=sess,
            timeout_sec=2.0,
        ),
        execute_mcp_call(
            server_id="s1",
            tool_name="echo",
            kwargs={"q": "b"},
            session=sess,
            timeout_sec=2.0,
        ),
    )

    assert r1[0] is True and r2[0] is True
    assert sess.max_inflight == 1

