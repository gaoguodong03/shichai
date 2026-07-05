# API 设计文档

## 概述

本文记录书童四九当前后端 API 的设计边界、认证约定、主要端点和响应格式。更细的字段以 `backend/app/api/` 下的 FastAPI 路由和 Pydantic 模型为准。

所有业务 API 统一挂载在 `/api` 下；健康检查和前端静态入口除外。

## API 基础

### 基础 URL

- 本地后端开发：`http://localhost:8000`
- 1Panel/Docker 默认主应用：`http://<server-ip>:8100`
- 前端同源部署：浏览器访问前端页面后，通过相对路径 `/api/...` 调用后端。

### 认证方式

当前系统已经实现账号登录和用户上下文隔离，不再是公开 API。

前端登录后保存会话凭据，后续请求携带认证信息。测试和本地开发中也支持通过 `X-User-Name` 请求头指定用户上下文。生产环境应关闭匿名 API：

```bash
ALLOW_ANONYMOUS_API=0
```

关键约束：

- 受保护路由通过 `user_context_dependency` 注入当前用户。
- 用户资源、会话、工作区文件、Skill、MCP、模型、密钥和沙箱配置都按用户隔离。
- API Key 等敏感字段返回前端时必须脱敏。

### 响应格式

多数 JSON API 使用以下格式：

```json
{
  "status": "ok",
  "data": {}
}
```

部分导出接口直接返回文件流；流式会话接口返回 Server-Sent Events (SSE)。

### 错误处理

常见 HTTP 状态码：

| 状态码 | 场景 |
|--------|------|
| `400` | 请求结构、导入包、路径或配置不合法 |
| `401` | 未登录或凭据无效 |
| `403` | 当前用户无权访问该资源 |
| `404` | 会话、资源、文件或配置不存在 |
| `500` | 服务内部错误 |
| `503` | 外部服务、模型、MCP 或沙箱不可用 |

## 主要端点

### 认证与账号

| 方法 | 路径 | 用途 |
|------|------|------|
| `POST` | `/api/auth/login` | 登录 |
| `POST` | `/api/auth/register` | 注册 |
| `PUT` / `POST` | `/api/auth/account` | 修改账号 |
| `PUT` / `POST` | `/api/auth/password` | 修改密码 |

### 统一会话

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/sessions` | 当前用户会话列表 |
| `POST` | `/api/sessions` | 新建普通会话或带专家/场景成员的会话 |
| `GET` | `/api/sessions/{session_id}` | 会话详情、历史、成员、meta |
| `PUT` | `/api/sessions/{session_id}` | 更新会话标题、成员或场景信息 |
| `DELETE` | `/api/sessions/{session_id}` | 删除会话 |
| `POST` | `/api/sessions/{session_id}/chat/stream` | SSE 流式发送消息 |
| `POST` | `/api/sessions/{session_id}/chat` | 非流式兜底聚合响应 |
| `POST` | `/api/sessions/{session_id}/chat/stop` | 停止当前会话回复 |
| `DELETE` | `/api/sessions/{session_id}/messages/{message_id}` | 删除单条消息 |
| `GET` | `/api/sessions/{session_id}/events/stream` | 会话事件流 |
| `POST` | `/api/sessions/{session_id}/export` | 导出会话到工作区 Markdown |
| `POST` | `/api/sessions/{session_id}/prompt-preview` | 预览提示词 |
| `GET` | `/api/sessions/{session_id}/archive` | 下载会话归档 |

`/api/sessions/{session_id}/chat/stream` 是主入口，单人对话和多人专家协作都复用同一套带主持人的会话模型。

### SSE 事件

流式会话以 SSE 返回，前端按事件类型消费。常见事件：

| 事件 | 说明 |
|------|------|
| `route` | 本轮路由到的专家、Skill 和工具信息 |
| `content` | 增量文本片段 |
| `message` | 完整消息气泡 |
| `tool_start` / `tool_result` | 工具调用开始和结果 |
| `end` | 本轮结束，包含调度阶段和下一步状态 |
| `error` | 可展示错误 |

非流式 `/chat` 会内部消费同一条 SSE 流，并优先返回 `route.agent_name` 对应的专家消息。

### 专家与资源

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/agents` | 专家列表 |
| `POST` | `/api/agents` | 新建专家 |
| `PUT` | `/api/agents/{agent_name}` | 更新专家 |
| `DELETE` | `/api/agents/{agent_name}` | 删除专家 |
| `GET` | `/api/dha/instances/{agent_name}/export-bundle` | 导出专家资源包 |
| `POST` | `/api/dha/instances/import-bundle` | 导入专家资源包 |

`/api/agents/*` 是 Agent 配置主入口；`/api/dha/instances/*` 仅保留专家资源包导入导出接口。

