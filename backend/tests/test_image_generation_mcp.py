from __future__ import annotations

import base64

import pytest
import httpx
from mcp.types import ImageContent, TextContent

from app.mcp.stdio import image_generation
from app.tools import chatanywhere_image_cli_lib


def test_get_api_key_prefers_jeniya_specific_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CHATANYWHERE_IMAGE_API_KEY", "fallback-key")
    monkeypatch.setenv("JENIYA_API_KEY", "jeniya-key")

    assert image_generation.get_api_key() == "Bearer jeniya-key"


def test_get_api_key_requires_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("JENIYA_API_KEY", raising=False)
    monkeypatch.delenv("CHATANYWHERE_IMAGE_API_KEY", raising=False)

    with pytest.raises(ValueError, match="JENIYA_API_KEY"):
        image_generation.get_api_key()


def test_get_api_key_ignores_legacy_chatanywhere_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("JENIYA_API_KEY", raising=False)
    monkeypatch.setenv("CHATANYWHERE_IMAGE_API_KEY", "legacy-key")

    with pytest.raises(ValueError, match="JENIYA_API_KEY"):
        image_generation.get_api_key()


def test_generate_image_returns_standard_mcp_content_without_saving(
    monkeypatch: pytest.MonkeyPatch,
):
    image_b64 = base64.b64encode(b"fake-png").decode("ascii")

    monkeypatch.setattr(
        image_generation,
        "_generate_image",
        lambda *, description, pic_size: f"data:image/png;base64,{image_b64}",
    )

    result = image_generation.generate_image(
        description="古风少年站在雪夜山门前",
        pic_size="1024x1024",
    )

    assert isinstance(result[0], TextContent)
    assert result[0].text == "图片生成完成。"
    assert isinstance(result[1], ImageContent)
    assert result[1].mimeType == "image/png"
    assert result[1].data == image_b64


def test_generate_image_reports_upstream_http_error_as_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        image_generation,
        "_generate_image",
        lambda *, description, pic_size: "请求失败 HTTP 301: <html>Moved Permanently</html>",
    )

    with pytest.raises(RuntimeError, match="请求失败 HTTP 301"):
        image_generation.generate_image(description="雪夜山门", pic_size="1024x1024")


def test_chatanywhere_image_default_base_uses_https(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("JENIYA_IMAGE_BASE_URL", raising=False)
    monkeypatch.delenv("JENIYA_IMAGE_MODEL", raising=False)

    assert chatanywhere_image_cli_lib._api_url().startswith("https://jeniya.top/")


def test_chatanywhere_image_upgrades_legacy_jeniya_http_base(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JENIYA_IMAGE_BASE_URL", "http://jeniya.top")
    monkeypatch.delenv("JENIYA_IMAGE_MODEL", raising=False)

    assert chatanywhere_image_cli_lib._api_url().startswith("https://jeniya.top/")


def test_chatanywhere_image_retries_remote_disconnect(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JENIYA_API_KEY", "key")
    monkeypatch.delenv("CHATANYWHERE_IMAGE_API_KEY", raising=False)

    calls = {"count": 0}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "image/png",
                                            "data": "ZmFrZQ==",
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", "https://jeniya.top"),
            )

    monkeypatch.setattr(chatanywhere_image_cli_lib.httpx, "Client", FakeClient)

    result = chatanywhere_image_cli_lib.generate_image("河南烩面", "1024x1792")

    assert calls["count"] == 2
    assert result == "data:image/png;base64,ZmFrZQ=="


def test_chatanywhere_image_posts_with_jeniya_authorization_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JENIYA_API_KEY", "key")
    monkeypatch.setenv("CHATANYWHERE_IMAGE_API_KEY", "legacy-key")

    seen = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            seen["headers"] = kwargs.get("headers")
            seen["body"] = kwargs.get("json")
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "image/png",
                                            "data": "ZmFrZQ==",
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", "https://jeniya.top"),
            )

    monkeypatch.setattr(chatanywhere_image_cli_lib.httpx, "Client", FakeClient)

    result = chatanywhere_image_cli_lib.generate_image("河南烩面", "1024x1792")

    assert result == "data:image/png;base64,ZmFrZQ=="
    assert seen["headers"] == {"Authorization": "Bearer key"}
    assert seen["body"]["contents"][0]["parts"][0]["text"] == (
        "河南烩面\n\n请生成尺寸约为 1024x1792 的图片，输出图像内容。"
    )


def test_chatanywhere_image_reports_remote_disconnect_after_retries(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JENIYA_API_KEY", "key")
    monkeypatch.delenv("CHATANYWHERE_IMAGE_API_KEY", raising=False)
    monkeypatch.delenv("JENIYA_IMAGE_MAX_ATTEMPTS", raising=False)

    calls = {"count": 0}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            calls["count"] += 1
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    monkeypatch.setattr(chatanywhere_image_cli_lib.httpx, "Client", FakeClient)

    result = chatanywhere_image_cli_lib.generate_image("河南胡辣汤", "1024x1792")

    assert calls["count"] == 2
    assert result == "请求失败（网络连接异常，已尝试 2 次）: Server disconnected without sending a response."
