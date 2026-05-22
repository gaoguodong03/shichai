from __future__ import annotations

import json
from pathlib import Path

import httpx


def _run_call_api(mod, **kwargs):
    tool_obj = mod.call_api
    if hasattr(tool_obj, "func"):
        return tool_obj.func(**kwargs)
    return tool_obj.invoke(kwargs)


def test_ssrf_guard_blocks_localhost():
    from app.tools import call_api as mod

    out = _run_call_api(mod, url="http://localhost:8000/health")
    assert "错误" in out
    assert "SSRF" in out


def test_call_api_json_success_with_scheme_autofill(monkeypatch):
    from app.tools import call_api as mod

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"ok":true}'

        @staticmethod
        def json():
            return {"ok": True, "source": "unit-test"}

    called = {}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def request(self, method, url, content=None, headers=None):
            called["method"] = method
            called["url"] = url
            called["content"] = content
            called["headers"] = headers
            return _Resp()

    monkeypatch.setattr(mod.httpx, "Client", _Client)
    out = _run_call_api(mod, url="example.com/api", method="post", body='{"x":1}')
    assert called["method"] == "POST"
    assert called["url"] == "https://example.com/api"
    assert "状态码: 200" in out
    assert '"ok": true' in out
    assert '"source": "unit-test"' in out


def test_call_api_returns_timeout_message(monkeypatch):
    from app.tools import call_api as mod

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def request(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(mod.httpx, "Client", _Client)
    out = _run_call_api(mod, url="https://example.com")
    assert "请求超时" in out


def test_call_api_rejects_invalid_headers_json():
    from app.tools import call_api as mod

    out = _run_call_api(mod, url="https://example.com", headers_json="{bad-json")
    assert "headers_json 不是合法 JSON" in out


def test_format_non_json_html_plaintext_fallback(monkeypatch):
    from app.tools import call_api as mod

    monkeypatch.setenv("CALL_API_HTML_EXTRACT", "0")
    monkeypatch.setenv("CALL_API_MIN_PLAINTEXT_CHARS", "1")
    html = "<html><body><h1>标题</h1><p>正文内容</p></body></html>"
    out = mod._format_non_json_body(html, "text/html", "https://example.com")
    assert "智能正文提取未命中" in out
    assert "标题 正文内容" in out


def test_call_api_accepts_json_string_as_url_object(monkeypatch):
    from app.tools import call_api as mod

    class _Resp:
        status_code = 201
        headers = {"content-type": "application/json"}
        text = '{"created":true}'

        @staticmethod
        def json():
            return {"created": True}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def request(self, method, url, content=None, headers=None):
            assert method == "PUT"
            assert url == "https://example.com/obj"
            assert headers == {"X-A": "1"}
            assert json.loads(content) == {"k": "v"}
            return _Resp()

    monkeypatch.setattr(mod.httpx, "Client", _Client)
    packed = json.dumps(
        {"url": "https://example.com/obj", "method": "PUT", "headers": {"X-A": "1"}, "body": {"k": "v"}},
        ensure_ascii=False,
    )
    out = _run_call_api(mod, url=packed)
    assert "状态码: 201" in out


def test_call_api_does_not_write_cursor_debug_log(monkeypatch):
    from app.tools import call_api as mod

    debug_log = Path(mod.__file__).resolve().parents[2] / ".cursor" / "debug.log"
    if debug_log.exists():
        debug_log.unlink()

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"ok":true}'

        @staticmethod
        def json():
            return {"ok": True}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def request(self, method, url, content=None, headers=None):
            return _Resp()

    monkeypatch.setattr(mod.httpx, "Client", _Client)
    out = _run_call_api(mod, url="https://example.com/api")

    assert "状态码: 200" in out
    assert not debug_log.exists()
