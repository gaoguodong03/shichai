from app.agent import sandbox_lifecycle_errors as errors


def test_lifecycle_connect_error_detects_common_transport_failures():
    assert errors.is_lifecycle_connect_error(RuntimeError("OpenSandbox lifecycle API: All connection attempts failed"))
    assert errors.is_lifecycle_connect_error(RuntimeError("ConnectError: connection refused"))


def test_host_path_mount_source_error_requires_mount_source_signal():
    assert errors.is_host_path_mount_source_error(RuntimeError("mount source path /host_mnt/tmp/ws does not exist"))
    assert not errors.is_host_path_mount_source_error(RuntimeError("sandbox not found"))


def test_lifecycle_connect_error_message_mentions_local_and_1panel_guidance():
    message = errors.lifecycle_connect_error_message(RuntimeError("connection refused"))

    assert "OpenSandbox lifecycle API" in message
    assert "1Panel" in message
    assert "本地 conda 调试" in message
