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

- 会话、资源、文件、Skill、MCP、模型、密钥和沙箱配置都按当前用户隔离。
- 未登录或令牌无效返回 `401`。
- 业务错误不要滥用 `401`，例如当前密码错误应返回 `400`。
- API Key 等敏感字段返回前端时必须脱敏。

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
| 工作区文件 | `/api/workspaces/*` | 会话文件列表、上传、编辑、下载、删除、重命名 |
| 模型与设置 | `/api/settings/app`、`/api/settings/host-profile`、`/api/settings/llm-providers/*` | 应用设置、主持人、模型导入导出 |
| 密钥 | `/api/settings/api-secrets/*` | 密钥新增、更新、删除、脱敏列表 |
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
  "system_prompt": "",
  "scenario_name": "场景名称",
  "orchestration_profile": "scene",
  "leader_agent_name": "四九",
  "host_config": {
    "leader_agent_name": "四九",
    "llm_name": "qwen3-max",
    "system_prompt": "主持人提示词",
    "skill_name": "主持人 Skill",
    "skill_directory": "host-skill"
  }
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | 否 | 会话标题，默认“新对话” |
| `agent_names` | string[] | 否 | 参与专家名称列表 |
| `system_prompt` | string | 否 | 会话额外系统提示 |
| `scenario_name` | string | 否 | 场景名称引用 |
| `orchestration_profile` | string | 否 | 编排模式，如 `scene` |
| `leader_agent_name` | string | 否 | 主持人显示名 |
| `host_config` | object | 否 | 场景或会话主持人配置 |

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
  "client_message_id": "client-msg-xxxx"
}
```

说明：

- 这是当前会话主入口。
- 普通会话、场景会话和多专家协作都使用该接口。
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
    "contents": [],
    "messages": [],
    "message": {},
    "end": {},
    "error": null,
    "interrupted": false
  }
}
```

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

用于会话运行态和消息更新订阅。

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
    "download_url": "/api/workspaces/{session_id}/files/download?path=session-xxx.md"
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

克隆请求体：

```json
{
  "checkpoint_id": "commit-xxxx",
  "message_id": "msg-xxxx"
}
```

回滚请求体至少提供一个字段：

```json
{
  "checkpoint_id": "commit-xxxx",
  "message_id": "msg-xxxx",
  "message_count": 3
}
```

### 5.13 会话归档

```http
GET /api/sessions/{group_session_id}/archive
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
| `start` | 本轮开始 | `session_id` |
| `route` | 路由到专家或 Skill | `agent_name`、`skill`、`skill_route_debug` |
| `content` | 增量内容 | `content` |
| `tool_start` | 工具开始 | `tool`、`args` |
| `tool_result` | 工具结果 | `tool`、`status`、`result`、`error` |
| `message` | 完整消息 | `message_id`、`role`、`speaker`、`content`、`agent_name` |
| `end` | 本轮结束 | `phase`、`waiting_for_user`、`suggested_add_agent_names` |
| `error` | 错误 | `error`、`detail` |

约束：

- 前端不自行推断主持人调度结果，只消费后端 `route` 和 `end`。
- `end.waiting_for_user=true` 表示界面应等待用户继续输入或确认。
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
  "transport": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "exa-mcp-server"],
    "env": {
      "EXA_API_KEY": "${vault:exa}"
    }
  },
  "server_config": null,
  "config": {},
  "metadata": {}
}
```

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

导出包不得包含密钥明文，只能保存密钥引用。

## 11. 工作区文件接口

### 11.1 有文件的会话列表

```http
GET /api/workspaces/sessions-with-files
```

### 11.2 文件列表

```http
GET /api/workspaces/{workspace_id}/files?path=
```

### 11.3 新建文件或目录

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/workspaces/{workspace_id}/files` | 新建文件 |
| `POST` | `/api/workspaces/{workspace_id}/files/mkdir` | 新建目录 |

### 11.4 上传文件

```http
POST /api/workspaces/{workspace_id}/files/upload
Content-Type: multipart/form-data
```

### 11.5 读取、保存和删除文件内容

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/workspaces/{workspace_id}/files/content?path=...` | 读取文件内容 |
| `PUT` | `/api/workspaces/{workspace_id}/files/content` | 保存文件内容 |
| `DELETE` | `/api/workspaces/{workspace_id}/files/content?path=...` | 删除文件 |

### 11.6 下载和重命名

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/workspaces/{workspace_id}/files/download?path=...` | 下载文件 |
| `PUT` | `/api/workspaces/{workspace_id}/files/rename` | 重命名文件或目录 |

路径约束：

- `path` 必须是工作区相对路径。
- 后端拒绝路径穿越。
- 当前用户只能访问自己的会话工作区。

## 12. 模型、主持人、密钥和应用设置接口

### 12.1 应用设置

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/app` | 获取应用设置、默认模型和模型配置 |
| `PUT` | `/api/settings/app` | 更新应用设置 |

响应中的模型 API Key 不返回明文，只返回 `api_key_set`。

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
  "leader_agent_name": "四九",
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

模型包不导入 API Key 明文。

### 12.4 密钥接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/settings/api-secrets` | 密钥列表，脱敏返回 |
| `POST` | `/api/settings/api-secrets` | 新建密钥 |
| `PUT` | `/api/settings/api-secrets/{secret_id}` | 更新密钥 |
| `DELETE` | `/api/settings/api-secrets/{secret_id}` | 删除密钥 |

密钥可被模型和 MCP 通过 `${vault:secret_id}` 或密钥引用字段使用。

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
| 密钥脱敏 | 前端接口不得返回完整 API Key |
| 路径安全 | 工作区文件路径必须归一化并拒绝 `../` |
| 工具授权 | 专家工具集合由专家配置和当前 Skill 声明收敛 |
| 导入导出安全 | ZIP 包不携带账号凭据和密钥明文 |
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
3. 是否影响用户隔离、密钥脱敏、路径安全或工具授权。
4. 是否需要更新 `frontend/e2e/fixtures/mockApi.ts`。
5. 是否需要更新 `docs/testing/test-case-catalog.md`。
6. 是否需要补充后端 API 测试或前端 E2E。

只改文档时，至少运行：

```bash
rtk proxy git diff --check -- docs
```
