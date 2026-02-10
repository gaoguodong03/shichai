"""调用外部 API / 服务，作为一等步骤能力。"""
import json
from typing import Optional

import httpx
from langchain_core.tools import tool


@tool
def call_api(
    url: str,
    method: str = "GET",
    headers_json: str = "",
    body: str = "",
) -> str:
    """
    调用外部 HTTP API。参数：url（必填），method（GET/POST/PUT/DELETE 等，默认 GET），
    headers_json（可选，JSON 对象字符串如 '{\"Authorization\": \"Bearer xxx\"}'），body（可选，请求体字符串）。
    当技能说明或脚本要求「调用某接口」「请求某 API」时使用本工具。
    """
    if not url or not url.strip():
        return "错误：未提供 url。"
    url = url.strip()
    method = (method or "GET").strip().upper()
    headers = {}
    if headers_json and headers_json.strip():
        try:
            headers = json.loads(headers_json)
        except json.JSONDecodeError as e:
            return f"错误：headers_json 不是合法 JSON：{e}"
    timeout_sec = float(__import__("os").getenv("CALL_API_TIMEOUT", "30"))
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            resp = client.request(method, url, content=body if body else None, headers=headers or None)
        text = resp.text
        try:
            data = resp.json()
            text = json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return f"状态码: {resp.status_code}\n\n{text}"
    except httpx.TimeoutException:
        return f"错误：请求超时（{timeout_sec} 秒）。"
    except Exception as e:
        return f"错误：请求失败 - {e}"
