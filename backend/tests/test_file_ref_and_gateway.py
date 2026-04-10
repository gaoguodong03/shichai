import os
import tempfile

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


@pytest.mark.asyncio
async def test_execute_mcp_call_via_gateway(temp_user_data_root, monkeypatch):
    from app.mcp.manager import execute_mcp_call

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
    assert sess.calls == 2

