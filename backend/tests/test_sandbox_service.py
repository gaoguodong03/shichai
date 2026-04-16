from __future__ import annotations

from pathlib import Path

from app.agent.sandbox_adapter import SandboxHandle
from app.agent.sandbox_service import SandboxExecutionRequest, SandboxService


class FakeAdapter:
    def __init__(self):
        self.created = []
        self.disposed = []

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

    assert len(adapter.created) == 1
    assert adapter.created[0][0].startswith("u1:")


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
    assert adapter.disposed[0].startswith("u2:")
