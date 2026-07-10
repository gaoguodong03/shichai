# 书童四九接口文档

版本：v1.0 项目验收版
日期：2026-07-05
适用范围：书童四九 Web 前端与 FastAPI 后端之间的业务接口、流式事件接口、资源导入导出接口、文件接口和部署健康检查接口。

## 1. 文档目的

本文记录书童四九当前对外业务接口的调用约定、认证方式、请求响应结构、端点清单、SSE 事件和错误处理规则，用于前后端联调、测试验收和后续接口变更评审。

接口事实以 `backend/app/api/` 下 FastAPI 路由为准。本文不描述内部 Python 函数调用，也不设计具体上层业务应用。

## 2. 基础约定

### 2.1 基础 URL

| 环境 | 地址 |
|------|------|
| 本地后端开发 | `http://localhost:8000` |
| Docker/1Panel 默认主应用 | `http://<server-ip>:8100` |
| 前端同源部署 | 浏览器通过相对路径 `/api/...` 调用后端 |

业务 API 统一以 `/api` 为前缀。例外：

- `/health`：健康检查。
- `/`：前端静态入口或根路径响应。

### 2.2 认证方式

前端登录后获得 `access_token`，后续请求携带认证信息。受保护接口由后端 `user_context_dependency` 注入当前用户上下文。

生产环境应关闭匿名 API：

```bash
ALLOW_ANONYMOUS_API=0
```

约束：

- 会话、资源、文件、Skill、MCP、模型、环境变量和沙箱配置都按当前用户隔离。
- 未登录或令牌无效返回 `401`。
- 业务错误不要滥用 `401`，例如当前密码错误应返回 `400`。
- 环境变量真实值等敏感字段返回前端时必须脱敏。

### 2.3 通用响应

多数 JSON 接口返回：

```json
{
  "status": "ok",
  "data": {}
}
```

导出接口返回文件流。流式会话接口返回 Server-Sent Events。

### 2.4 通用错误码

| 状态码 | 场景 |
|--------|------|
| `400` | 请求字段、导入包、路径、配置或参数不合法 |
| `401` | 未登录、凭据无效或用户上下文缺失 |
| `403` | 当前用户无权访问该资源 |
| `404` | 会话、资源、文件或配置不存在 |
| `409` | 同名资源冲突 |
| `500` | 服务内部错误 |
| `502` | 沙箱设置验证、依赖预热等下游执行失败 |
| `503` | 模型、MCP、OpenSandbox 等外部服务不可用 |

## 3. 接口总览

| 分组 | 路由前缀 | 说明 |
|------|----------|------|
| 认证与账号 | `/api/auth/*` | 登录、注册、修改账号、修改密码 |
| 统一会话 | `/api/sessions/*` | 会话 CRUD、流式对话、消息、快照、归档 |
| 专家资源 | `/api/agents/*` | 专家列表、新建、更新、删除、导入导出 |
| 场景资源 | `/api/settings/session-presets/*` | 场景列表、保存、导入导出 |
| Skill | `/api/settings/skills/*` | Skill 列表、正文、文件分区、ZIP 导入导出 |
| MCP 工具 | `/api/settings/mcp/*` | MCP 配置、连接测试、工具列表、工具调用、导入导出 |
| 工作区文件 | `/api/sessions/{session_id}/workspace/*` | 会话文件列表、上传、编辑、下载、删除、重命名 |
| 模型与设置 | `/api/settings/app`、`/api/settings/host-profile`、`/api/settings/llm-providers/*` | 应用设置、主持人、模型导入导出 |
| 环境变量 | `/api/settings/env-vars/*` | 用户级环境变量新增、更新、删除、脱敏列表 |
| 沙箱 | `/api/settings/sandbox*` | 沙箱版本、requirements、依赖状态 |
| 运维 | `/health` | 健康检查 |

## 4. 认证与账号接口

### 4.1 登录

```http
POST /api/auth/login
Content-Type: application/json
```

请求体：

```json
{
  "username": "user@example.com",
  "password": "******"
}
```

响应：

