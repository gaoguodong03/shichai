# 上线前模块化测试操作手册

本文档用于在上线前做可复现的模块化测试，目标是：研发机、本机、临时验收机或服务器上都能按同一套步骤完成验证，并明确每一层测试覆盖什么、不覆盖什么。

## 1. 测试分层

| 层级 | 命令 | 适用场景 | 覆盖范围 | 是否需要外部服务 |
| --- | --- | --- | --- | --- |
| 单模块测试 | `cd backend && python -m pytest tests/test_xxx.py -q` | 改完某个模块后快速验证 | 指定后端模块 | 通常不需要 |
| 第一层回归 | `./scripts/test-layer1.sh` | 上线前最低必跑项 | 后端核心链路 + 前端构建 | 不需要真实 LLM；前端需 npm 依赖 |
| 后端全量测试 | `cd backend && python -m pytest` | 合并前/发版前更完整验证 | `backend/tests/` 全量 | 依赖具体用例，优先本地 mock |
| 前端构建测试 | `cd frontend && npm ci && npm run build` | 验证 TypeScript 与生产构建 | Vue/TS/Vite 构建 | 不需要后端运行 |
| UI 点击级自动化 | `./scripts/test-ui-flow.sh` | 验证用户能点击到的核心路径 | 登录、工作空间、对话、资源中心、设置、导入导出 | 不需要真实后端；Playwright 用 API 替身 |
| 部署冒烟测试 | `docker compose -f docker-compose.1panel.yml up -d` 后访问接口 | 上线前在目标机器验收 | 容器启动、健康检查、登录、基础对话、技能沙箱 | 需要 Docker、镜像、`.env`、OpenSandbox |

第一层回归是上线前最低门槛；如果时间允许，推荐再跑后端全量测试与部署冒烟测试。

### 1.1 按用户需求编号验收

上线前验收应同时从“测试层级”和“用户需求”两个方向确认。测试层级回答跑哪些命令，用户需求编号回答这些命令保护哪些用户价值。

| 用户需求 | 最低验证 | 补充验收 |
|----------|----------|----------|
| UR-01 账号与用户隔离 | 第一层回归中的鉴权与会话测试 | 浏览器检查未登录跳转、登录刷新、跨账号资源隔离 |
| UR-02 工作区与统一会话 | 第一层回归中的会话、SSE、前端业务流测试 | 手工创建会话、上传文件、刷新后继续对话 |
| UR-03 主持人与专家协作 | 第一层回归中的调度 FSM、专家 runtime、主持人接管测试 | 普通会话、场景会话、`@专家` 三种路径各跑一轮 |
| UR-04 资源中心 | 第一层回归中的 Agent、资源配置和业务流测试 | 资源中心检查场景、专家、Skill、MCP、LLM 保存反馈 |
| UR-05 Skill 与脚本执行 | 第一层回归中的 Skill 脚本和工具网关测试 | 真实沙箱执行一个脚本型 Skill，检查成功和失败提示 |
| UR-06 MCP 工具能力 | 第一层回归中的 MCP 权限和工具解析测试 | 用一个已配置 MCP 做连通性、鉴权失败和断连诊断检查 |
| UR-07 沙箱运行环境 | 第一层回归中的沙箱服务和生命周期测试 | 普通版/Playwright 版镜像各做一次启动或冒烟 |
| UR-08 工作区文件管理 | 第一层回归中的工作区文件和路径保护测试 | 上传、预览、编辑、下载、专家生成文件落盘 |
| UR-09 导出与导入 | 第一层回归中的资源包导入导出测试 | 导出资源包后换账号导入，检查预览、冲突和导入结果 |
| UR-10 模型、密钥与个人设置 | 第一层回归中的 LLM 配置和设置业务流测试 | 保存模型、密钥、主题、账号安全设置并刷新检查 |
| UR-11 部署与运维 | 前端构建、生命周期测试、沙箱测试 | Docker/1Panel 健康检查、数据卷持久化和日志关键词排查 |

若某项用户需求本次改动直接影响，即使第一层回归通过，也应执行该行的补充验收。

## 2. 新机器准备

### 2.1 基础依赖

