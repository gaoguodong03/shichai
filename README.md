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

7. **改了代码但线上没变**
   - 如果 1Panel 用的是远端镜像（`ST49_IMAGE=...`），你改仓库代码不会自动生效。
   - 必须构建/推送新镜像并更新 tag（例如从 `26.04.15.2` 升到 `26.04.15.3`）。