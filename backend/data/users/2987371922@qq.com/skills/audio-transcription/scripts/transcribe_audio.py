#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://10.129.50.230/v1"
DEFAULT_MODEL = "qwen3-asr-1.7b"
DEFAULT_API_KEY = "gpustack_f5292152476df868_af0b124cdd6d9e84f329edbb7863d812"
SUPPORTED_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".amr"}


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


def _endpoint(base_url: str) -> str:
    explicit = (os.getenv("QWEN_AUDIO_TRANSCRIBE_ENDPOINT") or "").strip()
    if explicit:
        return explicit
    return base_url.rstrip("/") + "/chat/completions"


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
    data = audio_path.read_bytes()
    audio_b64 = base64.b64encode(data).decode("ascii")
    mime_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    final_prompt = prompt.strip() if prompt else "请将这段音频逐字转写为文本。只输出转写内容，不要编造。"
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
        with urllib.request.urlopen(req, timeout=170) as resp:
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
    parser.add_argument("--mode", choices=["input_audio", "audio_url"], default=os.getenv("QWEN_AUDIO_REQUEST_MODE", "input_audio"))
    args = parser.parse_args()

    base_url = (os.getenv("QWEN_AUDIO_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    api_key = (os.getenv("QWEN_AUDIO_API_KEY") or DEFAULT_API_KEY).strip()
    model = (os.getenv("QWEN_AUDIO_MODEL") or DEFAULT_MODEL).strip()
    if not api_key:
        _json_print({"ok": False, "code": "missing_api_key", "message": "缺少 QWEN_AUDIO_API_KEY 环境变量。"}, code=2)

    try:
        audio_path = _resolve_workspace_file(args.file)
        upstream = _request_transcription(
            endpoint=_endpoint(base_url),
            api_key=api_key,
            model=model,
            audio_path=audio_path,
            prompt=args.prompt,
            language=args.language,
            mode=args.mode,
        )
        text = _extract_text(upstream)
        if not text:
            _json_print(
                {
                    "ok": False,
                    "code": "empty_transcription",
                    "message": "模型已返回，但未解析到转写文本。",
                    "raw": upstream,
                },
                code=3,
            )
        _json_print(
            {
                "ok": True,
                "code": "transcribed",
                "file": args.file,
                "model": model,
                "text": text,
            }
        )
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        _json_print({"ok": False, "code": "transcription_failed", "message": str(exc)}, code=1)


if __name__ == "__main__":
    main()
