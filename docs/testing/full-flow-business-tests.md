# 全流程业务测试汇总

本文面向测试人员和上线前自测，按“前端能看到、能操作”的功能面整理需求与自动化覆盖。

## 一条命令

在项目根目录执行：

```bash
./scripts/test-ui-flow.sh
```

通过标准：

- Playwright 自动启动 Vite；
- Chrome 打开真实 Vue 页面；
- 六组 `frontend/e2e/*.spec.ts` 全部通过；
- 脚本末尾 summary 中 `ui-flow` 为 `PASS`。

常用变体：

```bash
FRONTEND_INSTALL=skip ./scripts/test-ui-flow.sh
FRONTEND_INSTALL=always ./scripts/test-ui-flow.sh
```

默认 `FRONTEND_INSTALL=auto`：若 `frontend/node_modules` 已存在，只执行 `npm run test:e2e:full`；否则先 `npm ci` 再执行完整 UI 回归。

如果要同时跑后端全量测试和前端生产构建，仍使用：

```bash
./scripts/test-full-flow.sh
```

## UI 点击级自动化

浏览器级 UI 自动化放在 `frontend/e2e/`，使用 Playwright 打开真实 Vue 页面并点击用户能看到的入口。该层不直连真实后端、LLM、Docker 或 OpenSandbox；测试内通过路由拦截返回稳定 API 替身，目标是验证前端页面、路由守卫、按钮、输入框、侧栏入口和关键用户路径没有断。

执行方式：

```bash
./scripts/test-ui-flow.sh
```

前置条件：本机已安装 Google Chrome。当前配置使用 Chrome 通道运行，避免为普通应用工程下载 Playwright 自带 Chromium 缓存。

调试单个用例：

```bash
cd frontend
npm run test:e2e:full -- --headed e2e/workspace.spec.ts
```

当前点击级覆盖：

- `frontend/e2e/auth.spec.ts`：登录、注册与进入主工作台；
- `frontend/e2e/workspace.spec.ts`：新建会话、发送消息、成员管理、文件插入、场景快捷入口；
- `frontend/e2e/resources-scenario-expert.spec.ts`：资源中心场景配置、专家新建与保存；
- `frontend/e2e/resources-skill-mcp-llm.spec.ts`：技能详情、技能依赖、工具新建、模型参数保存；
- `frontend/e2e/settings.spec.ts`：全局设置、配色、环境变量、账号、安全和沙箱 requirements。

通过标准：Playwright `chrome` 项目全部通过，无控制台致命错误、无页面白屏、无找不到可见控件的失败。

## 需求与覆盖

