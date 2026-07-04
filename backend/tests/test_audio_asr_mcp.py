from __future__ import annotations

from pathlib import Path

import pytest

from app.mcp.stdio import audio_asr


def test_resolve_data_audio_path_requires_backend_data_prefix(tmp_path: Path):
    data_root = tmp_path / "data"
    audio_file = data_root / "users" / "u1" / "sessions" / "s1" / "workspace" / "meeting.wav"
    audio_file.parent.mkdir(parents=True)
    audio_file.write_bytes(b"wav")

    resolved = audio_asr.resolve_data_audio_path(
        "backend/data/users/u1/sessions/s1/workspace/meeting.wav",
        data_root=data_root,
    )

    assert resolved == audio_file.resolve()

    with pytest.raises(ValueError, match="backend/data"):
        audio_asr.resolve_data_audio_path(
            "users/u1/sessions/s1/workspace/meeting.wav",
            data_root=data_root,
        )


def test_resolve_data_audio_path_rejects_traversal(tmp_path: Path):
    data_root = tmp_path / "data"
    outside = tmp_path / "secret.wav"
    outside.write_bytes(b"secret")

    with pytest.raises(ValueError, match="backend/data"):
        audio_asr.resolve_data_audio_path(
            "backend/data/../secret.wav",
            data_root=data_root,
        )


def test_get_api_key_prefers_audio_specific_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("QWEN_API_KEY", "general-key")
    monkeypatch.setenv("QWEN_AUDIO_API_KEY", "audio-key")

    assert audio_asr.get_api_key() == "audio-key"


def test_get_api_key_requires_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("QWEN_AUDIO_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)

    with pytest.raises(ValueError, match="QWEN_AUDIO_API_KEY"):
        audio_asr.get_api_key()
