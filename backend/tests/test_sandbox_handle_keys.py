from app.agent.sandbox_adapter import SandboxPolicy, SandboxVolumeMount
from app.agent import sandbox_handle_keys as keys


def test_request_handle_cache_key_isolates_workspace_fs_by_session():
    assert (
        keys.request_handle_cache_key(
            tool_name="__sandbox_workspace_fs__",
            user_id="alice",
            session_id="sess-1",
            session_isolation=False,
        )
        == "alice:workspace:sess-1"
    )


def test_request_handle_cache_key_respects_session_isolation():
    assert keys.request_handle_cache_key(
        tool_name="run_skill_script_demo",
        user_id="alice",
        session_id="sess-1",
        session_isolation=True,
    ) == "alice:sess-1"
    assert keys.request_handle_cache_key(
        tool_name="run_skill_script_demo",
        user_id="alice",
        session_id="sess-1",
        session_isolation=False,
    ) == "alice:sess-1"
    assert keys.request_handle_cache_key(
        tool_name="generic_tool",
        user_id="alice",
        session_id="sess-1",
        session_isolation=False,
    ) == "alice"


def test_policy_mount_fingerprint_changes_with_mount_target():
    left = SandboxPolicy(
        fs_root="/tmp/ws",
        volume_mounts=[SandboxVolumeMount(source="/tmp/ws", target="/workspace", read_only=False)],
    )
    right = SandboxPolicy(
        fs_root="/tmp/ws",
        volume_mounts=[SandboxVolumeMount(source="/tmp/ws", target="/other", read_only=False)],
    )

    assert keys.policy_mount_fingerprint(left) != keys.policy_mount_fingerprint(right)
