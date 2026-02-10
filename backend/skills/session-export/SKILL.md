---
description: 导出对话、导出为 .md、保存为 markdown、导出为完整 .md 文件。当用户要求导出当前对话为 markdown 时，调用 export_session_to_md
  工具即可，无需再调用 LLM 生成内容。
enabled: true
name: 导出对话
---
# Session Export

当用户要求导出对话时，**直接调用 `export_session_to_md` 工具**，不要用 LLM 生成文本。

工具会自动将会话历史保存为 `.md` 文件并返回下载链接。