在任意一台新机器上测试前，先准备：

- Git：用于拉取代码。
- Python 3.11+：用于后端测试。
- Node.js 18+ 与 npm：用于前端构建。
- Google Chrome：用于 `frontend/e2e/` 的 Playwright 点击级 UI 测试。
- Docker：仅部署冒烟测试需要。
- 可选 conda：如果团队统一用 conda 环境，可设置 `SHUTONG_CONDA_ENV`。

### 2.2 拉取代码

```bash
git clone <repo-url> shichai
cd shichai
```

如果测试的是待上线包或压缩包，解压后进入项目根目录即可。后续命令均默认在项目根目录执行。

### 2.3 后端测试环境

推荐使用项目内虚拟环境，便于不同机器复现：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
cd ..
```

如果使用 conda：

```bash
conda create -n st49 python=3.11 -y
conda activate st49
python -m pip install -r backend/requirements.txt
```

`scripts/test-layer1.sh` 会按以下顺序寻找后端 Python：

1. `BACKEND_PY=/path/to/python` 指定的解释器；
2. 当前激活且名称等于 `SHUTONG_CONDA_ENV` 的 conda 环境；
3. `backend/venv/bin/python`；
4. `backend/.venv/bin/python`；
5. `conda run -n ${SHUTONG_CONDA_ENV}`；
6. PATH 中的 `python3`。

### 2.4 前端测试环境

```bash
cd frontend
npm ci
cd ..
```

如果只是跑第一层回归，脚本默认会在 `frontend/` 内执行 `npm ci && npm run build`，所以也可以跳过这一步，由脚本自动安装。

### 2.5 环境变量

普通单元测试与前端构建通常不需要真实模型 Key。

部署冒烟测试需要准备：

```bash
cp backend/.env.1panel.example backend/.env
```

至少修改：

- `QWEN_API_KEY`：可用的模型供应商 Key。
- `AUTH_SECRET`：生产/准生产环境必须改成长随机串。
- `CORS_ORIGINS`：改成实际访问地址，例如 `http://<server-ip>:8100`。

## 3. 常用操作命令

### 3.1 单模块测试

