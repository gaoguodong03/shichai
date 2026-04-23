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

crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/dha:26.04.22.2
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

8. **改了代码但线上没变**
   - 如果 1Panel 用的是远端镜像（`ST49_IMAGE=...`），你改仓库代码不会自动生效。
   - 必须构建/推送新镜像并更新 tag（例如从 `26.04.15.2` 升到 `26.04.15.3`）。

9. **`gateway_timeout` / `gateway_tool_unavailable` 如何快速判读**
   - `gateway_timeout`：网关等待沙箱执行超时，通常发生在“建沙箱 + 首次装依赖 + 跑脚本”整体耗时过长。
   - `gateway_tool_unavailable`：执行器不可用，优先看 `gateway_error` 中的异常类型（如 `SandboxApiException`、`ClosedResourceError`）。
   - 推荐同时关注：
     - `gateway_elapsed_ms`（实际耗时）
     - `gateway_interrupt_reason`（`timeout_or_budget_exceeded` 或 `tool_unavailable`）
   - 若经常冷启动超时，可调大：
     - `SANDBOX_SCRIPT_GATEWAY_SLACK_MS`（网关整体等待余量，默认 300000ms）
     - `SKILL_SCRIPT_TIMEOUT`（脚本执行超时）

10. **OpenSandbox 502（`Could not connect to backend sandbox endpoint`）**
   - 典型日志：
     - `Failed to run command. Status code: 502`
     - `Could not connect to the backend sandbox endpoint='172.x.x.x:port'`
   - 这通常是 OpenSandbox 转发链路问题，不是脚本本身逻辑错误。
   - 实战经验：在部分 1Panel/宿主网络环境下，`OPENSANDBOX_USE_SERVER_PROXY=1` 会更易触发该问题，改为 `0` 可恢复。
   - 建议固定检查项：
     - `st49` 是否已生效 `OPENSANDBOX_USE_SERVER_PROXY=0`
     - `opensandbox-server` 与 `st49` 是否都健康
     - `st49` 是否依赖 `opensandbox-server: service_healthy`

11. **MCP 抓取偶发 `ClosedResourceError`（本地可用、远端偶发失败）**
   - 含义：MCP 长连接被远端服务回收/断开，常见于 `linkup-fetch` 这类远程 streamable-http。
   - 当前策略：检测到 `ClosedResourceError` 后自动重连对应 MCP server 并重试 1 次。
   - 若仍失败，再看远端 MCP 服务健康、API Key、上游限流与网络波动。

12. **用户沙箱常驻与统一资源（新增）**
   - 目标：每个用户一个常驻沙箱，减少首次执行冷启动波动。
   - 推荐配置（`docker-compose.yml` / `docker-compose.1panel.yml`）：
     - `SANDBOX_ALWAYS_ON=1`：开启常驻模式（不因空闲 TTL 回收）
     - `SANDBOX_PREWARM_ALL_USERS=1`：服务启动后扫描已存在用户并批量预热
     - `SANDBOX_FIXED_CPU=1.0`：统一 CPU 配额
     - `SANDBOX_FIXED_MEMORY_MB=512`：统一内存配额（MB）
   - 行为说明：
     - 登录仍会做单用户预热；启动期会额外尝试全用户预热（失败仅记日志，不阻塞启动）。
     - 运行时若检测到沙箱失联（not found / invalid），会自动失效旧句柄并重建一次。

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