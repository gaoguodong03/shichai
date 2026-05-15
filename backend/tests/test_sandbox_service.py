from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.agent.sandbox_adapter import OpenSandboxAdapter, SandboxHandle, SandboxPolicy
from app.agent.sandbox_image_policy import configured_sandbox_images
from app.agent.sandbox_mount_policy import SANDBOX_SKILLS_ROOT, SANDBOX_WORKSPACE_ROOT
from app.agent.sandbox_service import SandboxExecutionRequest, SandboxService


class FakeAdapter:
    def __init__(self):
        self.created = []
        self.disposed = []
        self.exec_commands = []
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
        self.exec_commands.append({"argv": list(argv or []), "cwd": cwd, "timeout_ms": timeout_ms, "env": dict(env or {})})
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
            command_text = " ".join(str(x) for x in (argv or []))
            if "requirements install received empty requirements payload" in command_text:
                return {
                    "exit_code": 0,
                    "stdout": "requirements_verify_start\nrequirements_verify_end",
                    "stderr": "",
                    "complete": True,
                }
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


class CleanupAdapter(FakeAdapter):
    def __init__(self):
        super().__init__()
        self.cleanup_calls = []

    async def cleanup_orphan_sandboxes(self, **kwargs):
        self.cleanup_calls.append(dict(kwargs))
        return {
            "scanned": 2,
            "deleted": ["old-sandbox"],
            "failed": [],
            "skipped_active": len(kwargs.get("active_sandbox_ids") or []),
            "skipped_young": 0,
            "skipped_unmanaged": 0,
        }


class MissingPackageAfterMetadataHitAdapter(FakeAdapter):
    async def exec_command(self, handle, argv, *, cwd="/workspace", timeout_ms=120_000, env=None):
        self.exec_commands.append({"argv": list(argv or []), "cwd": cwd, "timeout_ms": timeout_ms, "env": dict(env or {})})
        command_text = " ".join(str(x) for x in (argv or []))
        if "SANDBOX_REQUIREMENTS_TEXT" in dict(env or {}):
            return {
                "exit_code": 1,
                "stdout": "requirements_verify_start\nrequirements_verify_end",
                "stderr": "missing packages after metadata hit: xlrd",
            }
        if "SANDBOX_REQUIREMENTS_B64" in dict(env or {}):
            return {
                "exit_code": 0,
                "stdout": "requirements_verify_start\nimport_ok:xlrd\nxlrd==2.0.2\nrequirements_verify_end",
                "stderr": "",
            }
        if "requirements_verify_start" in command_text:
            return {
                "exit_code": 1,
                "stdout": "requirements_verify_start\nrequirements_verify_end",
                "stderr": "missing packages after metadata hit: xlrd",
            }
        return await super().exec_command(handle, argv, cwd=cwd, timeout_ms=timeout_ms, env=env)


class EnvDroppingAdapter(FakeAdapter):
    async def exec_command(self, handle, argv, *, cwd="/workspace", timeout_ms=120_000, env=None):
        self.exec_commands.append({"argv": list(argv or []), "cwd": cwd, "timeout_ms": timeout_ms, "env": dict(env or {})})
        command_text = " ".join(str(x) for x in (argv or []))
        if "requirements install received empty requirements payload" in command_text:
            if "SANDBOX_REQUIREMENTS_B64=" not in command_text:
                return {"exit_code": 1, "stdout": "wrote_requirements_bytes 0", "stderr": "empty env"}
            return {
                "exit_code": 0,
                "stdout": "wrote_requirements_bytes 5\nrequirements_verify_start\nimport_ok:xlrd\nxlrd==2.0.2\nrequirements_verify_end",
                "stderr": "",
            }
        if "requirements verify received empty requirements text" in command_text:
            if "SANDBOX_REQUIREMENTS_TEXT=" not in command_text:
                return {"exit_code": 1, "stdout": "", "stderr": "empty env"}
            return {
                "exit_code": 0,
                "stdout": "requirements_verify_start\nimport_ok:xlrd\nxlrd==2.0.2\nrequirements_verify_end",
                "stderr": "",
            }
        return await super().exec_command(handle, argv, cwd=cwd, timeout_ms=timeout_ms, env={})


