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
- 上线前模块化测试操作手册（可在其他机器复现）：见 [docs/上线前模块化测试操作手册.md](docs/上线前模块化测试操作手册.md)
docker buildx build --platform linux/amd64 \
  -t crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/dha:26.05.13 \
  -f Dockerfile \
  --push .

docker buildx build --platform linux/amd64,linux/arm64 \
  -t crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.12.1-standard \
  -f docker/skill-sandbox/Dockerfile \
  --push .

# Playwright/Chromium 大体积沙箱镜像：仅给设置中选择“Playwright 版”的用户使用，额外包含 sqlite3/aiosqlite。
docker buildx build --platform linux/amd64,linux/arm64 \
  -t crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.15-playwright \
  -f docker/skill-sandbox/Dockerfile.playwright \
  --push .

沙箱镜像版本映射（同一仓库 `crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox`）：

| 标签 | 对应版本 | Dockerfile | 说明 |
| --- | --- | --- | --- |
| `26.05.12.1-standard` | 普通版 | `docker/skill-sandbox/Dockerfile` | 轻量沙箱，不内置 Playwright/Chromium |
| `26.05.15-playwright` | Playwright 版 | `docker/skill-sandbox/Dockerfile.playwright` | 内置 Playwright/Chromium、Patchright、爬虫公共依赖，额外包含 `sqlite3` 与 `aiosqlite` |

# 本地 Apple Silicon / arm64 调试：默认会拉取上方远端多架构 tag；若要使用本地镜像，需先构建到当前 Docker daemon 并覆盖环境变量。
docker build -f docker/skill-sandbox/Dockerfile -t st49-skill-sandbox:local-standard .
export SANDBOX_BASE_IMAGE=st49-skill-sandbox:local-standard
docker build -f docker/skill-sandbox/Dockerfile.playwright -t st49-skill-sandbox:local-playwright .
export SANDBOX_PLAYWRIGHT_IMAGE=st49-skill-sandbox:local-playwright

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
- 1Panel 可导入备份包：`1panel-compose-backup.tar.gz`

### 三步完成

1. 准备环境变量  
   复制 `backend/.env.1panel.example` 为 `backend/.env`，至少填写 `QWEN_API_KEY`，并修改 `AUTH_SECRET`。
2. 在 1Panel 创建数据卷  
   创建名为 `st49` 的 Docker 卷（后端数据持久化；compose 会把内部卷 `st49_data` 绑定到该外部卷）。
3. 导入并启动  
   在 1Panel 导入 `1panel-compose-backup.tar.gz`（编排备份导入），点击启动。

### 访问与端口

- 主应用：宿主机 `8100` -> 容器 `8000`
- OpenSandbox：宿主机 `8091` -> 容器 `8090`
- 如需调整，可在 1Panel 的环境变量中覆盖：`ST49_HOST_PORT`、`OPENSANDBOX_HOST_PORT`、`ST49_IMAGE`
- 沙箱镜像优先写在 `backend/.env`：1Panel/Compose 用 `ST49_SANDBOX_STANDARD_IMAGE`、`ST49_SANDBOX_PLAYWRIGHT_IMAGE`，裸机后端用 `SANDBOX_STANDARD_IMAGE`、`SANDBOX_PLAYWRIGHT_IMAGE`；`pack_1panel_backup.sh` 会读取这些值后写入备份包。

### 常见踩坑（以后出问题先看这里）

1. **“导入编排备份”不是普通 `.tar.gz`**
   - 1Panel 的“导入编排备份”要求包内存在 `compose_meta.json`，仅把 compose 文件打包会报 `compose_meta.json not found in backup file`。
   - 推荐直接使用仓库里生成好的 `1panel-compose-backup.tar.gz`。

2. **external volume 必须预先存在**
   - 如果 compose 里写了 `external: true`，宿主机必须已经存在同名 Docker 卷，否则会报 `external volume "xxx" not found`。
   - 本项目约定外部卷名为 `st49`（承载 `/app/backend/data`）。

