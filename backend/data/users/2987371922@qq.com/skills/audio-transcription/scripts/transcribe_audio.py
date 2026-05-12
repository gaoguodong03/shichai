#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import urllib.error
import urllib.request
import re
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://10.129.50.230/v1"
DEFAULT_MODEL = "qwen3-asr-1.7b"
DEFAULT_API_KEY = "gpustack_f5292152476df868_af0b124cdd6d9e84f329edbb7863d812"
DEFAULT_REQUEST_MODE = "transcriptions"
SUPPORTED_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".amr"}
DEFAULT_CHUNK_SECONDS = 120
LENGTH_LIMIT_ERROR_MARKERS = (
    "exceeds the pre-allocated encoder cache size",
    "limit-mm-per-prompt",
    "reduce the input size",
)


def _request_timeout() -> float | None:
    raw = (os.getenv("QWEN_AUDIO_REQUEST_TIMEOUT_SEC") or "0").strip()
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 0
    return seconds if seconds > 0 else None


def _json_print(payload: dict[str, Any], *, code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(code)


def _workspace_root() -> Path:
    raw = os.getenv("SKILL_WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).resolve()


def _resolve_workspace_file(rel_path: str) -> Path:
    root = _workspace_root()
    cleaned = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not cleaned or "\x00" in cleaned:
        raise ValueError("file path is required")
    target = (root / cleaned).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("file path is outside workspace")
    if not target.is_file():
        raise FileNotFoundError(f"file not found: {cleaned}")
    if target.suffix.lower() not in SUPPORTED_EXTS:
        raise ValueError(f"unsupported audio suffix: {target.suffix}")
    return target


def _endpoint(base_url: str, mode: str) -> str:
    if mode == "transcriptions":
        return base_url.rstrip("/") + "/audio/transcriptions"
    return base_url.rstrip("/") + "/chat/completions"


def _multipart_body(fields: dict[str, str], file_field: str, file_path: Path, mime_type: str) -> tuple[bytes, str]:
    boundary = "----audio-transcribe-" + uuid.uuid4().hex
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
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode("utf-8"),
            f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), boundary


def _audio_payload(audio_b64: str, suffix: str, mime_type: str, prompt: str, mode: str) -> list[dict[str, Any]]:
    text_part = {
        "type": "text",
        "text": prompt or "请将这段音频逐字转写为文本。只输出转写内容，不要编造。",
    }
    audio_format = suffix.lower().lstrip(".") or "wav"
    if mode == "audio_url":
        return [
            text_part,
            {"type": "audio_url", "audio_url": {"url": f"data:{mime_type};base64,{audio_b64}"}},
        ]
    return [
        text_part,
        {"type": "input_audio", "input_audio": {"data": audio_b64, "format": audio_format}},
    ]


def _request_transcription(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    audio_path: Path,
    prompt: str,
    language: str,
    mode: str,
) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    final_prompt = prompt.strip() if prompt else "请将这段音频逐字转写为文本。只输出转写内容，不要编造。"
    if mode == "transcriptions":
        body_bytes, boundary = _multipart_body(
            {
                "model": model,
                "prompt": final_prompt,
                "language": language.strip(),
            },
            "file",
            audio_path,
            mime_type,
        )
        req = urllib.request.Request(
            endpoint,
            data=body_bytes,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
    else:
        audio_b64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        if language:
            final_prompt += f"\n语言提示：{language}。"
        body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": _audio_payload(audio_b64, audio_path.suffix, mime_type, final_prompt, mode),
                }
            ],
            "temperature": 0,
        }
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
    try:
        with urllib.request.urlopen(req, timeout=_request_timeout()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"upstream http {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"upstream request failed: {exc.reason}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"upstream returned non-json: {raw[:1000]}") from exc


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
        raise RuntimeError(f"audio split failed: {detail or 'ffmpeg exited non-zero'}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("audio split failed: ffmpeg timed out") from exc

    chunks = sorted(temp_dir.glob("chunk_*.mp3"))
    return chunks or [audio_path]


def _transcribe_chunks(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    audio_path: Path,
    prompt: str,
    language: str,
    mode: str,
    chunk_seconds: int,
) -> tuple[str, list[dict[str, Any]]]:
    with tempfile.TemporaryDirectory(prefix="audio_transcribe_") as raw_temp_dir:
        temp_dir = Path(raw_temp_dir)
        chunks = _split_audio(audio_path, chunk_seconds=chunk_seconds, temp_dir=temp_dir)
        transcripts: list[str] = []
        segment_results: list[dict[str, Any]] = []
        total = len(chunks)
        for index, chunk_path in enumerate(chunks, start=1):
            segment_prompt = prompt
            if total > 1:
                segment_prompt = (prompt.strip() + "\n" if prompt.strip() else "") + (
                    "这是长音频自动切分后的一个连续片段。请只逐字转写本段语音内容，"
                    "不要总结，不要改写，不要添加标题，不要提到分段、片段编号或上下文。"
                )
            upstream = _request_transcription(
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                audio_path=chunk_path,
                prompt=segment_prompt,
                language=language,
                mode=mode,
            )
            text = _extract_text(upstream)
            if not text:
                raise RuntimeError(f"empty transcription for segment {index}/{total}")
            transcripts.append(text)
            segment_results.append({"index": index, "total": total, "text": text})

        if total == 1:
            return transcripts[0], segment_results
        merged = _join_transcripts(transcripts)
        return merged, segment_results


def _join_transcripts(parts: list[str]) -> str:
    cleaned = []
    for part in parts:
        text = re.sub(r"\s+", " ", str(part or "")).strip()
        if text:
            cleaned.append(text)
    if not cleaned:
        return ""
    merged = "".join(_join_separator(prev, cur) + cur for prev, cur in zip(["", *cleaned[:-1]], cleaned)).strip()
    return re.sub(r"\s+([，。！？；：、,.!?;:])", r"\1", merged)


def _join_separator(prev: str, cur: str) -> str:
    if not prev:
        return ""
    if prev.endswith((" ", "\n")) or cur.startswith((" ", "\n")):
        return ""
    if prev[-1] in "。！？；：.!?;:" and _is_ascii_word_char(cur[0]):
        return " "
    if _is_ascii_word_char(prev[-1]) and _is_ascii_word_char(cur[0]):
        return " "
    return ""


def _is_ascii_word_char(ch: str) -> bool:
    return bool(re.match(r"[A-Za-z0-9]", ch or ""))


def _is_length_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker.lower() in message for marker in LENGTH_LIMIT_ERROR_MARKERS)


