#!/usr/bin/env python3
"""Local stdio MCP server for OpenAI-compatible image generation."""
from __future__ import annotations

import argparse
import base64
import logging
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

DEFAULT_BASE_URL = "https://quanzil.com/v1"
DEFAULT_MODEL = "gpt-image-2-c:stable"
DEFAULT_MAX_ATTEMPTS = 2
MAX_ATTEMPTS_CAP = 5

_NETWORK_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.ConnectError,
    httpx.TimeoutException,
    OSError,
)

mcp = FastMCP("Image Generation")
logger = logging.getLogger(__name__)


def get_api_key() -> str:
    """Return the configured image API key in Bearer form."""
    key = os.getenv("IMAGE_GENERATION_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "未配置 IMAGE_GENERATION_API_KEY。"
            "请在 MCP transport.env 中引用对应环境变量。"
        )
    return key if key.startswith("Bearer ") else f"Bearer {key}"


def _api_url() -> str:
    base_url = (os.getenv("IMAGE_GENERATION_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    if base_url.endswith("/images/generations"):
        return base_url
    return f"{base_url}/images/generations"


def _model() -> str:
    return (os.getenv("IMAGE_GENERATION_MODEL") or DEFAULT_MODEL).strip()


def _max_attempts() -> int:
    raw = os.getenv("IMAGE_GENERATION_MAX_ATTEMPTS", "").strip()
    if not raw:
        return DEFAULT_MAX_ATTEMPTS
    try:
        return max(1, min(int(raw), MAX_ATTEMPTS_CAP))
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS


def _sniff_image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _validated_base64(payload: str, mime_type: str = "") -> tuple[str, str]:
    compact = "".join((payload or "").split())
    if not compact:
        raise RuntimeError("图片服务返回了空的 base64 图片数据")
    try:
        raw = base64.b64decode(compact, validate=True)
    except ValueError as exc:
        raise RuntimeError("图片服务返回了无效的 base64 图片数据") from exc

    resolved_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if not resolved_mime.startswith("image/"):
        resolved_mime = _sniff_image_mime(raw)
    if not resolved_mime:
        raise RuntimeError("无法识别图片服务返回的数据格式")
    return resolved_mime, compact


def _parse_data_url(value: str) -> tuple[str, str]:
    header, separator, payload = (value or "").partition(";base64,")
    if not separator or not header.startswith("data:image/"):
        raise RuntimeError("图片服务返回了无效的 data URL")
    return _validated_base64(payload, header.removeprefix("data:"))


def _download_image(client: httpx.Client, url: str) -> tuple[str, str]:
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        preview = (exc.response.text or "")[:200]
        raise RuntimeError(
            f"下载生成图片失败 HTTP {exc.response.status_code}: {preview}"
        ) from exc
    except _NETWORK_ERRORS as exc:
        raise RuntimeError(f"下载生成图片失败（网络连接异常）: {exc}") from exc

    mime_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not mime_type.startswith("image/"):
        mime_type = _sniff_image_mime(response.content)
    if not mime_type:
        raise RuntimeError("图片下载地址没有返回有效图片")
    return mime_type, base64.b64encode(response.content).decode("ascii")


def _extract_image(data: Any, client: httpx.Client) -> tuple[str, str]:
    if not isinstance(data, dict):
        raise RuntimeError("图片服务返回格式错误：响应不是 JSON 对象")
    items = data.get("data")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise RuntimeError("图片服务返回格式错误：缺少 data[0]")

    item = items[0]
    b64_json = item.get("b64_json")
    if isinstance(b64_json, str) and b64_json.strip():
        return _validated_base64(b64_json, str(item.get("mime_type") or ""))

    url = item.get("url")
    if isinstance(url, str) and url.strip():
        image_url = url.strip()
        if image_url.startswith("data:image/"):
            return _parse_data_url(image_url)
        return _download_image(client, image_url)

    raise RuntimeError("图片服务返回格式错误：data[0] 缺少 b64_json 或 url")


def _generate_image(*, description: str, pic_size: str) -> tuple[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": get_api_key(),
    }
    body = {
        "model": _model(),
        "prompt": description,
        "size": pic_size,
    }

    attempts = _max_attempts()
    last_network_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                response = client.post(_api_url(), json=body, headers=headers)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    preview = (response.text or "")[:200]
                    raise RuntimeError(
                        f"图片生成请求失败 HTTP {response.status_code}: {preview}"
                    ) from exc
                return _extract_image(response.json(), client)
        except _NETWORK_ERRORS as exc:
            last_network_error = exc
            if attempt < attempts:
                continue
            break
        except ValueError as exc:
            raise RuntimeError("图片服务没有返回有效 JSON") from exc

    raise RuntimeError(
        "图片生成请求失败"
        f"（网络连接异常，已尝试 {attempts} 次）: {last_network_error}"
    )


@mcp.tool()
def generate_image(
    description: str,
    pic_size: str = "1024x1024",
) -> list[TextContent | ImageContent]:
    """根据文字描述生成图片。

    Args:
        description: 必填，图片提示词，应包含主体、构图、风格和负面约束。
        pic_size: 可选图片尺寸，默认 1024x1024。
    Returns:
        MCP 标准内容块。图片以 ImageContent 返回，由调用平台负责持久化。
    """
    prompt = (description or "").strip()
    if not prompt:
        raise ValueError("缺少 description，请传入具体图片提示词。")
    size = (pic_size or "1024x1024").strip()

    try:
        mime_type, image_data = _generate_image(description=prompt, pic_size=size)
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
