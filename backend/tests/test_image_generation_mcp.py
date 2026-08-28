from __future__ import annotations

import base64

import httpx
import pytest
from mcp.types import ImageContent, TextContent

from app.mcp.stdio import image_generation


PNG_BYTES = b"\x89PNG\r\n\x1a\nimage-data"
PNG_B64 = base64.b64encode(PNG_BYTES).decode("ascii")


def test_get_api_key_returns_bearer_value(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")

    assert image_generation.get_api_key() == "Bearer image-key"


def test_get_api_key_preserves_existing_bearer_prefix(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "Bearer image-key")

    assert image_generation.get_api_key() == "Bearer image-key"


def test_get_api_key_requires_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("IMAGE_GENERATION_API_KEY", raising=False)

    with pytest.raises(ValueError, match="IMAGE_GENERATION_API_KEY"):
        image_generation.get_api_key()


def test_default_api_url_uses_quanzil(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("IMAGE_GENERATION_BASE_URL", raising=False)

    assert image_generation._api_url() == "https://quanzil.com/v1/images/generations"


def test_api_url_accepts_base_or_full_endpoint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IMAGE_GENERATION_BASE_URL", "https://example.com/v1/")
    assert image_generation._api_url() == "https://example.com/v1/images/generations"

    monkeypatch.setenv(
        "IMAGE_GENERATION_BASE_URL",
        "https://example.com/v1/images/generations",
    )
    assert image_generation._api_url() == "https://example.com/v1/images/generations"


def test_generate_image_posts_openai_compatible_payload(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "key")
    seen: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, **kwargs):
            seen["url"] = url
            seen["headers"] = kwargs.get("headers")
            seen["body"] = kwargs.get("json")
            return httpx.Response(
                200,
                json={"data": [{"b64_json": PNG_B64}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(image_generation.httpx, "Client", FakeClient)

    mime_type, image_data = image_generation._generate_image(
        description="夕阳下霓虹闪烁的未来都市天际线",
        pic_size="1024x1024",
    )

    assert mime_type == "image/png"
    assert image_data == PNG_B64
    assert seen["url"] == "https://quanzil.com/v1/images/generations"
    assert seen["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer key",
    }
    assert seen["body"] == {
        "model": "gpt-image-2-c:stable",
        "prompt": "夕阳下霓虹闪烁的未来都市天际线",
        "size": "1024x1024",
    }


def test_generate_image_downloads_url_response(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "key")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"data": [{"url": "https://cdn.example.com/generated.png"}]},
                request=httpx.Request("POST", url),
            )

        def get(self, url):
            return httpx.Response(
                200,
                content=PNG_BYTES,
                headers={"content-type": "image/png"},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(image_generation.httpx, "Client", FakeClient)

    assert image_generation._generate_image(
        description="未来都市",
        pic_size="1024x1024",
    ) == ("image/png", PNG_B64)


def test_generate_image_retries_remote_disconnect(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "key")
    monkeypatch.delenv("IMAGE_GENERATION_MAX_ATTEMPTS", raising=False)
    calls = {"count": 0}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.RemoteProtocolError("Server disconnected")
            return httpx.Response(
                200,
                json={"data": [{"b64_json": PNG_B64}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(image_generation.httpx, "Client", FakeClient)

    assert image_generation._generate_image(
        description="河南烩面",
        pic_size="1024x1024",
    ) == ("image/png", PNG_B64)
    assert calls["count"] == 2


def test_generate_image_reports_upstream_http_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "key")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, **kwargs):
            return httpx.Response(
                401,
                json={"error": "invalid token"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(image_generation.httpx, "Client", FakeClient)

    with pytest.raises(RuntimeError, match="图片生成请求失败 HTTP 401"):
        image_generation._generate_image(description="雪夜山门", pic_size="1024x1024")


def test_mcp_tool_returns_standard_content_without_saving(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        image_generation,
        "_generate_image",
        lambda *, description, pic_size: ("image/png", PNG_B64),
    )

    result = image_generation.generate_image(
        description="古风少年站在雪夜山门前",
        pic_size="1024x1024",
    )

    assert isinstance(result[0], TextContent)
    assert result[0].text == "图片生成完成。"
    assert isinstance(result[1], ImageContent)
    assert result[1].mimeType == "image/png"
    assert result[1].data == PNG_B64
