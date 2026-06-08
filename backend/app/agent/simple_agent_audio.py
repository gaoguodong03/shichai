from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agent.tool_spec import ToolSpec

_AUDIO_ASR_TOOL_NAME = "audio-asr_transcribe_audio_file"
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".amr"}
_FILE_REF_TAG_RE = re.compile(r"【文件引用：([^】]+)】")
_AUDIO_PATH_RE = re.compile(r"([^\s`\"'，。；;：:\]\[（）()<>]+?\.(?:mp3|wav|m4a|aac|flac|ogg|opus|webm|amr))\b", re.I)


@dataclass
class _ForcedToolCall:
    message: AIMessage
    debug: dict[str, Any]


def _clean_audio_path_candidate(value: str) -> str:
    return (value or "").strip().strip(" \t\r\n\"'`“”‘’「」『』")


def _looks_like_audio_path(value: str) -> bool:
    path = _clean_audio_path_candidate(value).replace("\\", "/")
    if not path or "\x00" in path:
        return False
    lowered = path.lower()
    if lowered.startswith(("http://", "https://")) or ".." in path:
        return False
    return any(lowered.endswith(ext) for ext in _AUDIO_EXTS)


def _audio_path_from_user_content(content: str) -> str:
    text = str(content or "")
    for match in _FILE_REF_TAG_RE.finditer(text):
        payload = match.group(1)
        parts = re.split(r"[｜|]", payload)
        for candidate in reversed(parts):
            cleaned = _clean_audio_path_candidate(candidate).replace("\\", "/")
            if _looks_like_audio_path(cleaned):
                return cleaned
    for match in _AUDIO_PATH_RE.finditer(text):
        cleaned = _clean_audio_path_candidate(match.group(1)).replace("\\", "/")
        if _looks_like_audio_path(cleaned):
            return cleaned
    return ""


def _last_user_audio_path(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            path = _audio_path_from_user_content(str(getattr(msg, "content", "") or ""))
            if path:
                return path
    return ""


def _has_audio_asr_tool(tools: list[ToolSpec]) -> bool:
    return any(str(getattr(tool, "name", "") or "").strip() == _AUDIO_ASR_TOOL_NAME for tool in tools or [])


def _audio_asr_already_called(messages: list[BaseMessage]) -> bool:
    for msg in messages:
        for call in getattr(msg, "tool_calls", None) or []:
            if isinstance(call, dict) and str(call.get("name") or "").strip() == _AUDIO_ASR_TOOL_NAME:
                return True
    return False


def _forced_audio_asr_file_ref_message(messages: list[BaseMessage], tools: list[ToolSpec]) -> _ForcedToolCall | None:
    if not _has_audio_asr_tool(tools) or _audio_asr_already_called(messages):
        return None
    path = _last_user_audio_path(messages)
    if not path:
        return None
    call_id = f"forced_audio_asr_{hashlib.sha256(path.encode('utf-8')).hexdigest()[:24]}"
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": call_id,
                "name": _AUDIO_ASR_TOOL_NAME,
                "args": {"path": path},
            }
        ],
    )
    return _ForcedToolCall(
        message=msg,
        debug={
            "source": "forced_audio_asr_file_ref",
            "matched": True,
            "path": path,
        },
    )


def _audio_transcription_final_message(tool_out: dict[str, Any]) -> AIMessage | None:
    """Surface full audio transcripts directly instead of asking the LLM to restate them."""
    calls = tool_out.get("tool_calls") if isinstance(tool_out, dict) else None
    if not isinstance(calls, list):
        return None

    tool_names = {
        str(call.get("tool") or call.get("name") or "").strip()
        for call in calls
        if isinstance(call, dict)
    }
    has_script_call = any(name.startswith("run_skill_script_audio-transcription") for name in tool_names)
    has_audio_asr_call = _AUDIO_ASR_TOOL_NAME in tool_names
    if not has_script_call and not has_audio_asr_call:
        return None

    raw_outputs = tool_out.get("tool_raw_outputs")
    if not isinstance(raw_outputs, list):
        return None
    for raw in raw_outputs:
        try:
            outer = json.loads(str(raw or ""))
        except Exception:
            continue
        if not isinstance(outer, dict):
            continue
        if has_audio_asr_call and outer.get("ok") is True:
            transcript = outer.get("text")
            if isinstance(transcript, str) and transcript.strip():
                return AIMessage(content=transcript.strip())

        stdout = outer.get("stdout")
        if not isinstance(stdout, str) or not stdout.strip():
            continue
        try:
            payload = json.loads(stdout.strip())
        except Exception:
            continue
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            continue
        transcript = payload.get("text")
        if not isinstance(transcript, str) or not transcript.strip():
            continue
        return AIMessage(content=transcript.strip())
    return None
