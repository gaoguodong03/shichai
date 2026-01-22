# 技术栈

## 后端技术栈（Python）

### Web 框架

**推荐：FastAPI**
- 异步支持，适合流式响应
- 自动 API 文档生成
- 类型安全和验证（Pydantic）

**备选：Flask**
- 轻量级，简单易用
- 需要额外插件支持 SSE

### Agent 核心库

- **langgraph**: Python 版本的 LangGraph，用于实现 ReAct 循环
- **langchain**: Python 版本的 LangChain 核心库
- **langchain-core**: LangChain 核心抽象和接口
- **mcp**: MCP Python SDK（来自 `/Users/ggd/mycode/DHA/MCP_Learn/python-sdk`）
  - 直接使用 Python MCP SDK 连接 MCP Server
  - 无需 JavaScript 适配器，原生 Python 集成

### LLM 客户端

- **langchain-openai**: OpenAI 模型支持
- **langchain-anthropic**: Anthropic Claude 模型支持
- **langchain-community**: 社区模型支持（本地模型、其他 API 等）

### 数据存储

- **SQLite**: 轻量级数据库（开发/小规模部署）
- **PostgreSQL**: 生产环境数据库（可选）
- **文件系统**: JSON 配置文件存储

### 其他依赖

- **pydantic**: 数据验证和设置管理
- **httpx**: 异步 HTTP 客户端（用于 MCP HTTP 传输）
- **sse-starlette**: SSE 支持（FastAPI 使用）

## 前端技术栈

### 技术选型：Vue 3 + Vite

- **Vue 3**: UI 框架（Composition API）
  - 使用 `<script setup>` 语法
  - 更好的逻辑复用和类型推导
- **Vite**: 构建工具和开发服务器
  - 快速的开发服务器和热更新
  - 优化的生产构建
- **TypeScript**: 类型安全
  - 完整的类型检查和智能提示
- **Tailwind CSS + DaisyUI**: UI 样式和组件
  - DaisyUI：基于 Tailwind CSS，轻量级
  - Element Plus：备选的企业级组件库
- **Pinia**: 状态管理
  - Vue 官方推荐的状态管理库
  - 类型安全，支持 TypeScript
- **Vue Router**: 路由管理
  - 单页应用路由管理
- **Axios**: HTTP 客户端
  - 用于 REST API 调用
- **EventSource API**: SSE 流式处理
  - 接收 Agent 的实时流式输出
- **Iconify / Vue Icons**: 图标库
  - 丰富的图标选择

## 核心能力

- **无需手动重写 ReAct 逻辑**：直接使用 Python LangGraph
- **原生 MCP 集成**：使用 Python MCP SDK，无需桥接适配器
- **流式响应**：FastAPI 原生支持 SSE，实现实时流式输出
- **类型安全**：Python 类型提示 + Pydantic 验证
- **前后端分离**：前端和后端独立开发和部署

## 项目结构建议

```
DHA/
├── backend/                 # Python 后端
│   ├── app/
│   │   ├── api/            # API 路由
│   │   ├── agent/          # Agent 核心逻辑
│   │   ├── mcp/            # MCP 集成
│   │   ├── skills/         # Skills 管理
│   │   └── models/         # 数据模型
│   ├── requirements.txt
│   └── main.py
├── frontend/               # Vue 3 前端
│   ├── src/
│   │   ├── components/     # Vue 组件
│   │   ├── views/          # 页面视图
│   │   ├── stores/         # Pinia 状态管理
│   │   ├── api/            # API 客户端
│   │   ├── composables/    # Vue Composables
│   │   ├── utils/          # 工具函数
│   │   └── router/         # 路由配置
│   ├── package.json
│   └── vite.config.ts
└── docs/                   # 文档
```
