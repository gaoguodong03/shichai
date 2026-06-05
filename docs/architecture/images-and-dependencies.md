# 镜像与依赖边界

## 目标

本项目有三类容易混淆的运行环境：主应用镜像、OpenSandbox 控制面镜像、技能沙箱镜像。本文明确它们的职责、配置入口与排障顺序，避免把依赖装错地方。

## 镜像分层

| 层级 | 当前配置入口 | 作用 | 不应该承担 |
|------|--------------|------|------------|
| 主应用镜像 `ST49_IMAGE` | `docker-compose.1panel.yml` 的 `st49.image`，模板为根目录 `Dockerfile` | 运行 FastAPI 后端、托管前端静态产物、连接 MCP、调用 OpenSandbox | 不负责隔离执行用户 Skill 脚本 |
| OpenSandbox 控制面 | `OPENSANDBOX_SERVER_IMAGE`、`OPENSANDBOX_EXECD_IMAGE`、`OPENSANDBOX_EGRESS_IMAGE` | 提供沙箱生命周期 API、创建执行容器、转发执行命令 | 不应替换成业务沙箱镜像 |
| 技能沙箱镜像 | `SANDBOX_STANDARD_IMAGE`、`SANDBOX_PLAYWRIGHT_IMAGE` | 执行用户 Skill 脚本，挂载用户工作区和技能目录 | 不运行 FastAPI，不托管前端 |
| 用户沙箱依赖 | `backend/data/users/<user>/config/sandbox/requirements.txt` | 为单个用户额外安装 Python 包 | 不应写进主应用 `requirements.txt`，除非后端代码也依赖它 |

## 依赖应该放哪里

| 需求 | 放置位置 | 原因 |
|------|----------|------|
| FastAPI 后端 import 的包 | `backend/requirements.txt` | 主应用启动和测试需要 |
| 前端构建依赖 | `frontend/package.json` + `frontend/package-lock.json` | 只影响 Vue 构建 |
| 所有 Skill 都常用的系统命令 | `docker/skill-sandbox/Dockerfile` | 进入标准沙箱镜像，减少首次执行安装成本 |
| 只有网页自动化 Skill 需要的浏览器/爬虫能力 | `docker/skill-sandbox/Dockerfile.playwright` + `docker/skill-sandbox/requirements.playwright.txt` | 避免普通沙箱过大 |
| 单个用户或导入 Skill 的 Python 包 | 用户 `config/sandbox/requirements.txt` | 用户隔离，导入 Skill 时自动 merge 并预热 |
| OpenSandbox 控制面版本 | `docker-compose.1panel.yml` 的 OpenSandbox 镜像 tag | 需要与 upstream API/execd 匹配 |

## 运行时配置流向

1. `st49` 启动时由 `backend/app/core/runtime_env.py` 加载 `.env` 并填充默认值。
2. 用户在设置页选择沙箱版本，后端写入用户级 `config/sandbox/settings.json`。
3. `SandboxService` 读取用户沙箱设置，选择 `standard` 或 `playwright` 对应镜像。
4. 若用户 `requirements.txt` 非空，`SandboxService` 在该用户沙箱内执行 pip 安装和校验。
5. Skill 脚本通过统一工具网关进入该用户沙箱执行。

## 当前模块位置

| 模块 | 职责 |
|------|------|
| `backend/app/api/sandbox_settings.py` | 沙箱设置、requirements 读写、merge、保存后预热 API |
| `backend/app/core/sandbox_requirements.py` | requirements 去重 key、合并写入、错误信息格式化 |
| `backend/app/agent/sandbox_image_policy.py` | 沙箱镜像选项、用户 image variant 读写 |
| `backend/app/agent/sandbox_service.py` | 创建/复用/预热用户沙箱，安装用户 requirements |
| `backend/app/core/runtime_env.py` | 主应用启动默认环境变量 |

## 排障顺序

### 1. 后端服务起不来

- 看 `ST49_IMAGE` 是否正确构建/推送。
- 看 `backend/requirements.txt` 是否缺少后端 import 的包。
- 看 `/health` 是否返回 `{"status":"ok"}`。

### 2. Skill 脚本缺命令

