from app.agent.sandbox_adapter import SandboxHandle, SandboxPolicy, SandboxVolumeMount
from app.agent import sandbox_policy_builder as builder


def test_build_mounts_for_request_uses_user_resources_skills(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path))
    user_root = tmp_path / "alice"
    workspace = user_root / "sessions" / "workspaces" / "sess-1"
    workspace.mkdir(parents=True)
    (user_root / "resources" / "skills").mkdir(parents=True)

    sessions_root, skills_root, mounts = builder.build_mounts_for_request(
        user_id="alice",
        workspace_path=workspace,
    )

    assert sessions_root == user_root / "sessions" / "workspaces"
    assert skills_root == user_root / "resources" / "skills"
    assert (sessions_root / ".st49-mount-ready").is_file()
    assert {m.target for m in mounts} == {"/workspace", "/skills"}


def test_resolve_cwd_falls_back_when_workspace_is_not_mounted():
    policy = SandboxPolicy(fs_root="/tmp/ws", volume_mounts=[])

    assert builder.resolve_cwd(policy, session_id="sess-1", cwd="/workspace/sess-1") == "/"


def test_cached_handle_still_valid_rejects_image_change():
    handle = SandboxHandle(
        session_id="s",
        runtime="docker",
        root="/tmp/ws",
        metadata={
            "mount_fingerprint": "fp",
            "image_ref": "old",
            "policy_allow_network": False,
        },
    )
    policy = SandboxPolicy(
        image_ref="new",
        fs_root="/tmp/ws",
        volume_mounts=[SandboxVolumeMount(source="/tmp/ws", target="/workspace", read_only=False)],
        allow_network=False,
    )
    handle.metadata["mount_fingerprint"] = builder.policy_mount_fingerprint(policy)

    assert builder.cached_handle_still_valid(handle, policy, "tool") is False