3. **不要依赖相对路径挂载 `opensandbox/config.toml`**
   - 1Panel 导入后编排目录会变化，`./opensandbox/config.toml` 很容易不存在/类型不匹配，导致容器启动失败（`not a directory` / `no such file or directory`）。
   - 现方案是在 `opensandbox-server` 容器启动时生成 `/tmp/sandbox.toml` 并用 `--config` 启动，避免路径问题。

4. **OpenSandbox 误走 K8s 模式会直接 503**
   - 典型日志：`Failed to load Kubernetes configuration` / `KUBERNETES::INITIALIZATION_ERROR`。
   - 解决思路：强制使用 docker runtime 配置启动（`[runtime].type="docker"`）。

5. **sandbox 创建成功但 execd endpoint 为空（`endpoint=:`）**
   - 表现：`/v1/sandboxes` 200/202 正常，但执行命令阶段超时/`ConnectError`。
   - 关键点：
     - Linux 上默认不一定有 `host.docker.internal`，需要 `extra_hosts: host.docker.internal:host-gateway`
     - OpenSandbox 配置里要设置 `docker.host_ip = "host.docker.internal"`，否则 endpoint 可能返回空。

6. **`/skill/scripts/*.py` 不存在（但你明明有技能）**
   - 根因：OpenSandbox 的 `host_path` 挂载需要“宿主机可见路径”，但技能脚本目录在 `st49` 容器内部（例如 `/app/backend/data/...`），宿主机并没有这个路径。
   - 解决：配置容器路径到宿主路径映射：
     - `SANDBOX_HOST_PATH_MAP=/app/backend/data=/var/lib/docker/volumes/st49/_data`
   - 补充说明：
     - 你现在的 1Panel 编排（`docker-compose.1panel.yml`）已经内置该映射。
     - **只有在本地开发用 bind mount（例如 `./backend/data:/app/backend/data`）时**，才需要关心 Docker Desktop 的 File Sharing 是否包含你的项目目录；1Panel 外部卷场景不需要 Docker Desktop File Sharing。

7. **沙箱内脚本无法访问 GitHub（git clone/curl/pip 等失败）**
   - 默认：沙箱 **禁网**（更安全），因此沙箱内执行联网命令通常会失败。
   - 推荐做法：按“工具”单独授权出网（更接近权限系统的思路）。
     - `SANDBOX_ALLOW_NETWORK=0`（全局默认禁网）
     - `SANDBOX_NETWORK_TOOL_ALLOWLIST=run_skill_script,call_api`（逗号分隔；写 `*` 表示全放开）
     - `SANDBOX_ALLOWED_HOSTS=github.com,raw.githubusercontent.com,api.github.com`（可选，逗号分隔）
   - 兼容旧行为：`SANDBOX_ALLOW_NETWORK=1` 且未设置 `SANDBOX_NETWORK_TOOL_ALLOWLIST` 时，表示对所有工具放开。
   - 位置：
     - 1Panel：在 `docker-compose.1panel.yml` 的 `st49.environment` 中按需取消注释。
   - 本地：在 `docker-compose.yml` 的 `dha.environment` 中设置。

