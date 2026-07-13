#!/usr/bin/env python3
"""General image generation MCP server.

Local stdio MCP for generating images from text prompts. The API key is
provided through stdio transport env, typically ``JENIYA_API_KEY=${env:JENIYA_API_KEY}``.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.tools.chatanywhere_image_cli_lib import generate_image as _generate_image

mcp = FastMCP("Image Generation")
logger = logging.getLogger(__name__)


def get_api_key() -> str:
    """Return the configured image API key in Bearer form."""
    key = os.getenv("JENIYA_API_KEY", "").strip()
    if not key:
        raise ValueError("未配置 JENIYA_API_KEY。请在 MCP transport.env 中引用对应环境变量。")
    return key if key.startswith("Bearer ") else f"Bearer {key}"


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
) -> list[TextContent | ImageContent]:
    """根据文字描述生成图片。

    Args:
        description: 必填，图片提示词，应包含主体、构图、风格和负面约束。
        pic_size: 可选图片尺寸，默认 1024x1024，常用 1024x1792、1792x1024。
    Returns:
        MCP 标准内容块。图片以 ImageContent 原路返回，由调用平台负责持久化。
    """
    prompt = (description or "").strip()
    if not prompt:
        raise ValueError("缺少 description，请传入具体图片提示词。")

    try:
        result = _generate_image(description=prompt, pic_size=(pic_size or "1024x1024").strip())
        if _looks_like_upstream_failure(result):
            raise RuntimeError(result)
        text = str(result or "").strip()
        if not text.startswith("data:image/") or ";base64," not in text:
            raise RuntimeError("图片服务没有返回标准 data URL")
        header, image_data = text.split(";base64,", 1)
        mime_type = header.removeprefix("data:").strip() or "image/jpeg"
        return [
            TextContent(type="text", text="图片生成完成。"),
            ImageContent(type="image", data=image_data, mimeType=mime_type),
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_generation failed: %s", exc, exc_info=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-level", default=os.getenv("IMAGE_GENERATION_LOG_LEVEL", "WARNING"))
    args, _unknown = parser.parse_known_args()
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.WARNING))
    mcp.run(transport="stdio")
