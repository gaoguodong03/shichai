import asyncio
import os
import shutil
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


def test_looks_like_url_or_remote_path():
    from app.agent.read_path_utils import looks_like_url_or_remote_path

    assert looks_like_url_or_remote_path("//github.com/OpenGithubs/x/blob/main/a.md")
    assert looks_like_url_or_remote_path("https://example.com/a.md")
    assert not looks_like_url_or_remote_path("github-weekly-snapshot.md")
    assert not looks_like_url_or_remote_path("memory/facts.md")


def test_normalize_read_file_path_argument_only_cleans_existing_argument():
    from app.agent import skill_agent_paths

    args = {"path": "路径是 memory/facts.md"}
    skill_agent_paths._normalize_read_file_path_argument(args)
    assert args.get("path") == "memory/facts.md"

    missing = {}
    skill_agent_paths._normalize_read_file_path_argument(missing)
    assert missing == {}


def test_apply_audio_asr_path_converts_workspace_file_ref_to_backend_data(monkeypatch, tmp_path):
    from app.agent.messages import HumanMessage

    from app.agent import skill_agent_paths
    from app.api.files import get_workspace_root_path
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-audio", username="audio@example.com")
    try:
        ws = get_workspace_root_path("group-audio")
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "学生降转及研究方向调整.mp3").write_bytes(b"audio")

        args = {"path": "学生降转及研究方向调整.mp3", "language": "zh"}
        msgs = [
            HumanMessage(
                content="请转写【文件引用：学生降转及研究方向调整.mp3｜学生降转及研究方向调整.mp3】"
            )
        ]

        skill_agent_paths._apply_audio_asr_path_from_user_message(args, msgs, "group-audio")
    finally:
        reset_current_user_identity(token)

    assert args["path"] == (
        "backend/data/users/user-audio/sessions/group-audio/workspace/"
        "学生降转及研究方向调整.mp3"
    )


def test_apply_audio_asr_path_does_not_infer_from_user_message_file_ref(monkeypatch, tmp_path):
    from app.agent.messages import HumanMessage

    from app.agent import skill_agent_paths
    from app.api.files import get_workspace_root_path
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-audio", username="audio@example.com")
    try:
        ws = get_workspace_root_path("group-audio")
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "学生降转及研究方向调整.mp3").write_bytes(b"audio")

        args = {"language": "zh"}
        msgs = [
            HumanMessage(
                content="请转写【文件引用：学生降转及研究方向调整.mp3｜学生降转及研究方向调整.mp3】"
            )
        ]

        skill_agent_paths._apply_audio_asr_path_from_user_message(args, msgs, "group-audio")
    finally:
        reset_current_user_identity(token)

    assert args == {"language": "zh"}


def test_apply_image_generation_workspace_id_defaults_to_current_workspace():
    from app.agent import skill_agent_paths

    args = {"description": "河南胡辣汤封面", "workspace_id": ""}

    skill_agent_paths._apply_image_generation_workspace_id(args, "group-image")

    assert args["workspace_id"] == "group-image"


def test_apply_image_generation_workspace_id_preserves_explicit_workspace():
    from app.agent import skill_agent_paths

    args = {"description": "河南胡辣汤封面", "workspace_id": "custom-workspace"}

    skill_agent_paths._apply_image_generation_workspace_id(args, "group-image")

    assert args["workspace_id"] == "custom-workspace"


def test_mcp_stdio_env_includes_stable_user_identity(monkeypatch, tmp_path):
    import app.mcp.manager as mcp_manager

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    monkeypatch.setenv("EXISTING_ENV", "keep")

    env = mcp_manager._build_stdio_child_env(
        username="user-runtime",
        raw_env={"JENIYA_API_KEY": "${vault:image_key}"},
        secrets={"image_key": "sk-test"},
    )

    assert env["EXISTING_ENV"] == "keep"
    assert env["JENIYA_API_KEY"] == "sk-test"
    assert env["ST49_MCP_USER_ID"] == "user-runtime"
    assert env["ST49_MCP_USERNAME"] == "user-runtime"


