# DHA 项目依赖

本文档汇总项目前后端依赖，便于查阅与版本管理。

---

## 一、后端依赖（Python）

见 `backend/requirements.txt`，安装命令：`pip install -r backend/requirements.txt`

| 包名 | 版本 | 用途 |
|------|------|------|
| fastapi | 0.128.0 | Web 框架 |
| uvicorn[standard] | 0.40.0 | ASGI 服务器 |
| sse-starlette | 3.2.0 | SSE 流式输出 |
| langchain | 0.1.20 | LangChain 核心 |
| langchain-core | 0.1.53 | LangChain 基础 |
| langgraph | 0.0.51 | Agent 图编排 |
| langchain-openai | 0.1.7 | OpenAI 接口 |
| mcp | 1.25.0 | MCP SDK |
| mcp-server-fetch | ≥1.0.0 | MCP 服务 |
| mem0-mcp-server | ≥0.2.0 | MCP 服务 |
| httpx | 0.28.1 | HTTP 客户端 |
| pydantic | 2.12.5 | 数据校验 |
| pydantic-settings | 2.12.0 | 配置管理 |
| python-dotenv | 1.2.1 | 环境变量 |
| pyyaml | 6.0.3 | YAML 解析 |

---

## 二、前端依赖（Node.js）

见 `frontend/package.json`，安装命令：`cd frontend && npm install`

### 运行时依赖 (dependencies)

| 包名 | 版本 | 用途 |
|------|------|------|
| vue | ^3.3.4 | 前端框架 |
| vue-router | ^4.2.5 | 路由 |
| pinia | ^2.1.7 | 状态管理 |
| axios | ^1.6.2 | HTTP 客户端 |
| vue-pdf-embed | ^2.1.3 | PDF 预览 |
| docx-preview | ^0.3.7 | Word 文档预览 |
| jszip | ^3.10.1 | docx-preview 依赖 |
| xlsx | ^0.18.5 | Excel 预览 |

### 开发依赖 (devDependencies)

| 包名 | 版本 | 用途 |
|------|------|------|
| @vitejs/plugin-vue | ^4.5.0 | Vite Vue 插件 |
| vite | ^5.0.0 | 构建工具 |
| typescript | ^5.2.2 | TypeScript |
| vue-tsc | ^1.8.22 | Vue 类型检查 |
| tailwindcss | ^3.3.6 | CSS 框架 |
| postcss | ^8.4.32 | CSS 处理 |
| autoprefixer | ^10.4.16 | CSS 前缀 |

---

## 三、文件预览相关依赖（前端）

| 格式 | 包名 | 说明 |
|------|------|------|
| PDF | vue-pdf-embed | 基于 PDF.js 的 Vue 组件 |
| DOC/DOCX | docx-preview, jszip | DOCX 转 HTML 渲染 |
| Excel | xlsx | XLSX/XLS/CSV 解析与表格渲染 |