- 若是所有用户都需要的系统命令，改 `docker/skill-sandbox/Dockerfile` 或 `Dockerfile.playwright` 后发布新沙箱镜像。
- 若只是某个 Python 包，写入用户 `config/sandbox/requirements.txt`，不要改主应用镜像。

### 3. Playwright/浏览器失败

- 确认用户沙箱设置选择 `playwright`。
- 确认 `SANDBOX_PLAYWRIGHT_IMAGE` 指向 Playwright 镜像。
- 确认 `PLAYWRIGHT_BROWSERS_PATH` 与镜像内浏览器安装路径一致。
- 对浏览器/爬虫公共 Python 栈，优先更新并重发 `crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.15-playwright`，不要放进 `26.05.12.1-standard`。

### 4. OpenSandbox 连接失败

- 确认 `opensandbox-server` 健康检查通过。
- 确认 `OPENSANDBOX_DOMAIN` 从 `st49` 容器内可访问。
- 若出现 502 或 backend endpoint 连接失败，优先保持 `OPENSANDBOX_USE_SERVER_PROXY=0`。

## 维护原则

- 主应用依赖、沙箱基础能力、用户 Skill 依赖分开管理。
- 镜像 tag 不使用 `latest`，避免上游漂移。
- 代码里只保留默认值，生产差异尽量通过 `.env` 或 1Panel 环境变量覆盖。
- 新增镜像或依赖相关功能时，同步更新本文和 `docs/requirements/acceptance-and-tests.md`。

## 1Panel 日志关键词

排查 Skill 依赖和沙箱时，可以在 1Panel 容器日志中搜索以下稳定关键词：

| 关键词 | 含义 | 需要关注的字段 |
|--------|------|----------------|
| `st49_skill_script_execute_start` | Skill 脚本开始进入统一网关 | `user_id`、`skill_id`、`workspace_id`、`requirements_hash`、`requirements_present` |
| `st49_skill_env_passthrough` | Skill 执行前透传到沙箱的环境变量检查 | `present_keys`、`missing_keys`，音频转写重点看 `QWEN_AUDIO_API_KEY` |
| `st49_sandbox_command_env_injected` | SandboxService 兜底把用户 requirements 注入脚本环境 | `user_id`、`tool_name`、`requirements_hash` |
| `st49_sandbox_requirements_loaded` | 后端读到了该用户的 `requirements.txt` | `user_id`、`path`、`bytes`、`non_comment_lines` |
| `st49_sandbox_requirements_check` | 沙箱执行前检查依赖 hash | `dep_hash`、`installed_hash`、`verified_hash`、`sandbox_id`、`image_ref` |
| `st49_sandbox_requirements_install_start` | 开始在用户沙箱内 pip install | `user_id`、`dep_hash`、`sandbox_id`、`timeout_ms` |
| `st49_sandbox_requirements_install_done` | 用户沙箱依赖安装并校验完成 | `dep_hash`、`elapsed_ms`、`stdout_tail`、`stderr_tail` |
| `st49_sandbox_requirements_install_failed` | requirements 安装失败 | `code`、`exit_code`、`stdout_tail`、`stderr_tail`、`err` |
| `st49_sandbox_recreate` | 因镜像或 requirements 变化重建用户沙箱 | `code`、`old_hash`、`new_hash`、`old_image`、`new_image` |
| `st49_skill_script_execute_done` | Skill 脚本执行成功 | `sandbox_id`、`requirements_hash`、`installed_requirements_hash`、`verified_requirements_hash` |
| `st49_skill_script_execute_nonzero` | Skill 脚本执行了但返回非 0 | `exit_code`、`stderr_len`、`sandbox_id`、依赖 hash 字段 |

贴日志时优先贴同一次请求中这些行，尤其是 `user_id`、`dep_hash/requirements_hash`、`installed_requirements_hash`、`verified_requirements_hash` 是否一致。

浏览器类 Skill 需要同时确认两点：

- 用户沙箱设置文件位于 `data/users/<用户名>/config/sandbox/sandbox/settings.json`，执行层会从同一路径读取 `image_variant` 并写入 `SANDBOX_IMAGE_VARIANT`。
- 用户 requirements 中包含 `playwright` 或 `patchright` 且 `SANDBOX_IMAGE_VARIANT=playwright` 时，预热安装会自动补 Chromium 浏览器缓存；普通版沙箱不会因为全局 requirements 意外下载浏览器。
