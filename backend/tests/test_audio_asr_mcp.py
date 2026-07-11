from __future__ import annotations

from pathlib import Path

import pytest

from app.mcp.stdio import audio_asr
import json


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


def test_default_transcription_prompt_lives_in_platform_template_file():
    template_path = Path(__file__).resolve().parents[2] / "backend/app/agent/platform_prompt_templates.json"
    template_text = template_path.read_text(encoding="utf-8")
    module_text = Path(audio_asr.__file__).read_text(encoding="utf-8")

    assert "audio_asr.default_transcription.v1" in template_text
    assert "请将这段音频逐字转写为文本。只输出转写内容，不要编造。" not in module_text
    assert "from app.agent.platform_prompts import render_platform_prompt" in module_text
    assert "PLATFORM_PROMPT_TEMPLATES_PATH" not in module_text
    assert "def _platform_prompt_template" not in module_text


def test_request_transcription_uses_template_default_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    audio_file = tmp_path / "clip.wav"
    audio_file.write_bytes(b"wav")
    captured: dict[str, str] = {}

    def fake_multipart(fields, file_path, mime_type):
        captured.update(fields)
        return b"body", "boundary"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"text":"ok"}'

    monkeypatch.setattr(audio_asr, "_multipart_body", fake_multipart)
    monkeypatch.setattr(audio_asr.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    audio_asr._request_transcription(
        audio_path=audio_file,
        api_key="key",
        base_url="http://example.test/v1",
        model="asr",
        language="",
        prompt="",
    )

    assert captured["prompt"] == "请将这段音频逐字转写为文本。只输出转写内容，不要编造。"


def test_transcribe_audio_file_returns_current_stdout_shape_for_errors():
    result = json.loads(audio_asr.transcribe_audio_file("backend/data/users/u/sessions/s/workspace/missing.wav"))

    assert result["execution_status"] == "failed"
    assert "result_code" not in result
    assert "message" not in result
    assert "content" in result
    assert result["artifacts"] == []
    assert result["next_action"] == {
        "handoff": "host",
        "resume": "none",
        "reason": "stage_completed",
        "instruction": result["content"],
    }