8. **Skill 脚本缺少基础命令或运行时（不止 bash）**
   - 镜像职责分离：`ST49_IMAGE` 仅后端容器；`SANDBOX_BASE_IMAGE` 仅 Skill 沙箱容器，二者不要混用。
   - 主应用镜像默认不内置 Playwright/Chromium，也不在构建时预拉取 `@playwright/mcp`；浏览器自动化能力统一放在 Playwright 沙箱镜像中，避免普通应用版本打包时下载大体积 npx/Chromium 内容。
   - 当前 1Panel 默认普通沙箱镜像：`crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.12.1-standard`；独立镜像模板定义在 `docker/skill-sandbox/Dockerfile`。
   - Playwright 沙箱镜像：`crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.15-playwright`；模板定义在 `docker/skill-sandbox/Dockerfile.playwright`，额外安装 Chromium、Playwright、Patchright、`sqlite3`、`aiosqlite` 与 `docker/skill-sandbox/requirements.playwright.txt` 中的浏览器/爬虫公共依赖。
   - 用户 requirements 中包含 `playwright` 或 `patchright` 且该用户选择“Playwright 版”时，沙箱预热会自动执行浏览器安装校验，避免脚本运行时再报 `patchright install`。
   - 用户可在“设置 → 沙箱”选择“普通版”或“Playwright 版”。部署侧用 `SANDBOX_STANDARD_IMAGE`、`SANDBOX_PLAYWRIGHT_IMAGE` 分别配置两个镜像。
   - OpenSandbox 控制面不要使用 `opensandbox/server:latest`，否则上游镜像漂移可能导致 SDK、server、execd 接口不匹配，表现为 `Status code: 404` / `gateway_tool_unavailable`。1Panel 编排已固定为 `server:v0.1.13`、`execd:v1.0.15`、`egress:v1.0.10`。
   - 本地若出现 `pull access denied for st49-skill-sandbox`，说明环境变量指向了本地 tag，但该镜像没有构建到当前 Docker daemon；解决：取消本地覆盖改用远端 tag，或执行上方 `docker build ... -t st49-skill-sandbox:local-* .`。
   - 本地 Apple Silicon / arm64 若出现 `no matching manifest for linux/arm64`，说明沙箱镜像指向的远端 tag 没有 arm64 镜像。解决：要么按上方命令发布 `linux/amd64,linux/arm64` 多架构 sandbox 镜像，要么本地构建 `st49-skill-sandbox:local-standard` / `st49-skill-sandbox:local-playwright` 并覆盖对应环境变量。
   - 已内置常用命令/运行时：`bash`、`curl`、`wget`、`git`、`jq`、`rg`、`tree`、`zip/unzip`、`python3/pip`、`node/npm/pnpm/yarn/tsx`，以及 `ffmpeg`、`imagemagick`、`poppler-utils`、`tesseract-ocr` 等文档/图片处理工具。
   - 已支持脚本后缀：`.py`、`.sh`、`.bash`、`.js`、`.mjs`、`.cjs`、`.ts`、`.tsx`；其中 TypeScript 通过 `tsx` 执行。
   - 如需增加系统命令，优先改 `docker/skill-sandbox/Dockerfile` 并发布新 `SANDBOX_BASE_IMAGE`；仅后端依赖再改主 `Dockerfile` 并发布 `ST49_IMAGE`。
   - 架构建议：线上 Linux 虚拟机通常是 `linux/amd64`，但请以实际节点为准；发布前务必执行 `docker manifest inspect <镜像:tag>`，确认包含目标平台（`amd64` 或 `arm64`）。
   - 如需增加某个用户自己的 Python 包，使用 `data/users/<用户名>/config/sandbox/requirements.txt`，内容变更后会触发该用户沙箱重建/重装。
   - 经验教训：`ST49_IMAGE` 与 sandbox 镜像必须独立发布。普通应用版本号（如 `26.05.12.25`）不代表存在 `sandbox:26.05.12.25-standard`；1Panel 包默认应继续指向已发布的固定 sandbox 镜像，除非显式构建/推送新的 sandbox 镜像。
   - 1Panel 变量隔离：线上曾出现旧 `SANDBOX_STANDARD_IMAGE=sandbox:<应用版本>-standard` 残留，导致 OpenSandbox 拉取不存在的 sandbox tag 并报 `manifest unknown`。当前编排使用 `ST49_SANDBOX_STANDARD_IMAGE` / `ST49_SANDBOX_PLAYWRIGHT_IMAGE` 作为 1Panel 包内变量，避免被旧环境变量污染。
   - Docker Hub 不稳定时，主镜像构建可临时覆盖 `NODE_IMAGE` 为已有的内部镜像；网络正常时直接 `bash pack_1panel_backup.sh <tag>` 即可。

