"""Volces 图像生成 CLI 共享库。

与 mcp_servers/volces_icon.py 使用相同 API 与 KEY 方式：
- 环境变量 VOLCES_IMAGE_API_KEY（可为 "Bearer xxx" 或 "xxx"）
- 用于 run_skill_script 调用的脚本，供各图片生成 Skill 复用。
"""
import os
from pathlib import Path

import httpx

API_URL = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
MODEL = "ep-20250705144856-6jcl6"


def get_api_key() -> str:
    """从环境变量读取 API Key，与 volces_icon MCP 一致。若未设置则尝试从 backend/.env 加载。"""
    key = os.environ.get("VOLCES_IMAGE_API_KEY", "").strip()
    if not key:
        try:
            from dotenv import load_dotenv
            # run_skill_script 子进程 cwd 为 skill/scripts，需按 __file__ 定位 backend/.env
            _backend_dir = Path(__file__).resolve().parent.parent
            _env_path = _backend_dir / ".env"
            load_dotenv(_env_path)
            key = os.environ.get("VOLCES_IMAGE_API_KEY", "").strip()
        except Exception:
            pass
    if not key:
        raise ValueError(
            "未配置 VOLCES_IMAGE_API_KEY。请在 backend/.env 或 transport.env 中设置，"
            "格式可为 Bearer xxx 或仅 xxx。"
        )
    return key if key.startswith("Bearer ") else f"Bearer {key}"


def generate_image(description: str, pic_size: str = "1024x1024") -> str:
    """调用火山引擎图像生成 API，返回图片 URL 或错误信息字符串。"""
    try:
        api_key = get_api_key()
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
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            first = data["data"][0]
            if isinstance(first, dict) and "url" in first:
                return first["url"]
            if isinstance(first, dict) and "b64_json" in first:
                return f"[Base64 图片数据已返回，长度: {len(first['b64_json'])} 字符]"
        return str(data)
    except httpx.HTTPStatusError as e:
        text_preview = (e.response.text or "")[:200]
        return f"请求失败 HTTP {e.response.status_code}: {text_preview}"
    except (httpx.ConnectError, OSError) as e:
        err_msg = str(e)
        if "nodename" in err_msg or "not known" in err_msg or getattr(e, "errno", None) == 8:
            return "请求失败：无法解析接口域名（网络或 DNS 异常）。请检查本机网络、代理或防火墙，确认可访问 ark.cn-beijing.volces.com。"
        return f"请求失败（网络连接异常）: {e}"
    except Exception as e:
        return f"生成图片失败: {e}"