| 前端功能面 | 用户可操作需求 | 自动化覆盖 |
| --- | --- | --- |
| 登录与账号 | 注册、登录、多用户隔离、修改账号、修改密码、非法账号拦截 | `tests/test_auth_sqlite.py`、`frontend/e2e/auth.spec.ts`、`frontend/e2e/settings.spec.ts` |
| 工作空间会话 | 新建会话、列表、详情、改名/更新、停止、删除、缺失会话 404 | `tests/test_sessions_api.py`、`tests/test_frontend_business_flows.py`、`frontend/e2e/workspace.spec.ts` |
| 对话流 | 在会话中发出问题并检查回答、非流式兜底、SSE 事件协议、route/content/message/end、停止/中断状态 | `tests/test_frontend_business_flows.py`、`tests/test_group_chat_stream_protocol.py`、`tests/test_group_chat_skill_script_cli_flow.py`、`tests/test_host_takeover.py`、`frontend/e2e/workspace.spec.ts` |
| 工作区文件 | 新建目录、新建文件、读取内容、更新内容、上传、下载、重命名/移动、删除、路径穿越防护 | `tests/test_workspace_files.py`、`tests/test_file_ref_and_gateway.py`、`tests/test_frontend_business_flows.py` |
| 文件引用 | `【文件引用：...】` 展开、路径提取、URL/远程路径替换为真实工作区文件 | `tests/test_file_ref_and_gateway.py` |
| 资源中心-场景 | 场景列表、保存、导出包、上传导入、导入冲突、同名覆盖 | `tests/test_scenario_bundle.py`、`tests/test_session_preset_validate.py`、`tests/test_bundle_import_api.py`、`tests/test_frontend_business_flows.py`、`frontend/e2e/resources-scenario-expert.spec.ts` |
| 资源中心-专家 | Agent/Expert 新建、列表、更新、删除、别名路由、导入校验、导出包逻辑 | `tests/test_agents_api.py`、`tests/test_agent_import_validate.py`、`tests/test_expert_bundle.py`、`tests/test_frontend_business_flows.py`、`frontend/e2e/resources-scenario-expert.spec.ts` |
| 资源中心-Skill | Skill 新建、编辑名称/描述/正文、`auto-tools`/依赖解析、内容读取、parts 文件增删改查、ZIP 导入导出基础链路 | `tests/test_skill_mcp_and_script_requirements.py`、`tests/test_group_chat_skill_script_cli_flow.py`、`tests/test_frontend_business_flows.py`、`frontend/e2e/resources-skill-mcp-llm.spec.ts` |
| Skill 脚本执行 | CLI-only 参数、`.py`/`.sh`/`.bash` 命令构造、沙箱路径、requirements 注入、工具成功后自然语言合成链路 | `tests/test_file_ref_and_gateway.py`、`tests/test_sandbox_service.py`、`tests/test_group_chat_skill_script_cli_flow.py` |
| 资源中心-MCP | MCP 新建、启用、禁用、更新、删除、工具参数归一、沙箱调用入口 | `tests/test_skill_mcp_and_script_requirements.py`、`tests/test_file_ref_and_gateway.py`、`tests/test_frontend_business_flows.py`、`frontend/e2e/resources-skill-mcp-llm.spec.ts` |
| 资源中心-LLM | Provider 配置白名单、模型参数、thinking/tool choice 兼容、默认 LLM 保存 | `tests/test_llm_config.py`、`tests/test_frontend_business_flows.py`、`frontend/e2e/resources-skill-mcp-llm.spec.ts` |
| 设置-主持人/应用 | 主持人 profile、默认 provider、LLM provider 保存与敏感字段隐藏 | `tests/test_llm_config.py`、`tests/test_frontend_business_flows.py`、`frontend/e2e/settings.spec.ts` |
| 设置-环境变量 | 环境变量新增、列表隐藏真实值、更新、删除 | `tests/test_frontend_business_flows.py`、`frontend/e2e/settings.spec.ts` |
| 设置-沙箱 | 镜像 variant 保存、requirements 保存/merge、用户级沙箱复用/重建、网络策略、预热去重 | `tests/test_sandbox_service.py`、`tests/test_frontend_business_flows.py`、`frontend/e2e/settings.spec.ts` |
| 编排与场景运行时 | 场景 runtime、专家 runtime、主持人接管、轮次状态机、need-user-input 合约 | `tests/test_scene_runtime.py`、`tests/test_expert_runtime.py`、`tests/test_group_orchestration_fsm.py`、`tests/test_orchestration_contracts.py` |
| 记忆与审计 | 群聊记忆注入、事实存储、旧版运行审计文件清理合同 | `tests/test_group_chat_group_memory.py`、`tests/test_group_memory_store.py`、`tests/test_group_chat_cleanup_contract.py` |
| 启动与生命周期 | FastAPI 生命周期、懒加载初始化、预热开关 | `tests/test_lifespan.py` |

## 聚合业务流

`tests/test_frontend_business_flows.py` 是专门给前端业务验收看的聚合测试：

- `test_frontend_workspace_session_and_file_flow`：串起会话新建/更新/停止/删除，以及工作区文件目录、文本、上传、移动、删除；
- `test_frontend_session_question_answer_flow`：新建问答 Skill 与专家，在会话里发出一个问题，检查返回答案、会话历史落盘与会话导出；
- `test_frontend_resource_center_and_settings_flow`：串起资源中心与设置页的主要 CRUD，包括场景、专家、Skill、Skill parts、MCP、LLM 设置、全局设置、环境变量、沙箱设置。

该文件会把真实 Docker/OpenSandbox 预热和 MCP 连接替换成测试替身，因此适合作为本地与 CI 的稳定业务链路门禁。底层沙箱复用、requirements 注入、脚本执行等真实行为仍由 `test_sandbox_service.py` 与 `test_group_chat_skill_script_cli_flow.py` 覆盖。

## 与 Layer-1 的区别

- `./scripts/test-layer1.sh`：快速门禁，跑 `pytest -m layer1_core` 加前端构建，适合频繁开发自测；
- `./scripts/test-full-flow.sh`：完整门禁，跑全部后端测试加前端构建，适合提测、上线前、迁移到新机器后的验收。
- `./scripts/test-ui-flow.sh`：用户可见 UI 点击门禁，跑六组 Playwright 用例，适合验收页面路径是否真的能点通。

新增前端可操作功能时，至少做三件事：

1. 在对应接口或运行时增加单点测试；
2. 如属于主流程，把场景补进 `tests/test_frontend_business_flows.py`；
3. 如用户必须通过页面点击完成，把场景补进 `frontend/e2e/`，优先用可见文本、label、role 定位控件；
4. 更新本文“需求与覆盖”表。
