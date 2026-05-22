"""调用外部 API / 服务，作为一等步骤能力（专家需开启 url_capability）。"""
import ipaddress
import json
import os
import re
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.agent.tool_spec import ToolSpec


def _looks_like_html(body: str, content_type: str) -> bool:
    ct = (content_type or "").lower()
    if "html" in ct:
        return True
    s = body.lstrip()[:8000]
    if not s:
        return False
    sl = s.lower()
    if sl.startswith("<!doctype html") or sl.startswith("<html"):
        return True
    if "<body" in sl and "<" in s[:400]:
        return True
    # 常见服务端返回无正确 Content-Type 的 HTML 片段
    if s.strip().startswith("<") and ("<div" in sl or "<p" in sl or "<article" in sl) and sl.count("<") > 5:
        return True
    return False


def _trafilatura_try_extract(html: str, page_url: str, **kwargs) -> Optional[str]:
    """单次 trafilatura.extract，参数因版本略有差异时降级重试。"""
    try:
        import trafilatura
    except ImportError:
        return None
    try:
        return trafilatura.extract(html, url=page_url, **kwargs)
    except TypeError:
        kw = {k: v for k, v in kwargs.items() if k in ("include_comments", "include_tables", "include_formatting", "include_links", "favor_recall", "favor_precision")}
        try:
            return trafilatura.extract(html, url=page_url, **kw)
        except Exception:
            return trafilatura.extract(html, url=page_url)


def _extract_html_main_text(html: str, page_url: str) -> Optional[str]:
    """使用 trafilatura 多档策略抽取正文；项目已依赖 trafilatura。"""
    if os.getenv("CALL_API_HTML_EXTRACT", "1").strip() == "0":
        return None
    try:
        import trafilatura
    except ImportError:
        return None

    base_kw = dict(
        include_comments=False,
        include_tables=True,
        include_formatting=False,
        include_links=False,
    )
    attempts: list[dict] = [
        {**base_kw},
        {**base_kw, "favor_recall": True},
        {**base_kw, "favor_recall": True, "include_formatting": True},
    ]
    text: Optional[str] = None
    for extra in attempts:
        try:
            chunk = _trafilatura_try_extract(html, page_url, **extra)
        except Exception:
            chunk = None
        if chunk and str(chunk).strip():
            text = str(chunk).strip()
            break
    if not text:
        return None

    title = ""
    try:
        meta = trafilatura.extract_metadata(html, url=page_url)
        title = (getattr(meta, "title", None) or "").strip() if meta else ""
    except Exception:
        pass

    parts = ["【网页正文提取】以下由 trafilatura 从 HTML 中提取，已去除多数导航与脚本噪声。"]
    if title:
        parts.append(f"标题: {title}")
    parts.append("---")
    parts.append(text)
    return "\n".join(parts)


def _truncate_body(text: str) -> str:
    max_len = int(os.getenv("CALL_API_MAX_RESULT_CHARS", "50000"))
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n\n...[内容已截断，共 {len(text)} 字符；可调大环境变量 CALL_API_MAX_RESULT_CHARS]"


def _html_to_plaintext_fallback(html: str) -> str:
    """trafilatura 未命中时的轻量回退：去掉 script/style 与标签，保留可读纯文本（适合 CSR 壳页面里仍有少量文案）。"""
    max_chars = int(os.getenv("CALL_API_HTML_PLAINTEXT_MAX_CHARS", "6000"))
    s = html
    s = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", s)
    s = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", s)
    s = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", s)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_chars:
        s = s[:max_chars].rstrip() + "…"
    return s


