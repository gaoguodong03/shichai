#!/usr/bin/env python3
"""Audio transcription MCP server.

Local stdio MCP for transcribing audio files under ``backend/data``. API keys are
provided through stdio transport env, typically ``QWEN_AUDIO_API_KEY=${vault:id}``.
"""
from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

BACKEND_DIR = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = BACKEND_DIR / "data"
DEFAULT_BASE_URL = "http://10.129.50.230/v1"
DEFAULT_MODEL = "qwen3-asr-1.7b"
DEFAULT_CHUNK_SECONDS = 120
SUPPORTED_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".amr"}

mcp = FastMCP("Audio ASR")
logger = logging.getLogger(__name__)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _tool_result(
    *,
    execution_status: str,
    content: str,
    artifacts: list[dict[str, Any]] | None = None,
    agent_turn: str = "respond",
    skill_session: str = "release",
) -> str:
    return _json(
        {
            "execution_status": execution_status,
            "content": content,
            "artifacts": artifacts or [],
            "next_action": {
                "agent_turn": agent_turn,
                "skill_session": skill_session,
            },
        }
    )


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_data_audio_path(path: str, *, data_root: Path = DEFAULT_DATA_ROOT) -> Path:
    """Resolve a ``backend/data/...`` audio path under the configured data root."""
    cleaned = (path or "").strip().replace("\\", "/")
    prefix = "backend/data/"
    if not cleaned.startswith(prefix):
        raise ValueError("path 必须使用 backend/data/... 完整数据路径。")
    rel = cleaned[len(prefix) :].lstrip("/")
    if not rel or "\x00" in rel:
        raise ValueError("path 必须指向 backend/data 下的音频文件。")

    root = data_root.resolve()
    target = (root / rel).resolve()
    if not _is_under(target, root):
        raise ValueError("path 必须位于 backend/data 目录内。")
    if target.suffix.lower() not in SUPPORTED_EXTS:
        raise ValueError(f"不支持的音频格式：{target.suffix}")
    if not target.is_file():
        raise FileNotFoundError(f"音频文件不存在：{path}")
    return target


def get_api_key() -> str:
    key = (os.getenv("QWEN_AUDIO_API_KEY") or os.getenv("QWEN_API_KEY") or "").strip()
    if not key:
        raise ValueError("未配置 QWEN_AUDIO_API_KEY 或 QWEN_API_KEY。请在 MCP transport.env 中选择密钥。")
    return key


def _request_timeout() -> float | None:
    raw = (os.getenv("QWEN_AUDIO_REQUEST_TIMEOUT_SEC") or "0").strip()
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 0
    return seconds if seconds > 0 else None


def _multipart_body(fields: dict[str, str], file_path: Path, mime_type: str) -> tuple[bytes, str]:
    boundary = "----audio-asr-" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        if value == "":
            continue
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode("utf-8"),
            f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), boundary


def _request_transcription(
    *,
    audio_path: Path,
    api_key: str,
    base_url: str,
    model: str,
    language: str,
    prompt: str,
) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    body_bytes, boundary = _multipart_body(
        {
            "model": model,
            "language": language.strip(),
            "prompt": prompt.strip() or "请将这段音频逐字转写为文本。只输出转写内容，不要编造。",
        },
        audio_path,
        mime_type,
    )
    req = urllib.request.Request(
        base_url.rstrip("/") + "/audio/transcriptions",
        data=body_bytes,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_request_timeout()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"上游 ASR HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"上游 ASR 请求失败: {exc.reason}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"上游 ASR 返回非 JSON: {raw[:1000]}") from exc
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _extract_text(data: dict[str, Any]) -> str:
    for key in ("text", "transcript", "content"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content.strip()
                if isinstance(content, list):
                    parts = [str(item.get("text", "")).strip() for item in content if isinstance(item, dict)]
                    return "\n".join(part for part in parts if part)
            text = first.get("text")
            if isinstance(text, str):
                return text.strip()
    return ""


def _split_audio(audio_path: Path, *, chunk_seconds: int, temp_dir: Path) -> list[Path]:
    if chunk_seconds <= 0:
        return [audio_path]
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return [audio_path]

    output_pattern = temp_dir / "chunk_%04d.mp3"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "48k",
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        "-reset_timestamps",
        "1",
        str(output_pattern),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        return [audio_path]
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[:1000]
        raise RuntimeError(f"音频切片失败: {detail or 'ffmpeg exited non-zero'}") from exc

    chunks = sorted(temp_dir.glob("chunk_*.mp3"))
    return chunks or [audio_path]


@mcp.tool()
def transcribe_audio_file(
    path: str,
    language: str = "",
    prompt: str = "",
    chunk_seconds: int = DEFAULT_CHUNK_SECONDS,
) -> str:
    """转写 backend/data 下的音频文件。

    Args:
        path: 必填，形如 backend/data/users/<user_id>/sessions/<session_id>/workspace/audio.wav。
        language: 可选语言提示，如 zh 或 en。
        prompt: 可选转写提示词。
        chunk_seconds: 可选分片秒数，默认 120；大文件会按该长度分片后逐段转写。

    Returns:
        JSON 字符串，包含 execution_status、content、artifacts、next_action。
    """
    try:
        audio_path = resolve_data_audio_path(path)
        api_key = get_api_key()
        base_url = (os.getenv("QWEN_AUDIO_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
        model = (os.getenv("QWEN_AUDIO_MODEL") or DEFAULT_MODEL).strip()
        chunk_len = int(chunk_seconds or DEFAULT_CHUNK_SECONDS)

        with tempfile.TemporaryDirectory(prefix="audio-asr-") as td:
            chunks = _split_audio(audio_path, chunk_seconds=chunk_len, temp_dir=Path(td))
            texts: list[str] = []
            for idx, chunk in enumerate(chunks, start=1):
                data = _request_transcription(
                    audio_path=chunk,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    language=language,
                    prompt=prompt,
                )
                text = _extract_text(data)
                if not text:
                    return _tool_result(
                        execution_status="failed",
                        content=f"第 {idx} 段未返回可用转写文本。",
                        artifacts=[],
                    )
                texts.append(text)
        return _tool_result(
            execution_status="succeeded",
            content="\n".join(texts).strip() or "音频转写完成。",
            artifacts=[],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("audio_asr transcription failed: %s", exc, exc_info=True)
        return _tool_result(
            execution_status="failed",
            content=str(exc),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-level", default=os.getenv("AUDIO_ASR_LOG_LEVEL", "WARNING"))
    args, _unknown = parser.parse_known_args()
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.WARNING))
    mcp.run(transport="stdio")
