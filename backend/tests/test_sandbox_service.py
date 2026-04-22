from __future__ import annotations

from pathlib import Path

from app.agent.sandbox_adapter import SandboxHandle, SandboxPolicy
from app.agent.sandbox_mount_policy import SANDBOX_SKILLS_ROOT, SANDBOX_WORKSPACE_ROOT
from app.agent.sandbox_service import SandboxExecutionRequest, SandboxService


class FakeAdapter:
    def __init__(self):
        self.created = []
        self.disposed = []
        self.last_tool_request = None

    def _host_file(self, handle: SandboxHandle, inner: str) -> Path:
        rel = inner.replace("/workspace", "").lstrip("/") if inner.startswith("/workspace") else inner.lstrip("/")
        return (Path(handle.root) / rel).resolve() if rel else Path(handle.root).resolve()

    async def create_session_sandbox(self, session_id, policy):
        self.created.append((session_id, policy))
        return SandboxHandle(
            runtime="fake",
            session_id=session_id,
            root=policy.fs_root,
            metadata={
                "sandbox_id": f"sb-{session_id}",
                "policy": {"tool_allowlist": list(policy.tool_allowlist), "timeout_ms": policy.timeout_ms},
            },
        )

    async def run_tool_in_sandbox(self, handle, tool_request):
        self.last_tool_request = dict(tool_request or {})
        runner = tool_request["runner"]
        result = await runner()
        result["_sandbox_trace"] = {"sandbox_id": handle.metadata["sandbox_id"]}
        return result

    async def read_file(self, handle, path):
        hp = self._host_file(handle, path)
        if not hp.exists() or hp.is_dir():
            raise FileNotFoundError(str(hp))
        return hp.read_bytes()

    async def write_file(self, handle, path, data, token_version=0):
        hp = self._host_file(handle, path)
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_bytes(data)
        return {"status": "ok"}

    async def list_artifacts(self, handle, task_id=""):
        base = self._host_file(handle, task_id or "/workspace")
        if not base.exists():
            return []
        out = []
        for p in base.rglob("*"):
            if p.is_file():
                out.append({"path": str(p.relative_to(Path(handle.root))).replace("\\", "/"), "size": p.stat().st_size})
        return out

    async def exec_command(self, handle, argv, *, cwd="/workspace", timeout_ms=120_000, env=None):
        if len(argv) >= 3 and argv[0] == "mkdir" and argv[1] == "-p":
            self._host_file(handle, argv[2]).mkdir(parents=True, exist_ok=True)
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if len(argv) == 3 and argv[0] == "mv":
            src = self._host_file(handle, argv[1])
            dst = self._host_file(handle, argv[2])
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if argv and argv[0] == "sh":
            # minimal find for list_workspace_directory tests
            import os

            base = Path(handle.root)
            lines = []
            for r, _dirs, files in os.walk(base):
                for f in files:
                    fp = Path(r) / f
                    rel = str(fp.relative_to(base)).replace("\\", "/")
                    lines.append("./" + rel)
            return {"exit_code": 0, "stdout": "\n".join(sorted(lines)), "stderr": ""}
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    async def dispose_sandbox(self, handle):
        self.disposed.append(handle.session_id)


class FlakyNotFoundAdapter(FakeAdapter):
    def __init__(self):
        super().__init__()
        self._first_run = True

    async def run_tool_in_sandbox(self, handle, tool_request):
        if self._first_run:
            self._first_run = False
            raise RuntimeError(
                f"Kill sandbox {handle.metadata['sandbox_id']} failed: Sandbox {handle.metadata['sandbox_id']} not found."
            )
        return await super().run_tool_in_sandbox(handle, tool_request)


class DisposeNotFoundAdapter(FakeAdapter):
    async def dispose_sandbox(self, handle):
        raise RuntimeError(f"Sandbox {handle.metadata['sandbox_id']} not found")


async def _ok_runner():
    return {"ok": True}


async def test_session_isolation_one_session_one_sandbox():
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)

    req_a1 = SandboxExecutionRequest(
        user_id="u1",
        session_id="s1",
        turn_id="t1",
        tool_call_id="c1",
        tool_name="tool_a",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=Path("."),
    )
    req_b1 = SandboxExecutionRequest(
        user_id="u1",
        session_id="s2",
        turn_id="t1",
        tool_call_id="c2",
        tool_name="tool_b",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=Path("."),
    )
    await svc.execute(req_a1)
    await svc.execute(req_b1)
    await svc.execute(req_a1)

    # 全量挂载模式下：同一用户跨会话、跨工具复用同一个沙箱
    assert len(adapter.created) == 1
    assert adapter.created[0][0] == "u1"


async def test_dispose_session_releases_sandbox():
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    req = SandboxExecutionRequest(
        user_id="u2",
        session_id="s3",
        turn_id="t1",
        tool_call_id="c3",
        tool_name="tool_c",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=Path("."),
    )
    await svc.execute(req)
    await svc.dispose_user("u2", turn_id="t2")
    assert len(adapter.disposed) == 1
    assert adapter.disposed[0] == "u2"


async def test_recreate_when_sandbox_not_found_during_execute():
    adapter = FlakyNotFoundAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    req = SandboxExecutionRequest(
        user_id="u3",
        session_id="s1",
        turn_id="t1",
        tool_call_id="c1",
        tool_name="tool_x",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=Path("."),
    )
    out = await svc.execute(req)
    assert out.get("ok") is True
    assert len(adapter.created) == 2


