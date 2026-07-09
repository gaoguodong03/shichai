# 沙箱工具调用接口

本文档说明群聊技能执行阶段，模型可调用的沙箱/工具接口、参数格式、返回约定与推荐调用顺序。实现入口以 `backend/app/agent/tools_for_skill.py`、`backend/app/agent/skill_agent_runtime.py`、`backend/app/agent/simple_agent.py` 为准。

## 总体规则

- 工具由平台提供的结构化工具调用接口执行；正文用于呈现结论、路径和下一步说明。
- 所有工作区路径都使用“当前会话工作区相对路径”，例如 `notes/report.md`，不要带 `/workspace`、`agent-outputs/`、`workspaces/<session_id>/` 等内部前缀。
- 不确定文件名时，先使用 `list_workspace_directory`；`read_workspace_file` 只读取调用方提供的精确相对路径，不负责遍历工作区猜候选路径。
- 文件读写和脚本执行都只能访问当前会话工作区边界；模型不需要也不应该感知宿主机绝对路径。
- 工具返回值是给模型继续推理用的内部结果；最终回复应总结用户关心的结论，不要原样倾倒长 JSON/stdout，除非用户明确要求。
- LLM 可见工具字段统一为 `name`、`description`、`input_schema`。平台内部用 `source` 分发到 `mcp`、`http_api`、`workspace`、`skill_script` 四类执行路径；`provider` 和 `provider_tool` 只用于日志与 trace，执行层应尽量记录，但不得参与分发或业务分支。
- 实现应直接删除旧兜底逻辑，不保留通用 `call_api`、无 manifest 脚本注入、`script_path` / `cli_args` 入口、按工具名前缀猜执行路径、缺失 `source` 后自动猜 provider 等兼容分支。

## 内置工作区工具

这些工具由 `build_tools_for_group_chat()` 按专家 `file_capabilities` 注入。

### `read_workspace_file`

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
- 文件不存在时只返回缺失错误。收到这类错误后，应先调用 `list_workspace_directory` 查看真实路径，或向用户确认路径，不要继续猜测。

推荐：

- 用户说“查看/读取/打开某文件”时，优先使用 `read_workspace_file`。
- 如果用户只给文件名且不确定位置，先调用 `list_workspace_directory`。

### `write_workspace_file`

写入或覆盖当前会话工作区文本文件。

参数：

```json
{
  "path": "notes/result-2026070422145700.md",
  "content": "完整文件内容"
}
```

约束与返回：

- `content` 不能为空。
- `path` 是工作区相对路径；必要的父目录由沙箱侧处理。
- 除非用户明确指定已有路径或固定文件名，所有新建工作区文件名统一使用 `文件名-当前文件时间戳.扩展名`，当前文件时间戳由运行提示提供。
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
- 如果 `old_text` 不存在，会返回错误；此时应先使用 `read_workspace_file` 获取真实内容，再重试。

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

新建工作区目录。

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

## 技能脚本工具：`run_skill_script_<directory_name>`

每个已绑定且磁盘存在的技能会注入一个脚本工具，名称由 Skill 目录名转换而来，例如：

- directory name：`travel-expense-calculator`
- 工具名：`run_skill_script_travel_expense_calculator`

参数由当前 Skill 的 `scripts/manifest.json` 生成。manifest 只写 `entry`、`description`、`args`；不要写 `input_schema`、`cli_args` 或 `invocation`。

manifest 示例：

```json
{
  "entry": "extract_travel_standards.py",
  "description": "从差旅标准文件中提取指定地区标准。",
  "args": [
    {
      "name": "input_path",
      "description": "工作区内输入文件相对路径。",
      "required": true
    },
    {
      "name": "output_path",
      "description": "工作区内输出文件相对路径。",
      "required": true
    }
  ]
}
```

模型实际调用工具时只传 manifest `args` 中定义的结构化字段：

```json
{
  "input_path": "内蒙古差旅费标准.txt",
  "output_path": "notes/result.md"
}
```

规则：

