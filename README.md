# 书童四九（Shutong Sijiu）

私有化 AI Agent 对话与工具平台：多用户数据隔离，支持 ReAct、MCP 与每用户 Skills（含脚本）。

当前架构已统一为：
- 会话主入口：`/api/sessions/*`（单人与多人共用同一套带主持人的会话模型）
- Agent 主入口：`/api/agents/*`（专家资源包导入导出沿用 `/api/dha/instances/*`）

- 前端：见 [frontend/README.md](frontend/README.md)
- 后端：见 [backend/README.md](backend/README.md)
- 文档中心：见 [docs/README.md](docs/README.md)
- 发布入口：见 [docs/release/README.md](docs/release/README.md)
- 用户使用说明：见 [docs/user-manual/user-guide.md](docs/user-manual/user-guide.md)
- 程序如何启动、与专家对话时前后端如何协作（框架说明）：见 [docs/architecture/runtime-architecture.md](docs/architecture/runtime-architecture.md)
- 项目工作条目式清单（便于汇报与自述，可自改）：见 [docs/project/worklist.md](docs/project/worklist.md)
- 上线前模块化测试操作手册（可在其他机器复现）：见 [docs/testing/pre-release-testing.md](docs/testing/pre-release-testing.md)
- 兼容层与回退路径寿命台账：见 [docs/project/compatibility-lifecycle.md](docs/project/compatibility-lifecycle.md)

沙箱镜像版本映射（同一仓库 `crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox`）：

| 标签 | 对应版本 | Dockerfile | 说明 |
| --- | --- | --- | --- |
| `26.05.12.1-standard` | 普通版 | `docker/skill-sandbox/Dockerfile` | 轻量沙箱，不内置 Playwright/Chromium |
| `26.05.15-playwright` | Playwright 版 | `docker/skill-sandbox/Dockerfile.playwright` | 内置 Playwright/Chromium、Patchright、爬虫公共依赖，额外包含 `sqlite3` 与 `aiosqlite` |