class IncompleteRequirementsAdapter(FakeAdapter):
    async def exec_command(self, handle, argv, *, cwd="/workspace", timeout_ms=120_000, env=None):
        self.exec_commands.append({"argv": list(argv or []), "cwd": cwd, "timeout_ms": timeout_ms, "env": dict(env or {})})
        if "SANDBOX_REQUIREMENTS_B64" in dict(env or {}):
            return {
                "exit_code": None,
                "complete": False,
                "stdout": "Downloading openai-2.36.0-py3-none-any.whl",
                "stderr": "",
            }
        return await super().exec_command(handle, argv, cwd=cwd, timeout_ms=timeout_ms, env=env)


async def _ok_runner():
    return {"ok": True}


async def test_session_isolation_one_session_one_sandbox(monkeypatch):
    monkeypatch.setenv("SANDBOX_SESSION_ISOLATION", "1")
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

    # 会话级隔离：同一用户的不同会话互不影响，同一会话内继续复用。
    assert len(adapter.created) == 2
    assert adapter.created[0][0] == "u1:s1"
    assert adapter.created[1][0] == "u1:s2"


async def test_dispose_session_releases_sandbox(monkeypatch):
    monkeypatch.setenv("SANDBOX_SESSION_ISOLATION", "1")
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
    await svc.dispose_session("s3", turn_id="t2")
    assert len(adapter.disposed) == 1
    assert adapter.disposed[0] == "u2:s3"


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
    assert policy.image_ref.endswith("-standard")
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_prewarm_reads_saved_playwright_variant(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    settings_path = user_root / "config" / "sandbox" / "sandbox" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text('{"image_variant": "playwright"}\n', encoding="utf-8")
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)

    await svc.prewarm_user_sandbox("alice", reason="test")

    _sid, policy = adapter.created[0]
    assert policy.image_ref.endswith("-playwright")
    assert policy.environment["SANDBOX_IMAGE_VARIANT"] == "playwright"
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_prewarm_infers_playwright_from_browser_requirements(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("playwright>=1.52.0\npatchright>=1.52.5\n", encoding="utf-8")
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)

    await svc.prewarm_user_sandbox("alice", reason="test")

    settings_path = user_root / "config" / "sandbox" / "sandbox" / "settings.json"
    assert not settings_path.exists()
    _sid, policy = adapter.created[0]
    assert policy.image_ref.endswith("-playwright")
    assert policy.environment["SANDBOX_IMAGE_VARIANT"] == "playwright"
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


def test_configured_sandbox_images_ignore_blank_env(monkeypatch):
    monkeypatch.setenv("SANDBOX_STANDARD_IMAGE", "   ")
    monkeypatch.setenv("SANDBOX_PLAYWRIGHT_IMAGE", "   ")

    images = configured_sandbox_images()

    assert images["standard"].endswith("-standard")
    assert images["playwright"].endswith("-playwright")
    monkeypatch.delenv("SANDBOX_STANDARD_IMAGE", raising=False)
    monkeypatch.delenv("SANDBOX_PLAYWRIGHT_IMAGE", raising=False)


def test_opensandbox_spec_marks_st49_metadata():
    policy = SandboxPolicy(fs_root="/tmp/workspace", image_ref="example/sandbox:tag")

    spec = OpenSandboxAdapter._spec_from_policy(session_id="alice", policy=policy)

    assert spec["metadata"]["managed_by"] == "st49"
    assert spec["metadata"]["app"] == "shichai"
    assert spec["metadata"]["session_id"] == "alice"


def test_opensandbox_spec_sanitizes_email_session_metadata():
    policy = SandboxPolicy(fs_root="/tmp/workspace", image_ref="example/sandbox:tag")

    spec = OpenSandboxAdapter._spec_from_policy(session_id="wzr@bupt.edu.cn", policy=policy)

    assert spec["metadata"]["session_id"] == "wzr_bupt.edu.cn"
    assert "@" not in spec["metadata"]["session_id"]


