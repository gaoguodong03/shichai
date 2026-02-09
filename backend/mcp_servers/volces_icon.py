#!/usr/bin/env python3
"""图片生成 MCP Server

调用火山引擎（Volces）图像生成 API，根据文字描述生成图片。
API Key 通过环境变量 VOLCES_IMAGE_API_KEY 传入，或在 mcp_servers.json 的 transport.env 中配置。

使用方法：
    python volces_icon.py

配置到 DHA：
    在 backend/config/mcp_servers.json 中添加 stdio 配置，并在 transport.env 中设置 VOLCES_IMAGE_API_KEY。
"""
import os
import httpx
from mcp.server.fastmcp import FastMCP

API_URL = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
MODEL = "ep-20250705144856-6jcl6"

mcp = FastMCP("图片生成")


def _get_api_key() -> str:
    key = os.environ.get("VOLCES_IMAGE_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "未配置 VOLCES_IMAGE_API_KEY。请在 backend/config/mcp_servers.json 的该 server 的 transport.env 中设置，或设置系统环境变量。"
        )
    return key if key.startswith("Bearer ") else f"Bearer {key}"


@mcp.tool()
def generate_app_icon(
    description: str,
    pic_size: str = "1024x1024",
) -> str:
    """根据文字描述生成应用图标图片。接受两个参数：description（必填，字符串，图标的文字描述，如「天空」「一只蓝色的云」）；pic_size（可选，字符串，图片尺寸，默认 1024x1024，常用 1024x1024 或 768x768）。调用时 arguments 必须包含 description，可包含 pic_size。返回图片 URL 或错误信息。"""
    try:
        api_key = _get_api_key()
    except ValueError as e:
        return str(e)

    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key,
    }
    body = {
        "model": MODEL,
        "prompt": description,
        "response_format": "url",
        "size": pic_size,
        "seed": 12,
        "guidance_scale": 2.5,
        "watermark": False,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(API_URL, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        # 常见返回结构: {"data": [{"url": "https://..."}]} 或类似
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            first = data["data"][0]
            if isinstance(first, dict) and "url" in first:
                return first["url"]
            if isinstance(first, dict) and "b64_json" in first:
                return f"[Base64 图片数据已返回，长度: {len(first['b64_json'])} 字符]"
        return str(data)
    except httpx.HTTPStatusError as e:
        return f"请求失败 HTTP {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"生成图标失败: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
