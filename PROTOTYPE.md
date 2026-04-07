# DHA 原型机使用指南

## 概述

这是一个最小可用的 DHA 原型机，实现了基础的聊天功能，支持 MCP 工具和 Skills。

## 功能

- ✅ 基础聊天功能
- ✅ Qwen LLM 集成
- ✅ MCP 工具支持（框架已实现，需要配置 MCP Server）
- ✅ Skills 加载（框架已实现，可以添加 Skills）
- ✅ SSE 流式输出
- ❌ 登录功能（暂未实现）
- ❌ 记忆功能（暂未实现）

## 快速开始

### 后端启动

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖（包括 MCP SDK）
pip install -r requirements.txt

# 如果 MCP SDK 安装失败，可以尝试：
# 从 PyPI 安装：pip install mcp
# 或从 GitHub 安装：pip install git+https://github.com/modelcontextprotocol/python-sdk.git

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 QWEN_API_KEY、QWEN_BASE_URL 等

# 启动服务
python -m app.main
# 或
uvicorn app.main:app --reload
```

后端将在 `http://localhost:8000` 启动

### 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端将在 `http://localhost:5173` 启动

## 配置

### MCP Server 配置

编辑 `backend/config/mcp_servers.json`:

```json
[
  {
    "id": "example-server",
    "name": "示例 MCP Server",
    "enabled": true,
    "transport": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp_server_example"]
    }
  }
]
```

**详细配置指南**：查看 [MCP Server 配置指南](./docs/development/mcp-server-setup.md)

### Skills 配置

在每用户目录下创建 Skill（路径与登录邮箱一致）：

```
backend/data/users/<你的邮箱>/skills/
└── my-skill/
    └── SKILL.md
```

SKILL.md 格式：

```markdown
---
name: my-skill
description: 我的技能描述
---

# 我的技能

技能内容...
```

## 使用

1. 启动后端和前端
2. 在浏览器打开 `http://localhost:5173`
3. 在输入框中输入消息并发送
4. 查看 AI 的流式回复

## 项目结构

```
DHA/
├── backend/              # Python 后端
│   ├── app/
│   │   ├── main.py       # FastAPI 入口
│   │   ├── api/          # API 路由
│   │   ├── agent/        # Agent 逻辑
│   │   ├── mcp/          # MCP 集成
│   │   └── skills/       # Skills 管理
│   ├── config/           # 配置文件
│   └── skills/           # Skills 目录
└── frontend/             # Vue 3 前端
    └── src/
        ├── views/        # 页面
        └── composables/  # Composables
```

## 注意事项

1. **Python 版本**: 推荐使用 Python 3.10-3.12。Python 3.13 可能遇到某些包的兼容性问题
2. **MCP SDK**: 从 PyPI 安装：`pip install mcp`，或从 GitHub 安装
3. **Qwen API**: 需要有效的 Qwen API Key
4. **简化实现**: 当前版本简化了 ReAct 循环，直接调用 LLM
5. **工具调用**: MCP 工具框架已实现，需要配置实际的 MCP Server
   - 查看 [MCP Server 配置指南](./docs/development/mcp-server-setup.md) 了解如何配置

## 下一步

- [ ] 完善 ReAct 循环实现
- [ ] 实现工具调用的完整流程
- [ ] 添加错误处理和重试机制
- [ ] 优化流式输出性能
- [ ] 添加更多 Skills 示例