def test_opensandbox_metadata_value_is_label_safe_and_short():
    raw = "用户:" + ("a" * 100) + "@example.com"

    value = OpenSandboxAdapter._opensandbox_metadata_value(raw)

    assert len(value) <= 63
    assert value[0].isalnum()
    assert value[-1].isalnum()
    assert all(ch.isalnum() or ch in {"-", "_", "."} for ch in value)


async def test_startup_orphan_cleanup_passes_active_ids_and_known_images(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SANDBOX_ORPHAN_CLEANUP_MIN_AGE_SEC", "120")
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    adapter = CleanupAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    await svc.prewarm_user_sandbox("alice", reason="test")

    result = await svc.cleanup_orphan_sandboxes_on_startup()

    assert result["enabled"] is True
    assert result["deleted"] == ["old-sandbox"]
    call = adapter.cleanup_calls[-1]
    assert call["active_sandbox_ids"] == {"sb-alice"}
    assert call["min_age_sec"] == 120
    assert call["include_legacy_image_match"] is True
    assert any(str(image).endswith("-standard") for image in call["known_images"])
    assert any(str(image).endswith("-playwright") for image in call["known_images"])
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)
    monkeypatch.delenv("SANDBOX_ORPHAN_CLEANUP_MIN_AGE_SEC", raising=False)


