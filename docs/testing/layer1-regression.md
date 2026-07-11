# 第一层回归说明

本文记录当前 `layer1_core` 回归入口和真实纳入范围。旧版 layer1 清单已经废弃；本文以 `backend/tests/conftest.py` 中的 `LAYER1_CORE_MODULES` 为准。

完整业务链路入口见 [全流程业务测试汇总](full-flow-business-tests.md) 和 `./scripts/test-full-flow.sh`。

## 一键回归入口

推荐命令：

```bash
./scripts/test-layer1.sh
```

该脚本执行：

1. 后端：`pytest -m layer1_core --tb=short`
2. 前端：`npm ci && npm run build`

常用环境变量：

| 变量 | 用途 |
|------|------|
| `SHUTONG_CONDA_ENV=st49` | 指定 conda 目标环境，默认 `st49`。 |
| `SKIP_BACKEND=1` | 只跑前端构建。 |
| `SKIP_FRONTEND=1` | 只跑后端第一层测试。 |
| `FRONTEND_INSTALL=skip` | 跳过 `npm ci`，直接执行 `npm run build`。 |
| `BACKEND_PY=/path/to/python` | 指定后端 Python 解释器。 |

## 第一层边界

第一层是快速门禁，不是全量测试。它用于覆盖核心业务链路和最容易发生契约漂移的模块：

- 账号、会话、资源中心和工作区 API。
- 群聊、Skill、工具、MCP、LLM 和沙箱核心路径。
- 前端业务聚合测试和生产构建。
- 启动初始化、资源包导入导出和专家运行时基础契约。

第一层不承诺覆盖：

- 全部 HTTP 路由。
- 全部工具和全部 MCP 子模块。
- 真实 LLM、真实远程 MCP、Docker/OpenSandbox 长链路和非确定性慢测。
- 用户必须通过浏览器完整点击体验才能确认的路径。

这些内容进入专项测试、全流程测试或上线前手工验收。

## 已纳入第一层的测试文件（当前 24 个）

以下列表必须与 `backend/tests/conftest.py` 的 `LAYER1_CORE_MODULES` 同步。

### 账号、会话和资源 API

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_auth_sqlite.py` | 注册、登录、Token、密码哈希、账号修改和用户隔离。 |
| `test_sessions_api.py` | 会话创建、列表、详情、更新、删除、导出和默认主持人配置。 |
| `test_agents_api.py` | 专家资源 CRUD 和 name-based 资源身份。 |
| `test_bundle_import_api.py` | 资源包导入预览、旧冲突参数拒绝和落库结果。 |
| `test_agent_import_validate.py` | Agent 导入结构校验。 |
| `test_session_preset_validate.py` | 会话预设、主持人 Skill 和依赖引用校验。 |

### 资源包、专家和运行时

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_scenario_bundle.py` | 场景包合并、清洗、导出导入和敏感字段处理。 |
| `test_expert_bundle.py` | 专家包导入导出和 Skill/工具引用。 |
| `test_expert_runtime.py` | 专家运行时、Skill 选择和工具组装基础链路。 |
| `test_expert_self_awareness_prompt.py` | 专家自我认知 Prompt 拼装和当前工作区时间戳。 |
| `test_host_takeover.py` | 主持人接管、`target_agent_name` 强制路由和主持人输出解析。 |

### 工具、Skill、MCP 和 LLM

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_call_api_tool.py` | 保存型 HTTP API 工具、SSRF、防错入参和错误文案。 |
| `test_file_ref_and_gateway.py` | 文件引用、路径保护、工具网关、MCP 参数和脚本执行入口。 |
| `test_group_chat_skill_script_cli_flow.py` | 群聊中 Skill 脚本工具调用、manifest 参数和 CLI 转换。 |
| `test_skill_agent_tool_resolution.py` | Skill 工具名解析、别名拒绝和标准 stdout 摘要。 |
| `test_simple_agent_tool_intent.py` | SimpleAgent 工具意图、工具结果综合和错误停止规则。 |
| `test_llm_config.py` | LLM provider 配置、环境变量引用、参数白名单和提示日志。 |

### 群聊记忆、沙箱和工作区

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_group_chat_group_memory.py` | 群聊记忆注入、工具产物索引、交付声明保护和自动继续信号。 |
| `test_group_memory_store.py` | 群聊事实去重、索引写入和工作区引用。 |
| `test_sandbox_service.py` | 用户级沙箱复用、重建、释放、固定资源策略和预热。 |
| `test_workspace_files.py` | 工作区文件增删改查、上传下载、路径穿越防护和工具写入。 |

### 启动和前端聚合

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_core_init.py` | 启动初始化只加载有效用户资源。 |
| `test_lifespan.py` | FastAPI 生命周期、启动预热开关和健康检查基础行为。 |
| `test_frontend_business_flows.py` | 前端可操作业务流的后端聚合验证。 |

## 与其他测试层的关系

| 测试层 | 入口 | 适用场景 |
|--------|------|----------|
| 单文件定向测试 | `rtk conda run -n st49 pytest backend/tests/test_sessions_api.py -q` | 改动单个后端模块后快速验证。 |
| 第一层回归 | `./scripts/test-layer1.sh` | 提交前快速门禁。 |
| 后端全量 | `rtk conda run -n st49 pytest backend/tests -q` | 大范围后端改动或发布前。 |
| 前端构建 | `rtk npm --prefix frontend run build` | 前端类型、路由和组件引用检查。 |
| 前端 E2E | `rtk npx --prefix frontend playwright test` | 浏览器点击级路径验证。 |
| 上线前手工验收 | [上线前模块化测试操作手册](pre-release-testing.md) | 真实 LLM、真实沙箱、真实 MCP 和部署环境。 |

## 新增测试规则

新增测试是否纳入第一层，按以下标准判断：

1. 是否保护 P0 用户路径或核心运行契约。
2. 是否稳定、快速、可在本机和 CI 环境重复执行。
3. 是否不依赖真实外部网络、真实 LLM 或长时间 Docker 操作。
4. 是否能在失败时给出清晰定位。

纳入步骤：

1. 在 `backend/tests/` 新增或修改测试文件。
2. 运行目标文件，例如：

   ```bash
   rtk conda run -n st49 pytest backend/tests/test_sessions_api.py -q
   ```

3. 如果属于第一层，在 `backend/tests/conftest.py` 的 `LAYER1_CORE_MODULES` 加入模块名。
4. 更新本文的“已纳入第一层的测试文件”。
5. 运行：

   ```bash
   ./scripts/test-layer1.sh
   ```

## 维护规则

- 本文只记录当前真实第一层，不保留旧测试文件名作为计划项。
- 如果需要规划待补测试，写入 [契约实施追踪矩阵](contract-traceability-matrix.md)，不要混入第一层真实清单。
- 第一层清单、`LAYER1_CORE_MODULES` 和 `scripts/test-layer1.sh` 三者必须同步。