9. **沙箱 Python requirements 假安装 / `xlrd` 缺失**
   - 典型现象：脚本返回 `excel_read_failed`，提示 ``Import xlrd` failed`；但 `_sandbox_trace` 中 `installed_requirements_hash` / `verified_requirements_hash` 已等于当前 requirements hash。
   - 关键判据：脚本 stderr 若出现 `skill_python_requirements_bytes=0`，说明脚本命令没有拿到 `SKILL_REQUIREMENTS_B64`；安装日志若出现 `REQ_B64=` 或 `wrote_requirements_bytes 0`，说明 OpenSandbox 命令环境变量没有传入安装命令。
   - 根因复盘：部分 OpenSandbox command 路径中 `envs` 未进入实际 shell 进程，旧安装脚本会把空 requirements 写入 `/tmp/requirements.txt`，`pip install -r 空文件` 返回 0，随后错误地把 metadata 标为 verified。
   - 修复策略：requirements 安装与脚本执行都把关键环境变量内联进 shell 命令；非空 requirements 若解码后为空会直接失败，不再写入 verified metadata；metadata 命中时还会做真实 import 校验。
   - 正常验证：stderr 应包含 `skill_python_requirements_bytes=79`、`skill_python_requirements_hash=5817ace3254dfe26`，并看到 `skill_python_probe xlrd=2.0.x import=ok`。
   - 回归命令：更新 ST49 后端代码后，重新构建/推送 `ST49_IMAGE` 并重启 1Panel；无需为这类后端逻辑修复发布新的 sandbox 镜像。

10. **改了代码但线上没变**
   - 如果 1Panel 用的是远端镜像（`ST49_IMAGE=...`），你改仓库代码不会自动生效。
   - 必须构建/推送新镜像并更新 tag（例如从 `26.04.15.2` 升到 `26.04.15.3`）。

11. **长音频转写报 `encoder cache size 2048`**
   - 根因：上游 ASR 服务单次音频输入超过 vLLM 多模态缓存限制（错误里会提示 `--limit-mm-per-prompt`）。
   - 应用侧规避：`docker-compose.1panel.yml` 默认设置 `QWEN_AUDIO_CHUNK_SECONDS=120`，音频转写 Skill 会自动切成约 2 分钟片段后合并结果。
   - 线上快速修复：如果暂时不发新镜像，可在 1Panel 的 `st49` 环境变量中手动加入 `QWEN_AUDIO_CHUNK_SECONDS=120` 并重建/重启容器。
   - 服务侧优化：如果希望不切片，需要在上游 ASR/vLLM 启动参数中调大 `--limit-mm-per-prompt`，同时评估显存占用。

12. **`gateway_timeout` / `gateway_tool_unavailable` 如何快速判读**
   - `gateway_timeout`：网关等待沙箱执行超时，通常发生在“建沙箱 + 首次装依赖 + 跑脚本”整体耗时过长。
   - `gateway_tool_unavailable`：执行器不可用，优先看 `gateway_error` 中的异常类型（如 `SandboxApiException`、`ClosedResourceError`）。
   - 推荐同时关注：
     - `gateway_elapsed_ms`（实际耗时）
     - `gateway_interrupt_reason`（`timeout_or_budget_exceeded` 或 `tool_unavailable`）
   - 若经常冷启动超时，可调大：
     - `SANDBOX_SCRIPT_GATEWAY_SLACK_MS`（网关整体等待余量，默认 300000ms）
     - `SKILL_SCRIPT_TIMEOUT`（脚本执行超时）
   - 若 `gateway_error` 包含 `Failed to pull image ... sandbox:<tag>-standard ... manifest unknown`，优先检查 1Panel 包里的 `ST49_SANDBOX_STANDARD_IMAGE` 是否指向已发布的 sandbox 镜像。不要把应用 tag 当作 sandbox tag。