async def test_user_context_creates_default_sandbox_requirements(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    from app.core.user_context import get_user_context_for

    ctx = get_user_context_for("alice")
    req_path = ctx.config_dir / "sandbox" / "requirements.txt"
    content = req_path.read_text(encoding="utf-8")
    assert "pandas" in content
    assert "openpyxl" in content
    assert "xlrd" in content
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_default_sandbox_requirements_hash_regression(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    from app.core.user_context import get_user_context_for

    ctx = get_user_context_for("alice")
    content = (ctx.config_dir / "sandbox" / "requirements.txt").read_text(encoding="utf-8").strip()
    assert hashlib.sha256(content.encode("utf-8")).hexdigest()[:16] == "5817ace3254dfe26"
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_prewarm_installs_user_requirements_with_network(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("xlrd\n", encoding="utf-8")
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    await svc.prewarm_user_sandbox("alice", reason="requirements_saved")
    _sid, policy = adapter.created[0]
    assert policy.allow_network is True
    assert any("SANDBOX_REQUIREMENTS_B64" in cmd["env"] for cmd in adapter.exec_commands)
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_playwright_variant_does_not_install_browsers_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    settings_path = user_root / "config" / "sandbox" / "sandbox" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text('{"image_variant": "playwright"}\n', encoding="utf-8")
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("patchright>=1.52.5\n", encoding="utf-8")
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)

    await svc.prewarm_user_sandbox("alice", reason="requirements_saved")

    install_command = next(
        " ".join(cmd["argv"])
        for cmd in adapter.exec_commands
        if "SANDBOX_REQUIREMENTS_B64" in " ".join(cmd["argv"])
    )
    assert "browser_install_start" in install_command
    assert 'if [ "${SANDBOX_AUTO_INSTALL_BROWSERS:-0}" = "1" ]' in install_command
    assert '|| [ "${SANDBOX_IMAGE_VARIANT:-}" = "playwright" ]' not in install_command
    assert "--upgrade -r /tmp/requirements.txt" not in install_command
    install_env = next(
        cmd["env"]
        for cmd in adapter.exec_commands
        if "SANDBOX_REQUIREMENTS_B64" in " ".join(cmd["argv"])
    )
    assert install_env["SANDBOX_IMAGE_VARIANT"] == "playwright"
    assert install_env.get("SANDBOX_AUTO_INSTALL_BROWSERS") != "1"
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_requirements_install_survives_command_env_drop(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("xlrd\n", encoding="utf-8")
    dep_hash = hashlib.sha256("xlrd".encode("utf-8")).hexdigest()[:16]
    adapter = EnvDroppingAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)

    await svc.prewarm_user_sandbox("alice", reason="requirements_saved")

    current_handle, _ = svc._user_handles["alice"]
    assert current_handle.metadata.get("verified_requirements_hash") == dep_hash
    install_commands = [" ".join(cmd["argv"]) for cmd in adapter.exec_commands]
    assert any("SANDBOX_REQUIREMENTS_B64=" in command for command in install_commands)
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_incomplete_requirements_install_does_not_mark_verified(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("xlrd\n", encoding="utf-8")
    adapter = IncompleteRequirementsAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)

    with pytest.raises(RuntimeError, match="requirements 安装未完成"):
        await svc.prewarm_user_sandbox("alice", reason="requirements_saved")

    handle, _ = svc._user_handles["alice"]
    assert not handle.metadata.get("installed_requirements_hash")
    assert not handle.metadata.get("verified_requirements_hash")
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_execute_injects_user_requirements_env_when_payload_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("pendulum==3.0.0\n", encoding="utf-8")
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    req = SandboxExecutionRequest(
        user_id="alice",
        session_id="s1",
        turn_id="t1",
        tool_call_id="c1",
        tool_name="run_skill_script_demo",
        tool_kind="script",
        payload={"__sandbox_command": ["sh", "-lc", "true"], "__sandbox_env": {}},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=tmp_path / "alice" / "agent-outputs" / "workspaces" / "s1",
    )

    await svc.execute(req)

    env = adapter.last_tool_request.get("env") or {}
    assert env.get("SKILL_REQUIREMENTS_B64")
    import base64

    assert base64.b64decode(env["SKILL_REQUIREMENTS_B64"]).decode("utf-8") == "pendulum==3.0.0"
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_unverified_requirements_hash_reinstalls(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("xlrd\n", encoding="utf-8")
    dep_hash = hashlib.sha256("xlrd".encode("utf-8")).hexdigest()[:16]
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    await svc.prewarm_user_sandbox("alice", reason="requirements_saved")
    handle, touched = svc._user_handles["alice"]
    handle.metadata.pop("verified_requirements_hash", None)
    handle.metadata["installed_requirements_hash"] = dep_hash
    svc._user_handles["alice"] = (handle, touched)
    before = len(adapter.exec_commands)
    await svc.prewarm_user_sandbox("alice", reason="requirements_saved")
    assert len(adapter.exec_commands) > before
    current_handle, _ = svc._user_handles["alice"]
    assert current_handle.metadata.get("verified_requirements_hash") == dep_hash
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_metadata_hit_but_real_import_missing_reinstalls(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("xlrd\n", encoding="utf-8")
    dep_hash = hashlib.sha256("xlrd".encode("utf-8")).hexdigest()[:16]
    adapter = MissingPackageAfterMetadataHitAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)

    await svc.prewarm_user_sandbox("alice", reason="requirements_saved")
    handle, touched = svc._user_handles["alice"]
    handle.metadata["installed_requirements_hash"] = dep_hash
    handle.metadata["verified_requirements_hash"] = dep_hash
    handle.metadata["requirements_verifier_version"] = "import-v2"
    handle.metadata["requirements_real_verified_at"] = 1
    svc._user_handles["alice"] = (handle, touched)

    before = len(adapter.exec_commands)
    await svc.prewarm_user_sandbox("alice", reason="requirements_saved")
    after_commands = adapter.exec_commands[before:]

    assert any("SANDBOX_REQUIREMENTS_TEXT" in cmd["env"] for cmd in after_commands)
    assert any("SANDBOX_REQUIREMENTS_B64" in cmd["env"] for cmd in after_commands)
    current_handle, _ = svc._user_handles["alice"]
    assert current_handle.metadata.get("verified_requirements_hash") == dep_hash
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_fresh_prewarm_skips_repeated_real_requirements_verify(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("xlrd\n", encoding="utf-8")
    adapter = MissingPackageAfterMetadataHitAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)

    await svc.prewarm_user_sandbox("alice", reason="login")
    before = len(adapter.exec_commands)
    await svc.prewarm_user_sandbox("alice", reason="hot_request")
    after_commands = adapter.exec_commands[before:]

    assert after_commands
    assert not any("SANDBOX_REQUIREMENTS_TEXT" in cmd["env"] for cmd in after_commands)
    assert not any("SANDBOX_REQUIREMENTS_B64" in cmd["env"] for cmd in after_commands)
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)


async def test_prewarm_policy_reused_by_session_script_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SANDBOX_NETWORK_TOOL_ALLOWLIST", "run_skill_script")
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("xlrd\n", encoding="utf-8")
    workspace_root = user_root / "agent-outputs" / "workspaces" / "sess-1"
    workspace_root.mkdir(parents=True, exist_ok=True)
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)

    await svc.prewarm_user_sandbox("alice", reason="request")
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
            fs_root=str(workspace_root.resolve()),
            timeout_ms=1000,
            tool_allowlist=["run_skill_script_demo"],
        ),
    )
    await svc.execute(req)

    assert len(adapter.created) == 1
    assert adapter.created[0][0] == "alice"
    assert adapter.disposed == []
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)
    monkeypatch.delenv("SANDBOX_NETWORK_TOOL_ALLOWLIST", raising=False)


