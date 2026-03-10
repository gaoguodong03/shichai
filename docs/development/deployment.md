# 部署文档

## 概述

本文档描述了 DHA 项目的部署方案，包括开发环境、生产环境的部署步骤和配置说明。

## 部署架构

### 架构图

```
┌─────────────┐
│  前端 (Vue)  │  →  Nginx (静态文件)
└─────────────┘
       │
       ↓ HTTP/SSE
┌─────────────┐
│ 后端 (FastAPI) │  →  Uvicorn/Gunicorn
└─────────────┘
       │
       ↓
┌─────────────┐
│  数据库      │  →  SQLite/PostgreSQL
└─────────────┘
```

## Docker 部署（推荐）

项目根目录提供 Dockerfile 与 docker-compose，**前后端一体镜像**：前端构建为静态文件由后端托管，单容器即可运行。

### 构建与运行

```bash
# 在项目根目录 DHA/
docker compose up -d --build
# 访问 http://localhost:8000
```

默认已按 **linux/amd64** 构建（见 `docker-compose.yml` 中 `platform: linux/amd64`）。若需其他架构可改回本机平台或去掉 `platform` 配置。

### 配置

- **环境变量（QWEN_API_KEY 等）**：在 `backend/.env` 中配置，大多数敏感信息都放这里。`docker-compose.yml` 会通过 `env_file: backend/.env` 注入到容器：
  - 该文件 **只存在于宿主机**，不会被打进镜像，也不会出现在容器文件系统中（因此 Env 设置页在 Docker 环境下看到“未找到 .env”是正常的）。
  - 若未配置 `QWEN_API_KEY` 等，调用聊天接口时日志会出现 `ValueError: QWEN_API_KEY is required` 并返回 500。
- **数据 & 配置挂载（默认即复用本地）**：`docker-compose.yml` 默认绑定宿主机目录：
  - `./backend/data:/app/data`（会话历史、agent 产出等）
  - `./backend/skills:/app/data/skills`（Skills）
  - `./backend/config:/app/config`（MCP 配置等）
  这样容器内看到的 Skills、MCP Servers、历史会话与本地开发一致。若希望完全隔离的数据环境，可改为使用匿名卷 `dha_data`、`dha_config`。

### 仅构建镜像

```bash
docker build -t dha:latest .
docker run -p 8000:8000 -v dha_data:/app/data -v dha_config:/app/config --env-file backend/.env dha:latest
```

### Docker 常见问题（打包踩坑记录）

- **现象：Skill、MCP、历史会话全都不见了**
  - **原因**：容器内的 `/app/data`、`/app/config` 使用了空的匿名卷，未挂载宿主机的 `backend/data`、`backend/skills`、`backend/config`。
  - **解决**：在 `docker-compose.yml` 中使用当前推荐配置：
    - `./backend/data:/app/data`
    - `./backend/skills:/app/data/skills`
    - `./backend/config:/app/config`
- **现象：聊天接口 500，日志中有 `ValueError: QWEN_API_KEY is required`**
  - **原因**：容器内没有 `QWEN_API_KEY` 等 LLM 相关环境变量，通常是忘记配置或启用 `env_file: backend/.env`。
  - **解决**：
    - 在宿主机创建并配置 `backend/.env`（可从 `backend/.env.example` 复制）。
    - 确认 `docker-compose.yml` 中启用了 `env_file: backend/.env`，然后重新 `docker compose up -d --build`。
- **现象：前端“环境变量 (.env)” 页面显示“未找到 .env 文件”或看起来是空的**
  - **原因**：Docker 部署时 `.env` 文件只存在于宿主机，Compose 读取后以环境变量形式注入容器，容器内本身没有 `/app/backend/.env` 文件可供读取展示。
  - **说明**：这是预期行为，不影响实际环境变量生效。需要查看具体值时，应在宿主机直接打开 `backend/.env`，或通过 `docker compose run --rm dha env` 等方式查看。

### 1Panel + 阿里云镜像部署（启用 Playwright / 文件系统 / 高德 MCP）

