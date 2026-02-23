# 构建目标平台（默认 linux/amd64；可覆盖：docker build --platform linux/arm64）
ARG TARGETPLATFORM=linux/amd64
ARG BUILDPLATFORM=linux/amd64
# ========== 阶段 1：构建前端 ==========
FROM --platform=$BUILDPLATFORM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci 2>/dev/null || npm install
COPY frontend/ ./
# 仅执行 vite build，避免 vue-tsc 与 TypeScript 版本不兼容导致构建失败；类型检查可在本地或 CI 做
RUN npx vite build

# ========== 阶段 2：运行后端并托管前端静态 ==========
FROM --platform=$TARGETPLATFORM python:3.12-slim
WORKDIR /app

# 系统依赖（部分 MCP 或工具需要）
# - curl: 基础网络工具
# - nodejs/npm: 运行基于 npx 的本地 MCP（如 amap-maps、zhipu-web-search）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# 后端依赖与代码（保持 backend 目录结构，便于与本地一致）
COPY backend/ ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# 前端构建产物
COPY --from=frontend-builder /app/frontend/dist ./frontend_dist

# 环境变量：静态目录供 main 挂载；工作目录与 Python 路径
# 说明：
# - skills、config、data 都已经随 backend 目录一起打包进镜像
# - 这里直接指向 /app/backend 下的真实路径，这样即使没有挂载卷、也没有额外环境变量，
#   在 K8s/free4inno 这类只能改少量配置的平台中也能开箱即用
ENV STATIC_DIR=/app/frontend_dist
ENV PYTHONPATH=/app/backend
ENV SKILLS_DIR=/app/backend/skills
ENV MCP_CONFIG_PATH=/app/backend/config/mcp_servers.json
ENV APP_SETTINGS_PATH=/app/backend/config/app_settings.json
ENV SESSIONS_DIR=/app/backend/data/sessions
ENV AGENT_OUTPUTS_DIR=/app/backend/data/agent-outputs

# 默认端口
EXPOSE 8000

# 数据与配置目录（运行时挂载 volume）
RUN mkdir -p /app/data/sessions /app/data/agent-outputs /app/data/skills /app/config

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