async def test_workspace_fs_does_not_replace_user_skill_sandbox(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SANDBOX_NETWORK_TOOL_ALLOWLIST", "run_skill_script")
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    req_path = user_root / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text("xlrd\n", encoding="utf-8")
    workspace_root = user_root / "agent-outputs" / "workspaces" / "sess-1"
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "note.txt").write_text("hello", encoding="utf-8")
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)

    await svc.prewarm_user_sandbox("alice", reason="request")
    install_count_after_prewarm = len(adapter.exec_commands)
    items = await svc.list_workspace_files_flat(
        user_id="alice",
        session_id="sess-1",
        workspace_path=workspace_root,
    )

    assert any(str(item.get("path") or "").endswith("note.txt") for item in items)
    assert len(adapter.created) == 2
    assert adapter.created[0][0] == "alice"
    assert adapter.created[1][0] == "alice:workspace:sess-1"
    assert adapter.disposed == []
    assert len(adapter.exec_commands) == install_count_after_prewarm

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
            fs_root=str(workspace_root.resolve()),
            timeout_ms=1000,
            tool_allowlist=["run_skill_script_demo"],
        ),
    )
    await svc.execute(req)

    assert len(adapter.created) == 2
    assert adapter.disposed == []
    monkeypatch.delenv("SHUTONG_USER_DATA_ROOT", raising=False)
    monkeypatch.delenv("SANDBOX_NETWORK_TOOL_ALLOWLIST", raising=False)


async def test_cached_user_sandbox_recreated_when_network_policy_changes(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    (user_root / "skills").mkdir(parents=True, exist_ok=True)
    workspace_root = user_root / "agent-outputs" / "workspaces" / "sess-1"
    workspace_root.mkdir(parents=True, exist_ok=True)
    adapter = FakeAdapter()
    svc = SandboxService(sandbox_adapter=adapter, session_ttl_sec=3600)
    base = SandboxExecutionRequest(
        user_id="alice",
        session_id="sess-1",
        turn_id="t1",
        tool_call_id="c1",
        tool_name="tool_a",
        tool_kind="script",
        payload={},
        timeout_ms=1000,
        runner=_ok_runner,
        workspace_path=workspace_root,
        policy=SandboxPolicy(
            fs_root=str(workspace_root),
            timeout_ms=1000,
            allow_network=False,
        ),
    )
    await svc.execute(base)
    with_network = SandboxExecutionRequest(
        **{**base.__dict__, "tool_call_id": "c2", "policy": SandboxPolicy(
            fs_root=str(workspace_root),
            timeout_ms=1000,
            allow_network=True,
        )}
    )
    await svc.execute(with_network)
    assert len(adapter.created) == 2
    assert adapter.created[0][1].allow_network is False
    assert adapter.created[1][1].allow_network is True
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


async def test_execute_uses_workspace_cwd_after_policy_fills_mounts():
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
    assert adapter.last_tool_request.get("cwd") == "/workspace"


def test_resolve_cwd_falls_back_when_workspace_not_mounted():
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
    policy = req.policy
    assert policy is not None
    assert SandboxService._resolve_cwd(policy, req) == "/"


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