当使用 **1Panel** 从 **阿里云镜像** 拉取并运行 DHA 时，若希望「Playwright」「本地文件系统」「高德地图」等 MCP 显示为已连接，需满足以下条件（与前端打包无关，均为运行环境与配置）。

#### 1. 镜像已包含 Node.js

当前 Dockerfile 已从构建阶段复制 `node` / `npm` / `npx` 到运行镜像，无需在 1Panel 里再装 Node。只要使用本项目构建出的镜像（或按同一 Dockerfile 在阿里云构建的镜像），容器内即可用 `npx` 启动上述 MCP。

#### 2. 在 1Panel 中为容器配置环境变量

在 1Panel 的「容器」→ 选择 DHA 容器 →「编辑」→「环境变量」中，至少配置：

| 变量名 | 说明 |
|--------|------|
| `QWEN_API_KEY` | 通义千问等 LLM 调用（必填，否则聊天 500） |
| `AMAP_MAPS_API_KEY` | 高德地图 MCP（需在高德开放平台申请） |
| `ZHIPU_WEB_SEARCH_API_KEY` | 智谱 Web 搜索 MCP（若启用） |

其他如 `LINKUP_API_KEY`、`EXA_API_KEY`、`VOLCES_IMAGE_API_KEY` 等按需添加。**不配置的 MCP 会连接失败，前端会显示「未连接」。**

若本地有 `backend/.env`，可把其中需要的键值在 1Panel 里逐条添加；1Panel 通常不支持直接挂载 `.env` 文件，只能以环境变量形式填写。

#### 3. 卷挂载与 MCP 配置路径

- **不挂载 `/app/config`**：容器使用镜像内的 `/app/backend/config/mcp_servers.json`，无需任何操作即可使用内置 MCP 配置。
- **若在 1Panel 中挂载了「配置目录」到 `/app/config`**：请勿再设置 `MCP_CONFIG_PATH=/app/config/mcp_servers.json`，否则会读挂载卷里的文件；若该卷为空或没有 `mcp_servers.json`，MCP 会加载失败。要么不挂载 config，要么在挂载的目录中放入与仓库一致的 `mcp_servers.json`。

数据目录建议挂载，便于持久化会话与 agent 产出：

- 将宿主机某目录挂载到 `/app/data`（或保持镜像默认的 `/app/backend/data`，不挂载亦可）。
- 若设置了 `AGENT_OUTPUTS_DIR=/app/data/agent-outputs`，需保证该路径在容器内存在（例如挂载的卷中包含 `agent-outputs` 目录）。

#### 4. 首次连接 MCP 需要容器能访问外网

高德、文件系统、Playwright 等 MCP 通过 `npx -y <包名>` 启动，**首次运行会在容器内拉取 npm 包**。若 1Panel 所在环境限制出网或无法访问 npm  registry，会导致连接超时、前端显示「未连接」。解决办法：

- **允许容器访问外网**（推荐）：在 1Panel/防火墙/安全组中放行出站 HTTPS，确保容器内可访问 `registry.npmmirror.com` 或 `registry.npmjs.org`。
- **使用预缓存镜像**：项目 Dockerfile 中已包含可选的「预拉取 MCP 所需 npm 包」步骤（`npx -y @modelcontextprotocol/server-filesystem` 等）。用该 Dockerfile 重新构建并推送到阿里云后，容器内首次连接 MCP 时无需再访问外网。

#### 5. Playwright 在服务器上的方案

Playwright MCP 会启动浏览器（Chromium）。当前 **Dockerfile 已包含 Chromium 及系统依赖的安装**（仅 Chromium，以控制镜像体积），开箱即可在无头环境下使用 Playwright MCP。

- **若不需要线上浏览器能力**：在 `mcp_servers.json` 中把 `playwright-mcp` 的 `enabled` 设为 `false`，可避免启动浏览器、减小内存占用。
- **若需在 1Panel/Docker 中跑 Playwright**：使用本仓库构建的镜像即可；建议运行容器时加上 **`--ipc=host`**（或在 1Panel 的「容器」→「高级」中勾选 IPC 与主机一致），否则 Chromium 可能因内存不足崩溃。1Panel 若支持「额外运行参数」，可填 `--ipc=host`。

