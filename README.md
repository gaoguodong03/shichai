# 书童四九（Shutong Sijiu）

私有化 AI Agent 对话与工具平台：多用户数据隔离，支持 ReAct、MCP 与每用户 Skills（含脚本）。

当前架构已统一为：
- 会话主入口：`/api/sessions/*`（单人与多人共用同一套带主持人的会话模型）
- Agent 主入口：`/api/agents/*`（`/api/dha/instances/*` 与 `/api/experts/*` 为兼容别名）

- 前端：见 [frontend/README.md](frontend/README.md)
- 后端：见 [backend/README.md](backend/README.md)
- 架构与部署要点：见 [docs/书童四九.md](docs/书童四九.md)
- 程序如何启动、与专家对话时前后端如何协作（框架说明）：见 [docs/技术架构详解.md](docs/技术架构详解.md)
- 项目工作条目式清单（便于汇报与自述，可自改）：见 [docs/项目工作清单.md](docs/项目工作清单.md)
- 15 分钟技术介绍讲稿（时间轴、状态机页讲法、三问备用答法）：见 [docs/15分钟技术介绍讲稿.md](docs/15分钟技术介绍讲稿.md)

crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/dha:26.04.15.3
  python manage_accounts.py add --username hjl@bupt.edu.cn --password 'telestar'
  python manage_accounts.py delete --username 13800138000 --yes
  python manage_accounts.py delete --username 13800138000 --remove-data --yes

  cd .\backend\
  conda activate sc
  python -m app.main

  cd .\frontend\
  npm run dev



## 1Panel 最简部署（接近一条命令）

- 文件：`docker-compose.1panel.yml`
- 环境变量模板：`backend/.env.1panel.example`

### 三步完成

1. 准备环境变量  
   复制 `backend/.env.1panel.example` 为 `backend/.env`，至少填写 `QWEN_API_KEY`，并修改 `AUTH_SECRET`。
2. 在 1Panel 创建数据卷  
   创建名为 `st49_data` 的 Docker 卷（与 compose 内 `external: true` 对应）。
3. 导入并启动  
   在 1Panel 导入 `docker-compose.1panel.yml`，点击启动。

### 访问与端口

- 主应用：宿主机 `8100` -> 容器 `8000`
- OpenSandbox：宿主机 `8091` -> 容器 `8090`
- 如需调整，可在 1Panel 的环境变量中覆盖：`ST49_HOST_PORT`、`OPENSANDBOX_HOST_PORT`、`ST49_IMAGE`