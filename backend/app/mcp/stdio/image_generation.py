#!/usr/bin/env python3
"""General image generation MCP server.

Local stdio MCP for generating images from text prompts. The API key is
provided through stdio transport env, typically ``JENIYA_API_KEY=${env:JENIYA_API_KEY}``.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.files import get_workspace_root_path
from app.core.user_context import reset_current_user_identity, set_current_user_identity
from app.tools.chatanywhere_image_cli_lib import generate_image as _generate_image

DEFAULT_OUTPUT_ROOT = BACKEND_DIR / "data"

mcp = FastMCP("Image Generation")
logger = logging.getLogger(__name__)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _tool_result(
    *,
    execution_status: str,
    content: str,
    artifacts: list[dict[str, str]] | None = None,
    instruction: str = "",
) -> str:
    _ = instruction
    return _json(
        {
            "execution_status": execution_status,
            "content": content,
            "artifacts": artifacts or [],
        }
    )


def get_api_key() -> str:
    """Return the configured image API key in Bearer form."""
    key = os.getenv("JENIYA_API_KEY", "").strip()
    if not key:
        raise ValueError("未配置 JENIYA_API_KEY。请在 MCP transport.env 中引用对应环境变量。")
    return key if key.startswith("Bearer ") else f"Bearer {key}"


def _ext_from_mime(mime_type: str) -> str:
    mt = (mime_type or "").lower().strip()
    if mt == "image/png":
        return "png"
    if mt == "image/webp":
        return "webp"
    return "jpg"


def _safe_subdir(subdir: str) -> str:
    cleaned = (subdir or "generated_images").strip().replace("\\", "/").strip("/")
    if not cleaned or "\x00" in cleaned or ".." in cleaned.split("/"):
        raise ValueError("output_subdir 必须是安全的相对目录。")
    return cleaned


def _workspace_root_for_mcp(workspace_id: str) -> Path:
    user_id = (os.getenv("ST49_MCP_USER_ID") or "").strip()
    username = (os.getenv("ST49_MCP_USERNAME") or user_id).strip()
    if not user_id:
        return Path(get_workspace_root_path(workspace_id)).resolve()

    token = set_current_user_identity(user_id=user_id, username=username)
    try:
        return Path(get_workspace_root_path(workspace_id)).resolve()
    finally:
        reset_current_user_identity(token)


def _checkpoint_workspace_for_mcp(workspace_id: str) -> None:
    """Create a workspace_changed checkpoint in the MCP runtime user context."""
    wid = (workspace_id or "").strip()
    if not wid:
        return
    user_id = (os.getenv("ST49_MCP_USER_ID") or "").strip()
    username = (os.getenv("ST49_MCP_USERNAME") or user_id).strip()
    token = set_current_user_identity(user_id=user_id, username=username) if user_id else None
    try:
        from app.session_state.service import capture_session_checkpoint

        capture_session_checkpoint(wid, trigger="workspace_changed", force=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_generation checkpoint failed workspace_id=%s err=%s", wid, exc)
    finally:
        if token is not None:
            reset_current_user_identity(token)


def _save_data_url(result: str, *, workspace_id: str, output_subdir: str) -> dict[str, Any] | None:
    text = (result or "").strip()
    if not text.startswith("data:image/") or ";base64," not in text:
        return None

    header, b64_data = text.split(";base64,", 1)
    mime_type = header.replace("data:", "", 1).strip() or "image/jpeg"
    image_bytes = base64.b64decode(b64_data)
    ext = _ext_from_mime(mime_type)

    safe_dir = _safe_subdir(output_subdir)
    wid = (workspace_id or "").strip()
    if wid:
        workspace_root = _workspace_root_for_mcp(wid)
        output_dir = workspace_root / safe_dir
        download_prefix = f"/api/sessions/{wid}/workspace/files/download?path="
    else:
        workspace_root = DEFAULT_OUTPUT_ROOT.resolve()
        output_dir = workspace_root / safe_dir
        download_prefix = ""

    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d%H%M%S") + "00"
    filename = f"图片-{ts}-{uuid4().hex[:8]}.{ext}"
    output_path = output_dir / filename
    output_path.write_bytes(image_bytes)
    if wid:
        _checkpoint_workspace_for_mcp(wid)

    rel_path = output_path.relative_to(workspace_root).as_posix()
    payload: dict[str, Any] = {
        "file_path": rel_path,
        "mime_type": mime_type,
        "bytes": len(image_bytes),
    }
    if download_prefix:
        payload["download_url"] = f"{download_prefix}{rel_path}"
        payload["markdown"] = f"![生成图片]({payload['download_url']})"
    else:
        payload["local_path"] = str(output_path)
    return payload


def _looks_like_upstream_failure(result: str) -> bool:
    text = (result or "").strip()
    if not text:
        return True
    failure_prefixes = (
        "请求失败",
        "生成图片失败",
        "未配置 JENIYA_API_KEY",
    )
    return text.startswith(failure_prefixes)


@mcp.tool()
def generate_image(
    description: str,
    pic_size: str = "1024x1024",
    workspace_id: str = "",
    output_subdir: str = "generated_images",
) -> str:
    """根据文字描述生成图片。

    Args:
        description: 必填，图片提示词，应包含主体、构图、风格和负面约束。
        pic_size: 可选图片尺寸，默认 1024x1024，常用 1024x1792、1792x1024。
        workspace_id: 可选，会话工作区 ID；填写后 data URL 图片会写入该工作区并返回下载链接。
        output_subdir: 可选，写入工作区的相对目录，默认 generated_images。

    Returns:
        JSON 字符串。外层字段为 execution_status、message、content、artifacts。
    """
    prompt = (description or "").strip()
    if not prompt:
        return _tool_result(
            execution_status="blocked",
            content="缺少 description，请传入具体图片提示词。",
            artifacts=[],
        )

    try:
        result = _generate_image(description=prompt, pic_size=(pic_size or "1024x1024").strip())
        if _looks_like_upstream_failure(result):
            return _tool_result(
                execution_status="failed",
                content=result,
                artifacts=[],
            )
        saved = _save_data_url(result, workspace_id=workspace_id, output_subdir=output_subdir)
        artifacts: list[dict[str, str]] = []
        if saved:
            file_path = str(saved.get("file_path") or "").strip()
            if file_path:
                artifacts.append(
                    {
                        "type": "image",
                        "name": Path(file_path).name,
                        "path": file_path,
                    }
                )
        return _tool_result(
            execution_status="succeeded",
            content="图片生成完成。",
            artifacts=artifacts,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_generation failed: %s", exc, exc_info=True)
        return _tool_result(
            execution_status="failed",
            content=str(exc),
            artifacts=[],
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-level", default=os.getenv("IMAGE_GENERATION_LOG_LEVEL", "WARNING"))
    args, _unknown = parser.parse_known_args()
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.WARNING))
    mcp.run(transport="stdio")
