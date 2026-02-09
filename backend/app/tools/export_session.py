"""导出会话为 Markdown 文件工具"""
from datetime import datetime
from pathlib import Path

from langchain.tools import Tool

from app.api.files import AGENT_OUTPUTS_DIR


def _render_history_to_markdown(messages) -> str:
    """将对话历史渲染为 Markdown"""
    lines = ["# 对话导出\n", f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "---\n"]
    for msg in messages:
        role = getattr(msg, "type", None) or type(msg).__name__
        content = msg.content if hasattr(msg, "content") else str(msg)
        if isinstance(content, str):
            pass
        else:
            content = str(content)
        if "human" in role.lower() or "HumanMessage" in role:
            lines.append("## 用户\n\n")
        else:
            lines.append("## 助手\n\n")
        lines.append(content.strip())
        lines.append("\n\n")
    return "".join(lines)


def create_export_session_tool(session_id: str):
    """创建导出会话工具（闭包绑定 session_id）"""

    def export_session_to_md(**kwargs) -> str:
        from app.api.chat import _CHAT_HISTORY

        history = _CHAT_HISTORY.get(session_id, [])
        if not history:
            return "当前会话无历史消息，无法导出。"
        md = _render_history_to_markdown(history)
        root = Path(AGENT_OUTPUTS_DIR).resolve()
        root.mkdir(parents=True, exist_ok=True)
        filename = f"session-{session_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        filepath = root / filename
        filepath.write_text(md, encoding="utf-8")
        rel_path = str(filepath.relative_to(root)).replace("\\", "/")
        return f"已导出到 {filename}。下载链接: /api/files/download?path={rel_path}"

    return Tool(
        name="export_session_to_md",
        description="导出当前会话为完整 markdown 文件。当用户说「导出为 .md」「导出对话」「保存为 markdown」「导出为完整 .md 文件」等时调用。无需参数。",
        func=export_session_to_md,
    )
