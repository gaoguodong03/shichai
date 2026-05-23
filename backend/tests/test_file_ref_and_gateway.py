import asyncio
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

    from app.agent import skill_agent_runtime as runtime

    msgs = [HumanMessage(content="请看【文件引用：快照｜github-weekly-snapshot.md】")]
    assert runtime._extract_path_from_last_user_for_read(msgs) == "github-weekly-snapshot.md"


def test_apply_read_file_replaces_url_with_file_ref_path():
    from langchain_core.messages import HumanMessage

    from app.agent import skill_agent_runtime as runtime

    args = {"path": "//github.com/OpenGithubs/github-weekly-rank/blob/main/2026/04/20260406.md"}
    msgs = [HumanMessage(content="【文件引用：github-weekly-snapshot.md｜github-weekly-snapshot.md】")]
    runtime._apply_read_file_path_from_user_message(args, msgs)
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


def test_parse_cli_args_json_accepts_array():
    from app.tools import run_skill_script as rss

    argv, err = rss._parse_cli_args_json('["--query","河北张家口其他人员住宿标准"]')

    assert err is None
    assert argv == ["--query", "河北张家口其他人员住宿标准"]


def test_parse_cli_args_json_recovers_concatenated_json_strings():
    from app.tools import run_skill_script as rss

    argv, err = rss._parse_cli_args_json('"--query" "河北张家口其他人员住宿标准"')

    assert err is None
    assert argv == ["--query", "河北张家口其他人员住宿标准"]


def test_parse_cli_args_json_recovers_concatenated_json_arrays():
    from app.tools import run_skill_script as rss

    argv, err = rss._parse_cli_args_json('["--query"]["河北张家口其他人员住宿标准"]')

    assert err is None
    assert argv == ["--query", "河北张家口其他人员住宿标准"]


def test_parse_cli_args_json_recovers_embedded_json_array():
    from app.tools import run_skill_script as rss

    argv, err = rss._parse_cli_args_json('cli_args_json: ["--query","广西南宁的差旅标准是什么"]')

    assert err is None
    assert argv == ["--query", "广西南宁的差旅标准是什么"]


def test_requirements_b64_uses_explicit_user_without_context(monkeypatch, tmp_path):
    from app.tools import run_skill_script as rss

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("pendulum==3.0.0\n", encoding="utf-8")

    encoded = rss._current_user_requirements_b64("alice")

    assert encoded
    import base64

    assert base64.b64decode(encoded).decode("utf-8") == "pendulum==3.0.0"


def test_parse_cli_args_json_recovers_comma_separated_json_strings():
    from app.tools import run_skill_script as rss

    argv, err = rss._parse_cli_args_json('"--query", "广西南宁的差旅标准是什么"')

    assert err is None
    assert argv == ["--query", "广西南宁的差旅标准是什么"]


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


def test_run_skill_script_subprocess_executes_shell_script(monkeypatch, tmp_path):
    from app.tools import run_skill_script as rss

    ws_root = tmp_path / "ws"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rss, "_get_workspace_root", lambda _wid: ws_root)

    script_root = tmp_path / "skill" / "scripts"
    script_root.mkdir(parents=True, exist_ok=True)
    script_path = script_root / "probe.sh"
    script_path.write_text("printf 'shell:%s:%s:%s' \"$1\" \"$SKILL_ID\" \"$PWD\"\n", encoding="utf-8")

    out = rss._execute_script_subprocess(
        script_full_path=script_path,
        script_path="probe.sh",
        skill_id="probe-skill",
        workspace_id="sess-probe",
        write_mode="workspace_all",
        input_json="",
        cli_argv=["arg with space"],
        script_root=script_root,
        timeout_sec=10,
    )
    assert out.get("ok") is True
    assert str(out.get("stdout") or "") == f"shell:arg with space:probe-skill:{ws_root}"


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


def test_build_sandbox_exec_request_for_shell_script_uses_bash():
    from app.tools import run_skill_script as rss

    cmd, env, cwd = rss._build_sandbox_exec_request(
        skill_id="demo-skill",
        workspace_id="sess-1",
        script_path="tools/check.sh",
        suffix=".sh",
        cli_argv=["--name", "张 三"],
        input_json="",
    )

    shell = " ".join(cmd)
    assert "/skills/demo-skill/scripts/tools/check.sh" in shell
    assert 'exec bash "$SCRIPT_PATH"' in shell
    assert "--name" in shell
    assert "'张 三'" in shell
    assert env == {}
    assert cwd == "/workspace"


