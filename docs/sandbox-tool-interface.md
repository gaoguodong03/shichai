# 沙箱工具调用接口

本文档说明群聊技能执行阶段，模型可调用的沙箱/工具接口、参数格式、返回约定与推荐调用顺序。实现入口以 `backend/app/agent/tools_for_skill.py`、`backend/app/agent/skill_agent_runtime.py`、`backend/app/agent/simple_agent.py` 为准。

## 总体规则

- 工具必须通过模型结构化工具调用（`tool_calls` / function calling）调用，不要把 JSON 工具调用写进正文。
- 所有工作区路径都使用“当前会话工作区相对路径”，例如 `notes/report.md`，不要带 `/workspace`、`agent-outputs/`、`workspaces/<session_id>/` 等内部前缀。
- 不确定文件名时，先调用 `list_workspace_directory`；如果 `read_file` 返回候选路径，下一步必须使用候选中的真实路径，不要继续猜文件名。
- 文件读写、脚本执行都经 OpenSandbox 挂载的 `/workspace` 与 `/skills` 完成；模型不需要也不应该感知宿主机绝对路径。
- 工具返回值是给模型继续推理用的内部结果；最终回复应总结用户关心的结论，不要原样倾倒长 JSON/stdout，除非用户明确要求。

## 内置工作区工具

这些工具由 `build_tools_for_group_chat()` 按专家 `file_capabilities` 注入。

### `read_file`

读取当前会话工作区文本文件。

参数：

```json
{
  "path": "notes/report.md"
}
```

约束与返回：

- `path` 必须是工作区相对路径。
- 只能读取 UTF-8 文本；非文本会返回错误。
- 文件不存在时会返回候选路径或工作区真实文件列表。收到这类错误后，应改用真实路径或先询问用户，不要继续猜测。

推荐：

- 用户说“查看/读取/打开某文件”时，优先调用 `read_file`。
- 如果用户只给文件名且不确定位置，先调用 `list_workspace_directory`。

### `write_workspace_file`

写入或覆盖当前会话工作区文本文件。

参数：

```json
{
  "path": "notes/result.md",
  "content": "完整文件内容"
}
```

约束与返回：

- `content` 不能为空。
- `path` 是工作区相对路径；必要的父目录由沙箱侧处理。
- 用户要求“保存/写入/生成文件”时，应调用此工具，而不是只在自然语言里说“已保存”。

### `edit_workspace_file`

按文本片段替换编辑工作区文件。

参数：

```json
{
  "path": "notes/report.md",
  "old_text": "原文本片段",
  "new_text": "替换后的文本"
}
```

约束与返回：

- 适合小范围精确编辑。
- 如果 `old_text` 不存在，会返回错误；此时应先 `read_file` 获取真实内容，再重试。

### `rename_workspace_file`

重命名或移动工作区文件/目录。

参数：

```json
{
  "path": "notes/draft.md",
  "new_name": "notes/final.md"
}
```

约束：

- `new_name` 可以是新文件名，也可以是新的相对路径。
- 禁止 `..` 和工作区外路径。

### `mkdir_workspace`

创建工作区目录。

参数：

```json
{
  "path": "notes/archive"
}
```

### `list_workspace_directory`

递归列出当前工作区目录内容。

参数：

```json
{
  "path": ""
}
```

说明：

- `path` 为空表示工作区根目录。
- 返回路径通常带 `./` 前缀；后续调用其他工具时去掉或保留相对含义均可，但不要补内部绝对前缀。

## 技能脚本工具：`run_skill_script_<skill_id>`

每个已绑定且磁盘存在的技能会注入一个脚本工具，名称由技能 id 转换而来，例如：

- skill id：`travel-expense-calculator`
- 工具名：`run_skill_script_travel_expense_calculator`

参数：

```json
{
  "script_path": "extract_travel_standards.py",
  "cli_args_json": "[\"--input\", \"内蒙古差旅费标准.txt\", \"--output\", \"notes/result.md\"]"
}
```