def _fallback_chunk_seconds(chunk_seconds: int) -> int:
    if chunk_seconds > 0:
        return max(30, chunk_seconds // 2)
    return DEFAULT_CHUNK_SECONDS


def _extract_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict):
                        txt = item.get("text") or item.get("transcript")
                        if isinstance(txt, str) and txt.strip():
                            parts.append(txt.strip())
                if parts:
                    return "\n".join(parts).strip()
        text = choices[0].get("text") if isinstance(choices[0], dict) else None
        if isinstance(text, str):
            return text.strip()
    for key in ("text", "transcript", "content"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe a workspace audio file through a multimodal model.")
    parser.add_argument("--file", required=True, help="工作区内音频文件相对路径")
    parser.add_argument("--language", default="", help="可选语言提示，如 zh/en")
    parser.add_argument("--prompt", default="", help="可选转写要求")
    parser.add_argument(
        "--mode",
        choices=["transcriptions", "input_audio", "audio_url"],
        default=DEFAULT_REQUEST_MODE,
    )
    parser.add_argument(
        "--chunk-seconds",
        type=int,
        default=int(os.getenv("QWEN_AUDIO_CHUNK_SECONDS", str(DEFAULT_CHUNK_SECONDS))),
        help="自动切分音频的秒数；设为 0 可禁用切分。",
    )
    args = parser.parse_args()

    base_url = DEFAULT_BASE_URL.rstrip("/")
    api_key = DEFAULT_API_KEY
    model = DEFAULT_MODEL

    try:
        audio_path = _resolve_workspace_file(args.file)
        effective_chunk_seconds = args.chunk_seconds
        try:
            text, segments = _transcribe_chunks(
                endpoint=_endpoint(base_url, args.mode),
                api_key=api_key,
                model=model,
                audio_path=audio_path,
                prompt=args.prompt,
                language=args.language,
                mode=args.mode,
                chunk_seconds=effective_chunk_seconds,
            )
        except RuntimeError as exc:
            fallback_seconds = _fallback_chunk_seconds(effective_chunk_seconds)
            if fallback_seconds == effective_chunk_seconds or not _is_length_limit_error(exc):
                raise
            effective_chunk_seconds = fallback_seconds
            text, segments = _transcribe_chunks(
                endpoint=_endpoint(base_url, args.mode),
                api_key=api_key,
                model=model,
                audio_path=audio_path,
                prompt=args.prompt,
                language=args.language,
                mode=args.mode,
                chunk_seconds=effective_chunk_seconds,
            )
        if not text:
            _json_print(
                {
                    "ok": False,
                    "code": "empty_transcription",
                    "message": "模型已返回，但未解析到转写文本。",
                },
                code=3,
            )
        _json_print(
            {
                "ok": True,
                "code": "transcribed",
                "done": True,
                "final": True,
                "file": args.file,
                "model": model,
                "chunk_seconds": effective_chunk_seconds,
                "segment_count": len(segments),
                "segments": segments,
                "text": text,
            }
        )
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        _json_print({"ok": False, "code": "transcription_failed", "message": str(exc)}, code=1)


if __name__ == "__main__":
    main()