```json
{
  "status": "ok",
  "data": {
    "username": "user@example.com",
    "user_id": "user-xxxx",
    "display_name": "user@example.com",
    "access_token": "<token>",
    "token_type": "bearer"
  }
}
```

错误：

- `400`：账号格式不正确。
- `401`：用户名或密码错误。

### 4.2 注册

```http
POST /api/auth/register
```

请求体：

```json
{
  "username": "user@example.com",
  "password": "******"
}
```

成功后返回同登录接口，并初始化当前用户资源目录和空场景资源。

### 4.3 修改账号

```http
PUT /api/auth/account
POST /api/auth/account
```

请求体：

```json
{
  "new_username": "new@example.com",
  "current_password": "******"
}
```

成功后返回新 token。当前密码错误返回 `400`。

### 4.4 修改密码

```http
PUT /api/auth/password
POST /api/auth/password
```

请求体：

```json
{
  "current_password": "******",
  "new_password": "******"
}
```

新密码至少 6 位，且不能与当前密码相同。

## 5. 统一会话接口

### 5.1 会话列表

```http
GET /api/sessions
```

响应：

```json
{
  "status": "ok",
  "data": {
    "sessions": []
  }
}
```

会话列表按 `updated_at` 倒序返回，只包含当前用户会话。

### 5.2 新建会话

```http
POST /api/sessions
Content-Type: application/json
```

请求体：

```json
{
  "title": "新对话",
  "agent_names": ["写作专家"],
  "host": {
    "name": "四九",
    "llm_name": "qwen3-max",
    "system_prompt": "主持人提示词",
    "skill_directory": "host-skill"
  }
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | 否 | 会话标题，默认“新对话” |
| `agent_names` | string[] | 否 | 参与专家名称列表 |
| `host` | object | 否 | 会话级主持人快照；上层对象固定为 `host` |
| `host.name` | string | 否 | 主持人显示名 |
| `host.llm_name` | string | 否 | 主持人使用的模型名称 |
| `host.system_prompt` | string | 否 | 主持人调度提示词，只影响主持人 |
| `host.skill_directory` | string | 否 | 主持人 Skill 目录名，引用 Skill `directory_name` |

### 5.3 会话详情

```http
GET /api/sessions/{session_id}
```

返回会话定义、成员、消息历史、运行状态和工作区相关信息。

### 5.4 更新会话

```http
PUT /api/sessions/{session_id}
```

用于更新标题、成员、场景信息或主持人配置。字段以 `GroupSessionUpdate` 当前后端模型为准。

### 5.5 删除会话

```http
DELETE /api/sessions/{session_id}
```

删除当前用户会话及其关联状态。删除后继续访问应返回不存在。

### 5.6 流式对话

```http
POST /api/sessions/{session_id}/chat/stream
Content-Type: application/json
Accept: text/event-stream
```

请求体：

```json
{
  "message": "请帮我处理这个任务",
  "client_message_id": "client-msg-xxxx",
  "attachments": [
    {
      "type": "workspace_file",
      "name": "附件1.pdf",
      "path": "附件1.pdf"
    }
  ],
  "target_agent_name": "写作专家"
}
```

说明：

- 这是当前会话主入口。
- 普通会话、场景会话和多专家协作都使用该接口。
- `client_message_id` 必填，用于幂等和消息关联。
- `message` 可以为空，但 `message`、`attachments`、`target_agent_name` 至少一个有效。
- `attachments` 只引用当前会话工作区内已存在的文件；原始文件上传先走工作区文件接口。
- `target_agent_name` 可选；存在时必须是当前会话成员，本轮直接交给该专家。
- 请求体不接受 `action`、`host_takeover_requested`、`ignore_auto_agent_name`、`ignore_auto_skill`、`agent_name`、`next_speaker` 等旧控制字段。
- 后端返回 SSE 事件。

### 5.7 非流式对话

```http
POST /api/sessions/{session_id}/chat
```

请求体同流式接口。后端内部复用 SSE 逻辑并聚合结果。

响应：

```json
{
  "status": "ok",
  "data": {
    "route": {},
    "progress": [],
    "messages": [],
    "message": {},
    "end": {},
    "error": null,
    "interrupted": false
  }
}
```

聚合结果必须保持 `/chat/stream` 同一套事件载荷：`route`、`progress`、`message`、`end`、`error`。不得为了非流式接口重新生成 `contents`、顶层 `content` 或 `meta.phase`。

### 5.8 停止会话回复

```http
POST /api/sessions/{session_id}/chat/stop
```

停止当前会话正在运行的回复。

### 5.9 删除消息

```http
DELETE /api/sessions/{session_id}/messages/{message_id}
```

从会话历史中删除单条消息，避免污染后续上下文。

### 5.10 会话事件流

```http
GET /api/sessions/{session_id}/events/stream
Accept: text/event-stream
```

用于会话运行态和消息更新订阅，不返回 `/chat/stream` 的聊天编排事件。

事件：

| 事件 | 载荷重点 | 说明 |
|------|----------|------|
| `snapshot` | `session_id`、`server_time`、`runtime`、`last_message_id`、`updated_at` | 连接成功后立即发送，用于刷新恢复。 |
| `runtime` | `session_id`、`runtime` | `runtime.json` 变化时推送。 |
| `message` | 与 `history.json` 相同的完整消息结构 | 新消息落盘后可选推送；前端也可按 `last_message_id` 触发重拉。 |
| `keepalive` | `server_time` | 保活，不改变业务状态。 |
| `deleted` | `session_id` | 会话被删除。 |
| `error` | `code`、`message` | 订阅错误。 |

约束：

- 关闭浏览器窗口或断开 `/events/stream` 只取消本次订阅，不停止后端运行。
- 停止当前回复必须调用 `POST /api/sessions/{session_id}/chat/stop`。
- 后端发现 `runtime.json.running=true` 但进程内任务不存在且超过过期阈值时，清理运行态并推送 `runtime`，`running=false`、`phase="failed"`。
- 新窗口通过 `GET /api/sessions/{session_id}` 读取历史消息；`/events/stream` 不回放历史 `/chat/stream` 事件。

### 5.11 导出会话 Markdown

```http
POST /api/sessions/{session_id}/export
```

响应：

```json
{
  "status": "ok",
  "data": {
    "path": "session-xxx.md",
    "download_url": "/api/sessions/{session_id}/workspace/files/download?path=session-xxx.md"
  }
}
```

### 5.12 会话快照、克隆和回滚

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/sessions/{session_id}/snapshot` | 创建当前会话检查点 |
| `GET` | `/api/sessions/{session_id}/snapshots` | 列出检查点 |
| `POST` | `/api/sessions/{session_id}/clone` | 从当前或指定检查点克隆会话 |
| `POST` | `/api/sessions/{session_id}/rollback` | 回滚到指定消息或检查点 |