def test_skill_extra_instructions_prevent_workspace_scheduler_files():
    from app.agent import skill_agent_runtime as runtime
    from app.agent.tool_spec import ToolSpec

    instructions = runtime._skill_execution_extra_instructions(
        [
            ToolSpec(name="read_workspace_file"),
            ToolSpec(name="write_workspace_file"),
        ]
    )

    assert "调度任务由平台通过本轮提示词传入" in instructions
    assert "不要自行读写任何调度状态文件" in instructions
    assert "先基于最近讨论承接，不要自行构造文件名" in instructions
    assert "上一位专家的可见发言在最近讨论中" in instructions
    assert "不限于用户显式要求保存或读取" in instructions
    assert "只有在工具返回写入成功后，才能对用户说文件已保存至工作区" in instructions
    assert "当前文件时间戳" in instructions
    assert "文件名-当前文件时间戳.扩展名" in instructions
    assert "网页采集、资料检索、素材整理" in instructions
    assert "每一条独立素材" in instructions
    assert "分开调用 `write_workspace_file`" in instructions
    assert "memory/" not in instructions
    assert "必须先调用 `write_workspace_file` 新建或覆盖该文件" not in instructions


def test_skill_extra_instructions_tell_audio_asr_to_use_workspace_relative_paths():
    from app.agent import skill_agent_runtime as runtime
    from app.agent.tool_spec import ToolSpec

    instructions = runtime._skill_execution_extra_instructions(
        [
            ToolSpec(name="audio-asr_transcribe_audio_file"),
            ToolSpec(name="list_workspace_directory"),
        ]
    )

    assert "audio-asr_transcribe_audio_file" in instructions
    assert "工作区相对路径" in instructions
    assert "不要要求用户提供 `backend/data/`" in instructions


def test_normalize_skill_script_path_strips_scripts_prefix():
    from app.tools import run_skill_script as rss

    assert rss._normalize_skill_script_path("kb_document_store_cli.py") == "kb_document_store_cli.py"
    assert rss._normalize_skill_script_path("scripts/kb_document_store_cli.py") == "kb_document_store_cli.py"
    assert rss._normalize_skill_script_path(r"scripts\kb_document_store_cli.py") == "kb_document_store_cli.py"
    assert rss._normalize_skill_script_path("./scripts/foo.py") == "foo.py"
    assert rss._apply_script_path_normalization("scripts/__list__") == "__list__"
    assert rss._apply_script_path_normalization("__describe__:scripts/bar.py") == "__describe__:bar.py"


def test_parse_cli_args_accepts_array():
    from app.tools import run_skill_script as rss

    argv, err = rss._parse_cli_args(["--query", "河北张家口其他人员住宿标准"])

    assert err is None
    assert argv == ["--query", "河北张家口其他人员住宿标准"]


def test_parse_cli_args_rejects_legacy_json_string():
    from app.tools import run_skill_script as rss

    argv, err = rss._parse_cli_args('["--query","河北张家口其他人员住宿标准"]')

    assert argv is None
    assert err == "cli_args 必须是数组（每项为字符串，对应 argv 片段）"


def test_manifest_required_fields_validate_cli_args_positionals():
    from app.tools import run_skill_script as rss

    meta = {"input_schema": {"type": "object", "required": ["skill_name"]}}

    assert rss._validate_against_manifest("init_skill.py", meta, {}, ["my-skill"]) is None
    assert (
        rss._validate_against_manifest("init_skill.py", meta, {}, [])
        == "脚本 init_skill.py 缺少必填字段: ['skill_name']"
    )


def test_run_skill_script_tool_description_lists_available_scripts(monkeypatch, tmp_path):
    from app.core.user_context import reset_current_user_identity, set_current_user_identity
    from app.tools.run_skill_script import create_run_skill_script_tool

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-script-desc", username="script@example.com")
    try:
        skill_dir = tmp_path / "users" / "user-script-desc" / "resources" / "skills" / "webv10"
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: Web\n---\nbody\n", encoding="utf-8")
        (scripts_dir / "crawl_and_store.py").write_text("print('ok')\n", encoding="utf-8")
        (scripts_dir / "manifest.json").write_text(
            '{"crawl_and_store.py":{"description":"抓取公开网页"}}',
            encoding="utf-8",
        )

        tool = create_run_skill_script_tool("webv10", "workspace-a", "workspace_all")
    finally:
        reset_current_user_identity(token)

    assert "crawl_and_store.py" in tool.description
    assert "抓取公开网页" in tool.description
    props = tool.args_schema["properties"]
    assert "cli_args" in props
    assert props["cli_args"]["type"] == "array"
    assert set(props) == {"script_path", "cli_args"}


