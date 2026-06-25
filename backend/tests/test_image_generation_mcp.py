from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest
import httpx

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


def test_generate_image_saves_data_url_to_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    workspace_root = tmp_path / "users" / "u1" / "sessions" / "workspaces" / "s1"
    image_b64 = base64.b64encode(b"fake-png").decode("ascii")

    monkeypatch.setattr(image_generation, "get_workspace_root_path", lambda workspace_id: workspace_root)
    monkeypatch.setattr(
        image_generation,
        "_generate_image",
        lambda *, description, pic_size: f"data:image/png;base64,{image_b64}",
    )

    result = json.loads(
        image_generation.generate_image(
            description="古风少年站在雪夜山门前",
            pic_size="1024x1024",
            workspace_id="s1",
        )
    )

    artifacts = result["artifacts"]
    assert result["execution_status"] == "succeeded"
    assert artifacts["file_path"].startswith("generated_images/image-")
    assert re.match(r"^generated_images/image-\d{16}-[0-9a-f]{8}\.png$", artifacts["file_path"])
    assert not re.search(r"\d{8}-\d{6}", artifacts["file_path"])
    assert artifacts["file_path"].endswith(".png")
    assert artifacts["download_url"] == f"/api/workspaces/s1/files/download?path={artifacts['file_path']}"
    assert artifacts["output"] == artifacts["download_url"]
    assert artifacts["markdown"] == f"![生成图片]({artifacts['download_url']})"
    assert (workspace_root / artifacts["file_path"]).read_bytes() == b"fake-png"


def test_generate_image_without_workspace_uses_single_generated_images_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    image_b64 = base64.b64encode(b"fake-jpg").decode("ascii")

    monkeypatch.setattr(image_generation, "DEFAULT_OUTPUT_ROOT", tmp_path / "data")
    monkeypatch.setattr(
        image_generation,
        "_generate_image",
        lambda *, description, pic_size: f"data:image/jpeg;base64,{image_b64}",
    )

    result = json.loads(
        image_generation.generate_image(
            description="河南胡辣汤封面",
            pic_size="1024x1792",
            workspace_id="",
        )
    )

    artifacts = result["artifacts"]
    assert result["execution_status"] == "succeeded"
    assert artifacts["file_path"].startswith("generated_images/image-")
    assert "/generated_images/generated_images/" not in artifacts["local_path"]
    assert (tmp_path / "data" / artifacts["file_path"]).read_bytes() == b"fake-jpg"


def test_generate_image_saves_to_mcp_runtime_user_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    image_b64 = base64.b64encode(b"runtime-user-jpg").decode("ascii")

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    monkeypatch.setenv("ST49_MCP_USER_ID", "user-runtime")
    monkeypatch.setenv("ST49_MCP_USERNAME", "runtime@example.com")
    monkeypatch.setattr(
        image_generation,
        "_generate_image",
        lambda *, description, pic_size: f"data:image/jpeg;base64,{image_b64}",
    )

    result = json.loads(
        image_generation.generate_image(
            description="河南烩面封面",
            pic_size="1024x1792",
            workspace_id="group-runtime",
        )
    )

    expected = (
        tmp_path
        / "users"
        / "user-runtime"
        / "sessions"
        / "workspaces"
        / "group-runtime"
        / result["artifacts"]["file_path"]
    )
    assert result["execution_status"] == "succeeded"
    assert expected.read_bytes() == b"runtime-user-jpg"
    assert not (
        tmp_path
        / "users"
        / "free4inno"
        / "sessions"
        / "workspaces"
        / "group-runtime"
        / result["artifacts"]["file_path"]
    ).exists()


def test_generate_image_reports_upstream_http_error_as_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        image_generation,
        "_generate_image",
        lambda *, description, pic_size: "请求失败 HTTP 301: <html>Moved Permanently</html>",
    )

    result = json.loads(image_generation.generate_image(description="雪夜山门", pic_size="1024x1024"))

    assert result["execution_status"] == "failed"
    assert result["message"] == "请求失败 HTTP 301: <html>Moved Permanently</html>"


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
