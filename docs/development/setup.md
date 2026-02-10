# 开发设置

## 概述

本文档说明 DHA 项目的开发环境配置、安装与启动步骤。

## 环境要求

| 依赖 | 版本 |
|------|------|
| Python | 3.10+ |
| Node.js | 18+ |
| pip | 最新版 |

## 一、后端设置

### 1. 进入目录并创建虚拟环境

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

在 `backend` 目录下创建 `.env` 文件：

```bash
# 至少需配置 LLM API Key（二选一或都配）
QWEN_API_KEY=sk-xxx
# JENIYA_API_KEY=xxx   # 若使用 jeniya 作为 default_llm

# 应用配置
DEBUG=true
CORS_ORIGINS=http://localhost:5173

# MCP 配置
MCP_CONFIG_PATH=./config/mcp_servers.json

# Skills 配置
SKILLS_DIR=./skills
```

其他可选配置（MCP、Skills 等）见 [MCP Server 配置](./mcp-server-setup.md)。

### 4. 启动后端

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端将在 `http://localhost:8000` 启动，API 文档：`http://localhost:8000/docs`。

---

## 二、前端设置

### 1. 进入目录并安装依赖

```bash
cd frontend
npm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

前端将在 `http://localhost:5173` 启动。Vite 已配置代理：`/api` 转发到 `http://localhost:8000`。

---

## 三、同时运行前后端

可使用两个终端分别运行：

```bash
# 终端 1
cd backend && source venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 终端 2
cd frontend && npm run dev
```

浏览器访问 `http://localhost:5173` 即可使用完整应用。

---

## 四、相关文档

- [项目依赖](../requirements.md) - 前后端依赖清单
- [MCP Server 配置](./mcp-server-setup.md) - 创建与配置 MCP Server
- [MCP 操作指南](./mcp-operation-guide.md) - 远程接入、本地编写
- [部署](./deployment.md) - 生产环境部署
