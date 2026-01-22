# 开发设置

## 环境要求

### 后端环境

- **Python**: 3.10 或更高版本
- **pip** 或 **uv**: Python 包管理器
- **虚拟环境**: 推荐使用 `venv` 或 `uv`

### 前端环境

- **Node.js**: 18.0 或更高版本
- **npm** 或 **pnpm**: Node.js 包管理器

## 项目结构

```
DHA/
├── backend/                 # Python 后端
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI 应用入口
│   │   ├── api/             # API 路由
│   │   │   ├── __init__.py
│   │   │   ├── chat.py      # 对话 API
│   │   │   └── settings.py  # 设置 API
│   │   ├── agent/           # Agent 核心逻辑
│   │   │   ├── __init__.py
│   │   │   ├── graph.py     # LangGraph 工作流
│   │   │   ├── types.py     # 类型定义
│   │   │   ├── event_processor.py
│   │   │   └── stream_handler.py
│   │   ├── mcp/             # MCP 集成
│   │   │   ├── __init__.py
│   │   │   ├── client.py    # MCP 客户端
│   │   │   ├── manager.py   # MCP Server 管理
│   │   │   └── adapter.py   # LangChain 适配器
│   │   ├── skills/          # Skills 管理
│   │   │   ├── __init__.py
│   │   │   ├── loader.py    # Skills 加载器
│   │   │   ├── parser.py    # SKILL.md 解析器
│   │   │   └── registry.py  # Skills 注册表
│   │   ├── models/          # 数据模型
│   │   │   ├── __init__.py
│   │   │   ├── session.py
│   │   │   └── config.py
│   │   └── storage/         # 数据存储
│   │       ├── __init__.py
│   │       ├── database.py
│   │       └── file_storage.py
│   ├── requirements.txt     # Python 依赖
│   ├── .env.example         # 环境变量示例
│   └── pyproject.toml        # 项目配置（可选）
├── frontend/                # Vue 3 前端
│   ├── src/
│   │   ├── components/      # Vue 组件
│   │   ├── views/           # 页面视图
│   │   ├── stores/          # Pinia 状态管理
│   │   ├── api/             # API 客户端
│   │   ├── composables/    # Vue Composables
│   │   ├── utils/           # 工具函数
│   │   └── router/          # 路由配置
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
└── docs/                    # 文档
```

## 安装步骤

### 1. 克隆项目

```bash
git clone <repository-url>
cd DHA
```

### 2. 后端设置

#### 创建虚拟环境

```bash
cd backend

# 使用 venv
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 或使用 uv
uv venv
source .venv/bin/activate  # Linux/Mac
```

#### 安装依赖

```bash
# 使用 pip
pip install -r requirements.txt

# 或使用 uv
uv pip install -r requirements.txt
```

#### 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，配置必要的环境变量
```

`.env` 文件示例：

```env
# 应用配置
DEBUG=true
SECRET_KEY=your-secret-key-here

# 数据库配置
DATABASE_URL=sqlite:///./dha.db
# 或 PostgreSQL
# DATABASE_URL=postgresql://user:password@localhost/dha

# LLM 配置
OPENAI_API_KEY=your-openai-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key

# MCP 配置
MCP_CONFIG_PATH=./config/mcp_servers.json

# Skills 配置
SKILLS_DIR=./skills
```

#### 初始化数据库

```bash
python -m app.storage.database init
```

### 3. 前端设置

```bash
cd frontend

# 安装依赖
npm install
# 或
pnpm install
```

#### 配置环境变量

创建 `frontend/.env` 文件：

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

### 4. 启动开发服务器

#### 启动后端

```bash
cd backend
source venv/bin/activate  # 如果使用虚拟环境
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端将在 `http://localhost:8000` 启动，API 文档可在 `http://localhost:8000/docs` 访问。

#### 启动前端

```bash
cd frontend
npm run dev
# 或
pnpm dev
```

前端将在 `http://localhost:5173` 启动（Vite 默认端口）。

