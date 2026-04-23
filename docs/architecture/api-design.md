# API 设计文档

## 概述

本文档描述了 DHA 项目的 RESTful API 设计规范，包括所有端点的详细说明、请求/响应格式和错误处理。

## API 基础

### 基础 URL

- **开发环境**: `http://localhost:8000`
- **生产环境**: `https://api.yourdomain.com`

### 认证方式

当前版本暂不实现用户认证，所有 API 为公开访问。未来版本将支持：

- JWT Token 认证
- API Key 认证

### 响应格式

所有 API 响应使用 JSON 格式：

```json
{
  "data": {...},
  "message": "Success",
  "status": "ok"
}
```

### 错误处理

错误响应格式：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Error message",
    "details": {...}
  },
  "status": "error"
}
```

常见 HTTP 状态码：

- `200 OK`: 请求成功
- `201 Created`: 资源创建成功
- `400 Bad Request`: 请求参数错误
- `404 Not Found`: 资源不存在
- `500 Internal Server Error`: 服务器内部错误

## API 端点

### 对话 API

#### 发送消息（流式响应）

```http
POST /api/chat/stream
Content-Type: application/json
```

**请求体**:
```json
{
  "message": "Hello, how can you help me?",
  "session_id": "session-123",
  "model_id": "model-1",
  "stream": true
}
```

**响应**: Server-Sent Events (SSE) 流

```
event: react_step
data: {"type": "thought", "content": "用户询问如何帮助..."}

event: react_step
data: {"type": "tool_call", "tool": "search", "args": {...}}

