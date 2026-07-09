"""Path argument normalization helpers for skill agent tool calls."""

import logging
import re
from typing import Sequence

from app.agent.messages import BaseMessage

from app.agent.read_path_utils import (
    looks_like_url_or_remote_path,
    strip_llm_junk_from_read_path,
)

logger = logging.getLogger(__name__)

_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".amr"}


def _clean_path_candidate(s: str) -> str:
    return (s or "").strip().strip(" \t\r\n\"'""''「」『』")


def _tool_is_workspace_plain_read_file(tool_name: str) -> bool:
    n = (tool_name or "").strip()
    return n == "read_workspace_file"


def _normalize_read_file_path_argument(arguments: dict) -> None:
    raw_arg = str(arguments.get("path") or "").strip()
    if not raw_arg:
        return
    fixed = strip_llm_junk_from_read_path(raw_arg)
    if fixed and fixed != raw_arg:
        logger.info("read_workspace_file: 清理模型 path 中的说明性文字: %s -> %s", raw_arg, fixed)
        arguments["path"] = fixed


def _looks_like_audio_workspace_rel_path(path: str) -> bool:
    p = _clean_path_candidate(path).replace("\\", "/")
    if not p or p.startswith("/") or ".." in p or looks_like_url_or_remote_path(p):
        return False
    return any(p.lower().endswith(ext) for ext in _AUDIO_EXTS)


def _workspace_audio_path_to_backend_data_arg(rel_path: str, workspace_id: str) -> str:
    rel = _clean_path_candidate(rel_path).replace("\\", "/").lstrip("/")
    if not rel or rel.startswith("backend/data/"):
        return rel
    if not workspace_id:
        return rel
    if not _looks_like_audio_workspace_rel_path(rel):
        return rel

    from app.api.files import get_workspace_root_path
    from app.core.user_context import users_data_root

    ws_root = get_workspace_root_path(workspace_id).resolve()
    target = (ws_root / rel).resolve()
    try:
        target.relative_to(ws_root)
    except ValueError:
        return rel

    data_root = users_data_root().resolve().parent
    try:
        data_rel = target.relative_to(data_root).as_posix()
    except ValueError:
        return rel
    return f"backend/data/{data_rel}"


def _apply_audio_asr_path_from_user_message(
    arguments: dict,
    messages: Sequence[BaseMessage],
    workspace_id: str,
) -> None:
    """Convert only an explicit audio tool path; user text is not a path source."""
    _ = messages
    cur = str(arguments.get("path") or "").strip()
    if cur.startswith("backend/data/"):
        arguments["path"] = cur
        return

    if not _looks_like_audio_workspace_rel_path(cur):
        return
    converted = _workspace_audio_path_to_backend_data_arg(cur, workspace_id)
    if converted and converted != cur:
        logger.info("audio_asr: 工作区音频路径转换为 backend/data 路径: %s -> %s", cur, converted)
        arguments["path"] = converted


def _apply_image_generation_workspace_id(arguments: dict, workspace_id: str) -> None:
    wid = (workspace_id or "").strip()
    if not wid:
        return
    if str(arguments.get("workspace_id") or "").strip():
        return
    arguments["workspace_id"] = wid