@pytest.mark.asyncio
async def test_build_tools_blocks_call_api_when_declared_mcp_is_unavailable(monkeypatch):
    from app.agent import tools_for_skill
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    class DummyManager:
        server_configs = [{"name": "Exa 搜索"}]

        async def ensure_servers_loaded(self, server_names):
            self.server_names = list(server_names)

        def get_tools(self):
            return []

    monkeypatch.setattr(tools_for_skill, "get_mcp_servers_for_skill", lambda _sid: ["Exa 搜索"])
    monkeypatch.setattr(
        tools_for_skill,
        "load_mcp_config",
        lambda: [
            {
                "name": "Exa 搜索",
                "type": "mcp",
                "transport": {
                    "type": "http",
                    "base_url": "https://mcp.exa.ai/mcp",
                    "headers": {"Authorization": "${vault:exa}"},
                },
            }
        ],
    )
    monkeypatch.setattr(tools_for_skill, "load_api_secret_values", lambda: {})
    monkeypatch.setattr(tools_for_skill, "ensure_user_mcp_config_loaded", lambda _username: DummyManager())
    monkeypatch.setattr(tools_for_skill, "skill_has_skill_md", lambda _sid: False)

    token = set_current_user_identity(user_id="user-mcp-missing", username="mcp-missing@example.com")
    try:
        tools = await tools_for_skill.build_tools_for_group_chat(
            {"skills": [{"directory_name": "webv10"}]},
            "workspace-mcp-missing",
            resolved_skill="webv10",
        )
    finally:
        reset_current_user_identity(token)

    names = {getattr(tool, "name", "") for tool in tools}
    assert "call_api" not in names
    assert "mcp_configuration_status" in names
    diagnostic_tool = next(tool for tool in tools if getattr(tool, "name", "") == "mcp_configuration_status")
    diagnostic = await diagnostic_tool.acall()
    assert "vault:exa" in diagnostic
    assert "Exa 搜索" in diagnostic


@pytest.mark.asyncio
async def test_build_tools_keeps_safe_named_mcp_tools_for_declared_server(monkeypatch):
    from app.agent import tools_for_skill
    from app.agent.tool_spec import ToolSpec
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    class DummyManager:
        server_configs = [{"name": "Exa 搜索"}]

        async def ensure_servers_loaded(self, server_names):
            self.server_names = list(server_names)

        def get_tools(self):
            tool = ToolSpec(name="Exa_web_search_exa_a1b2c3d4", description="search")
            tool.metadata.update({"mcp_server_name": "Exa 搜索", "mcp_tool_name": "web_search_exa"})
            return [tool]

    monkeypatch.setattr(tools_for_skill, "get_mcp_servers_for_skill", lambda _sid: ["Exa 搜索"])
    monkeypatch.setattr(
        tools_for_skill,
        "load_mcp_config",
        lambda: [
            {
                "name": "Exa 搜索",
                "type": "mcp",
                "transport": {
                    "type": "http",
                    "base_url": "https://mcp.exa.ai/mcp",
                    "headers": {"Authorization": "${vault:exa}"},
                },
            }
        ],
    )
    monkeypatch.setattr(tools_for_skill, "load_api_secret_values", lambda: {"exa": "set"})

    async def fake_ensure_user_mcp_config_loaded(_username):
        return DummyManager()

    monkeypatch.setattr(tools_for_skill, "ensure_user_mcp_config_loaded", fake_ensure_user_mcp_config_loaded)
    monkeypatch.setattr(tools_for_skill, "skill_has_skill_md", lambda _sid: False)

    token = set_current_user_identity(user_id="user-mcp-ready", username="mcp-ready@example.com")
    try:
        tools = await tools_for_skill.build_tools_for_group_chat(
            {"skills": [{"directory_name": "webv10"}]},
            "workspace-mcp-ready",
            resolved_skill="webv10",
        )
    finally:
        reset_current_user_identity(token)

    names = {getattr(tool, "name", "") for tool in tools}
    assert "Exa_web_search_exa_a1b2c3d4" in names