适合改动后先验证目标模块：

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/test_sandbox_service.py -q
```

也可以替换为任意 `backend/tests/test_*.py` 文件，例如：

```bash
python -m pytest tests/test_sessions_api.py -q
python -m pytest tests/test_group_chat_stream_protocol.py -q
python -m pytest tests/test_auth_sqlite.py -q
```

### 3.2 第一层回归

项目根目录执行：

```bash
./scripts/test-layer1.sh
```

只跑后端：

```bash
SKIP_FRONTEND=1 ./scripts/test-layer1.sh
```

只跑前端：

```bash
SKIP_BACKEND=1 ./scripts/test-layer1.sh
```

指定 Python：

```bash
BACKEND_PY=$PWD/backend/.venv/bin/python ./scripts/test-layer1.sh
```

使用指定 conda 环境：

```bash
SHUTONG_CONDA_ENV=st49 ./scripts/test-layer1.sh
```

前端已安装依赖时跳过 `npm ci`：

```bash
FRONTEND_INSTALL=skip ./scripts/test-layer1.sh
```

通过标准：脚本末尾汇总里 `backend: PASS` 且 `frontend: PASS`。

### 3.3 后端全量测试

```bash
cd backend
source .venv/bin/activate
python -m pytest
```

通过标准：所有测试通过，无新增失败用例。

### 3.4 前端生产构建

```bash
cd frontend
npm ci
npm run build
```

通过标准：`vue-tsc` 与 `vite build` 均成功，生成 `frontend/dist/`。

### 3.5 UI 点击级自动化

```bash
./scripts/test-ui-flow.sh
```

通过标准：脚本末尾 `ui-flow: PASS`，且 Playwright `chrome` 项目全部通过。该层会自动启动 Vite dev server，并用测试内 API 替身模拟后端返回；它验证“用户能看见并点击”的页面路径，不验证真实 LLM、Docker、OpenSandbox 或线上网络。当前配置使用本机 Chrome 通道，避免为普通应用工程预下载大体积 Playwright Chromium 缓存。

当前六组用例：

- `frontend/e2e/auth.spec.ts`：登录、注册与进入主工作台；
- `frontend/e2e/workspace.spec.ts`：新建会话、发送消息、成员管理、文件插入、场景快捷入口；
- `frontend/e2e/resources-scenario-expert.spec.ts`：资源中心场景配置、专家创建与保存；
- `frontend/e2e/resources-skill-mcp-llm.spec.ts`：技能详情、技能依赖、工具创建、模型参数保存；
- `frontend/e2e/settings.spec.ts`：主持人设置、配色、密钥、账号、安全和沙箱 requirements。

调试时可打开浏览器：

```bash
cd frontend
npm run test:e2e:full -- --headed e2e/workspace.spec.ts
```

### 3.6 1Panel/容器部署冒烟

在具备 Docker 的机器上执行：

```bash
docker volume create st49
docker compose -f docker-compose.1panel.yml up -d
docker ps
```

健康检查：

```bash
curl -f http://127.0.0.1:8100/health
curl -f http://127.0.0.1:8091/health
```

浏览器访问：

```text
http://<server-ip>:8100
```

冒烟检查项：

- 页面能打开且无明显白屏；
- 能登录测试账号；
- 能创建/进入会话；
- 能发送一条普通消息；
- 如本次改动涉及技能或文件，需额外验证对应技能脚本和工作区文件读写；
- `docker ps` 中 `st49` 与 `opensandbox-server` 为 healthy 或持续运行状态。

## 4. 第一层回归覆盖范围

第一层回归由 `scripts/test-layer1.sh` 执行，后端范围来自 `backend/tests/conftest.py` 的 `LAYER1_CORE_MODULES`。

当前包含：

- 鉴权与用户数据：`test_auth_sqlite`、`test_sessions_api`；
- 编排与主持人状态机：`test_group_orchestration_fsm`、`test_orchestration_contracts`、`test_group_chat_cleanup_contract`；
- 群聊协议与记忆：`test_group_chat_stream_protocol`、`test_group_chat_group_memory`、`test_group_memory_store`；
- Agent/专家：`test_agents_api`、`test_expert_bundle`、`test_expert_runtime`、`test_host_takeover`；
- 沙箱与技能脚本：`test_sandbox_service`、`test_group_chat_skill_script_cli_flow`；
- 文件与工作区：`test_workspace_files`、`test_file_ref_and_gateway`；
- Runtime/MCP/工具网关切片：`test_skill_agent_tool_resolution`、`test_call_api_tool`、`test_frontend_business_flows`；
- 场景与配置校验：`test_bundle_import_api`、`test_scenario_bundle`、`test_session_preset_validate`、`test_llm_config`。

不包含：

- 所有 HTTP 路由的系统性覆盖；
- 所有 tools 与 MCP 子模块的端到端覆盖；
- 真实 LLM 长链路稳定性；
- 生产服务器网络、镜像仓库、DNS、证书等基础设施问题。

## 5. 新增模块测试规范

新增或拆分模块时，按以下方式纳入模块化测试：

1. 在 `backend/tests/` 新增 `test_xxx.py`；
2. 本地先执行 `cd backend && python -m pytest tests/test_xxx.py -q`；
3. 如果属于上线前核心路径，把 `test_xxx` 加入 `backend/tests/conftest.py` 的 `LAYER1_CORE_MODULES`；
4. 回到项目根目录执行 `./scripts/test-layer1.sh`；
5. 文档或 PR 说明里写清楚该测试覆盖的模块、输入、预期输出与不覆盖范围。

如果新增的是用户必须在前端点击完成的功能，还要补充 `frontend/e2e/` 用例：

1. 用 `getByRole`、`getByLabel`、`getByPlaceholder` 或可见文本定位控件；
2. API 依赖优先在测试里用 `page.route('**/api/**', ...)` 替身化；
3. 断言用户最终能看到的页面状态，而不是组件内部变量；
4. 避免依赖真实 LLM、Docker、OpenSandbox 或外部网络；
5. 同步更新 `docs/testing/full-flow-business-tests.md` 的需求覆盖表。

建议命名：

- API：`test_<domain>_api.py`；
- 核心服务：`test_<service_name>.py`；
- 协议/契约：`test_<domain>_contracts.py`；
- 数据迁移/校验：`test_<domain>_validate.py`。

### 5.1 新增或修改 Skill

新增或修改 Skill 时，先按 `docs/skills/skill-standard.md` 检查目录结构、`SKILL.md` frontmatter、脚本调用契约与结束点判断。

重点确认：

- 脚本型 Skill 的 stdout JSON 使用 `execution_status`、`result_code`、`message`、`artifacts`、`next_action`；
- `next_action.agent_turn` 只允许 `continue` 或 `respond`；
- `next_action.skill_session` 只允许 `keep` 或 `release`；
- `next_action.skill_session=keep` 表示保留同一专家与同一 Skill，等待用户补充或继续处理；
- `next_action.skill_session=release` 表示 Skill 本轮流程结束，释放会话锁并交回四九调度；
- 脚本型 Skill 使用 `cli_args_json`，不再使用 `input_json` 或 stdin 读取。

建议执行：

```bash
cd backend
python scripts/validate_skill_cli_contract.py
python -m pytest tests/test_group_chat_skill_script_cli_flow.py -q
```

## 6. 上线前测试记录模板

每次上线前建议复制以下模板到发布记录或群公告：

```text
版本/分支：
提交号：
测试机器：
测试人：
测试时间：