克隆请求体可为空；如需从历史状态分叉，必须且只能提供 `checkpoint_id` 或 `message_id` 之一：

```json
{
  "message_id": "msg-xxxx"
}
```

回滚请求体必须且只能提供 `checkpoint_id` 或 `message_id` 之一：

```json
{
  "checkpoint_id": "checkpoint-xxxx"
}
```

检查点摘要对象字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `checkpoint_id` | string | 对外检查点身份。 |
| `parent_checkpoint_id` | string / null | 上一个检查点身份。 |
| `created_at` | string | 检查点创建时间。 |
| `trigger` | string | 检查点触发来源，如 `turn_started`、`turn_completed`、`workspace_changed`、`manual_snapshot`、`rollback`、`clone`；只用于审计和展示。 |
| `state_hash` | sha256 | 整体状态 hash，用于显示和一致性校验。 |
| `last_message_id` | string / null | 快照对应的最后一条消息 ID。 |

`session_blob`、`history_blob`、`orchestration_state_blob`、`workspace_tree`、`memory_tree` 是检查点内部落盘字段，只允许后端恢复逻辑读取，普通列表和详情接口不返回。

接口不再返回或接收 `commit_id`、`parent`、`reason`、`session_definition`、`chat_blob`、`message_count`。`trigger` 不进入 `state_hash`，也不得被运行时用作恢复分支判断。

行为约束：

