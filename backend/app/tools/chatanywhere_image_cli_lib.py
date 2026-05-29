"""Jeniya Gemini 图像生成 CLI 共享库。

供 run_skill_script 调用的脚本使用（如 app-icon-generator）。
- 环境变量 JENIYA_API_KEY（兼容 CHATANYWHERE_IMAGE_API_KEY 作为回退）
- 可选 JENIYA_IMAGE_BASE_URL，默认 https://jeniya.top
- POST {base}/v1beta/models/gemini-3.1-flash-image-preview:generateContent
"""
import os
from pathlib import Path

import httpx

_DEFAULT_BASE = "https://jeniya.top"
_DEFAULT_MODEL = "gemini-3.1-flash-image-preview"
_DEFAULT_MAX_ATTEMPTS = 2
_MAX_ATTEMPTS_CAP = 5


def _api_url() -> str:
    base = (os.environ.get("JENIYA_IMAGE_BASE_URL") or _DEFAULT_BASE).rstrip("/")
    if base == "http://jeniya.top" or base.startswith("http://jeniya.top/"):
        base = "https://" + base[len("http://") :]
    model = (os.environ.get("JENIYA_IMAGE_MODEL") or _DEFAULT_MODEL).strip()
    return f"{base}/v1beta/models/{model}:generateContent"


def _max_attempts() -> int:
    raw = os.environ.get("JENIYA_IMAGE_MAX_ATTEMPTS", "").strip()
    if not raw:
        return _DEFAULT_MAX_ATTEMPTS
    try:
        return max(1, min(int(raw), _MAX_ATTEMPTS_CAP))
    except ValueError:
        return _DEFAULT_MAX_ATTEMPTS


def get_api_key() -> str:
    """从环境变量读取 API Key；若未设置则尝试从 backend/.env 加载。"""
    key = os.environ.get("JENIYA_API_KEY", "").strip()
    if not key:
        try:
            from dotenv import load_dotenv
            # __file__ = backend/app/tools/xxx.py -> parent.parent.parent = backend
            _backend_dir = Path(__file__).resolve().parent.parent.parent
            _env_path = _backend_dir / ".env"
            load_dotenv(_env_path)
            key = os.environ.get("JENIYA_API_KEY", "").strip()
            if not key:
                key = os.environ.get("CHATANYWHERE_IMAGE_API_KEY", "").strip()
        except Exception:
            pass
    if not key:
        key = os.environ.get("CHATANYWHERE_IMAGE_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "未配置 JENIYA_API_KEY（或 CHATANYWHERE_IMAGE_API_KEY 回退值）。请在 backend/.env 中设置，"
            "格式可为 Bearer sk-xxx 或仅 sk-xxx。"
        )
    return key if key.startswith("Bearer ") else f"Bearer {key}"


def generate_image(description: str, pic_size: str = "1024x1024") -> str:
    """调用 Jeniya Gemini 图像生成接口，返回 data URL 或错误信息字符串。"""
    try:
        api_key = get_api_key()
    except ValueError as e:
        return str(e)

    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key,
    }
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            f"{description}\n\n"
                            f"请生成尺寸约为 {pic_size} 的图片，输出图像内容。"
                        )
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
        },
    }

    attempts = _max_attempts()
    resp = None
    last_network_error = None
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                resp = client.post(_api_url(), json=body, headers=headers)
            break
        except (
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.ConnectError,
            httpx.TimeoutException,
            OSError,
        ) as e:
            last_network_error = e
            if attempt >= attempts:
                break

    if resp is None and last_network_error is not None:
        err_msg = str(last_network_error)
        if (
            "nodename" in err_msg
            or "not known" in err_msg
            or getattr(last_network_error, "errno", None) == 8
        ):
            return "请求失败：无法解析接口域名（网络或 DNS 异常）。请检查本机网络、代理或防火墙。"
        return f"请求失败（网络连接异常，已尝试 {attempts} 次）: {last_network_error}"

    try:
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            candidates = data.get("candidates")
            if isinstance(candidates, list):
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    content = candidate.get("content")
                    if not isinstance(content, dict):
                        continue
                    parts = content.get("parts")
                    if not isinstance(parts, list):
                        continue
                    for part in parts:
                        if not isinstance(part, dict):
                            continue
                        inline = part.get("inlineData")
                        if isinstance(inline, dict) and inline.get("data"):
                            mime_type = inline.get("mimeType") or "image/png"
                            return f"data:{mime_type};base64,{inline['data']}"
                        text = part.get("text")
                        if isinstance(text, str) and text.strip():
                            return text.strip()
        return str(data)
    except httpx.HTTPStatusError as e:
        text_preview = (e.response.text or "")[:200]
        return f"请求失败 HTTP {e.response.status_code}: {text_preview}"
    except Exception as e:
        return f"生成图片失败: {e}"
