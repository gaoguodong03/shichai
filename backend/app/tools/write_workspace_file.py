"""写入当前会话工作区文件工具"""
import json
from langchain_core.tools import StructuredTool

# LangChain 的 StructuredTool.args_schema 要求 pydantic v1 的 BaseModel
try:
    from langchain_core.pydantic_v1 import BaseModel, Field
except ImportError:
    from pydantic.v1 import BaseModel, Field  # type: ignore

from app.api.files import get_workspace_root
from app.agent.host_plan import is_host_plan_reserved_path


class WriteWorkspaceFileInput(BaseModel):
    """write_workspace_file 的入参。一次调用必须同时传 path 和 content。"""

    path: str = Field(description="工作区内相对路径，例如 notes/report.md 或 workspace-write-test.txt")
    content: str = Field(
        default="",
        description="要保存的完整文本内容；若为空则工具会报错并提示重新传入。与 path 在同一次调用中一起传入。",
    )


def _normalize_path(path_or_input) -> str:
    """从多种输入格式提取 path 字符串，避免把 {\"__arg1\": \"xxx.md\"} 当文件名写入。"""
    if path_or_input is None:
        return ""
    if isinstance(path_or_input, dict):
        return str(path_or_input.get("path") or path_or_input.get("__arg1") or "").strip()
    s = str(path_or_input).strip()
    if not s:
        return ""
    if s.startswith("{"):
        try:
            data = json.loads(s)
            return str(data.get("path") or data.get("__arg1") or "")
        except json.JSONDecodeError:
            pass
    return s


def _normalize_content(content_or_input, **kwargs) -> str:
    """从多种输入格式提取 content，兼容 LLM 传 __arg2、text、body 等。"""
    if content_or_input is not None and str(content_or_input).strip():
        return str(content_or_input)
    for key in ("content", "__arg2", "text", "body"):
        val = kwargs.get(key)
        if val is not None and str(val).strip():
            return str(val)
    return ""


def create_write_workspace_file_tool(workspace_id: str) -> StructuredTool:
    """
    创建写入当前会话 workspace 文件的工具。
    workspace_id 为 session_id 或 group_session_id。
    使用显式 args_schema 将 path、content 标为必填，确保 LLM 传入 content。
    """

    def _write_to_workspace_file(path: str, content: str = "", **kwargs) -> str:
        path_value = _normalize_path(path) or _normalize_path(kwargs.get("path")) or _normalize_path(kwargs.get("__arg1")) or ""
        content_value = _normalize_content(content, **kwargs)
        path_value = path_value.strip()
        if not path_value:
            return "错误：write_workspace_file 需要提供 path（workspace 内相对路径，例如 notes/report.md）。"
        if is_host_plan_reserved_path(path_value):
            return (
                "错误：memory/host_plan.md 为用户可编辑的任务清单，智能体工具禁止覆盖；"
                "请用户在侧边栏工作区中打开该文件编辑。"
            )
        if not content_value:
            return (
                "错误：content 为空。未传 content 时系统会用本条回复的正文作为要保存的内容；若本条回复无正文，请在本条中写出要保存的内容后重试，或调用时显式传入 content。"
            )
        try:
            ws_root = get_workspace_root(workspace_id)
            normalized = path_value.strip("/").replace("..", "")
            target = (ws_root / normalized).resolve()
            if not str(target).startswith(str(ws_root)):
                return f"错误：路径 {path_value} 不在当前工作区内。"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content_value), encoding="utf-8")
            rel = str(target.relative_to(ws_root)).replace("\\", "/")
            return f"已写入当前 Chat 工作区文件：{rel}"
        except Exception as e:
            return f"错误：写入工作区文件失败 - {e}"

    return StructuredTool.from_function(
        name="write_workspace_file",
        description=(
            "将文本内容写入当前 Chat 对应的工作区（workspace）中的文件。\n"
            "- path: 工作区内相对路径，例如 'notes/report.md'。\n"
            "- content: 要保存的完整文本内容。若不传或为空，系统会自动把本条回复的正文当作要保存的内容写入。"
        ),
        func=_write_to_workspace_file,
        args_schema=WriteWorkspaceFileInput,
    )