- 接收用户消息后、专家或工具执行前创建 `turn_started` 检查点；一轮完整结束后创建 `turn_completed` 检查点。
- 文件上传、新建、保存、删除、重命名完成后创建 `workspace_changed` 检查点；自动保存和连续编辑可短窗口合并。
- rollback 到 `message_id` 表示恢复该消息完成后的状态；没有精确检查点时使用不晚于该消息的最近检查点。找不到可用检查点返回错误。
- rollback 不删除旧检查点链，而是在目标状态上生成新的检查点并更新当前会话 `HEAD`。
- 会话运行中允许修改工作区文件；clone、rollback 和删除消息在运行中不可用，必须等待当前回复结束或先停止当前运行后才能操作。
- 当前回合读取附件或工作区输入时，以本轮 `turn_started` 检查点的工作区快照为准；运行中用户修改文件只影响后续回合。
- 本轮工具或专家产物写入当前 `workspace/`，与运行中用户文件操作按完成顺序串行落盘；同一路径后完成的写入覆盖先完成的写入，且每次写入都形成可回滚检查点。
- `message_id` 不存在、对象缺失或 hash 校验失败时返回错误，不进行猜测恢复。
- 检查点默认逻辑永久保留，不自动清理或压缩。

### 5.13 会话归档

```http
GET /api/sessions/{session_id}/archive
```

返回归档片段和专家信息映射，用于会话归档展示或下载前组装。

## 6. SSE 事件

流式会话接口返回 `text/event-stream`。事件块格式：

```text
event: message
data: {"key":"value"}
```

常见事件：

| 事件 | 说明 | 典型字段 |
|------|------|----------|
| `start` | 本轮开始 | `session_id`、`run_id` |
| `route` | 路由到专家或 Skill | `run_id`、`agent_name`、`skill` |
| `progress` | 当前运行阶段 | `run_id`、`phase`、`agent_name`、`skill`、`text` |
| `message` | 完整消息 | `message_id`、`speaker`、`message`、`created_at`、`client_message_id`、`skill_result` |
| `end` | 本轮结束 | `run_id`、`phase`、`waiting_for_user`、`suggested_next_speaker`、`suggested_add_agent_names` |
| `error` | 错误 | `run_id`、`code`、`message` |

约束：

- 前端不自行推断主持人调度结果，只消费后端 `route` 和 `end`。
- `route` 不返回 `expert_route_debug`、`skill_route_debug`、`routing`、`route_source`。`route_source` 只用于后端内部日志和测试断言，不进入 API 响应或 SSE 事件。
- `progress.phase` 必须等于当前 `runtime.json.phase`；平台不使用 `meta.phase`。
- `end.waiting_for_user=true` 表示界面应等待用户继续输入或确认。
- 平台不提供 `discussion_ended` 字段；`end` 表示当前回合结束，不表示整个会话关闭。
- `tool_start`、`tool_result` 不作为顶层 SSE 事件；工具明细进入执行 trace、运行日志或 `skill_result.artifacts`。
- `error.message` 只放错误文本，不承载附件、主持人下一步或完整消息结构；需要给用户展示的恢复说明应另发标准 `message` 事件。
- 前端可以把 `progress.phase` 映射成中文 UI 文案，但不能把 UI 文案或本地 `_streaming` 状态写回 API、历史、运行态或 mock。
- 前端不得从 `message.content` 正则推断招募专家、下一位专家、文件引用或路由结果；这些必须来自结构化字段。
- 场景模式下，后端会抑制场景外专家招募建议。

## 7. 专家接口

### 7.1 专家列表

```http
GET /api/agents
```

响应字段：

| 字段 | 说明 |
|------|------|
| `instances` | 当前用户专家列表 |

### 7.2 新建专家

```http
POST /api/agents
```

请求体：

```json
{
  "name": "写作专家",
  "description": "负责写作和润色",
  "system_prompt": "专家提示词",
  "skills": [
    {
      "name": "写作 Skill",
      "directory_name": "writing-skill"
    }
  ],
  "llm_name": "qwen3-max"
}
```

同名专家返回 `409`。

