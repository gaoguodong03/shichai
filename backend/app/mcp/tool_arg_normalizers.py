"""MCP 工具调用参数归一化：仅保留当前 schema 契约允许的稳定修正。"""
from typing import Any, Dict, Optional


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


def _linkup_linkup_search(call_kwargs: Dict[str, Any]) -> None:
    """linkup linkup-search：depth 仅接受 standard 或 deep，否则设为 standard。"""
    depth = call_kwargs.get("depth")
    if depth not in ("standard", "deep"):
        call_kwargs["depth"] = "standard"


def _schema_single_param(call_kwargs: Dict[str, Any], input_schema: Optional[Dict[str, Any]]) -> None:
    """Only single-field tools may receive a bare string through __arg1."""
    if "__arg1" not in call_kwargs or not input_schema:
        return
    schema = input_schema if isinstance(input_schema, dict) else {}
    props = schema.get("properties") or {}
    if not isinstance(props, dict) or len(props) != 1:
        return
    param = next(iter(props.keys()), None)
    if param and param not in call_kwargs:
        call_kwargs[param] = call_kwargs.pop("__arg1")


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

    if server_name == "linkup" and original_tool_name == "linkup-search":
        _linkup_linkup_search(call_kwargs)

    _schema_single_param(call_kwargs, input_schema)

    if server_name == "amap-maps" and original_tool_name == "maps_geo":
        _amap_maps_geo_beijing_city(call_kwargs)

    _strip_arg_placeholders(call_kwargs)
    return call_kwargs