环境：
- Python：
- Node.js：
- npm：
- Docker：

测试结果：
- 单模块测试：通过/未跑/失败，命令：
- 第一层回归：通过/失败，命令：./scripts/test-layer1.sh
- 后端全量：通过/未跑/失败，命令：cd backend && python -m pytest
- 前端构建：通过/失败，命令：cd frontend && npm run build
- UI 点击级自动化：通过/未跑/失败，命令：./scripts/test-ui-flow.sh
- 部署冒烟：通过/未跑/失败，访问地址：

异常与处理：
- 

上线结论：可上线/暂缓上线
```

## 7. 常见问题

### 7.1 `pytest: command not found` 或缺依赖

确认已安装后端依赖：

```bash
cd backend
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

### 7.2 `npm ci` 失败

确认 Node.js 版本为 18+，并优先使用仓库内 `frontend/package-lock.json`：

```bash
node -v
npm -v
cd frontend
npm ci
```

### 7.3 新机器没有 conda 环境

不强依赖 conda。使用 `backend/.venv` 即可：

```bash
BACKEND_PY=$PWD/backend/.venv/bin/python ./scripts/test-layer1.sh
```

### 7.4 部署后 OpenSandbox 不健康

优先检查：

```bash
docker logs opensandbox-server --tail=200
docker logs st49 --tail=200
```

重点看：Docker socket 是否挂载、`host.docker.internal` 是否可解析、`OPENSANDBOX_DOMAIN` 是否正确、`st49` 数据卷是否存在。

### 7.5 技能脚本找不到文件或依赖

检查：

- `SANDBOX_HOST_PATH_MAP=/app/backend/data=/var/lib/docker/volumes/st49/_data` 是否与部署方式匹配；
- 远程 1Panel 编排应使用外部卷 `st49`，OpenSandbox allowlist 应包含 `/var/lib/docker/volumes/st49/_data`；不要把本地开发机 `/Users/...` 路径作为生产默认值；
- 本地 conda 后端若直接连 OpenSandbox，需要 Docker Desktop File Sharing 覆盖项目目录；这只是本地调试限制，不代表 1Panel 外部卷路径不可用；
- 对应用户技能目录下是否存在 `SKILL.md`、`scripts/manifest.json` 与脚本文件；
- 沙箱镜像是否包含脚本需要的系统命令或 Python 包。

## 8. 推荐上线门禁

上线前最低要求：

```bash
./scripts/test-layer1.sh
```

推荐完整要求：

```bash
./scripts/test-layer1.sh
./scripts/test-ui-flow.sh
cd backend && python -m pytest
cd ../frontend && npm ci && npm run build
```

如果本次改动涉及 Docker、沙箱、技能脚本、登录或线上环境变量，还必须在一台非开发机上完成部署冒烟测试。