@pytest.mark.asyncio
async def test_skill_runtime_normalizes_safe_mcp_tool_using_original_metadata(monkeypatch):
    from app.agent.messages import AIMessage

    from app.agent.skill_agent_runtime import _call_tool_impl
    from app.agent.tool_spec import ToolSpec
    import app.mcp.manager as mcp_manager

    seen = []

    def fake_normalize(server_name, original_tool_name, args, input_schema=None):
        seen.append((server_name, original_tool_name, dict(args), input_schema))
        return {"query": args["__arg1"]}

    async def fake_tool(**kwargs):
        return f"ok:{kwargs['query']}"

    monkeypatch.setattr(mcp_manager, "normalize_mcp_kwargs_for_call", fake_normalize)
    tool = ToolSpec(name="Exa_web_search_exa_a1b2c3d4", coroutine=fake_tool)
    tool.metadata.update({"mcp_server_name": "Exa 搜索", "mcp_tool_name": "web_search_exa"})
    tool._mcp_input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-safe-mcp",
                        "name": "Exa_web_search_exa_a1b2c3d4",
                        "args": {"__arg1": "智能软件工程"},
                    }
                ],
            )
        ],
        "tools": [tool],
    }

    out = await _call_tool_impl(state, [tool])

    assert out.get("messages")
    assert seen[0][0] == "Exa 搜索"
    assert seen[0][1] == "web_search_exa"


def test_requirements_b64_uses_explicit_user_without_context(monkeypatch, tmp_path):
    from app.tools import run_skill_script as rss

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    req_path = user_root / "settings" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("pendulum==3.0.0\n", encoding="utf-8")

    encoded = rss._current_user_requirements_b64("alice")

    assert encoded
    import base64

    assert base64.b64decode(encoded).decode("utf-8") == "pendulum==3.0.0"


async def test_tool_gateway_does_not_retry_sandbox_environment_errors():
    from app.agent.sandbox_service import SandboxEnvironmentError
    from app.agent.tool_gateway import ToolGateway, ToolRequest

    calls = 0

    async def _executor(_payload):
        nonlocal calls
        calls += 1
        raise SandboxEnvironmentError("Docker Desktop File Sharing 未配置")

    gateway = ToolGateway(executor=_executor)
    result = await gateway.execute(
        ToolRequest(
            tool_name="run_skill_script_demo",
            payload={},
            session_id="s1",
            task_id="task",
            turn_id="t1",
            tool_call_id="c1",
            agent_name="专家A",
            directory_name="skill",
            retry_count=2,
        )
    )

    assert calls == 1
    assert result.ok is False
    assert result.retries_used == 0
    assert "Docker Desktop File Sharing" in result.error


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
        directory_name="probe-skill",
        workspace_id="sess-probe",
        write_mode="workspace_all",
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
        directory_name="probe-skill",
        workspace_id="sess-probe",
        write_mode="workspace_all",
        cli_argv=["arg with space"],
        script_root=script_root,
        timeout_sec=10,
    )
    assert out.get("ok") is True
    assert str(out.get("stdout") or "") == f"shell:arg with space:probe-skill:{ws_root}"


def test_build_sandbox_exec_request_uses_full_mount_skill_paths():
    from app.tools import run_skill_script as rss

    cmd, env, cwd = rss._build_sandbox_exec_request(
        directory_name="demo-skill",
        workspace_id="sess-1",
        script_path="tools/check.py",
        suffix=".py",
        cli_argv=["--x", "1"],
    )
    shell = " ".join(cmd)
    assert "/skills/demo-skill/scripts/tools/check.py" in shell
    assert "cd /workspace" in shell
    assert "cd /workspace/sess-1" not in shell
    assert env == {}
    assert cwd == "/workspace"


def test_build_sandbox_exec_request_for_shell_script_uses_bash():
    from app.tools import run_skill_script as rss

    cmd, env, cwd = rss._build_sandbox_exec_request(
        directory_name="demo-skill",
        workspace_id="sess-1",
        script_path="tools/check.sh",
        suffix=".sh",
        cli_argv=["--name", "张 三"],
    )

    shell = " ".join(cmd)
    assert "/skills/demo-skill/scripts/tools/check.sh" in shell
    assert "cd /workspace" in shell
    assert "cd /workspace/sess-1" not in shell
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
    try:
        local_user_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(local_user_root))
        monkeypatch.setenv("ALLOW_ANONYMOUS_API", "1")

        # 合法路径会被归一化到当前 session 前缀
        ok = _normalize_path_for_session("notes/a.md", "sess-a")
        assert "/sessions/sess-a/workspace/" in ok
        # 越界路径应被拒绝
        import pytest

        with pytest.raises(ValueError):
            _normalize_path_for_session("../sess-b/secrets.txt", "sess-a")
    finally:
        shutil.rmtree(local_user_root, ignore_errors=True)


