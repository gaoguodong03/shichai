# 心像 EchoTwin Backend

心像 EchoTwin 后端服务（原 DHA，Digital Human Agent）

## 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate 

# 安装依赖（包括 MCP SDK）
pip install -r requirements.txt

```

### 2. 配置环境变量

```bash
# 创建 .env 文件
cat > .env << 'EOF'
# Qwen API 配置
QWEN_API_KEY=sk-364125e5aa404a04bd3d3d01918ffde2
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 应用配置
DEBUG=true
CORS_ORIGINS=http://localhost:5173

# MCP 配置
MCP_CONFIG_PATH=./config/mcp_servers.json

# Skills 配置
SKILLS_DIR=./skills
EOF

# 或手动创建 .env 文件，复制上面的内容
```

### 3. 运行服务

```bash
python -m app.main
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

服务将在 `http://localhost:8000` 启动

API 文档: `http://localhost:8000/docs`

## 项目结构

```
backend/
├── app/
│   ├── main.py          # FastAPI 应用入口
│   ├── api/             # API 路由
│   ├── agent/           # Agent 核心逻辑
│   ├── mcp/             # MCP 集成
│   └── skills/          # Skills 管理
├── config/              # 配置文件
├── skills/               # Skills 目录
└── requirements.txt     # Python 依赖
```

## 功能

- ✅ Qwen LLM 集成
- ✅ MCP 工具支持
- ✅ Skills 加载
- ✅ ReAct Agent 工作流（使用 LangGraph 实现完整的 ReAct 循环）
- ✅ SSE 流式输出