## 开发指南

### 后端开发

#### 代码结构

- **API 路由**: `app/api/` - 定义 RESTful API 端点
- **Agent 逻辑**: `app/agent/` - ReAct 工作流和流式处理
- **MCP 集成**: `app/mcp/` - MCP Server 连接和管理
- **Skills 管理**: `app/skills/` - Skills 加载和解析
- **数据模型**: `app/models/` - Pydantic 模型定义
- **存储层**: `app/storage/` - 数据库和文件存储

#### 添加新的 API 端点

1. 在 `app/api/` 中创建新的路由文件
2. 使用 FastAPI 的 `APIRouter` 定义路由
3. 在 `app/main.py` 中注册路由

示例：

```python
# app/api/example.py
from fastapi import APIRouter

router = APIRouter(prefix="/api/example", tags=["example"])

@router.get("/")
async def example():
    return {"message": "Hello, World!"}
```

```python
# app/main.py
from app.api import example

app.include_router(example.router)
```

#### 添加新的工具

1. 在 `app/mcp/adapter.py` 中创建 LangChain 工具包装器
2. 在 `app/tools/registry.py` 中注册工具
3. 工具会自动在 Agent 中可用

### 前端开发

#### 代码结构

- **组件**: `src/components/` - 可复用的 Vue 组件
- **页面**: `src/views/` - 页面级组件
- **状态管理**: `src/stores/` - Pinia stores
- **API 客户端**: `src/api/` - API 调用封装
- **Composables**: `src/composables/` - 可复用的组合式函数
- **工具函数**: `src/utils/` - 工具函数

#### 添加新页面

1. 在 `src/views/` 中创建新的 Vue 组件
2. 在 `src/router/index.ts` 中添加路由配置

示例：

```vue
<!-- src/views/Example.vue -->
<template>
  <div class="example-page">
    <h1>Example Page</h1>
  </div>
</template>

<script setup lang="ts">
// 页面逻辑
</script>
```

```typescript
// src/router/index.ts
import Example from '@/views/Example.vue'

const routes = [
  {
    path: '/example',
    name: 'Example',
    component: Example
  }
]
```

#### 使用 Pinia Store

```typescript
// src/stores/example.ts
import { defineStore } from 'pinia'

export const useExampleStore = defineStore('example', {
  state: () => ({
    count: 0
  }),
  actions: {
    increment() {
      this.count++
    }
  }
})
```

```vue
<!-- 在组件中使用 -->
<script setup lang="ts">
import { useExampleStore } from '@/stores/example'

const store = useExampleStore()
</script>
```

## 调试

### 后端调试

- 使用 `--reload` 参数启用自动重载
- 查看 FastAPI 自动生成的 API 文档：`http://localhost:8000/docs`
- 使用 Python 调试器（pdb）或 IDE 调试工具

### 前端调试

- Vite 提供热模块替换（HMR）
- 使用 Vue DevTools 浏览器扩展
- 查看浏览器控制台的错误信息

## 测试

### 后端测试

```bash
cd backend
pytest
```

### 前端测试

```bash
cd frontend
npm run test
```

## 常见问题

### 后端问题

**Q: MCP Server 连接失败**

A: 检查 MCP Server 配置，确保命令和参数正确。查看日志获取详细错误信息。

**Q: 数据库连接错误**

A: 检查 `DATABASE_URL` 环境变量，确保数据库服务正在运行。

### 前端问题

**Q: API 请求失败（CORS 错误）**

A: 确保后端已配置 CORS，允许前端域名访问。检查 `VITE_API_BASE_URL` 配置。

**Q: SSE 连接断开**

A: 检查网络连接，确保后端 SSE 端点正常工作。查看浏览器控制台的错误信息。

## 下一步

- 查看 [开发计划](./plan.md) 了解开发任务
- 查看 [代码规范](./code-styleguide.md) 了解编码标准
- 查看 [测试文档](./testing.md) 了解测试方法
