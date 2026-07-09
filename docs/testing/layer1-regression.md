# 测试清单与第一层回归说明

./scripts/test-layer1.sh  

完整业务链路入口见 `docs/testing/full-flow-business-tests.md` 与 `./scripts/test-full-flow.sh`。

本文档用于回答两个问题：

1. 当前项目「都测试了什么」；
2. 如何稳定执行第一层一键回归，并把新增测试纳入其中。

## 一键回归入口

- 命令：`./scripts/test-layer1.sh`
- 后端：`pytest -m layer1_core --tb=short`
- 前端：`npm ci && npm run build`

### 常用环境变量

- `SHUTONG_CONDA_ENV=st49`：指定 conda 目标环境（默认 `st49`）。
- `SKIP_BACKEND=1`：只跑前端。
- `SKIP_FRONTEND=1`：只跑后端。
- `FRONTEND_INSTALL=skip`：跳过 `npm ci`，直接 `npm run build`。
- `BACKEND_PY=/path/to/python`：强制后端 Python 解释器。

## 第一层（layer1_core）当前覆盖范围

第一层范围由 `backend/tests/conftest.py` 中的 `LAYER1_CORE_MODULES` 控制。

设计目标：

- 覆盖核心业务链路：编排、群聊、沙箱、鉴权、工作区、runtime/工具/MCP 网关；
- 保持执行速度与稳定性；
- 不追求一次性覆盖全部路由与全部运行时分支。

## 用户需求覆盖索引

本节承接 `docs/requirements/user-requirements.md` 与 `docs/requirements/acceptance-and-tests.md` 的 UR 编号，用于判断第一层回归是否覆盖对应核心需求。自动化测试不能替代全部手工验收；涉及真实浏览器、真实模型、Docker/OpenSandbox 部署或外部网络的路径，应继续按上线前手册补充验证。

| 用户需求 | 第一层自动化覆盖 | 仍需手工或专项验证 |
|----------|------------------|--------------------|
| UR-01 账号与用户隔离 | `test_auth_sqlite.py`、`test_sessions_api.py` | 未登录页面跳转、浏览器刷新登录态 |
| UR-02 工作区与统一会话 | `test_sessions_api.py`、`test_group_chat_stream_protocol.py`、`test_frontend_business_flows.py` | 长回答流式体验、真实文件预览体验 |
| UR-03 主持人与专家协作 | `test_group_orchestration_fsm.py`、`test_scene_scheduler.py`、`test_host_takeover.py`、`test_expert_runtime.py` | 真实 LLM 下主持人可读性与用户等待状态 |
| UR-04 资源中心 | `test_agents_api.py`、`test_frontend_business_flows.py`、`test_bundle_import_api.py` | 前端资源详情页完整点击路径 |
| UR-05 Skill 与脚本执行 | `test_file_ref_and_gateway.py`、`test_group_chat_skill_script_cli_flow.py`、`test_skill_agent_tool_resolution.py` | 真实沙箱依赖安装、长耗时脚本错误展示 |
| UR-06 MCP 工具能力 | `test_file_ref_and_gateway.py`、`test_skill_agent_tool_resolution.py`、`test_frontend_business_flows.py` | 真实远程 MCP 鉴权、断连、网络异常 |
| UR-07 沙箱运行环境 | `test_sandbox_service.py`、`test_lifespan.py`、`test_file_ref_and_gateway.py` | Docker/OpenSandbox 镜像、Playwright 版沙箱冒烟 |
| UR-08 工作区文件管理 | `test_workspace_files.py`、`test_file_ref_and_gateway.py`、`test_frontend_business_flows.py` | 图片、PDF、Office 等文件前端预览 |
| UR-09 导出与导入 | `test_bundle_import_api.py`、`test_scenario_bundle.py`、`test_expert_bundle.py` | 跨账号导入、冲突确认和导入后页面检查 |
| UR-10 模型、环境变量与个人设置 | `test_llm_config.py`、`test_frontend_business_flows.py` | 设置页保存反馈、模型环境变量连通性 |
| UR-11 部署与运维 | `test_lifespan.py`、`test_sandbox_service.py`、前端构建 | 1Panel/Docker 健康检查、数据卷持久化、日志排查 |

## 已纳入第一层的测试文件（当前 31 个）

