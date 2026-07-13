import base64
from pathlib import Path

import pytest
from mcp.types import BlobResourceContents, CallToolResult, EmbeddedResource, ImageContent, TextContent


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture
def runtime_user(tmp_path, monkeypatch):
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-artifacts", username="artifact-user")
    try:
        yield
    finally:
        reset_current_user_identity(token)


@pytest.mark.asyncio
async def test_mcp_image_content_is_saved_to_current_session_workspace(runtime_user):
    from app.agent.tool_artifact_ingestion import ingest_tool_result
    from app.api.files import get_workspace_root_path

    raw = CallToolResult(
        content=[
            TextContent(type="text", text="图片生成完成"),
            ImageContent(
                type="image",
                data=base64.b64encode(_ONE_PIXEL_PNG).decode("ascii"),
                mimeType="image/png",
            ),
        ]
    )

    result = await ingest_tool_result(raw, workspace_id="group-artifacts")

    assert result["execution_status"] == "succeeded"
    assert result["content"] == "图片生成完成"
    assert len(result["artifacts"]) == 1
    artifact = result["artifacts"][0]
    assert artifact["type"] == "image"
    assert artifact["path"].startswith("generated_images/")
    saved = get_workspace_root_path("group-artifacts") / artifact["path"]
    assert saved.read_bytes() == _ONE_PIXEL_PNG


@pytest.mark.asyncio
async def test_mcp_image_ingestion_does_not_depend_on_tool_name(runtime_user):
    from app.agent.tool_artifact_ingestion import ingest_tool_result

    raw = CallToolResult(
        content=[
            ImageContent(
                type="image",
                data=base64.b64encode(_ONE_PIXEL_PNG).decode("ascii"),
                mimeType="image/png",
            )
        ]
    )

    first = await ingest_tool_result(raw, workspace_id="group-a")
    second = await ingest_tool_result(raw, workspace_id="group-b")

    assert first["artifacts"][0]["path"].startswith("generated_images/")
    assert second["artifacts"][0]["path"].startswith("generated_images/")


@pytest.mark.asyncio
async def test_mcp_structured_content_does_not_repeat_binary_payload(runtime_user):
    from app.agent.tool_artifact_ingestion import ingest_tool_result

    encoded = base64.b64encode(_ONE_PIXEL_PNG).decode("ascii")
    raw = CallToolResult(
        content=[ImageContent(type="image", data=encoded, mimeType="image/png")],
        structuredContent={
            "result": [
                {"type": "text", "text": "图片生成完成。"},
                {"type": "image", "data": encoded, "mimeType": "image/png"},
            ]
        },
    )

    result = await ingest_tool_result(raw, workspace_id="group-no-binary-copy")

    assert encoded not in str(result)
    assert result.get("json_data") == {"result": [{"type": "text", "text": "图片生成完成。"}]}


@pytest.mark.asyncio
async def test_http_image_response_is_saved_without_tool_configuration(runtime_user):
    from app.agent.tool_artifact_ingestion import ingest_tool_result
    from app.api.files import get_workspace_root_path
    from app.tools.call_api import HttpToolResponse

    raw = HttpToolResponse(
        status_code=200,
        content_type="image/png",
        body=_ONE_PIXEL_PNG,
        url="https://images.example.test/generated.png",
    )

    result = await ingest_tool_result(raw, workspace_id="group-http-image")

    assert result["execution_status"] == "succeeded"
    assert len(result["artifacts"]) == 1
    artifact = result["artifacts"][0]
    saved = get_workspace_root_path("group-http-image") / artifact["path"]
    assert saved.read_bytes() == _ONE_PIXEL_PNG


@pytest.mark.asyncio
async def test_http_binary_file_response_is_saved_without_tool_configuration(runtime_user):
    from app.agent.tool_artifact_ingestion import ingest_tool_result
    from app.api.files import get_workspace_root_path
    from app.tools.call_api import HttpToolResponse

    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
    raw = HttpToolResponse(
        status_code=200,
        content_type="application/pdf",
        body=pdf,
        url="https://files.example.test/report.pdf",
    )

    result = await ingest_tool_result(raw, workspace_id="group-http-file")

    artifact = result["artifacts"][0]
    assert artifact["type"] == "file"
    assert artifact["path"].startswith("tool_artifacts/")
    saved = get_workspace_root_path("group-http-file") / artifact["path"]
    assert saved.read_bytes() == pdf


