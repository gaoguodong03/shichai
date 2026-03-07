"""写入当前会话工作区文件工具 - 供单聊/群聊共用"""
from langchain.tools import Tool

from app.api.files import get_workspace_root


def create_write_workspace_file_tool(workspace_id: str) -> Tool:
    """
    创建写入当前会话 workspace 文件的工具。
    workspace_id 为 session_id 或 group_session_id。
    """

    def _write_to_workspace_file(path: str, content: str = "", **kwargs) -> str:
        path_value = path or kwargs.get("path") or ""
        content_value = content if content is not None else kwargs.get("content") or ""
        path_value = str(path_value).strip()
        if not path_value:
            return "错误：write_workspace_file 需要提供 path（workspace 内相对路径，例如 notes/report.md）。"
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

    return Tool(
        name="write_workspace_file",
        description=(
            "将文本内容写入当前 Chat 对应的工作区（workspace）中的文件。\n"
            "- 参数 path: 工作区内相对路径，例如 'notes/report.md'。\n"
            "- 参数 content: 要保存的完整文本内容（覆盖写入）。\n"
            "适用于：在完成分析或写作后，把报告、草稿等保存到本 Chat 的 workspace 文件中。"
        ),
        func=_write_to_workspace_file,
    )
