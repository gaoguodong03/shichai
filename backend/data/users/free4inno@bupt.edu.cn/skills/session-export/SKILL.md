---
description: 导出对话、导出为 .md、保存为 markdown。当前产品通过界面或会话 API 导出，不再提供 Agent 内置导出工具。
name: 导出对话
allowed-tools:
  mcp: []
  python: ''
---
# Session Export

当用户要求导出对话为 Markdown 时：

- **请引导用户使用会话侧栏或菜单中的「导出」功能**，或说明可通过 `POST /api/sessions/{session_id}/export` 导出；
- **不要**假装已导出或编造下载链接；导出文件会写入该会话工作区并由服务端生成下载地址。

历史消息中若出现 `export_session_to_md` 工具名，仅为旧版兼容展示，当前运行时不再注入该工具。
