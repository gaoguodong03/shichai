"""Normalize structured tool responses and persist binary artifacts in the active workspace."""
from __future__ import annotations

import base64
import binascii
import io
import os
import tempfile
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import filetype
from mcp.types import BlobResourceContents, CallToolResult, EmbeddedResource, ImageContent, TextContent
from PIL import Image, UnidentifiedImageError

from app.api.files import get_workspace_root_path
from app.tools.call_api import HttpToolResponse


_DEFAULT_MAX_BYTES = 20 * 1024 * 1024
_IMAGE_MIME_PREFIX = "image/"


def _max_artifact_bytes() -> int:
    try:
        return max(1, int(os.getenv("TOOL_ARTIFACT_MAX_BYTES", str(_DEFAULT_MAX_BYTES))))
    except ValueError:
        return _DEFAULT_MAX_BYTES


def _decode_base64(value: str) -> bytes:
    try:
        return base64.b64decode(str(value or ""), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("工具返回的产物不是合法 base64 数据") from exc


def _verify_binary(data: bytes, *, declared_mime: str) -> tuple[str, str, str]:
    if not data:
        raise ValueError("工具返回了空产物")
    if len(data) > _max_artifact_bytes():
        raise ValueError(f"工具产物超过大小限制：{len(data)} bytes")

    kind = filetype.guess(data)
    if kind is None:
        if str(declared_mime or "").lower().startswith(_IMAGE_MIME_PREFIX):
            raise ValueError("工具声明为图片，但无法识别有效图片内容")
        raise ValueError("无法根据文件内容识别产物类型")
    actual_mime = str(kind.mime or "application/octet-stream").lower()
    extension = str(kind.extension or "bin").lower()

    declared = str(declared_mime or "").split(";", 1)[0].strip().lower()
    if declared.startswith(_IMAGE_MIME_PREFIX) and not actual_mime.startswith(_IMAGE_MIME_PREFIX):
        raise ValueError("工具声明为图片，但返回内容不是有效图片")

    artifact_type = "image" if actual_mime.startswith(_IMAGE_MIME_PREFIX) else "file"
    if artifact_type == "image":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombWarning) as exc:
            raise ValueError("工具返回的图片内容校验失败") from exc

    return actual_mime, extension, artifact_type


def _artifact_subdir(artifact_type: str) -> str:
    return "generated_images" if artifact_type == "image" else "tool_artifacts"


def _write_workspace_artifact(
    data: bytes,
    *,
    workspace_id: str,
    declared_mime: str,
) -> dict[str, str]:
    actual_mime, extension, artifact_type = _verify_binary(data, declared_mime=declared_mime)
    workspace_root = get_workspace_root_path(workspace_id).resolve()
    output_dir = (workspace_root / _artifact_subdir(artifact_type)).resolve()
    output_dir.relative_to(workspace_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    display_prefix = "图片" if artifact_type == "image" else "文件"
    filename = f"{display_prefix}-{timestamp}-{uuid4().hex[:8]}.{extension}"
    target = output_dir / filename

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".artifact-", dir=output_dir, delete=False) as temp_file:
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)

    if not target.is_file() or target.stat().st_size != len(data):
        target.unlink(missing_ok=True)
        raise ValueError("工具产物写入工作区后校验失败")

    relative_path = target.relative_to(workspace_root).as_posix()
    return {
        "type": artifact_type,
        "name": filename,
        "path": relative_path,
        "mime_type": actual_mime,
    }


def _checkpoint_workspace(workspace_id: str) -> None:
    try:
        from app.session_state.service import capture_session_checkpoint

        capture_session_checkpoint(workspace_id, trigger="workspace_changed", force=True)
    except Exception:
        # 产物已经持久化；checkpoint 失败不应伪装成工具执行失败。
        return


def _public_artifact(artifact: dict[str, str]) -> dict[str, str]:
    return {key: artifact[key] for key in ("type", "name", "path")}