### 7.3 更新专家

```http
PUT /api/agents/{agent_name}
```

请求体字段均可选，支持改名、描述、提示词、Skill 引用和模型引用。

### 7.4 删除专家

```http
DELETE /api/agents/{agent_name}
```

### 7.5 专家资源包

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/agents/{agent_name}/export-bundle` | 导出专家 ZIP 包 |
| `POST` | `/api/agents/import-bundle` | 导入专家 ZIP 包 |

导入表单字段：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `file` | file | 必填 | ZIP 专家包 |
| `dry_run` | bool | `true` | 只预览不写入 |
| `overwrite_skills` | bool | `true` | 是否覆盖同名 Skill |
| `mcp_skip_existing` | bool | `false` | 是否跳过已有 MCP |

## 8. 场景接口

### 8.1 场景列表

```http
GET /api/settings/session-presets
```

返回当前用户场景/会话预设列表。

### 8.2 保存场景

```http
PUT /api/settings/session-presets
```

用于保存场景资源列表。场景通过名称引用主持人配置、专家和 Skill。

### 8.3 场景资源包

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/session-presets/{preset_name}/export-bundle` | 导出场景 ZIP 包 |
| `POST` | `/api/settings/session-presets/import-bundle` | 导入场景 ZIP 包 |

导入接口使用 multipart form，至少包含 `file` 和可选 `dry_run`。

## 9. Skill 接口

### 9.1 Skill 列表与创建

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/skills` | Skill 列表 |
| `POST` | `/api/settings/skills` | 新建 Skill |

### 9.2 Skill 元信息和正文

| 方法 | 路径 | 说明 |
|------|------|------|
| `PUT` | `/api/settings/skills/{directory_name}` | 更新 Skill 元信息 |
| `DELETE` | `/api/settings/skills/{directory_name}` | 删除 Skill |
| `GET` | `/api/settings/skills/{directory_name}/content` | 读取 `SKILL.md` |

### 9.3 Skill 文件分区

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/skills/{directory_name}/parts` | 列出文件分区 |
| `GET` | `/api/settings/skills/{directory_name}/parts/{part_type}/{file_path}` | 读取文件 |
| `POST` | `/api/settings/skills/{directory_name}/parts/{part_type}` | 新建文件 |
| `POST` | `/api/settings/skills/{directory_name}/parts/{part_type}/mkdir` | 新建目录 |
| `PUT` | `/api/settings/skills/{directory_name}/parts/{part_type}/{file_path}` | 保存文件 |
| `DELETE` | `/api/settings/skills/{directory_name}/parts/{part_type}/{file_path}` | 删除文件 |

常见 `part_type`：

- `scripts`
- `references`
- `assets`
- `templates`

### 9.4 Skill ZIP 导入导出

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/skills/{directory_name}/export-zip` | 导出 Skill ZIP |
| `POST` | `/api/settings/skills/import-zip` | 导入 Skill ZIP |

## 10. MCP 接口

### 10.1 MCP 列表

```http
GET /api/settings/mcp
```

### 10.2 新建 MCP

```http
POST /api/settings/mcp
```

请求体：

```json
{
  "name": "Exa 搜索",
  "type": "mcp",
  "description": "搜索工具",
  "server_config": "{\"mcpServers\":{\"exa-search\":{\"command\":\"npx\",\"args\":[\"-y\",\"exa-mcp-server\"],\"env\":{\"EXA_API_KEY\":\"${env:EXA_API_KEY}\"}}}}",
  "config": {},
  "metadata": {}
}
```

`server_config` 使用 MCP 标准配置结构的 JSON 字符串。导入标准 `mcpServers` JSON 时按工具名称保存到 `server_config`。

### 10.3 更新和删除 MCP

| 方法 | 路径 | 说明 |
|------|------|------|
| `PUT` | `/api/settings/mcp/{tool_name}` | 更新 MCP 配置 |
| `DELETE` | `/api/settings/mcp/{tool_name}` | 删除 MCP 配置 |

### 10.4 MCP 测试与调用

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/settings/mcp/{tool_name}/test` | 测试连接 |
| `GET` | `/api/settings/mcp/{tool_name}/tools` | 获取工具列表和 schema |
| `POST` | `/api/settings/mcp/{server_name}/tools/{tool_name}/call` | 直接调用指定工具 |
| `POST` | `/api/settings/mcp/{tool_name}/sandbox-call` | 沙箱内测试调用 |

