#!/usr/bin/env python3
"""抓取 URL 并提取网页中心正文，供 run_skill_script 调用。

当 fetch_fetch（MCP）抓不到或不可用时，可用本脚本作为备选：直接请求 URL，
用 trafilatura 提取标题与正文，输出 JSON 供后续「整理思想」使用。

stdin：JSON 字符串，如 {"url": "https://...", "max_chars": 50000}。max_chars 可选，默认 100000。
stdout：JSON 字符串，成功时 {"title": "...", "text": "...", "url": "..."}，失败时 {"error": "..."}。
"""
import json
import sys

try:
    import httpx
except ImportError:
    print(json.dumps({"error": "缺少依赖：httpx。请安装 pip install httpx"}, ensure_ascii=False))
    sys.exit(1)

try:
    import trafilatura
except ImportError:
    print(json.dumps({"error": "缺少依赖：trafilatura。请安装 pip install trafilatura"}, ensure_ascii=False))
    sys.exit(1)


def main() -> None:
    raw = (sys.stdin.read() or "").strip() or "{}"
    try:
        obj = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"input_json 不是合法 JSON: {e}"}, ensure_ascii=False))
        sys.exit(1)

    url = (obj.get("url") or "").strip()
    if not url:
        print(json.dumps({"error": "缺少必填参数 url。input_json 示例: {\"url\": \"https://...\"}"}, ensure_ascii=False))
        sys.exit(1)
    if not url.startswith(("http://", "https://")):
        print(json.dumps({"error": "url 必须以 http:// 或 https:// 开头"}, ensure_ascii=False))
        sys.exit(1)

    max_chars = int(obj.get("max_chars") or 100000)
    if max_chars <= 0 or max_chars > 500000:
        max_chars = 100000

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; EchoTwin/1.0; +https://github.com)",
            },
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPStatusError as e:
        print(json.dumps({"error": f"HTTP 错误 {e.response.status_code}: {url}"}, ensure_ascii=False))
        sys.exit(1)
    except httpx.RequestError as e:
        print(json.dumps({"error": f"请求失败: {e!s}"}, ensure_ascii=False))
        sys.exit(1)

    # 提取正文与标题（trafilatura 会去掉导航、评论等，保留中心文字）
    try:
        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            output_format="txt",
            no_fallback=False,
        )
        metadata = trafilatura.extract_metadata(html, url)
        title = (metadata and metadata.title) or ""
        title = (title or "").strip()
        text = (text or "").strip()
        if not text:
            print(
                json.dumps(
                    {"error": "未能从该页面提取到正文，可能不是文章页或结构不被支持", "url": url},
                    ensure_ascii=False,
                )
            )
            sys.exit(1)

        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[正文已截断，仅保留前 {} 字]".format(max_chars)

        out = {"title": title, "text": text, "url": url}
        print(json.dumps(out, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": f"提取正文时出错: {e!s}", "url": url}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