async def test_ignore_not_found_when_dispose_stale_handle():
    adapter = DisposeNotFoundAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    req1 = SandboxExecutionRequest(
        user_id="u4",
        session_id="s1",
        turn_id="t1",
        tool_call_id="c1",
        tool_name="tool_a",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=Path("."),
    )
    req2 = SandboxExecutionRequest(
        user_id="u4",
        session_id="s1",
        turn_id="t2",
        tool_call_id="c2",
        tool_name="tool_b",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=Path("."),
    )
    await svc.execute(req1)
    out = await svc.execute(req2)
    assert out.get("ok") is True
    assert len(adapter.created) == 1


async def test_always_on_skips_ttl_recycle(monkeypatch):
    monkeypatch.setenv("SANDBOX_ALWAYS_ON", "1")
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=60)
    req = SandboxExecutionRequest(
        user_id="u5",
        session_id="s1",
        turn_id="t1",
        tool_call_id="c1",
        tool_name="tool_a",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=Path("."),
    )
    await svc.execute(req)
    key = "u5"
    handle, _touched = svc._user_handles[key]
    svc._user_handles[key] = (handle, 0.0)
    out = await svc.execute(req)
    assert out.get("ok") is True
    assert len(adapter.created) == 1
    monkeypatch.delenv("SANDBOX_ALWAYS_ON", raising=False)


async def test_fixed_resource_env_applies_to_policy(monkeypatch):
    monkeypatch.setenv("SANDBOX_FIXED_CPU", "2.5")
    monkeypatch.setenv("SANDBOX_FIXED_MEMORY_MB", "2048")
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    req = SandboxExecutionRequest(
        user_id="u6",
        session_id="s1",
        turn_id="t1",
        tool_call_id="c1",
        tool_name="tool_a",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=Path("."),
    )
    await svc.execute(req)
    _sid, policy = adapter.created[0]
    assert float(policy.cpu_limit) == 2.5
    assert int(policy.memory_limit_mb) == 2048
    monkeypatch.delenv("SANDBOX_FIXED_CPU", raising=False)
    monkeypatch.delenv("SANDBOX_FIXED_MEMORY_MB", raising=False)


async def test_prewarm_all_known_users_scans_user_root(monkeypatch, tmp_path):
    (tmp_path / "alice").mkdir(parents=True, exist_ok=True)
    (tmp_path / "bob").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    out = await svc.prewarm_all_known_users(reason="test")
    assert out["users_total"] == 2
    assert out["ok"] == 2
    assert out["failed"] == 0
    assert len(adapter.created) == 2
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_build_policy_mounts_workspace_and_all_skills(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    workspace_root = user_root / "agent-outputs" / "workspaces" / "sess-1"
    workspace_root.mkdir(parents=True, exist_ok=True)
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    req = SandboxExecutionRequest(
        user_id="alice",
        session_id="sess-1",
        turn_id="t1",
        tool_call_id="c1",
        tool_name="run_skill_script_demo",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=workspace_root,
    )
    policy = await svc._build_policy(req)
    targets = {m.target for m in (policy.volume_mounts or [])}
    assert SANDBOX_WORKSPACE_ROOT in targets
    assert SANDBOX_SKILLS_ROOT in targets
    assert policy.skill_scripts_host_path.endswith("/alice/skills")
    assert policy.tool_allowlist == []
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_prewarm_user_sandbox_mounts_all_skills(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    out = await svc.prewarm_user_sandbox("alice", reason="test")
    assert out["status"] == "ok"
    _sid, policy = adapter.created[0]
    targets = {m.target for m in (policy.volume_mounts or [])}
    assert SANDBOX_WORKSPACE_ROOT in targets
    assert SANDBOX_SKILLS_ROOT in targets
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_build_policy_fills_mounts_when_req_policy_missing_them(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    workspace_root = user_root / "agent-outputs" / "workspaces" / "sess-1"
    workspace_root.mkdir(parents=True, exist_ok=True)
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    req = SandboxExecutionRequest(
        user_id="alice",
        session_id="sess-1",
        turn_id="t1",
        tool_call_id="c1",
        tool_name="run_skill_script_demo",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=workspace_root,
        policy=SandboxPolicy(
            fs_root=str(workspace_root),
            timeout_ms=1000,
            tool_allowlist=["run_skill_script_demo"],
        ),
    )
    policy = await svc._build_policy(req)
    targets = {m.target for m in (policy.volume_mounts or [])}
    assert SANDBOX_WORKSPACE_ROOT in targets
    assert SANDBOX_SKILLS_ROOT in targets
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_execute_falls_back_cwd_when_workspace_not_mounted():
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    req = SandboxExecutionRequest(
        user_id="u7",
        session_id="s1",
        turn_id="t1",
        tool_call_id="c1",
        tool_name="tool_a",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=Path("."),
        policy=SandboxPolicy(
            fs_root=".",
            timeout_ms=1000,
            tool_allowlist=["tool_a"],
            volume_mounts=[],
        ),
        cwd="/workspace",
    )
    await svc.execute(req)
    assert adapter.last_tool_request is not None
    assert adapter.last_tool_request.get("cwd") == "/"


async def test_sandbox_events_include_mount_diagnostic_fields(monkeypatch):
    events = []

    def _capture(*, session_id, event_type, payload, turn_id=""):
        events.append((event_type, payload))

    monkeypatch.setattr("app.agent.sandbox_service.append_sandbox_event", _capture)
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    req = SandboxExecutionRequest(
        user_id="u8",
        session_id="s1",
        turn_id="t1",
        tool_call_id="c1",
        tool_name="tool_a",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=Path("."),
    )
    await svc.execute(req)
    created = next(p for e, p in events if e == "sandbox_session_created")
    mounted = next(p for e, p in events if e == "sandbox_mount_applied")
    assert "mount_count" in created
    assert "resource_limit" in created
    assert "mount_targets" in mounted
    assert "mounts_empty" in mounted
