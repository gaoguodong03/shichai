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

crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/dha:26.04.02
  python manage_accounts.py add --username mzg@bupt.edu.cn --password 'telestar'
  python manage_accounts.py delete --username 13800138000 --yes
  python manage_accounts.py delete --username 13800138000 --remove-data --yes