event: content
data: {"text": "我可以帮助您..."}
```

#### 发送消息（非流式）

```http
POST /api/chat
Content-Type: application/json
```

**请求体**:
```json
{
  "message": "Hello",
  "session_id": "session-123",
  "model_id": "model-1"
}
```

**响应**:
```json
{
  "data": {
    "response": "Hello! How can I help you?",
    "session_id": "session-123",
    "steps": [
      {
        "type": "thought",
        "content": "..."
      }
    ]
  },
  "status": "ok"
}
```

### Session API

#### 获取 Session 列表

```http
GET /api/sessions?status=active&limit=20&offset=0
```

**查询参数**:
- `status`: Session 状态（active, archived, deleted）
- `limit`: 每页数量（默认 20）
- `offset`: 偏移量（默认 0）

**响应**:
```json
{
  "data": {
    "sessions": [
      {
        "id": "session-123",
        "title": "Python 编程讨论",
        "status": "active",
        "message_count": 10,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:05:00Z"
      }
    ],
    "total": 50,
    "limit": 20,
    "offset": 0
  },
  "status": "ok"
}
```

#### 创建 Session

```http
POST /api/sessions
Content-Type: application/json
```

**请求体**:
```json
{
  "title": "新对话",
  "metadata": {
    "model": "gpt-4",
    "temperature": 0.7
  }
}
```

**响应**:
```json
{
  "data": {
    "id": "session-123",
    "title": "新对话",
    "status": "active",
    "messages": [],
    "metadata": {
      "model": "gpt-4",
      "temperature": 0.7
    },
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  },
  "status": "ok"
}
```

#### 获取 Session 详情

```http
GET /api/sessions/{session_id}
```

**响应**:
```json
{
  "data": {
    "id": "session-123",
    "title": "Python 编程讨论",
    "status": "active",
    "messages": [
      {
        "role": "user",
        "content": "Hello",
        "timestamp": "2024-01-01T00:00:00Z"
      },
      {
        "role": "assistant",
        "content": "Hi! How can I help you?",
        "timestamp": "2024-01-01T00:00:01Z"
      }
    ],
    "metadata": {},
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:05:00Z"
  },
  "status": "ok"
}
```

#### 更新 Session

```http
PUT /api/sessions/{session_id}
Content-Type: application/json
```

**请求体**:
```json
{
  "title": "更新后的标题",
  "metadata": {
    "model": "gpt-4"
  }
}
```

#### 删除 Session

```http
DELETE /api/sessions/{session_id}
```

**响应**:
```json
{
  "data": {
    "id": "session-123",
    "deleted": true
  },
  "status": "ok"
}
```

#### 归档 Session

```http
POST /api/sessions/{session_id}/archive
```

### 模型配置 API

#### 获取模型列表

```http
GET /api/settings/models
```

**响应**:
```json
{
  "data": {
    "models": [
      {
        "id": "model-1",
        "name": "GPT-4",
        "provider": "openai",
        "model_name": "gpt-4",
        "enabled": true,
        "status": "connected"
      }
    ],
    "default_model_id": "model-1"
  },
  "status": "ok"
}
```

#### 添加模型配置

```http
POST /api/settings/models
Content-Type: application/json
```

**请求体**:
```json
{
  "name": "GPT-4",
  "provider": "openai",
  "model_name": "gpt-4",
  "api_key": "sk-...",
  "default_params": {
    "temperature": 0.7,
    "max_tokens": 2000
  }
}
```

#### 更新模型配置

```http
PUT /api/settings/models/{model_id}
Content-Type: application/json
```

#### 删除模型配置

```http
DELETE /api/settings/models/{model_id}
```

#### 设置默认模型

```http
POST /api/settings/models/{model_id}/set-default
```

#### 测试模型连接

```http
POST /api/settings/models/{model_id}/test
```

**响应**:
```json
{
  "data": {
    "connected": true,
    "response_time": 123,
    "error": null
  },
  "status": "ok"
}
```

### MCP 配置 API

#### 获取 MCP Server 列表

```http
GET /api/settings/mcp
```

**响应**:
```json
{
  "data": {
    "servers": [
      {
        "id": "mcp-server-1",
        "name": "文件系统 MCP",
        "enabled": true,
        "tool_count": 5,
        "status": "connected"
      }
    ]
  },
  "status": "ok"
}
```

#### 添加 MCP Server

```http
POST /api/settings/mcp
Content-Type: application/json
```

**请求体**:
```json
{
  "name": "文件系统 MCP",
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "mcp_server_fs"]
  }
}
```

#### 更新 MCP Server

```http
PUT /api/settings/mcp/{server_id}
Content-Type: application/json
```

#### 删除 MCP Server

```http
DELETE /api/settings/mcp/{server_id}
```

#### 启用/禁用 MCP Server

```http
POST /api/settings/mcp/{server_id}/enable
POST /api/settings/mcp/{server_id}/disable
```

#### 获取 MCP Server 工具列表

```http
GET /api/settings/mcp/{server_id}/tools
```

**响应**:
```json
{
  "data": {
    "tools": [
      {
        "name": "file-reader_read_pdf",
        "description": "读取 PDF 文件内容（示例，实际工具名以 MCP 为准）",
        "parameters": {
          "type": "object",
          "properties": {
            "path": {
              "type": "string",
              "description": "文件路径"
            }
          }
        }
      }
    ]
  },
  "status": "ok"
}
```

#### 测试 MCP Server 连接

```http
POST /api/settings/mcp/{server_id}/test
```

### Skills 配置 API

#### 获取 Skills 列表

```http
GET /api/settings/skills
```

**响应**:
```json
{
  "data": {
    "skills": [
      {
        "id": "skill-1",
        "name": "数据分析",
        "description": "数据分析技能",
        "path": "/path/to/skill",
        "allowed_tools": {
          "mcp": ["file-reader"],
          "python": "requests==2.32.3"
        }
      }
    ]
  },
  "status": "ok"
}
```

#### 添加 Skill

```http
POST /api/settings/skills
Content-Type: application/json
```

**请求体**:
```json
{
  "name": "数据分析",
  "description": "用于分析数据并生成报告"
}
```

#### 更新 Skill

```http
PUT /api/settings/skills/{skill_id}
Content-Type: application/json
```

#### 删除 Skill

```http
DELETE /api/settings/skills/{skill_id}
```

## 错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| `INVALID_REQUEST` | 400 | 请求参数无效 |
| `RESOURCE_NOT_FOUND` | 404 | 资源不存在 |
| `MODEL_NOT_AVAILABLE` | 503 | 模型不可用 |
| `MCP_SERVER_ERROR` | 500 | MCP Server 错误 |
| `INTERNAL_ERROR` | 500 | 服务器内部错误 |

## 版本控制

当前 API 版本：`v1`

未来版本将通过 URL 路径或请求头指定：

```
/api/v1/chat
```

或

```
/api/chat
X-API-Version: v1
```

## 限流

当前版本暂不实现限流。未来版本将支持：

- 基于 IP 的限流
- 基于用户的限流
- 基于 API Key 的限流

## 参考资源

- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [OpenAPI 规范](https://swagger.io/specification/)
- [RESTful API 设计最佳实践](https://restfulapi.net/)