13. **OpenSandbox 502（`Could not connect to backend sandbox endpoint`）**
   - 典型日志：
     - `Failed to run command. Status code: 502`
     - `Could not connect to the backend sandbox endpoint='172.x.x.x:port'`
   - 这通常是 OpenSandbox 转发链路问题，不是脚本本身逻辑错误。
   - 实战经验：在部分 1Panel/宿主网络环境下，`OPENSANDBOX_USE_SERVER_PROXY=1` 会更易触发该问题，改为 `0` 可恢复。
   - 建议固定检查项：
     - `st49` 是否已生效 `OPENSANDBOX_USE_SERVER_PROXY=0`
     - `opensandbox-server` 与 `st49` 是否都健康
     - `st49` 是否依赖 `opensandbox-server: service_healthy`

14. **后端重启后遗留很多 OpenSandbox 沙箱**
   - 当前后端启动时默认执行一次孤儿沙箱清理：`SANDBOX_CLEANUP_ORPHANS_ON_START=1`。
   - 新建沙箱会带 `metadata: managed_by=st49, app=shichai`，便于后续精确识别；旧版本没有 metadata 的沙箱会按当前 `SANDBOX_STANDARD_IMAGE` / `SANDBOX_PLAYWRIGHT_IMAGE` 镜像匹配清理。
   - 保护参数：
     - `SANDBOX_ORPHAN_CLEANUP_MIN_AGE_SEC`：默认 60 秒，避免误删刚创建的沙箱。
     - `SANDBOX_ORPHAN_CLEANUP_LEGACY_IMAGE_MATCH`：默认 1；如同一个 OpenSandbox 被多个应用共用，可设为 0，仅清理带 st49 metadata 的沙箱。
     - `SANDBOX_ORPHAN_CLEANUP_TIMEOUT_SEC`：默认 30 秒，启动清理超时后只打日志，不阻断后端启动。
   - 日志关键词：`sandbox_orphan_cleanup_start`、`sandbox_orphan_cleanup_done`、`sandbox_orphan_cleanup_startup_result`。

15. **用户沙箱按需启动、镜像模板与常驻资源**
   - 默认策略：后端启动时不批量拉起所有历史用户沙箱；用户登录后，或用户手动点击预热时，再异步预热该用户自己的沙箱。
   - 沙箱用 `SANDBOX_STANDARD_IMAGE` / `SANDBOX_PLAYWRIGHT_IMAGE` 指向统一模板镜像。OpenSandbox 创建用户沙箱时按 `image_ref` 使用这两个模板；镜像层由 Docker daemon 缓存，同一个 tag 已下载后不会为每个用户重复下载。
   - 如果希望部署后提前下载模板镜像但不创建用户沙箱，可在宿主机执行 `docker pull <SANDBOX_STANDARD_IMAGE>` 和需要时 `docker pull <SANDBOX_PLAYWRIGHT_IMAGE>`。
   - 推荐配置（`docker-compose.yml` / `docker-compose.1panel.yml`）：
     - `SANDBOX_ALWAYS_ON=1`：用户沙箱创建后保持常驻，减少后续工具调用冷启动。
     - `SANDBOX_PREWARM_ALL_USERS=0`：默认关闭启动期全用户预热，避免部署后瞬间创建大量沙箱。
     - `SANDBOX_PREWARM_ON_USER_REQUEST=0`：默认关闭普通接口触发预热，避免打开页面就创建当前用户沙箱；确实需要时显式设为 1。
     - `SANDBOX_LOGIN_PREWARM_TIMEOUT_MS=600000`：登录预热超时，默认 10 分钟。
     - `SANDBOX_REQUEST_PREWARM_TIMEOUT_MS=600000`：访问触发预热启用时的超时，默认沿用登录预热超时。
     - `SANDBOX_FIXED_CPU=1.0`：统一 CPU 配额。
     - `SANDBOX_FIXED_MEMORY_MB=2048`：统一内存配额（MB）。
   - 如确实需要维护窗口提前拉起所有用户，可临时设 `SANDBOX_PREWARM_ALL_USERS=1` 后重启；日常线上不建议默认开启。
   - 日志关键词：`sandbox_prewarm_all_users_disabled`、`sandbox_login_prewarm_start`、`sandbox_user_request_prewarm_start`、`st49_sandbox_user_bound`。

