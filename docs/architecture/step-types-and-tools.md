# 步骤类型与工具（执行路径）

本文档说明 Skill 步骤的**多种执行路径**及当前实现：MCP、script、service、export、只读文件等均作为工具注入技能执行 Agent。

## 执行路径总览

Skill 的每一步可能走以下某一类路径；**应在 SKILL.md 中写明本步走哪一类**，避免模型误选工具：

| 路径 | 含义 | 工具 / 实现 | 在 SKILL 中如何写明 |
|------|------|-------------|----------------------|
| **MCP** | 调用某个 MCP 工具 | 按技能过滤的 MCP 工具，如 `volces-icon_generate_app_icon`、`linkup_linkup-search`、`amap-maps_maps_geo` | 「本步使用 MCP 工具 xxx」「调用 volces-icon_generate_app_icon」等 |
| **script** | 执行当前技能 `scripts/` 下脚本 | 工具 `run_skill_script`，参数 `script_path`、`input_json` | 「本步使用 run_skill_script」「script_path=generate_image.py」，禁止本步用 call_api |
| **service** | 调用外部 HTTP API | 工具 `call_api`，参数 `url`、`method`、`headers_json`、`body` | 「本步使用 call_api」「GET/POST 某 URL」等 |
| **export** | 将会话导出为 Markdown | 工具 `export_session_to_md`（若会话 API 提供） | 「本步使用 export_session_to_md」或由用户意图触发导出 |
| **只读文件** | 读取工作区或指定路径文件 | MCP：`file-reader_*`（如 read_pdf、read_docx）、`filesystem_read_text_file` 等；写文件工具已过滤不提供 | 「本步使用 file-reader / filesystem 读取 xxx」 |
| **仅推理** | 本步不调工具 | 无 tool_call | 直接写出本步结论或下一步计划 |

流程上可**多步重复**或**跳过**某步，由 LLM 在 ReAct 循环中根据技能说明决定；**每一步应明确对应一个路径**。

## 当前工具形态（单聊已合并）

**单聊已下线**，统一为「带主持人的会话」；会话列表与流式接口均为 `/api/sessions`，工具组装以 **群聊路径** 为准（见 [统一对话模型](unified-conversation-model.md)）。

- **统一会话**（`build_tools_for_group_chat`）：按 DHA 的 `mcp_server_ids` 或技能 MCP 依赖过滤 MCP 工具 + file-reader/filesystem **只读** + `call_api`；若 DHA 配置了 `skill_ids`，为每个技能注入 `run_skill_script_<skill_id>`（可执行该技能 `scripts/` 下脚本）。文件类工具经 `wrap_filesystem_tools` 限定到当前会话工作区。导出等能力若在统一会话中提供，由同一路径扩展。
- **已移除**：原单聊专用 `build_tools_for_chat` 已删除；`/api/chat/stream` 已不再挂载。

读文件实际工具名为 MCP 暴露的 `file-reader_*`、`filesystem_*`（如 `filesystem_read_text_file`），**不是**已废弃的 `read_file`。

## 在 SKILL.md 中写明执行路径

- 在描述某一步时**直接写出本步使用的路径与工具**，例如：
  - 「本步**使用 run_skill_script**，script_path=hello_dha.py。禁止使用 call_api。」
  - 「本步**使用 MCP**：调用 volces-icon_generate_app_icon，参数 description、pic_size。」
  - 「本步**使用 call_api**：GET https://api.xxx.com/weather?city=…」
  - 「本步**使用 filesystem 或 file-reader** 读取用户上传的文档后再总结。」
- 当前为「LLM 解释型」：工具列表 + 技能全文注入，**依赖 SKILL 正文中每步写明执行路径**。

## 工具说明

### run_skill_script

- **创建**：在统一会话中，按 DHA 的 `skill_ids` 为每个技能注入 `run_skill_script_<skill_id>`（见 `build_tools_for_group_chat`）。
- **参数**：`script_path`（相对该技能 `scripts/` 的文件名）、`input_json`（可选，作为 stdin 传入脚本）。
- **约束**：仅允许运行该技能 `scripts/` 目录内 `.py` 或 `.sh`；禁止 `..`；超时由 `SKILL_SCRIPT_TIMEOUT`（默认 60 秒）控制。

### call_api

- **创建**：全局单例，单聊与群聊均加入。
- **参数**：`url`（必填）、`method`（默认 GET）、`headers_json`（可选）、`body`（可选）。
- **约束**：请求超时由 `CALL_API_TIMEOUT`（默认 30 秒）控制。

### export_session_to_md

- **创建**：若会话 API 提供导出能力，则注入 `create_export_session_tool(session_id)`。
- **用途**：将会话历史导出为 Markdown 并写入当前会话工作区；也可由「导出会话」意图走 HTTP 导出接口。

### 只读文件（MCP）

- **来源**：file-reader、filesystem 等 MCP 提供的工具；写文件类（如 `file-reader_write_file`、名称含 write/edit 的 filesystem 工具）在组装时已过滤，不提供给 Agent。

## 与运行流程的关系

见 [运行流程 - 1.3 Skill 步骤执行体](runtime-flow.md#13-skill-步骤执行体目标模型-vs-当前实现)。