### 10.5 MCP ZIP 导入导出

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/mcp/{tool_name}/export-zip` | 导出 MCP ZIP |
| `POST` | `/api/settings/mcp/import-zip` | 导入 MCP ZIP |

导出包不得包含环境变量真实值，只能保存 `${env:NAME}` 引用名。

## 11. 工作区文件接口

### 11.1 有文件的会话列表

```http
GET /api/sessions/with-workspace-files
```

### 11.2 文件列表

```http
GET /api/sessions/{session_id}/workspace/files?path=
```

### 11.3 新建文件或目录

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/sessions/{session_id}/workspace/files` | 新建文件 |
| `POST` | `/api/sessions/{session_id}/workspace/files/mkdir` | 新建目录 |

### 11.4 上传文件

```http
POST /api/sessions/{session_id}/workspace/files/upload
Content-Type: multipart/form-data
```

### 11.5 读取、保存和删除文件内容

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/sessions/{session_id}/workspace/files/content?path=...` | 读取文件内容 |
| `PUT` | `/api/sessions/{session_id}/workspace/files/content` | 保存文件内容 |
| `DELETE` | `/api/sessions/{session_id}/workspace/files/content?path=...` | 删除文件 |

### 11.6 下载和重命名

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/sessions/{session_id}/workspace/files/download?path=...` | 下载文件 |
| `PUT` | `/api/sessions/{session_id}/workspace/files/rename` | 重命名或移动文件 |

路径约束：

- `path` 必须是工作区相对路径。
- 重命名或移动目标使用 `target_path`，含义为当前会话 `workspace/` 内目标相对路径。
- 后端拒绝路径穿越、绝对路径、`memory/`、`checkpoints/`、运行日志目录和任何会话内部系统目录。
- `workspace/` 内允许普通点文件，例如 `.gitignore` 和 `.env.example`。
- 当前用户只能访问自己的会话工作区。
- 用户主动导出的 Markdown、ZIP、报告等成果文件可以写入 `workspace/`；运行日志、trace 和中间缓存不得写入 `workspace/`。

## 12. 模型、主持人、环境变量和应用设置接口

### 12.1 应用设置

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/app` | 获取应用设置、默认模型和模型配置 |
| `PUT` | `/api/settings/app` | 更新应用设置 |

响应中的模型环境变量真实值不返回明文，只返回是否已配置的状态。

### 12.2 默认主持人

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/host-profile` | 获取默认主持人配置 |
| `PUT` | `/api/settings/host-profile` | 更新默认主持人配置 |
| `GET` | `/api/settings/host-profile/defaults` | 获取内置默认主持人 |
| `POST` | `/api/settings/host-profile/reset` | 重置默认主持人 |

主持人请求体：

```json
{
  "name": "四九",
  "system_prompt": "主持人提示词",
  "llm_name": "qwen3-max",
  "skill_name": "主持人 Skill",
  "skill_directory": "host-skill"
}
```

### 12.3 模型导入导出

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/llm-providers/{llm_name}/export-bundle` | 导出模型配置 ZIP |
| `POST` | `/api/settings/llm-providers/import-bundle` | 导入模型配置 ZIP |

模型包不导入环境变量真实值。

### 12.4 环境变量接口

平台内用户级环境变量是产品主契约，不等同于宿主机 `.env`。宿主机环境变量只作为部署级默认值。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/env-vars` | 环境变量列表，不返回真实值 |
| `POST` | `/api/settings/env-vars` | 新建环境变量 |
| `PUT` | `/api/settings/env-vars/{name}` | 更新环境变量 |
| `DELETE` | `/api/settings/env-vars/{name}` | 删除环境变量 |

环境变量可被模型、MCP、HTTP API、Skill 脚本和沙箱通过 `api_key_env` 或 `${env:NAME}` 使用。旧 `/api/settings/api-secrets`、`${vault:...}` 和 `api_key_ref` 不属于当前目标契约。