#### 6. 小结检查清单（1Panel）

- [ ] 使用本仓库构建的镜像（或阿里云上按同 Dockerfile 构建的镜像），保证含 Node/npx。
- [ ] 在 1Panel 环境变量中配置 `QWEN_API_KEY`、`AMAP_MAPS_API_KEY` 等所需 Key。
- [ ] 不覆盖 `MCP_CONFIG_PATH`，或挂载的 config 目录中提供完整 `mcp_servers.json`。
- [ ] 容器能访问外网（或使用预缓存 npx 的镜像），以便首次连接 MCP 时拉包。
- [ ] 若不需要线上浏览器能力，将 Playwright MCP 关闭，避免无头环境下的兼容问题。

---

## 环境要求

### 服务器要求

- **操作系统**: Linux (Ubuntu 20.04+ 推荐) 或 macOS
- **Python**: 3.10 或更高版本
- **Node.js**: 18.0 或更高版本（用于构建前端）
- **内存**: 至少 2GB RAM（推荐 4GB+）
- **存储**: 至少 10GB 可用空间

### 依赖服务

- **数据库**: SQLite（默认）或 PostgreSQL（生产环境推荐）
- **反向代理**: Nginx（推荐）或 Caddy

## 部署步骤

### 1. 准备服务器

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装 Python 和 pip
sudo apt install python3.10 python3-pip python3-venv -y

# 安装 Node.js (使用 nvm)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
source ~/.bashrc
nvm install 18
nvm use 18

# 安装 Nginx
sudo apt install nginx -y
```

### 2. 部署后端

#### 克隆项目

```bash
cd /opt
sudo git clone <repository-url> dha
sudo chown -R $USER:$USER dha
cd dha/backend
```

#### 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate
```

#### 安装依赖

```bash
pip install -r requirements.txt
```

#### 配置环境变量

```bash
cp .env.example .env
nano .env
```

`.env` 配置示例：

```env
# 应用配置
DEBUG=false
SECRET_KEY=your-secret-key-here
ALLOWED_ORIGINS=http://localhost:5173,https://yourdomain.com

# 数据库配置
DATABASE_URL=postgresql://user:password@localhost/dha

# LLM 配置
OPENAI_API_KEY=your-openai-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key

# MCP 配置
MCP_CONFIG_PATH=/opt/dha/config/mcp_servers.json

# Skills 配置
SKILLS_DIR=/opt/dha/skills
```

#### 初始化数据库

```bash
python -m app.storage.database init
```

#### 使用 Gunicorn 运行（生产环境）

```bash
pip install gunicorn

# 创建 Gunicorn 配置文件
cat > gunicorn_config.py << EOF
bind = "127.0.0.1:8000"
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
keepalive = 5
EOF

# 启动服务
gunicorn app.main:app -c gunicorn_config.py
```

#### 使用 systemd 管理服务

```bash
sudo nano /etc/systemd/system/dha-backend.service
```

服务文件内容：

```ini
[Unit]
Description=DHA Backend Service
After=network.target

[Service]
Type=notify
User=www-data
WorkingDirectory=/opt/dha/backend
Environment="PATH=/opt/dha/backend/venv/bin"
ExecStart=/opt/dha/backend/venv/bin/gunicorn app.main:app -c gunicorn_config.py
Restart=always

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable dha-backend
sudo systemctl start dha-backend
sudo systemctl status dha-backend
```

### 3. 部署前端

#### 构建前端

```bash
cd /opt/dha/frontend
npm install
npm run build
```

构建产物在 `dist/` 目录。

#### 配置 Nginx

```bash
sudo nano /etc/nginx/sites-available/dha
```