@pytest.mark.asyncio
async def test_mcp_embedded_binary_resource_is_saved_as_workspace_file(runtime_user):
    from app.agent.tool_artifact_ingestion import ingest_tool_result
    from app.api.files import get_workspace_root_path

    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
    raw = CallToolResult(
        content=[
            EmbeddedResource(
                type="resource",
                resource=BlobResourceContents(
                    uri="file:///report.pdf",
                    mimeType="application/pdf",
                    blob=base64.b64encode(pdf).decode("ascii"),
                ),
            )
        ]
    )

    result = await ingest_tool_result(raw, workspace_id="group-mcp-file")

    artifact = result["artifacts"][0]
    assert artifact["type"] == "file"
    assert artifact["path"].startswith("tool_artifacts/")
    saved = get_workspace_root_path("group-mcp-file") / artifact["path"]
    assert saved.read_bytes() == pdf


@pytest.mark.asyncio
async def test_invalid_image_payload_is_not_published_as_artifact(runtime_user):
    from app.agent.tool_artifact_ingestion import ingest_tool_result

    raw = CallToolResult(
        content=[ImageContent(type="image", data=base64.b64encode(b"not-an-image").decode("ascii"), mimeType="image/png")]
    )

    result = await ingest_tool_result(raw, workspace_id="group-invalid-image")

    assert result["execution_status"] == "failed"
    assert result["artifacts"] == []
    assert "图片" in result["content"]


def test_no_tool_name_specific_image_workspace_injection_remains():
    runtime_path = Path(__file__).resolve().parents[1] / "app" / "agent" / "skill_agent_runtime.py"
    source = runtime_path.read_text(encoding="utf-8")

    assert "image-generation_generate_image" not in source
    assert "_apply_image_generation_workspace_id" not in source


def test_builtin_image_mcp_returns_standard_image_content_without_workspace_parameters(monkeypatch):
    from app.mcp.stdio import image_generation

    data_url = "data:image/png;base64," + base64.b64encode(_ONE_PIXEL_PNG).decode("ascii")
    monkeypatch.setattr(image_generation, "_generate_image", lambda **_kwargs: data_url)

    result = image_generation.generate_image(description="一张测试图片", pic_size="1024x1024")

    assert isinstance(result, list)
    assert any(isinstance(block, ImageContent) for block in result)
    assert "workspace_id" not in image_generation.generate_image.__annotations__


@pytest.mark.asyncio
async def test_mcp_tool_spec_preserves_structured_call_result(monkeypatch):
    from types import SimpleNamespace

    import app.mcp.manager as mcp_manager

    raw = CallToolResult(
        content=[
            TextContent(type="text", text="done"),
            ImageContent(
                type="image",
                data=base64.b64encode(_ONE_PIXEL_PNG).decode("ascii"),
                mimeType="image/png",
            ),
        ]
    )

    async def fake_execute_mcp_call(**_kwargs):
        return True, raw, ""

    monkeypatch.setattr(mcp_manager, "execute_mcp_call", fake_execute_mcp_call)
    manager = mcp_manager.MCPToolManager()
    tool = manager._create_tool_spec(
        SimpleNamespace(name="generate", description="generate", inputSchema={"type": "object", "properties": {}}),
        session="session",
        server_name="server",
    )

    result = await tool.acall()

    assert result is raw


@pytest.mark.asyncio
async def test_skill_runtime_ingests_structured_mcp_result_before_prompting(runtime_user):
    from app.agent.messages import AIMessage
    from app.agent.skill_agent_runtime import _call_tool_impl
    from app.agent.tool_spec import ToolSpec

    async def execute() -> CallToolResult:
        return CallToolResult(
            content=[
                TextContent(type="text", text="生成结束"),
                ImageContent(
                    type="image",
                    data=base64.b64encode(_ONE_PIXEL_PNG).decode("ascii"),
                    mimeType="image/png",
                ),
            ]
        )

    tool = ToolSpec.from_function(name="third_party_generate", description="generate", coroutine=execute)
    tool.metadata.update({"source": "mcp", "provider": "third-party", "provider_tool": "generate"})
    state = {
        "messages": [AIMessage(content="", tool_calls=[{"id": "call-image", "name": tool.name, "args": {}}])],
        "tools": [tool],
        "workspace_id": "group-runtime-image",
    }

    output = await _call_tool_impl(state, [tool])

    record = output["tool_results"][0]
    assert record["output"]["content"] == "生成结束"
    assert len(record["output"]["artifacts"]) == 1
    assert "generated_images/" in output["messages"][0].content
    assert "iVBOR" not in output["messages"][0].content