def test_filesystem_wrapper_test_data_is_removed():
    backend_root = Path(__file__).resolve().parents[1]
    assert not (backend_root / ".tmp-test-user-data").exists()


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
        server_name="server-a",
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
        server_name="server-a",
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
        server_name="linkup",
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
        server_name="mcp-empty",
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

    async def _fake_execute_mcp_call(*, server_name, tool_name, kwargs, session, timeout_sec=None):
        calls.append((server_name, tool_name, kwargs, session, timeout_sec))
        if len(calls) == 1:
            return (
                False,
                None,
                "MCP tool call failed: server=mcp-exa tool=web_search_exa "
                "type=RuntimeError message=<empty> repr=RuntimeError()",
            )
        result = SimpleNamespace(content=[SimpleNamespace(text="ok after reconnect")])
        return True, result, ""

    async def _fake_reconnect_server(server_name):
        reconnects.append(server_name)
        mgr.sessions[server_name] = "fresh-session"
        return True

    monkeypatch.setattr(mcp_manager, "execute_mcp_call", _fake_execute_mcp_call)
    monkeypatch.setattr(mgr, "_reconnect_server", _fake_reconnect_server)

    mcp_tool = SimpleNamespace(
        name="web_search_exa",
        description="search",
        inputSchema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    tool = mgr._create_tool_spec(mcp_tool, session="stale-session", server_name="mcp-exa")
    out = await tool.acall(query="pytest")

    assert out == "ok after reconnect"
    assert reconnects == ["mcp-exa"]
    assert calls[0][3] == "stale-session"
    assert calls[1][3] == "fresh-session"


def test_mcp_tool_spec_name_is_model_safe_for_non_ascii_server_name():
    from types import SimpleNamespace
    import re

    import app.mcp.manager as mcp_manager

    mgr = mcp_manager.MCPToolManager()
    mcp_tool = SimpleNamespace(
        name="linkup-search",
        description="search",
        inputSchema={"type": "object", "properties": {"q": {"type": "string"}}},
    )

    tool = mgr._create_tool_spec(mcp_tool, session=object(), server_name="Linkup抓取网页")

    assert re.fullmatch(r"^[a-zA-Z0-9_-]+$", tool.name)
    assert tool.name.startswith("mcp_")
    assert "Linkup抓取网页" not in tool.name
    assert tool.metadata["mcp_server_name"] == "Linkup抓取网页"
    assert tool.metadata["mcp_tool_name"] == "linkup-search"


@pytest.mark.asyncio
async def test_mcp_tool_normalization_error_reports_server_and_tool(monkeypatch):
    from types import SimpleNamespace

    import app.mcp.manager as mcp_manager

    mgr = mcp_manager.MCPToolManager()

    def _raise_normalization_error(*_args, **_kwargs):
        raise ValueError("bad argument shape")

    monkeypatch.setattr(mcp_manager, "normalize_mcp_kwargs_for_call", _raise_normalization_error)

    mcp_tool = SimpleNamespace(
        name="search",
        description="search",
        inputSchema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    tool = mgr._create_tool_spec(mcp_tool, session=object(), server_name="mcp-exa")
    out = await tool.acall(query={"nested": "bad"})

    assert "Error:" in out
    assert "MCP tool argument normalization failed" in out
    assert "server=mcp-exa" in out
    assert "tool=search" in out
    assert "bad argument shape" in out


@pytest.mark.asyncio
async def test_mcp_manager_warns_and_ignores_legacy_enabled_false_when_loading_server(monkeypatch, caplog):
    import app.mcp.manager as mcp_manager

    mgr = mcp_manager.MCPToolManager()
    mgr.server_configs = [
        {
            "name": "Legacy Off",
            "enabled": False,
            "transport": {"type": "stdio", "command": "python"},
        }
    ]
    connected = []

    async def _fake_connect_server(server_name, config):
        connected.append((server_name, config))
        mgr.sessions[server_name] = "session"
        return True

    monkeypatch.setattr(mgr, "connect_server", _fake_connect_server)

    caplog.set_level("WARNING")
    await mgr.ensure_servers_loaded(["Legacy Off"])

    assert connected == [("Legacy Off", mgr.server_configs[0])]
    assert "旧运行字段" in caplog.text


def test_mcp_streamable_http_log_context_redacts_sensitive_endpoint_details():
    from app.mcp.manager import _mcp_connection_log_context

    context = _mcp_connection_log_context(
        "mcp-f0e12d4e",
        {
            "name": "Remote Search",
            "transport": {
                "type": "streamable_http",
                "url": "https://user:secret@example.com/mcp?token=secret-token",
                "headers": {
                    "Authorization": "Bearer secret-token",
                    "X-Trace": "trace-id",
                },
            },
        },
    )

    assert "server_name=mcp-f0e12d4e" in context
    assert "name=Remote Search" in context
    assert "transport=streamable_http" in context
    assert "url=https://example.com/mcp" in context
    assert "headers=Authorization,X-Trace" in context
    assert "secret-token" not in context
    assert "user:secret" not in context


@pytest.mark.asyncio
async def test_mcp_streamable_http_missing_placeholder_fails_before_connect(monkeypatch, caplog):
    import logging

    import app.mcp.manager as mcp_manager

    def _unexpected_streamable_client(*_args, **_kwargs):
        raise AssertionError("streamable_http_client should not be called with missing placeholders")

    monkeypatch.delenv("LINKUP_API_KEY", raising=False)
    monkeypatch.setattr(mcp_manager, "_streamable_http_available", True)
    monkeypatch.setattr(mcp_manager, "streamable_http_client", _unexpected_streamable_client)

    mgr = mcp_manager.MCPToolManager()
    config = {
        "name": "Linkup抓取网页",
        "transport": {
            "type": "http",
            "base_url": "https://mcp.linkup.so/mcp?apiKey=${LINKUP_API_KEY}",
        },
    }

    with caplog.at_level(logging.ERROR, logger="app.mcp.manager"):
        ok = await mgr.connect_server("mcp-f0e12d4e", config)

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert ok is False
    assert "MCP Server HTTP 传输缺少必需变量" in messages
    assert "LINKUP_API_KEY" in messages
    assert "server_name=mcp-f0e12d4e" in messages
    assert "url=https://mcp.linkup.so/mcp" in messages


@pytest.mark.asyncio
async def test_mcp_streamable_http_protocol_error_logs_connection_context(monkeypatch, caplog):
    import logging

    import app.mcp.manager as mcp_manager

    class _AsyncContext:
        def __init__(self, value):
            self.value = value

        async def __aenter__(self):
            return self.value

        async def __aexit__(self, *_args):
            return False

    class _FailingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def initialize(self):
            raise RuntimeError("MCP error -32603: Invalid response format")

    monkeypatch.setattr(mcp_manager, "_streamable_http_available", True)
    monkeypatch.setattr(
        mcp_manager,
        "streamable_http_client",
        lambda *_args, **_kwargs: _AsyncContext((object(), object(), lambda: "session-id")),
    )
    monkeypatch.setattr(mcp_manager, "ClientSession", lambda *_args, **_kwargs: _FailingSession())
    monkeypatch.setenv("MCP_CONNECT_RETRY_COOLDOWN_SEC", "300")

    mgr = mcp_manager.MCPToolManager()
    config = {
        "name": "Remote Search",
        "server_config": (
            '{\n'
            '  "mcpServers": {\n'
            '    "Remote Search": {\n'
            '      "type": "streamable_http",\n'
            '      "url": "https://user:secret@example.com/mcp?token=secret-token",\n'
            '      "headers": {"Authorization": "Bearer secret-token"}\n'
            "    }\n"
            "  }\n"
            "}"
        ),
    }

    with caplog.at_level(logging.WARNING, logger="app.mcp.manager"):
        ok = await mgr.connect_server("mcp-f0e12d4e", config)

    messages = "\n".join(record.getMessage() for record in caplog.records)
    cooldown_messages = [
        record.getMessage() for record in caplog.records if "连接出现协议不兼容" in record.getMessage()
    ]
    assert ok is False
    assert "连接出现协议不兼容" in messages
    assert cooldown_messages
    assert "transport=streamable_http" in cooldown_messages[0]
    assert "transport=stdio" not in cooldown_messages[0]
    assert "server_name=mcp-f0e12d4e" in messages
    assert "name=Remote Search" in messages
    assert "url=https://example.com/mcp" in messages
    assert "secret-token" not in messages
    assert "user:secret" not in messages
    assert mgr._server_retry_not_before["mcp-f0e12d4e"] > 0


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
            server_name="s1",
            tool_name="echo",
            kwargs={"q": "a"},
            session=sess,
            timeout_sec=2.0,
        ),
        execute_mcp_call(
            server_name="s1",
            tool_name="echo",
            kwargs={"q": "b"},
            session=sess,
            timeout_sec=2.0,
        ),
    )

    assert r1[0] is True and r2[0] is True
    assert sess.max_inflight == 1
