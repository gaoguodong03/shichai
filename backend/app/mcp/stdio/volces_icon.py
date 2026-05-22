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
import logging
import httpx
from mcp.server.fastmcp import FastMCP

API_URL = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
MODEL = "ep-20250705144856-6jcl6"

mcp = FastMCP("图片生成")
logger = logging.getLogger(__name__)


def _agent_log(message: str, data: dict | None = None, hypothesis_id: str | None = None) -> None:
    """Structured diagnostics through the standard logger; secrets stay masked by callers."""
    logger.debug(
        "volces_icon: %s",
        message,
        extra={
            "volces_icon_data": data or {},
            "volces_icon_hypothesis_id": hypothesis_id or "",
        },
    )


def _get_api_key() -> str:
    key = os.environ.get("VOLCES_IMAGE_API_KEY", "").strip()
    if not key:
        _agent_log(
            "VOLCES_IMAGE_API_KEY 缺失或为空",
            data={"has_env": False},
            hypothesis_id="api-key-missing",
        )
        raise ValueError(
            "未配置 VOLCES_IMAGE_API_KEY。请在 backend/config/mcp_servers.json 的该 server 的 transport.env 中设置，或设置系统环境变量。"
        )
    masked = f"{'Bearer ' if key.startswith('Bearer ') else ''}***{len(key)}"
    _agent_log(
        "成功读取 VOLCES_IMAGE_API_KEY（已脱敏）",
        data={"masked": masked},
        hypothesis_id="api-key-present",
    )
    return key if key.startswith("Bearer ") else f"Bearer {key}"


@mcp.tool()
def generate_app_icon(
    description: str,
    pic_size: str = "1024x1024",
) -> str:
    """根据文字描述生成应用图标图片。

    参数：
    - description（string，必填）：图标的文字描述，例如「应用图标，极简扁平矢量风格：一只小羊……」。
    - pic_size（string，可选）：图片尺寸，默认 "1024x1024"（推荐），常用 "768x768"、"1024x1024"。

    调用规范（供 LLM 参考）：
    ```json
    {
      "action": "tool_call",
      "tool": "volces-icon_generate_app_icon",
      "arguments": {
        "description": "应用图标，极简扁平矢量风格：一只小羊……",
        "pic_size": "1024x1024"
      }
    }
    ```

    注意：必须使用参数名 description 传入提示词，不要使用 __arg1 / prompt 等其他字段名。
    函数返回值为图片 URL 或错误信息字符串。
    """
    if not (description and str(description).strip()):
        return "错误：description（图标的文字描述）不能为空。请提供具体描述后再调用本工具，例如：「应用图标，极简扁平矢量风格：一只小羊……」"
    description = str(description).strip()
    try:
        api_key = _get_api_key()
    except ValueError as e:
        _agent_log(
            "获取 API Key 失败",
            data={"error": str(e)},
            hypothesis_id="api-key-missing",
        )
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
        _agent_log(
            "准备调用 Volces 图像生成 API",
            data={
                "url": API_URL,
                "model": MODEL,
                "size": pic_size,
                "prompt_len": len(description or ""),
            },
            hypothesis_id="call-api",
        )
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(API_URL, json=body, headers=headers)
        _agent_log(
            "Volces API 返回响应",
            data={"status_code": resp.status_code},
            hypothesis_id="api-response",
        )
        resp.raise_for_status()
        data = resp.json()
        # 常见返回结构: {"data": [{"url": "https://..."}]} 或类似
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            first = data["data"][0]
            if isinstance(first, dict) and "url" in first:
                return first["url"]
            if isinstance(first, dict) and "b64_json" in first:
                return f"[Base64 图片数据已返回，长度: {len(first['b64_json'])} 字符]"
        _agent_log(
            "Volces API 返回非标准数据结构",
            data={"status_code": resp.status_code},
            hypothesis_id="api-unexpected",
        )
        return str(data)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        text_preview = (e.response.text or "")[:200]
        _agent_log(
            "Volces API HTTPStatusError",
            data={"status_code": status, "body_preview": text_preview},
            hypothesis_id="http-error",
        )
        return f"请求失败 HTTP {status}: {text_preview}"
    except Exception as e:
        _agent_log(
            "调用 Volces 图像生成 API 异常",
            data={"error": str(e)},
            hypothesis_id="exception",
        )
        return f"生成图标失败: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