- `entry` 是相对该技能 `scripts/` 目录的路径；不要带宿主机绝对路径、`../`、shell 管道或 `scripts/` 前缀。
- 模型不传 `script_path`、`cli_args`、`invocation` 或 `input_schema`。
- 平台根据 manifest `args` 自动生成 LLM 可见 `input_schema`，并把结构化参数转换为 CLI 参数；参数名使用 snake_case，执行时转换为 `--kebab-case`。
- 没有 `scripts/manifest.json` 时，平台不注入脚本工具；不要回退到默认 `cli_args` 或让模型指定脚本路径。
- 脚本运行时当前目录是会话工作区；脚本可读写工作区文件。
- 脚本环境变量包括：`SKILL_ID`、`SKILL_WORKSPACE_ID`、`SKILL_WORKSPACE_ROOT`、`SKILL_SCRIPT_ROOT`、`SKILL_HOME`。
- 脚本 stdout 应输出单个 JSON 对象，并使用标准字段 `execution_status`、`content`、`artifacts`、`next_action`。`content` 是脚本文本结果，平台不做 LLM 总结或改写；`artifacts` 是产物索引数组，每项固定为 `type`、`name`、`path`。`next_action.agent_turn` 控制当前专家本轮继续行动还是回复用户，`next_action.skill_session` 控制下一条用户消息是否回到同一专家和同一 Skill；两者是独立维度，四种组合都合法。
- 脚本 stdout 缺少 `next_action`、字段缺失、枚举非法或 JSON 结构不合法时，按脚本协议失败处理：本轮回复协议错误，并释放 Skill 会话锁。
- MCP / HTTP / workspace 工具本身不要求返回 `next_action`；这些工具执行后如需决定本轮是否继续或跨轮是否锁定 Skill，应由专家最终回复末尾的隐藏状态块表达。
- 给 Skill 作者的依赖声明、`argparse` 模板、计数字段（如 `segment_count` / `chunk_count`）与 stdout 字段建议，见 `docs/skills/skill-standard.md` 的“给 Skill 作者的脚本函数调用建议”。

何时使用：

- 技能有明确脚本能力，且任务需要解析文件、生成文档、生成图片、批处理数据等确定性执行。
- 优先按照技能 `SKILL.md` 和 `scripts/manifest.json` 中描述的参数调用。

## 保存型 HTTP API 工具：`http_api_<name>`

保存型 HTTP API 工具来自资源中心配置，只在当前 Skill 的 `allowed-tools.http_api` 中声明后加载。通用 `call_api` 不再作为 LLM 可见工具注入。

参数：

```json
{
  "query": {
    "q": "keyword"
  },
  "headers": {
    "Accept": "application/json"
  },
  "body": {
    "key": "value"
  }
}
```

约束：

- URL、method、默认 query/header/body 来自资源中心保存的 HTTP API 配置，模型不能传任意 URL。
- LLM 只能传 `query`、`headers`、`body` 覆盖或补充默认配置。
- 不保留通用 `call_api` 兜底，也不允许模型临时指定 URL、method 或任意 headers 作为替代入口。
- 后端执行时仍必须做 SSRF、环境变量引用和 URL 安全校验。

## MCP 工具

MCP 工具只在当前 Skill `SKILL.md` frontmatter 的 `allowed-tools.mcp` 中声明后加载。

调用规则：

- 使用实际注入的工具名，通常形如 `<server_id>_<tool_name>`。
- 参数以工具 schema 为准；不要把所有参数塞进 `__arg1`，除非该 MCP 工具本身只接受单字符串参数。
- 文件系统类 MCP 工具中与内置工作区工具重复的 `file-reader_*` 会被过滤，避免绕过平台工作区边界。

## 推荐决策顺序

1. 用户明确要求读/写/列工作区文件：使用内置工作区工具。
2. 技能说明要求运行脚本，或任务适合确定性处理：使用 `run_skill_script_<directory_name>`。
3. 需要已保存的专用 HTTP API：使用当前 Skill 声明的 `http_api_<name>`。
4. 需要技能声明的专用外部能力：使用对应 MCP 工具。
5. 需要网页检索、抓取、图片、音频等外部能力：优先使用当前 Skill 声明的 MCP 工具。
6. 工具报错后先根据错误修正参数；不要反复猜测路径、URL 或脚本名。

## 是否需要让模型知道

需要，但只需要给模型注入“精简版、与当前实际工具列表匹配”的调用规则，不应把本文档全文塞进系统提示词。原因：

- 全文档适合开发者排查和维护，直接注入会增加上下文、拖慢首轮 LLM，并可能干扰技能正文。
- 模型真正需要的是当前可用工具的名称、用途、参数形态、路径规则和错误恢复策略。
- 当前实现应继续按实际 `tools` 动态生成提示：有文件工具才注入文件规则，有保存型 HTTP API 工具才注入 HTTP 规则，有脚本工具才注入 manifest 参数规则，有 MCP 才注入 MCP 规则。