## 13. 沙箱接口

### 13.1 沙箱设置

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/sandbox` | 获取沙箱版本、镜像和可选项 |
| `PUT` | `/api/settings/sandbox` | 保存沙箱版本 |

请求体：

```json
{
  "image_variant": "standard"
}
```

常见版本：

- `standard`
- `playwright`

### 13.2 requirements

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/sandbox/requirements` | 获取当前用户 requirements |
| `PUT` | `/api/settings/sandbox/requirements` | 保存 requirements |
| `POST` | `/api/settings/sandbox/requirements/merge` | 合并依赖 |
| `POST` | `/api/settings/sandbox/requirements/status` | 查询依赖状态 |

保存请求体：

```json
{
  "content": "requests>=2.31\npandas"
}
```

合并请求体：

```json
{
  "requirements": ["requests>=2.31", "pandas"]
}
```

## 14. 运维接口

### 14.1 健康检查

```http
GET /health
```

响应：

```json
{
  "status": "ok"
}
```

### 14.2 根路径

```http
GET /
```

当前端静态目录存在时返回前端入口；否则返回后端基础信息或由静态 SPA fallback 处理。

## 15. 安全与权限规则

| 规则 | 说明 |
|------|------|
| 用户隔离 | 所有受保护接口必须基于当前用户上下文读写 |
| 环境变量脱敏 | 前端接口不得返回完整变量值 |
| 路径安全 | 工作区文件路径必须归一化并拒绝 `../` |
| 工具授权 | 外部工具集合由当前 Skill `allowed-tools` 收敛；专家不直接保存工具权限 |
| 导入导出安全 | ZIP 包不携带账号凭据和环境变量真实值 |
| 运行态可见 | 工具失败、等待用户、沙箱异常必须通过事件或响应返回 |

## 16. 测试映射

| 接口分组 | 自动化入口 |
|----------|------------|
| 认证与账号 | `backend/tests/test_auth_sqlite.py`、`frontend/e2e/auth.spec.ts` |
| 统一会话 | `backend/tests/test_sessions_api.py`、`backend/tests/test_group_chat_stream_protocol.py`、`frontend/e2e/workspace.spec.ts` |
| 主持人调度 | `backend/tests/test_group_host_decision.py`、`backend/tests/test_host_takeover.py`、`backend/tests/test_scene_scheduler.py` |
| 资源中心 | `backend/tests/test_agents_api.py`、`frontend/e2e/resources-scenario-expert.spec.ts`、`frontend/e2e/resources-skill-mcp-llm.spec.ts` |
| Skill 与 MCP | `backend/tests/test_skill_agent_tool_resolution.py`、`backend/tests/test_file_ref_and_gateway.py` |
| 工作区文件 | `backend/tests/test_workspace_files.py`、`frontend/e2e/workspace.spec.ts` |
| 导入导出 | `backend/tests/test_bundle_import_api.py`、`backend/tests/test_scenario_bundle.py`、`backend/tests/test_expert_bundle.py` |
| 沙箱 | `backend/tests/test_sandbox_service.py`、`backend/tests/test_sandbox_policy_runtime.py`、`backend/tests/test_sandbox_requirements_runtime.py` |
| 部署 | `backend/tests/test_lifespan.py`、`backend/tests/test_static_spa.py`、`backend/tests/test_pack_1panel_backup.py` |

## 17. 变更规则

后续修改接口时必须同步检查：

1. 是否改变前端调用路径或请求字段。
2. 是否改变 SSE 事件类型或事件载荷。
3. 是否影响用户隔离、环境变量脱敏、路径安全或工具授权。
4. 是否需要更新 `frontend/e2e/fixtures/mockApi.ts`；mock 必须使用真实 API 的事件名和消息结构，不得保留旧字段。
5. 是否需要更新 `docs/testing/test-case-catalog.md`。
6. 是否需要补充后端 API 测试或前端 E2E。

只改文档时，至少运行：

```bash
rtk proxy git diff --check -- docs
```
