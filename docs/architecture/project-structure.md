# 项目结构文档

## 概述

本文档详细说明了 DHA 项目的目录结构和文件组织方式，帮助开发者快速理解项目架构。

## 整体结构

```
DHA/
├── backend/                 # Python 后端
│   ├── app/                 # 应用主目录
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI 应用入口
│   │   ├── api/             # API 路由
│   │   ├── agent/           # Agent 核心逻辑
│   │   ├── mcp/             # MCP 集成
│   │   ├── skills/          # Skills 管理
│   │   ├── models/          # 数据模型
│   │   ├── storage/         # 数据存储
│   │   └── utils/           # 工具函数
│   ├── config/              # 配置文件
│   ├── logs/                # 日志文件
│   ├── requirements.txt     # Python 依赖
│   ├── .env.example         # 环境变量示例
│   └── pyproject.toml       # 项目配置
├── frontend/                # Vue 3 前端
│   ├── src/                 # 源代码
│   │   ├── components/      # Vue 组件
│   │   ├── views/           # 页面视图
│   │   ├── stores/          # Pinia 状态管理
│   │   ├── api/             # API 客户端
│   │   ├── composables/     # Vue Composables
│   │   ├── utils/           # 工具函数
│   │   ├── router/          # 路由配置
│   │   ├── App.vue          # 根组件
│   │   └── main.ts          # 入口文件
│   ├── public/              # 静态资源
│   ├── dist/                # 构建产物
│   ├── package.json         # Node.js 依赖
│   ├── vite.config.ts       # Vite 配置
│   ├── tsconfig.json        # TypeScript 配置
│   └── .env.example         # 环境变量示例
├── docs/                    # 文档
│   ├── architecture/        # 架构文档
│   ├── design/              # 设计文档
│   ├── development/         # 开发文档
│   └── features/            # 功能文档
├── config/                  # 项目配置
│   ├── mcp_servers.json     # MCP Server 配置
│   └── models.json          # 模型配置
├── skills/                  # Skills 目录
│   └── example-skill/       # 示例 Skill
│       ├── SKILL.md
│       ├── scripts/
│       ├── references/
│       └── assets/
└── README.md                # 项目说明
```

## 后端结构详解

### `backend/app/`

应用主目录，包含所有业务逻辑。

#### `main.py`

FastAPI 应用入口，初始化应用和路由：

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import chat, sessions, settings

app = FastAPI(title="DHA API", version="1.0.0")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(settings.router)
```

#### `api/`

API 路由目录，按功能模块组织：

```
api/
├── __init__.py
├── chat.py          # 对话 API
├── sessions.py      # Session 管理 API
└── settings.py      # 设置 API（模型、MCP、Skills）
```

#### `agent/`

Agent 核心逻辑：

```
agent/
├── __init__.py
├── graph.py              # LangGraph 工作流定义
├── types.py              # 类型定义
├── event_processor.py    # 事件处理
├── stream_handler.py     # 流式处理
└── llm_service.py        # LLM 服务封装
```

#### `mcp/`

MCP 集成：

```
mcp/
├── __init__.py
├── client.py         # MCP 客户端
├── manager.py        # MCP Server 管理
└── adapter.py       # LangChain 适配器
```

#### `skills/`

Skills 管理：

```
skills/
├── __init__.py
├── loader.py         # Skills 加载器
├── parser.py         # SKILL.md 解析器
└── registry.py      # Skills 注册表
```

#### `models/`

数据模型（Pydantic）：

```
models/
├── __init__.py
├── session.py        # Session 模型
├── message.py        # Message 模型
├── model_config.py   # 模型配置模型
└── mcp_config.py     # MCP 配置模型
```

#### `storage/`

数据存储层：

```
storage/
├── __init__.py
├── database.py       # 数据库连接和操作
├── session_manager.py # Session 管理器
├── model_manager.py  # 模型管理器
└── file_storage.py   # 文件存储
```

#### `utils/`

工具函数：

```
utils/
├── __init__.py
├── token_counter.py  # Token 计数
├── session_title.py  # Session 标题生成
└── helpers.py        # 辅助函数
```

## 前端结构详解

### `frontend/src/`

源代码目录。

#### `components/`

可复用的 Vue 组件：

```
components/
├── chat/
│   ├── ChatContainer.vue      # 对话容器
│   ├── MessageBubble.vue       # 消息气泡
│   └── ReActStepDisplay.vue   # ReAct 步骤显示
├── layout/
│   ├── Sidebar.vue            # 侧边栏
│   └── Header.vue             # 头部
└── common/
    ├── Button.vue             # 按钮组件
    └── Modal.vue              # 模态框
```

#### `views/`

页面级组件：

```
views/
├── ChatView.vue               # 对话页面
├── SettingsView.vue           # 设置页面
├── SessionsView.vue           # Session 列表页面
└── ModelConfigView.vue        # 模型配置页面
```

#### `stores/`

Pinia 状态管理：

```
stores/
├── index.ts                   # Store 入口
├── session.ts                 # Session Store
├── chat.ts                    # Chat Store
└── settings.ts                # Settings Store
```

#### `api/`

API 客户端：

```
api/
├── index.ts                   # API 客户端入口
├── chat.ts                    # 对话 API
├── sessions.ts                # Session API
└── settings.ts                # 设置 API
```

#### `composables/`

Vue Composables：

```
composables/
├── useEventSource.ts          # SSE 流式处理
├── useChat.ts                 # 对话相关逻辑
└── useSession.ts              # Session 相关逻辑
```

#### `router/`

路由配置：

```
router/
└── index.ts                   # 路由定义
```

## 配置文件

### 后端配置

- `requirements.txt`: Python 依赖列表
- `.env`: 环境变量（不提交到 Git）
- `.env.example`: 环境变量示例
- `pyproject.toml`: 项目元数据和配置

### 前端配置

- `package.json`: Node.js 依赖和脚本
- `vite.config.ts`: Vite 构建配置
- `tsconfig.json`: TypeScript 配置
- `.env`: 环境变量
- `.env.example`: 环境变量示例

## 数据存储

### 数据库

- **开发环境**: SQLite (`backend/dha.db`)
- **生产环境**: PostgreSQL（推荐）

### 配置文件

- `config/mcp_servers.json`: MCP Server 配置
- `config/models.json`: 模型配置

### Skills

- `skills/`: Skills 目录，每个 Skill 是一个子目录

## 命名规范

### Python 后端

- **文件**: 使用小写字母和下划线（`snake_case`）
- **类**: 使用大驼峰（`PascalCase`）
- **函数/变量**: 使用小写字母和下划线（`snake_case`）
- **常量**: 使用大写字母和下划线（`UPPER_SNAKE_CASE`）

## 代码组织原则

1. **单一职责**: 每个模块/文件只负责一个功能
2. **分层清晰**: 明确区分 API、业务逻辑、数据存储层
3. **易于扩展**: 使用接口和抽象类，便于扩展
4. **类型安全**: 使用类型提示和 TypeScript
5. **文档完善**: 关键函数和类都有文档字符串

## 参考资源

- [FastAPI 项目结构](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- [Vue 3 项目结构](https://vuejs.org/guide/scaling-up/structure.html)
- [Python 项目结构最佳实践](https://docs.python-guide.org/writing/structure/)