### 鉴权与账户

- `test_auth_sqlite.py`：注册/登录、密码哈希、跨用户隔离、改账号改密码。

### 工具与能力

- `test_call_api_tool.py`：`call_api` 的 SSRF、防错入参、超时、HTML 回退、JSON 返回。
- `test_simple_agent_tool_intent.py`：`SimpleAgent` 的工具调用判定与调试信息。
- `test_skill_agent_tool_resolution.py`：工具名解析、别名/非 ASCII 名称解析。
- `test_file_ref_and_gateway.py`：文件引用解析、路径保护、网关执行与串行化。
- `test_frontend_business_flows.py`：按前端可操作功能串起会话、文件、资源中心与设置页主要 CRUD。

### Agent / 场景包 / 配置校验

- `test_agents_api.py`：`/api/agents` 路由 CRUD。
- `test_agent_import_validate.py`：Agent 导入校验。
- `test_session_preset_validate.py`：会话预设校验。
- `test_scenario_bundle.py`：场景包合并与清洗。
- `test_expert_bundle.py`：专家包导入导出。

### 群聊编排与状态机

- `test_group_orchestration_fsm.py`：技能会话锁、接管/跳过规则、状态机辅助函数。
- `test_orchestration_contracts.py`：调度决策与 end payload 合同约束。
- `test_scene_runtime.py`：场景 runtime 入口、虚拟主持人与候选专家策略。
- `test_expert_runtime.py`：专家 runtime 入口、技能选择与工具组装。
- `test_scene_scheduler.py`：场景调度收敛与建议专家逻辑。
- `test_host_takeover.py`：主持人接管语义、`target_agent_name` 强制路由、主持人输出解析。
- `test_group_chat_cleanup_contract.py`：不再生成旧版 `host_plan`、`orchestrator_audit` 运行期文件。
- `test_orchestration_contracts.py`：调度和终止事件合同约束。

### 群聊记忆与协议

- `test_group_memory_store.py`：事实去重、工作区索引写入、facts/index 分发上下文。
- `test_group_chat_group_memory.py`：群聊 facts 注入、专家工具产物索引、图片预览 markdown、自动继续信号。
- `test_group_chat_stream_protocol.py`：群聊流式事件协议。
- `test_group_chat_skill_script_cli_flow.py`：结构化目标专家字段触发 Skill 脚本，模型传 manifest `args` 字段，平台转换为 CLI 参数。

### 沙箱

- `test_sandbox_service.py`：用户级沙箱复用/重建/释放、固定资源策略、预热。
- `test_lifespan.py`：应用生命周期与启动预热开关。

### 会话与工作区 API

- `test_sessions_api.py`：会话新建/列表/详情/删除与 404。
- `test_workspace_files.py`：工作区文件增删改查、下载、上传、路径穿越防护、工具写入。
- `test_scenario_bundle.py`：场景包导出、导入和依赖收集。

### 其他核心配置

- `test_llm_config.py`：LLM 提供商配置解析与回退。
- `test_expert_self_awareness_prompt.py`：专家自我认知提示词拼装。
- `test_bundle_import_api.py`：资源包导入、依赖缺失预览与导入后资源落盘。

## 当前不在第一层的内容（刻意留空）

以下不是第一层目标（可在后续第二层/专项测试补）：

- 全量 HTTP 路由的系统性覆盖；
- 全部 tools 与全部 MCP 子模块的端到端覆盖；
- 强依赖外部环境的纯运行时路径（长链路、慢测、非确定性流程）。

## 如何新增测试并纳入第一层

1. 在 `backend/tests/` 新增 `test_xxx.py`；
2. 先确保 `pytest test_xxx.py` 通过；
3. 将 `test_xxx`（不含 `.py`）加入 `backend/tests/conftest.py` 的 `LAYER1_CORE_MODULES`；
4. 执行 `./scripts/test-layer1.sh` 验证汇总为 PASS。

## 推荐执行顺序

本地开发阶段：

1. 改动后先跑目标文件：`pytest tests/test_xxx.py -q`
2. 提交前跑第一层：`./scripts/test-layer1.sh`

合并前（建议）：

1. 后端全量：`cd backend && pytest`
2. 前端构建：`cd frontend && npm run build`