规则：

- `script_path` 是相对该技能 `scripts/` 目录的路径；不要带宿主机绝对路径。误写 `scripts/xxx.py` 会被兼容纠正，但不推荐。
- 统一使用 `cli_args_json` 传参，值必须是 JSON 数组字符串。
- 不再支持 `input_json` / stdin；传 `input_json` 会返回 `invalid_input_mode`。
- 脚本运行时当前目录是会话工作区；脚本可读写工作区文件。
- 脚本环境变量包括：`SKILL_ID`、`SKILL_WORKSPACE_ID`、`SKILL_WORKSPACE_ROOT`、`SKILL_SCRIPT_ROOT`、`SKILL_HOME`。
- 脚本 stdout 应尽量输出单个 JSON 对象；若脚本能确定当前 Skill 会话是否结束，使用 `skill_session_over: true|false`。`done/final` 只表示工具循环收束，不释放群聊 Skill 会话锁。
- 给 Skill 作者的依赖声明、`argparse` 模板、计数字段（如 `segment_count` / `chunk_count`）与 stdout 字段建议，见 `docs/书童四九Skill规范.md` 的“给 Skill 作者的脚本函数调用建议”。

何时使用：

- 技能有明确脚本能力，且任务需要解析文件、生成文档、生成图片、批处理数据等确定性执行。
- 优先按照技能 `SKILL.md` 或 `scripts/manifest.json` 中描述的脚本和参数调用。

## 外部 HTTP 工具：`call_api`

访问公网 HTTP API 或公开网页。

参数：

```json
{
  "url": "https://example.com/api",
  "method": "GET",
  "headers_json": "{\"Accept\": \"application/json\"}",
  "body": ""
}
```

POST 示例：

```json
{
  "url": "https://example.com/api/search",
  "method": "POST",
  "headers_json": "{\"Content-Type\": \"application/json\"}",
  "body": "{\"q\": \"keyword\"}"
}
```

约束：

- 仅允许公网可达的 `http(s)` URL；内网、本机地址会被 SSRF 防护拒绝。
- HTML 响应会尝试抽取正文；JSON 响应会格式化返回。
- 需要登录、验证码、强反爬的网站可能无法完整获取。

## MCP 工具

MCP 工具只在当前技能 `SKILL.md` frontmatter 声明的 `mcp_server_ids` 被允许时加载；若专家实例还配置了 `mcp_server_ids`，会与技能声明取交集。

调用规则：

- 使用实际注入的工具名，通常形如 `<server_id>_<tool_name>`。
- 参数以工具 schema 为准；不要把所有参数塞进 `__arg1`，除非该 MCP 工具本身只接受单字符串参数。
- 文件系统类 MCP 工具中与内置工作区工具重复的 `file-reader_*` 会被过滤，避免绕过 OpenSandbox 直读写宿主数据。

## 推荐决策顺序

1. 用户明确要求读/写/列工作区文件：使用内置工作区工具。
2. 技能说明要求运行脚本，或任务适合确定性处理：使用 `run_skill_script_<skill_id>`。
3. 需要公网网页/API：使用 `call_api` 或技能绑定的检索类 MCP。
4. 需要技能声明的专用外部能力：使用对应 MCP 工具。
5. 工具报错后先根据错误修正参数；不要反复猜测路径、URL 或脚本名。

## 是否需要让模型知道

需要，但只需要给模型注入“精简版、与当前实际工具列表匹配”的调用规则，不应把本文档全文塞进系统提示词。原因：

- 全文档适合开发者排查和维护，直接注入会增加上下文、拖慢首轮 LLM，并可能干扰技能正文。
- 模型真正需要的是当前可用工具的名称、用途、参数形态、路径规则和错误恢复策略。
- 当前实现应继续按实际 `tools` 动态生成提示：有文件工具才注入文件规则，有 `call_api` 才注入 HTTP 规则，有脚本工具才注入 CLI-only 规则，有 MCP 才注入 MCP 规则。