### 场景和会话预设

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/settings/session-presets` | 场景/会话预设列表 |
| `PUT` | `/api/settings/session-presets` | 保存场景/会话预设 |
| `GET` | `/api/settings/session-presets/{preset_id}/export-bundle` | 导出场景资源包 |
| `POST` | `/api/settings/session-presets/import-bundle` | 导入场景资源包 |

公开分享链接、分享预览页和公共分享 API 已下线。跨账号复用使用 ZIP 资源包导入导出。

### Skill

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/settings/skills` | Skill 列表 |
| `POST` | `/api/settings/skills` | 新建 Skill |
| `PUT` | `/api/settings/skills/{directory_name}` | 更新 Skill 元信息 |
| `DELETE` | `/api/settings/skills/{directory_name}` | 删除 Skill |
| `GET` | `/api/settings/skills/{directory_name}/content` | 读取 `SKILL.md` |
| `GET` | `/api/settings/skills/{directory_name}/parts` | 读取 Skill 文件分区 |
| `GET` | `/api/settings/skills/{directory_name}/parts/{part_type}/{file_path}` | 读取 Skill 文件 |
| `POST` | `/api/settings/skills/{directory_name}/parts/{part_type}` | 新建 Skill 文件 |
| `POST` | `/api/settings/skills/{directory_name}/parts/{part_type}/mkdir` | 新建目录 |
| `PUT` | `/api/settings/skills/{directory_name}/parts/{part_type}/{file_path}` | 保存 Skill 文件 |
| `DELETE` | `/api/settings/skills/{directory_name}/parts/{part_type}/{file_path}` | 删除 Skill 文件 |
| `GET` | `/api/settings/skills/{directory_name}/export-zip` | 导出 Skill ZIP |
| `POST` | `/api/settings/skills/import-zip` | 导入 Skill ZIP |

脚本路径、工作区路径和沙箱约束见 [Skill 脚本路径手册](../skills/skill-script-paths.md)。

### MCP

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/settings/mcp` | MCP Server 列表 |
| `POST` | `/api/settings/mcp` | 新建 MCP Server |
| `PUT` | `/api/settings/mcp/{server_id}` | 更新 MCP Server |
| `DELETE` | `/api/settings/mcp/{server_id}` | 删除 MCP Server |
| `POST` | `/api/settings/mcp/{server_id}/test` | 测试连接 |
| `GET` | `/api/settings/mcp/{server_id}/tools` | 工具列表 |
| `POST` | `/api/settings/mcp/{server_id}/tools/{tool_name}/call` | 直接测试工具调用 |
| `POST` | `/api/settings/mcp/{server_id}/sandbox-call` | 沙箱内测试调用 |
| `GET` | `/api/settings/mcp/{server_id}/export-zip` | 导出 MCP 配置 |
| `POST` | `/api/settings/mcp/import-zip` | 导入 MCP 配置 |

### 工作区文件

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/workspaces/sessions-with-files` | 有文件的会话列表 |
| `GET` | `/api/workspaces/{workspace_id}/files` | 文件列表 |
| `POST` | `/api/workspaces/{workspace_id}/files` | 新建文件 |
| `POST` | `/api/workspaces/{workspace_id}/files/upload` | 上传文件 |
| `POST` | `/api/workspaces/{workspace_id}/files/mkdir` | 新建目录 |
| `GET` | `/api/workspaces/{workspace_id}/files/content` | 读取文件内容 |
| `PUT` | `/api/workspaces/{workspace_id}/files/content` | 保存文件内容 |
| `DELETE` | `/api/workspaces/{workspace_id}/files/content` | 删除文件 |
| `PUT` | `/api/workspaces/{workspace_id}/files/rename` | 重命名 |
| `GET` | `/api/workspaces/{workspace_id}/files/download` | 下载 |

所有工作区路径都必须经过后端归一化和路径穿越检查。

### LLM、密钥、主持人和应用设置

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` / `PUT` | `/api/settings/app` | 应用级设置 |
| `GET` / `PUT` | `/api/settings/host-profile` | 默认主持人配置 |
| `GET` | `/api/settings/host-profile/defaults` | 主持人默认值 |
| `POST` | `/api/settings/host-profile/reset` | 重置主持人 |
| `GET` / `POST` | `/api/settings/api-secrets` | 密钥列表与新增 |
| `PUT` / `DELETE` | `/api/settings/api-secrets/{secret_id}` | 更新或删除密钥 |

模型供应商配置保存在应用设置中，具体解析逻辑见 `backend/app/agent/llm_client.py`。

### 沙箱设置

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` / `PUT` | `/api/settings/sandbox` | 沙箱版本与策略设置 |
| `GET` / `PUT` | `/api/settings/sandbox/requirements` | 当前用户 Python requirements |
| `POST` | `/api/settings/sandbox/requirements/merge` | 合并依赖 |

## 版本控制

当前 API 未引入 URL 版本号，统一使用 `/api` 前缀。若后续引入破坏性变更，再通过 `/api/v2` 或请求头约定迁移。

## 相关文档

- [系统架构图](system-architecture.md)
- [运行架构说明](runtime-architecture.md)
- [项目结构文档](project-structure.md)
- [需求说明与验收测试](../requirements/acceptance-and-tests.md)
