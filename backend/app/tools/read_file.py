"""读取引用文件工具 - 支持用户消息中的【文件引用：path】"""
import json
from pathlib import Path

from langchain.tools import Tool

from app.api.files import AGENT_OUTPUTS_DIR


def _normalize_path(path_or_input) -> str:
    """从多种输入格式提取 path 字符串。兼容 arun(tool_input) 传入的 JSON 字符串。"""
    if path_or_input is None:
        return ""
    s = str(path_or_input).strip()
    if not s:
        return ""
    # arun 可能传入 JSON 字符串 '{"__arg1": "test.docx"}'，需解析
    if s.startswith("{"):
        try:
            data = json.loads(s)
            return str(data.get("path") or data.get("__arg1") or "")
        except json.JSONDecodeError:
            pass
    return s


def _read_file_content(path: str = None, **kwargs) -> str:
    """读取 AGENT_OUTPUTS_DIR 下的文件内容，path 为相对路径。
    兼容 bind_tools 传入的 __arg1、arun 传入的 JSON 字符串等格式。"""
    path = _normalize_path(path) or _normalize_path(kwargs.get("__arg1")) or _normalize_path(kwargs.get("path"))
    root = Path(AGENT_OUTPUTS_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    normalized = (path or "").strip("/").replace("..", "")
    if not normalized:
        return "错误：未提供文件路径。"
    full = (root / normalized).resolve()
    if not str(full).startswith(str(root)):
        return f"错误：路径 {path} 不在允许的目录内。"
    if not full.exists():
        return f"错误：文件不存在：{path}"
    if full.is_dir():
        return f"错误：{path} 是目录，无法读取。"
    try:
        return full.read_text(encoding="utf-8")
    except Exception as e:
        return f"错误：读取文件失败 - {e}"


def create_read_file_tool():
    """创建读取引用文件工具"""
    return Tool(
        name="read_file",
        description="读取用户引用的文件内容。当用户消息中出现【文件引用：path】时，必须先用此工具读取该文件，path 为相对路径（如 genimi.txt、qwen.md）。读取后再根据文件内容回答用户问题。",
        func=_read_file_content,
    )