def _format_non_json_body(raw: str, content_type: str, url: str) -> str:
    """非 JSON 时：HTML 优先 trafilatura，其次去标签纯文本；避免把上万字符原始 HTML 塞进模型与 UI。"""
    if _looks_like_html(raw, content_type):
        extracted = _extract_html_main_text(raw, url)
        if extracted:
            return _truncate_body(extracted)

        plain = _html_to_plaintext_fallback(raw)
        min_plain = int(os.getenv("CALL_API_MIN_PLAINTEXT_CHARS", "80"))
        if len(plain) >= min_plain:
            return _truncate_body(
                "【提示】智能正文提取未命中（常见于纯前端渲染、强反爬或需登录页面）。"
                "以下为去除 script/style 与 HTML 标签后的纯文本片段，便于扫一眼；完整内容请在浏览器打开链接。\n---\n"
                + plain
            )

        raw_cap = int(os.getenv("CALL_API_MAX_HTML_RAW_SNIPPET_CHARS", "900"))
        snippet = raw[:raw_cap] if raw else ""
        return (
            "【提示】无法从该页得到可用文本（多为仅含脚本的壳页面或需登录）。"
            f"原始 HTML 前 {min(len(raw), raw_cap)} 字符供排查（勿依赖其可读性）：\n---\n"
            + snippet
            + (f"\n...[共 {len(raw)} 字符，已截断；可调 CALL_API_MAX_HTML_RAW_SNIPPET_CHARS]" if len(raw) > raw_cap else "")
        )
    return _truncate_body(raw)


def _ssrf_block_reason(url: str) -> Optional[str]:
    """阻止访问 obvious 内网/本机目标；域名未解析时无法防御 DNS 重绑定，生产可再加代理白名单。"""
    if os.getenv("CALL_API_DISABLE_SSRF_GUARD", "").strip() == "1":
        return None
    try:
        p = urlparse(url)
    except Exception:
        return "URL 解析失败"
    if p.scheme not in ("http", "https"):
        return "仅允许 http:// 或 https://"
    host = (p.hostname or "").strip().lower()
    if not host:
        return "缺少主机名"
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return "禁止访问本地或回环地址（SSRF 防护）"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return "禁止访问内网或保留地址（SSRF 防护）"
    except ValueError:
        pass
    if host.endswith(".local") or host.endswith(".localhost"):
        return "禁止访问本地域名（SSRF 防护）"
    return None


def _call_api_impl(
    url: str,
    method: str = "GET",
    headers_json: str = "",
    body: str = "",
) -> str:
    """
    调用外部 HTTP API。
    参数：url（必填，需含 http:// 或 https://）；method（GET/POST/PUT/DELETE 等，默认 GET）；
    headers_json（可选，JSON 字符串如 {\"Content-Type\": \"application/json\", \"Authorization\": \"Bearer xxx\"}）；
    body（可选，请求体字符串，POST/PUT 时常用）。
    使用 POST 时请显式传 method=\"POST\"，并设置 headers_json 的 Content-Type 为 application/json，body 为 JSON 字符串。
    当技能说明或脚本要求「调用某接口」「请求某 API」或获取公开网页内容时使用本工具。
    对 HTML 网页响应会自动用 trafilatura 提取正文，减少整页标签噪声；纯 JSON API 仍返回格式化 JSON。
    仅允许访问公网可达的 http(s) URL；内网/本机地址会被拒绝（SSRF 防护）。调试可设 CALL_API_DISABLE_SSRF_GUARD=1（不推荐生产）。
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

    block = _ssrf_block_reason(url)
    if block:
        return f"错误：{block}"

    import os as _os_env
    timeout_sec = float(_os_env.getenv("CALL_API_TIMEOUT", "30"))
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            resp = client.request(method, url, content=body if body else None, headers=headers or None)
        raw = resp.text
        ct = resp.headers.get("content-type", "") or ""
        try:
            data = resp.json()
            text = json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            text = _format_non_json_body(raw, ct, url)

        return f"状态码: {resp.status_code}\n\n{text}"
    except httpx.TimeoutException:
        return f"错误：请求超时（{timeout_sec} 秒）。"
    except Exception as e:
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


call_api = ToolSpec.from_function(
    name="call_api",
    description=(
        "调用外部 HTTP API。url 必填，需含 http:// 或 https://；method 默认 GET；"
        "headers_json 为 JSON 字符串；body 为请求体字符串。对 HTML 响应会尝试提取正文，"
        "仅允许公网 http(s) URL。"
    ),
    func=_call_api_impl,
    args_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "公网 http(s) URL；未带协议时会自动补 https://。",
            },
            "method": {
                "type": "string",
                "description": "HTTP 方法，如 GET、POST、PUT、DELETE，默认 GET。",
                "default": "GET",
            },
            "headers_json": {
                "type": "string",
                "description": "可选请求头 JSON 字符串。",
                "default": "",
            },
            "body": {
                "type": "string",
                "description": "可选请求体字符串，POST/PUT 时常用。",
                "default": "",
            },
        },
        "required": ["url"],
    },
)
