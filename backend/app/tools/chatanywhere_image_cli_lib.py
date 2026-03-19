"""ChatAnywhere 图像生成 CLI 共享库。

供 run_skill_script 调用的脚本使用（如 app-icon-generator）。
- 环境变量 CHATANYWHERE_IMAGE_API_KEY（Bearer sk-xxx 或仅 sk-xxx）
- 可选 CHATANYWHERE_IMAGE_BASE_URL，默认 https://api.chatanywhere.tech（与 Apifox 正式环境一致）
- POST {base}/v1/images/generations
- body 必填: prompt, n, model, size（见 https://chatanywhere.apifox.cn/api-92222078）
"""
import os
from pathlib import Path

import httpx

_DEFAULT_BASE = "https://api.chatanywhere.tech"


def _api_url() -> str:
    base = (os.environ.get("CHATANYWHERE_IMAGE_BASE_URL") or _DEFAULT_BASE).rstrip("/")
    return f"{base}/v1/images/generations"


def get_api_key() -> str:
    """从环境变量读取 API Key；若未设置则尝试从 backend/.env 加载。"""
    key = os.environ.get("CHATANYWHERE_IMAGE_API_KEY", "").strip()
    if not key:
        try:
            from dotenv import load_dotenv
            # __file__ = backend/app/tools/xxx.py -> parent.parent.parent = backend
            _backend_dir = Path(__file__).resolve().parent.parent.parent
            _env_path = _backend_dir / ".env"
            load_dotenv(_env_path)
            key = os.environ.get("CHATANYWHERE_IMAGE_API_KEY", "").strip()
        except Exception:
            pass
    if not key:
        raise ValueError(
            "未配置 CHATANYWHERE_IMAGE_API_KEY。请在 backend/.env 中设置，"
            "格式可为 Bearer sk-xxx 或仅 sk-xxx。"
        )
    return key if key.startswith("Bearer ") else f"Bearer {key}"


def generate_image(description: str, pic_size: str = "1024x1024") -> str:
    """调用 ChatAnywhere 图像生成 API（POST），返回图片 URL 或错误信息字符串。"""
    try:
        api_key = get_api_key()
    except ValueError as e:
        return str(e)

    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key,
    }
    body = {
        "prompt": description,
        "n": 1,
        "model": "gemini-3.1-flash-lite-preview",
        "size": pic_size,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(_api_url(), json=body, headers=headers)
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
        hint = ""
        if e.response.status_code == 500:
            hint = "（图像接口 ChatAnywhere 服务端异常，与合并/会话类型无关。请检查 CHATANYWHERE_IMAGE_API_KEY、额度或稍后重试）"
        return f"请求失败 HTTP {e.response.status_code}: {text_preview} {hint}"
    except (httpx.ConnectError, OSError) as e:
        err_msg = str(e)
        if "nodename" in err_msg or "not known" in err_msg or getattr(e, "errno", None) == 8:
            return "请求失败：无法解析接口域名（网络或 DNS 异常）。请检查本机网络、代理或防火墙。"
        return f"请求失败（网络连接异常）: {e}"
    except Exception as e:
        return f"生成图片失败: {e}"