16. **MCP 抓取偶发 `ClosedResourceError`（本地可用、远端偶发失败）**
   - 含义：MCP 长连接被远端服务回收/断开，常见于 `linkup-fetch` 这类远程 streamable-http。
   - 当前策略：检测到 `ClosedResourceError` 后自动重连对应 MCP server 并重试 1 次。
   - 若仍失败，再看远端 MCP 服务健康、API Key、上游限流与网络波动。

### 回归验证（建议每次改沙箱/文件工具后跑一遍）
- **文件读写（会话隔离）**
  - 在某个会话里写入：`write_workspace_file path="memory/facts.md" content="hello"`
  - 再读取：`read_file path="memory/facts.md"`
  - 预期：只在该会话工作区可见（其它会话读不到同名文件）。
- **列目录（含空格/中文目录名）**
  - 新建目录：`mkdir_workspace path="中文 目录/子目录"`
  - 列目录：`list_workspace_directory path="中文 目录"`
  - 预期：能正常返回 `./子目录` 等相对路径；不会因为空格/中文失败。
- **GitHub（两条路径分开测）**
  - `call_api`：对 `https://github.com/<owner>/<repo>/blob/<ref>/<file>` 测一次，预期会自动改写为 raw 并返回文件内容（或至少返回清晰的 HTTP 状态码/错误）。
  - 沙箱脚本：仅在你开启 `SANDBOX_ALLOW_NETWORK=1` 后，再在技能脚本里 `curl -I https://github.com` 进行验证；不开启时失败是预期行为。
  - 沙箱脚本（按工具放行）：若使用 `SANDBOX_NETWORK_TOOL_ALLOWLIST`，则只要把 `run_skill_script` 加入 allowlist 即可；不开启时失败是预期行为。

### 本次 `docker-compose.1panel.yml` 关键改动（务必随镜像一起发布）

1. **`OPENSANDBOX_USE_SERVER_PROXY=0`（原为 1）**
   - 触发背景：出现 `502` + `Could not connect to backend sandbox endpoint='172.x.x.x:port'`。
   - 目的：绕过 server-proxy 路径，降低某些宿主网络环境下的转发失败概率。
   - 现状：已验证可恢复脚本执行。

2. **给 `opensandbox-server` 增加 `healthcheck`**
   - 目的：避免“容器已启动但服务未就绪”时，`st49` 提前接流量导致网关超时或 5xx。
   - 检查点：`http://127.0.0.1:8090/health` 返回 200。

3. **`st49.depends_on.opensandbox-server.condition=service_healthy`（原为 `service_started`）**
   - 目的：确保 `st49` 在 OpenSandbox 真正健康后再启动，减少冷启动竞态问题。

4. **保留并强调 `SANDBOX_SCRIPT_GATEWAY_SLACK_MS=300000`**
   - 目的：给“建沙箱 + 首次装依赖 + 执行脚本”整段流程预留网关等待余量，降低误报 `gateway_timeout`。

5. **脚本网络策略仍保持最小放行**
   - `SANDBOX_ALLOW_NETWORK=0`
   - `SANDBOX_NETWORK_TOOL_ALLOWLIST=run_skill_script`
   - 说明：只放行 `run_skill_script*`，其余工具默认禁网，符合线上最小权限原则。