Nginx 配置：

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    # 前端静态文件
    root /opt/dha/frontend/dist;
    index index.html;

    # 前端路由（SPA）
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 代理
    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE 流式响应
    location /api/chat/stream {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

启用站点：

```bash
sudo ln -s /etc/nginx/sites-available/dha /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 4. 配置 SSL（可选但推荐）

使用 Let's Encrypt：

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d yourdomain.com
```

### 5. 配置防火墙

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## Docker 部署（多容器示例，可选）

> **说明**：本节是基于旧版结构的多容器示例，已根据当前项目目录和环境变量约定做了更新。实际生产环境 **推荐优先使用前文的“一体化镜像 + 单容器 Compose” 方案**，这里主要作为需要前后端、数据库独立容器时的参考。

### Docker Compose 配置

创建 `docker-compose.yml`（关键点：通过 `env_file` 挂载 `backend/.env`，统一管理包括高德/智谱在内的所有 Key）：

```yaml
version: '3.8'

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    # 从 backend/.env 注入所有 LLM / MCP 相关环境变量
    # 例如 QWEN_API_KEY、AMAP_MAPS_API_KEY、ZHIPU_WEB_SEARCH_API_KEY 等
    env_file:
      - ./backend/.env
    environment:
      # 如需在 Compose 中覆盖数据库连接，可在这里显式指定
      - DATABASE_URL=postgresql://postgres:password@db:5432/dha
    volumes:
      # 挂载数据与配置目录，保持与本地开发一致
      - ./backend/data:/app/data
      - ./backend/skills:/app/data/skills
      - ./backend/config:/app/config
    depends_on:
      - db

  frontend:
    build: ./frontend
    ports:
      - "80:80"
    volumes:
      - ./frontend/dist:/usr/share/nginx/html
    depends_on:
      - backend

  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=dha
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### 后端 Dockerfile

```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["gunicorn", "app.main:app", "-c", "gunicorn_config.py"]
```

### 前端 Dockerfile

```dockerfile
FROM node:18-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

### 使用 Docker Compose 部署

```bash
docker-compose up -d
```

## 监控和日志

### 日志配置

后端日志：

```python
# app/main.py
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
```

查看日志：

```bash
# systemd 服务日志
sudo journalctl -u dha-backend -f

# 应用日志
tail -f /opt/dha/backend/logs/app.log
```

### 健康检查

创建健康检查端点：

```python
# app/api/health.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "dha-backend"}
```

## 备份和恢复

### 数据库备份

```bash
# PostgreSQL
pg_dump -U postgres dha > backup_$(date +%Y%m%d).sql

# SQLite
cp /opt/dha/backend/dha.db backup_$(date +%Y%m%d).db
```

### 恢复

```bash
# PostgreSQL
psql -U postgres dha < backup_20240101.sql

# SQLite
cp backup_20240101.db /opt/dha/backend/dha.db
```

## 性能优化

### 后端优化

1. **增加 Worker 数量**: 根据 CPU 核心数调整 Gunicorn workers
2. **使用连接池**: 数据库连接池
3. **启用缓存**: 使用 Redis 缓存（可选）

### 前端优化

1. **启用 Gzip 压缩**: Nginx 配置
2. **CDN 加速**: 静态资源使用 CDN
3. **代码分割**: Vue Router 懒加载

## 故障排查

### 常见问题

1. **后端无法启动**: 检查端口占用、环境变量、依赖安装
2. **前端无法访问**: 检查 Nginx 配置、文件权限
3. **SSE 连接断开**: 检查 Nginx 超时配置、防火墙设置

### 调试命令

```bash
# 检查服务状态
sudo systemctl status dha-backend

# 查看错误日志
sudo journalctl -u dha-backend -n 100

# 测试 API
curl http://localhost:8000/api/health

# 检查端口
sudo netstat -tlnp | grep 8000
```

## 安全建议

1. **使用 HTTPS**: 生产环境必须使用 SSL/TLS
2. **API Key 安全**: 使用环境变量存储敏感信息
3. **防火墙配置**: 只开放必要端口
4. **定期更新**: 保持系统和依赖包更新
5. **访问控制**: 实现用户认证和授权（未来版本）

## 参考资源

- [FastAPI 部署文档](https://fastapi.tiangolo.com/deployment/)
- [Nginx 配置指南](https://nginx.org/en/docs/)
- [Gunicorn 文档](https://docs.gunicorn.org/)