def _sanitize_structured_content(value: Any) -> Any:
    """Remove protocol-level binary copies after they have been persisted as artifacts."""
    if isinstance(value, list):
        items = [_sanitize_structured_content(item) for item in value]
        return [item for item in items if item is not None]
    if not isinstance(value, dict):
        return value

    block_type = str(value.get("type") or "").strip().lower()
    if block_type in {"image", "audio"} and "data" in value:
        return None

    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        if key == "blob" and str(value.get("mimeType") or value.get("mime_type") or "").strip():
            continue
        cleaned = _sanitize_structured_content(item)
        if cleaned is not None:
            sanitized[str(key)] = cleaned
    return sanitized


def _ingest_mcp_result(raw_result: CallToolResult, *, workspace_id: str) -> dict[str, Any]:
    texts: list[str] = []
    artifacts: list[dict[str, str]] = []
    errors: list[str] = []

    for block in raw_result.content or []:
        if isinstance(block, TextContent):
            text = str(block.text or "").strip()
            if text:
                texts.append(text)
            continue
        try:
            if isinstance(block, ImageContent):
                artifact = _write_workspace_artifact(
                    _decode_base64(block.data),
                    workspace_id=workspace_id,
                    declared_mime=block.mimeType,
                )
                artifacts.append(_public_artifact(artifact))
            elif isinstance(block, EmbeddedResource) and isinstance(block.resource, BlobResourceContents):
                artifact = _write_workspace_artifact(
                    _decode_base64(block.resource.blob),
                    workspace_id=workspace_id,
                    declared_mime=str(block.resource.mimeType or ""),
                )
                artifacts.append(_public_artifact(artifact))
        except ValueError as exc:
            errors.append(str(exc))

    if artifacts:
        _checkpoint_workspace(workspace_id)
    if not texts and artifacts:
        texts.append(f"工具已返回并保存 {len(artifacts)} 个产物。")
    if errors:
        texts.append("；".join(errors))

    status = "failed" if raw_result.isError or (errors and not artifacts) else "succeeded"
    content = "\n".join(texts).strip() or ("工具执行失败。" if status == "failed" else "工具执行完成。")
    payload: dict[str, Any] = {
        "execution_status": status,
        "content": content,
        "artifacts": artifacts,
    }
    if isinstance(raw_result.structuredContent, dict):
        structured = _sanitize_structured_content(raw_result.structuredContent)
        if isinstance(structured, dict) and structured:
            payload["json_data"] = structured
    return payload


def _ingest_http_result(raw_result: HttpToolResponse, *, workspace_id: str) -> dict[str, Any] | str:
    content_type = str(raw_result.content_type or "").split(";", 1)[0].strip().lower()
    textual_markers = ("json", "xml", "html", "javascript", "x-www-form-urlencoded")
    is_textual = content_type.startswith("text/") or any(marker in content_type for marker in textual_markers)
    detected_kind = filetype.guess(raw_result.body)
    if is_textual or detected_kind is None:
        return raw_result.to_model_text()
    try:
        artifact = _write_workspace_artifact(
            raw_result.body,
            workspace_id=workspace_id,
            declared_mime=content_type,
        )
    except ValueError as exc:
        return {"execution_status": "failed", "content": str(exc), "artifacts": []}
    _checkpoint_workspace(workspace_id)
    artifact_label = "图片" if artifact["type"] == "image" else "文件"
    return {
        "execution_status": "succeeded" if 200 <= raw_result.status_code < 400 else "failed",
        "content": f"HTTP {raw_result.status_code} 返回{artifact_label}，已保存到当前工作区。",
        "artifacts": [_public_artifact(artifact)],
        "json_data": {"status_code": raw_result.status_code, "content_type": content_type, "url": raw_result.url},
    }


async def ingest_tool_result(raw_result: object, *, workspace_id: str) -> object:
    """Persist protocol-level binary content without relying on tool names or tool configuration."""
    wid = str(workspace_id or "").strip()
    if not wid:
        return raw_result
    if isinstance(raw_result, CallToolResult):
        return _ingest_mcp_result(raw_result, workspace_id=wid)
    if isinstance(raw_result, HttpToolResponse):
        return _ingest_http_result(raw_result, workspace_id=wid)
    return raw_result
