from app.mcp.tool_arg_normalizers import normalize_mcp_tool_kwargs


def test_mcp_arg1_maps_only_for_single_field_schema():
    out = normalize_mcp_tool_kwargs(
        "exa",
        "search",
        {"__arg1": "智能软件工程"},
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    )

    assert out == {"query": "智能软件工程"}


def test_mcp_arg1_is_not_mapped_for_multi_field_schema():
    out = normalize_mcp_tool_kwargs(
        "amap-maps",
        "maps_geo",
        {"__arg1": "北京大学,北京"},
        {
            "type": "object",
            "properties": {"address": {"type": "string"}, "city": {"type": "string"}},
            "required": ["address"],
        },
    )

    assert out == {}


def test_mcp_arg1_is_not_mapped_without_schema():
    out = normalize_mcp_tool_kwargs("file-reader", "read_file", {"__arg1": "notes/a.md"}, None)

    assert out == {}


def test_mcp_specific_aliases_do_not_replace_schema_fields():
    out = normalize_mcp_tool_kwargs(
        "volces-icon",
        "generate_app_icon",
        {"prompt": "生成图标", "__arg1": "兜底提示"},
        {
            "type": "object",
            "properties": {"description": {"type": "string"}, "pic_size": {"type": "string"}},
            "required": ["description"],
        },
    )

    assert "description" not in out
    assert "__arg1" not in out
