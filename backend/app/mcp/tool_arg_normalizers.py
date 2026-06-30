"""MCP 工具调用参数归一化：按 server_name / tool_name 分发到具体归一化函数，主流程在 manager 中只做一次调用。"""
import json
from typing import Any, Dict, Optional


def _volces_icon_generate_app_icon(call_kwargs: Dict[str, Any]) -> None:
    """volces-icon generate_app_icon：prompt/input/text/content → description，__arg1 → description/pic_size，缺则补空串。"""
    if "description" not in call_kwargs:
        desc = (
            call_kwargs.pop("prompt", None)
            or call_kwargs.pop("input", None)
            or call_kwargs.pop("text", None)
            or call_kwargs.pop("content", None)
        )
        if desc is not None:
            call_kwargs["description"] = str(desc).strip() or ""

    if "__arg1" in call_kwargs and "description" not in call_kwargs:
        arg1 = call_kwargs.pop("__arg1")
        mapped = False
        if isinstance(arg1, str):
            try:
                parsed = json.loads(arg1)
                if isinstance(parsed, dict) and "description" in parsed:
                    call_kwargs["description"] = parsed["description"]
                    if "pic_size" in parsed and "pic_size" not in call_kwargs:
                        call_kwargs["pic_size"] = parsed["pic_size"]
                    mapped = True
            except (ValueError, TypeError):
                pass
        if not mapped:
            call_kwargs["description"] = str(arg1) if arg1 is not None else ""

    if "description" not in call_kwargs:
        call_kwargs["description"] = ""


def _amap_maps_geo(call_kwargs: Dict[str, Any]) -> None:
    """amap-maps maps_geo：__arg1 → address/city（地址,城市 | JSON | 纯地址）。"""
    if "__arg1" not in call_kwargs:
        return
    arg1 = call_kwargs.pop("__arg1", "")
    if isinstance(arg1, str) and "," in arg1 and "city" not in call_kwargs:
        parts = arg1.split(",", 1)
        if len(parts) == 2:
            call_kwargs.setdefault("address", parts[0].strip())
            call_kwargs.setdefault("city", parts[1].strip())
            arg1 = None
    if arg1 is not None:
        try:
            parsed = json.loads(arg1) if isinstance(arg1, str) else arg1
            if isinstance(parsed, dict) and "address" in parsed:
                call_kwargs.setdefault("address", parsed["address"])
                if "city" in parsed and "city" not in call_kwargs:
                    call_kwargs["city"] = parsed["city"]
            else:
                if "address" not in call_kwargs:
                    call_kwargs["address"] = str(arg1) if arg1 else ""
        except (ValueError, TypeError):
            if "address" not in call_kwargs:
                call_kwargs["address"] = str(arg1) if arg1 else ""


def _amap_maps_geo_beijing_city(call_kwargs: Dict[str, Any]) -> None:
    """amap-maps maps_geo：北京关键词或区名时补 city=北京。"""
    addr = (call_kwargs.get("address") or "").strip()
    city = (call_kwargs.get("city") or "").strip()
    beijing_keywords = ("北邮", "海淀", "天安门", "故宫", "北京", "西单", "东单", "国贸", "中关村")
    district_not_city = ("海淀", "朝阳", "东城", "西城", "丰台", "石景山", "通州", "顺义")
    needs_fix = (not city) or (
        city in district_not_city and any(kw in addr for kw in beijing_keywords)
    )
    if needs_fix and any(kw in addr for kw in beijing_keywords):
        call_kwargs["city"] = "北京"


def _amap_maps_route(call_kwargs: Dict[str, Any], tool_name: str) -> None:
    """amap-maps 路线/距离类工具：__arg1 内 JSON 的 origin/destination/city/cityd/type 填入 call_kwargs。"""
    route_tools = (
        "maps_direction_driving",
        "maps_direction_walking",
        "maps_bicycling",
        "maps_direction_transit",
        "maps_direction_transit_integrated",
        "maps_distance",
    )
    if tool_name not in route_tools or "__arg1" not in call_kwargs:
        return
    arg1 = call_kwargs.pop("__arg1", "")
    try:
        parsed = json.loads(arg1) if isinstance(arg1, str) else arg1
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        for k in ("origin", "destination", "city", "cityd", "type"):
            if k in parsed and k not in call_kwargs:
                call_kwargs[k] = parsed[k]


def _linkup_linkup_search(call_kwargs: Dict[str, Any]) -> None:
    """linkup linkup-search：depth 仅接受 standard 或 deep，否则设为 standard。"""
    depth = call_kwargs.get("depth")
    if depth not in ("standard", "deep"):
        call_kwargs["depth"] = "standard"


def _file_reader_filesystem_path(server_name: str, call_kwargs: Dict[str, Any]) -> None:
    """file-reader / filesystem：__arg1 → path。"""
    if server_name not in ("file-reader", "filesystem") or "__arg1" not in call_kwargs:
        return
    if "path" not in call_kwargs:
        call_kwargs["path"] = str(call_kwargs["__arg1"]) if call_kwargs["__arg1"] is not None else ""


def _schema_first_param(call_kwargs: Dict[str, Any], input_schema: Optional[Dict[str, Any]]) -> None:
    """通用：__arg1 映射到 input_schema 的第一个 required 或 properties 首键。"""
    if "__arg1" not in call_kwargs or not input_schema:
        return
    schema = input_schema if isinstance(input_schema, dict) else {}
    first_param = None
    required = schema.get("required") or []
    if required:
        first_param = required[0]
    else:
        props = schema.get("properties") or {}
        if props:
            first_param = next(iter(props.keys()), None)
    if first_param and first_param not in call_kwargs:
        call_kwargs[first_param] = call_kwargs.pop("__arg1")


def _strip_arg_placeholders(call_kwargs: Dict[str, Any]) -> None:
    """移除所有 __argX 占位键，避免传入 MCP。"""
    to_del = [k for k in list(call_kwargs.keys()) if k.startswith("__arg")]
    for k in to_del:
        call_kwargs.pop(k, None)


def normalize_mcp_tool_kwargs(
    server_name: Optional[str],
    original_tool_name: str,
    kwargs: Dict[str, Any],
    input_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    规范化 MCP 工具调用参数。纯函数，不写日志。
    由 manager.normalize_mcp_kwargs_for_call 委托调用，chat 层展示参数时也可复用。
    """
    call_kwargs = dict(kwargs or {})

    if server_name == "volces-icon" and original_tool_name == "generate_app_icon":
        _volces_icon_generate_app_icon(call_kwargs)

    if server_name == "amap-maps" and original_tool_name == "maps_geo":
        _amap_maps_geo(call_kwargs)

    if server_name == "amap-maps":
        _amap_maps_route(call_kwargs, original_tool_name)

    if server_name == "linkup" and original_tool_name == "linkup-search":
        _linkup_linkup_search(call_kwargs)

    if server_name in ("file-reader", "filesystem"):
        _file_reader_filesystem_path(server_name or "", call_kwargs)

    _schema_first_param(call_kwargs, input_schema)

    if server_name == "amap-maps" and original_tool_name == "maps_geo":
        _amap_maps_geo_beijing_city(call_kwargs)

    _strip_arg_placeholders(call_kwargs)
    return call_kwargs
