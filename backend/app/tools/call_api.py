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
    # 原始入参字符串，便于日志排查
    raw_url_param = url.strip()

    # 兼容错误用法：有时上游会把 {"url": "...", "method": "..."} 整个 JSON 当成 url 传进来
    # 这里尝试解析这种情况，提取真正的 url / method / headers / body
    try:
        if raw_url_param.startswith("{") and raw_url_param.endswith("}"):
            maybe_obj = json.loads(raw_url_param)
            if isinstance(maybe_obj, dict) and "url" in maybe_obj:
                # 提取真正 URL
                url = str(maybe_obj.get("url", "")).strip()
                # 若 JSON 内同时给了 method / headers / body，则在未显式传参时补用它们
                if "method" in maybe_obj and (not method or method == "GET"):
                    method = str(maybe_obj["method"]).strip().upper() or "GET"
                if "headers" in maybe_obj and not headers_json:
                    try:
                        headers_json = json.dumps(maybe_obj["headers"], ensure_ascii=False)
                    except Exception:
                        pass
                if "body" in maybe_obj and not body:
                    body_val = maybe_obj["body"]
                    body = json.dumps(body_val, ensure_ascii=False) if not isinstance(body_val, str) else body_val
            else:
                url = raw_url_param
        else:
            url = raw_url_param
    except Exception:
        # 解析失败则退回原始字符串
        url = raw_url_param

    # 若 url 未带协议，自动补 https://（避免模型只填域名导致 httpx 报错）
    if url and not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url.lstrip("/")

    method = (method or "GET").strip().upper()
    headers = {}
    if headers_json and headers_json.strip():
        try:
            headers = json.loads(headers_json)
        except json.JSONDecodeError as e:
            return f"错误：headers_json 不是合法 JSON：{e}"

    # #region agent log: call_api entry
    try:
        from urllib.parse import urlparse, parse_qs, urlunparse
        parsed = urlparse(url)
        # redacted: 去掉 key 值，避免在日志中记录敏感信息
        qs = parse_qs(parsed.query, keep_blank_values=True)
        if "key" in qs:
            qs["key"] = ["***"]
        redacted_query = "&".join(f"{k}={v[0]}" for k, v in qs.items())
        redacted_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, redacted_query, parsed.fragment))
    except Exception:
        redacted_url = "parse_error"
    try:
        import time as _t, json as _json, os as _os
        log_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), ".cursor", "debug.log")
        _os.makedirs(_os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as _f:
            _f.write(
                _json.dumps(
                    {
                        "id": f"log_{int(_t.time()*1000)}_call_api_enter",
                        "timestamp": int(_t.time() * 1000),
                        "location": "app/tools/call_api.py:entry",
                        "message": "call_api_enter",
                        "runId": "call_api-debug-1",
                        "hypothesisId": "H-all",
                        "data": {"method": method, "url_redacted": redacted_url},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion agent log: call_api entry

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

        # #region agent log: call_api success
        try:
            import time as _t2, json as _json2, os as _os2
            log_path2 = _os2.path.join(_os2.path.dirname(_os2.path.dirname(_os2.path.dirname(__file__))), ".cursor", "debug.log")
            _os2.makedirs(_os2.path.dirname(log_path2), exist_ok=True)
            with open(log_path2, "a", encoding="utf-8") as _f2:
                _f2.write(
                    _json2.dumps(
                        {
                            "id": f"log_{int(_t2.time()*1000)}_call_api_success",
                            "timestamp": int(_t2.time() * 1000),
                            "location": "app/tools/call_api.py:success",
                            "message": "call_api_success",
                            "runId": "call_api-debug-1",
                            "hypothesisId": "H-all",
                            "data": {"status_code": resp.status_code, "text_preview": text[:200]},
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:
            pass
        # #endregion agent log: call_api success

        return f"状态码: {resp.status_code}\n\n{text}"
    except httpx.TimeoutException:
        # #region agent log: call_api timeout
        try:
            import time as _t3, json as _json3, os as _os3
            log_path3 = _os3.path.join(_os3.path.dirname(_os3.path.dirname(_os3.path.dirname(__file__))), ".cursor", "debug.log")
            _os3.makedirs(_os3.path.dirname(log_path3), exist_ok=True)
            with open(log_path3, "a", encoding="utf-8") as _f3:
                _f3.write(
                    _json3.dumps(
                        {
                            "id": f"log_{int(_t3.time()*1000)}_call_api_timeout",
                            "timestamp": int(_t3.time() * 1000),
                            "location": "app/tools/call_api.py:except_timeout",
                            "message": "call_api_timeout",
                            "runId": "call_api-debug-1",
                            "hypothesisId": "H-all",
                            "data": {"timeout_sec": timeout_sec},
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:
            pass
        # #endregion agent log: call_api timeout
        return f"错误：请求超时（{timeout_sec} 秒）。"
    except Exception as e:
        # #region agent log: call_api error
        try:
            import time as _t4, json as _json4, os as _os4
            log_path4 = _os4.path.join(_os4.path.dirname(_os4.path.dirname(_os4.path.dirname(__file__))), ".cursor", "debug.log")
            _os4.makedirs(_os4.path.dirname(log_path4), exist_ok=True)
            with open(log_path4, "a", encoding="utf-8") as _f4:
                _f4.write(
                    _json4.dumps(
                        {
                            "id": f"log_{int(_t4.time()*1000)}_call_api_error",
                            "timestamp": int(_t4.time() * 1000),
                            "location": "app/tools/call_api.py:except_error",
                            "message": "call_api_error",
                            "runId": "call_api-debug-1",
                            "hypothesisId": "H-all",
                            "data": {"error_type": type(e).__name__, "error_msg": str(e)[:200]},
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:
            pass
        # #endregion agent log: call_api error
        err_str = str(e)
        if "protocol" in err_str.lower() and ("missing" in err_str.lower() or "http" in err_str.lower()):
            return (
                f"错误：请求失败 - {e}\n\n"
                "提示：call_api 的 url 需包含 http:// 或 https://。若您要**生成图片**，请使用 run_skill_script（script_path=generate_image.py）或 volces-icon_generate_app_icon，不要用 call_api。"
            )
        if "nodename" in err_str or "not known" in err_str or getattr(e, "errno", None) == 8:
            return (
                "错误：无法解析请求的域名（网络或 DNS 异常）。请检查本机网络、代理或防火墙。\n\n"
                "若您要**生成图片**，请改用 run_skill_script（script_path=generate_image.py）或 volces-icon_generate_app_icon，不要用 call_api 请求外部 URL。"
            )
        return f"错误：请求失败 - {e}"