def test_inline_shell_env_embeds_requirements_for_opensandbox_env_drop():
    from app.tools import run_skill_script as rss

    command = ["sh", "-lc", "python3 -c 'print(1)'"]
    out = rss._inline_shell_env(
        command,
        {
            "SKILL_REQUIREMENTS_B64": "eGxyZA==",
            "SKILL_REQUIREMENTS_HASH": "6baab75838f232a5",
        },
    )

    assert out[:2] == ["sh", "-lc"]
    assert "SKILL_REQUIREMENTS_B64=eGxyZA==" in out[2]
    assert "SKILL_REQUIREMENTS_HASH=6baab75838f232a5" in out[2]
    assert "python3 -c" in out[2]


def test_run_skill_script_user_identity_uses_stable_user_id():
    from app.core.user_context import reset_current_user_identity, set_current_user_identity
    from app.tools import run_skill_script as rss

    token = set_current_user_identity(user_id="user-stable-123", username="owner@example.com")
    try:
        assert rss._get_current_user_id() == "user-stable-123"
    finally:
        reset_current_user_identity(token)


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
async def test_execute_mcp_call_direct_does_not_use_sandbox_gateway(monkeypatch):
    from app.mcp.manager import execute_mcp_call

    # 这个开关仍可影响其它工具路径，但 MCP 调用应直接由 MCP manager 执行，
    # 不再借 OpenSandbox gateway 包装远端 MCP 错误。
    monkeypatch.setenv("UNIFIED_TOOL_GATEWAY_ENABLED", "1")

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


@pytest.mark.asyncio
async def test_execute_mcp_call_treats_internal_cancel_as_tool_error(monkeypatch):
    from app.mcp.manager import execute_mcp_call

    monkeypatch.setenv("UNIFIED_TOOL_GATEWAY_ENABLED", "1")

    class _CancelledSession:
        async def call_tool(self, tool_name, kwargs):
            raise asyncio.CancelledError("remote stream ended")

    ok, result, err = await execute_mcp_call(
        server_id="linkup",
        tool_name="search",
        kwargs={"q": "x"},
        session=_CancelledSession(),
        timeout_sec=2.0,
    )
    assert ok is False
    assert result is None
    assert "cancelled" in err.lower()
    assert "sandbox_diag" not in err
    assert "gateway executor" not in err


@pytest.mark.asyncio
async def test_execute_mcp_call_surfaces_empty_runtime_error_without_sandbox_diag(monkeypatch):
    from app.mcp.manager import execute_mcp_call

    monkeypatch.setenv("UNIFIED_TOOL_GATEWAY_ENABLED", "1")

    class _RuntimeErrorSession:
        async def call_tool(self, tool_name, kwargs):
            raise RuntimeError()

    ok, result, err = await execute_mcp_call(
        server_id="mcp-empty",
        tool_name="web_search_exa",
        kwargs={"query": "x"},
        session=_RuntimeErrorSession(),
        timeout_sec=2.0,
    )
    assert ok is False
    assert result is None
    assert "type=RuntimeError" in err
    assert "message=<empty>" in err
    assert "sandbox_diag" not in err
    assert "gateway executor" not in err


@pytest.mark.asyncio
async def test_mcp_tool_reconnects_once_for_empty_runtime_error(monkeypatch):
    from types import SimpleNamespace

    import app.mcp.manager as mcp_manager

    mgr = mcp_manager.MCPToolManager()
    mgr.sessions["mcp-exa"] = "stale-session"
    calls = []
    reconnects = []

    async def _fake_execute_mcp_call(*, server_id, tool_name, kwargs, session, timeout_sec=None):
        calls.append((server_id, tool_name, kwargs, session, timeout_sec))
        if len(calls) == 1:
            return (
                False,
                None,
                "MCP tool call failed: server=mcp-exa tool=web_search_exa "
                "type=RuntimeError message=<empty> repr=RuntimeError()",
            )
        result = SimpleNamespace(content=[SimpleNamespace(text="ok after reconnect")])
        return True, result, ""

    async def _fake_reconnect_server(server_id):
        reconnects.append(server_id)
        mgr.sessions[server_id] = "fresh-session"
        return True

    monkeypatch.setattr(mcp_manager, "execute_mcp_call", _fake_execute_mcp_call)
    monkeypatch.setattr(mgr, "_reconnect_server", _fake_reconnect_server)

    mcp_tool = SimpleNamespace(
        name="web_search_exa",
        description="search",
        inputSchema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    tool = mgr._create_tool_spec(mcp_tool, session="stale-session", server_id="mcp-exa")
    out = await tool.acall(query="pytest")

    assert out == "ok after reconnect"
    assert reconnects == ["mcp-exa"]
    assert calls[0][3] == "stale-session"
    assert calls[1][3] == "fresh-session"


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
