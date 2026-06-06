# 书童四九测试用例目录

## 1. 文档目的

本文沉淀可复用测试用例，承接 [用户需求文档](../requirements/user-requirements.md)、[验收测试矩阵](../requirements/acceptance-and-tests.md) 和 [工程任务拆分](../project/implementation-task-breakdown.md)。

测试用例编号格式为 `TC-URxx-nn`。自动化测试优先落到 `backend/tests/` 和 `frontend/e2e/`；无法稳定自动化的用例进入上线前手工验收。

## 2. 执行分层

| 层级 | 目标 | 命令或入口 |
|------|------|------------|
| 后端定向测试 | 验证 API、编排、沙箱、导入导出和文件契约 | `rtk conda run -n st49 pytest backend/tests/test_sessions_api.py -q` |
| 前端构建 | 验证路由、组件、类型和打包引用 | `rtk proxy npm --prefix frontend run build` |
| E2E | 验证登录、工作区、资源中心和设置页面 | `rtk proxy npm --prefix frontend run test:e2e` |
| 第一层回归 | 合并前最低回归门槛 | `rtk ./scripts/test-layer1.sh` |
| 手工验收 | 覆盖沙箱、外部 MCP、真实模型和部署环境 | `docs/testing/pre-release-testing.md` |

## 3. 用例目录

| 用例 | 需求 | 类型 | 前置条件 | 操作 | 期望结果 | 自动化入口 |
|------|------|------|----------|------|----------|------------|
| TC-UR01-01 | UR-01 | API | 未登录 | 请求受保护 API | 返回 401，不返回用户数据 | `backend/tests/test_auth_sqlite.py` |
| TC-UR01-02 | UR-01 | E2E | 未登录 | 访问 `/workspace` | 跳转 `/login?redirect=...` | `frontend/e2e/auth.spec.ts` |
| TC-UR01-03 | UR-01 | API | A、B 两个账号 | A 请求 B 的会话或文件 | 请求被拒绝或返回不存在 | `backend/tests/test_sessions_api.py`、`backend/tests/test_workspace_files.py` |
| TC-UR01-04 | UR-01 | API | 已登录 | 刷新页面后继续请求当前用户接口 | 登录态保持，用户上下文不丢失 | `backend/tests/test_auth_sqlite.py` |
| TC-UR02-01 | UR-02 | API | 已登录 | `POST /api/sessions` 创建会话 | 返回唯一 `session_id` 并出现在列表 | `backend/tests/test_sessions_api.py` |
| TC-UR02-02 | UR-02 | API/E2E | 已有会话 | 发送消息并读取 SSE | 前端收到增量、完整消息和结束事件 | `backend/tests/test_group_chat_stream_protocol.py`、`frontend/e2e/workspace.spec.ts` |
| TC-UR02-03 | UR-02 | E2E | 会话含消息和文件 | 刷新工作区页面 | 历史、成员、文件和状态恢复 | `frontend/e2e/workspace.spec.ts` |
| TC-UR02-04 | UR-02 | API | 已有会话 | 删除会话后继续发消息 | 列表不再显示，后续发送被拒绝 | `backend/tests/test_sessions_api.py` |
| TC-UR03-01 | UR-03 | API | 普通会话无专家 | 用户提出复杂任务 | 主持人推荐可邀请专家 | `backend/tests/test_group_host_decision.py` |
| TC-UR03-02 | UR-03 | API | 场景会话有固定专家 | 用户发起场景任务 | 调度只使用场景内专家 | `backend/tests/test_scene_scheduler.py` |
| TC-UR03-03 | UR-03 | API/E2E | 会话有多个专家 | 用户 `@专家` 发消息 | 被点名专家优先响应 | `backend/tests/test_host_takeover.py`、`frontend/e2e/workspace.spec.ts` |
| TC-UR03-04 | UR-03 | API | 专家需要补充字段 | 专家返回补充请求 | 会话进入等待用户状态 | `backend/tests/test_group_orchestration_fsm.py` |
| TC-UR04-01 | UR-04 | API/E2E | 已登录 | 新建、编辑、删除专家 | 列表和详情同步更新 | `backend/tests/test_dha_api.py`、`frontend/e2e/resources-scenario-expert.spec.ts` |
| TC-UR04-02 | UR-04 | E2E | 已登录 | 编辑 Skill 的 `SKILL.md` 和脚本 | 保存后详情页展示最新内容 | `frontend/e2e/resources-skill-mcp-llm.spec.ts` |
| TC-UR04-03 | UR-04 | API/E2E | 已登录 | 新增 MCP 和模型配置 | 资源中心展示配置，专家可引用授权项 | `backend/tests/test_llm_config.py`、`frontend/e2e/resources-skill-mcp-llm.spec.ts` |
| TC-UR05-01 | UR-05 | API | 专家绑定 Skill | 用户请求触发 Skill | runtime 选择对应 Skill 并组装工具 | `backend/tests/test_skill_agent_tool_resolution.py` |
| TC-UR05-02 | UR-05 | API | Skill 声明脚本 | 执行脚本工具 | 输出、错误、超时能回传会话 | `backend/tests/test_group_chat_skill_script_cli_flow.py` |
| TC-UR05-03 | UR-05 | API | Skill 依赖缺失 | 触发需要依赖的脚本 | 返回 requirements 或沙箱版本诊断 | `backend/tests/test_skill_mcp_and_script_requirements.py` |
| TC-UR06-01 | UR-06 | API | 专家未授权某 MCP | 询问需要该 MCP 的任务 | 未授权工具不进入工具列表 | `backend/tests/test_skill_agent_tool_resolution.py` |
| TC-UR06-02 | UR-06 | API | MCP 配置错误 | 调用 MCP 工具 | 返回连接、鉴权或参数维度错误 | `backend/tests/test_file_ref_and_gateway.py` |
| TC-UR06-03 | UR-06 | E2E | 配置远程 MCP 密钥 | 查看配置详情 | 前端不展示完整密钥 | `frontend/e2e/resources-skill-mcp-llm.spec.ts` |
| TC-UR07-01 | UR-07 | API | 已登录 | 保存普通版或 Playwright 版沙箱 | 新会话读取对应沙箱版本 | `backend/tests/test_sandbox_service.py` |
| TC-UR07-02 | UR-07 | API | 默认禁网策略 | 脚本尝试未授权网络访问 | 请求被拦截并返回诊断 | `backend/tests/test_sandbox_policy_runtime.py` |
| TC-UR07-03 | UR-07 | API | requirements 变化 | 安装依赖并执行脚本 | 依赖状态可追踪，失败可诊断 | `backend/tests/test_sandbox_requirements_runtime.py` |
| TC-UR08-01 | UR-08 | API/E2E | 工作区已有文件 | 上传、预览、编辑、保存、下载 | 内容正确，操作后列表刷新 | `backend/tests/test_workspace_files.py`、`frontend/e2e/workspace.spec.ts` |
| TC-UR08-02 | UR-08 | API | 恶意路径 `../` | 请求读取工作区外文件 | 返回拒绝，不泄露路径内容 | `backend/tests/test_file_ref_and_gateway.py` |
| TC-UR08-03 | UR-08 | API | 专家生成文件 | 工具写入当前工作区 | 新文件出现在对应会话文件列表 | `backend/tests/test_sandbox_workspace_fs.py` |
| TC-UR09-01 | UR-09 | API/E2E | 有场景资源包 | 导入前预览 | 展示对象、依赖、缺失引用、同名冲突和覆盖/重映射项 | `backend/tests/test_bundle_import_api.py`、`frontend/e2e/resources-scenario-expert.spec.ts` |
| TC-UR09-02 | UR-09 | API | ZIP 结构错误 | 上传导入 | 返回明确结构错误 | `backend/tests/test_scenario_bundle.py` |
| TC-UR09-03 | UR-09 | API | 专家资源包 | 导入专家包 | 专家、Skill 和工具引用按规则落库 | `backend/tests/test_expert_bundle.py` |
| TC-UR10-01 | UR-10 | API/E2E | 已登录 | 保存模型、API Key 和默认主持人 | 新会话可引用最新配置，设置响应和前端均不泄露完整 Key | `backend/tests/test_llm_config.py`、`backend/tests/test_sessions_api.py`、`backend/tests/test_frontend_business_flows.py`、`frontend/e2e/settings.spec.ts` |
| TC-UR10-02 | UR-10 | E2E | 已登录 | 切换主题后刷新 | 主题保持 | `frontend/e2e/settings.spec.ts` |
| TC-UR10-03 | UR-10 | API/E2E | 已登录 | 修改密码或账号安全项 | 保存反馈明确，错误不触发误登出 | `backend/tests/test_auth_sqlite.py`、`frontend/e2e/settings.spec.ts` |
| TC-UR11-01 | UR-11 | API | 后端启动 | 请求 `/health` | 返回 `{ "status": "ok" }` | `backend/tests/test_lifespan.py` |
| TC-UR11-02 | UR-11 | API | `STATIC_DIR` 存在 | 请求根路径和非 API 路由 | 返回前端入口和 SPA fallback | `backend/tests/test_static_spa.py` |
| TC-UR11-03 | UR-11 | 脚本 | 准备 1Panel 打包 | 运行打包测试 | 包内不含本地输出、缓存、认证库和本地密钥 | `backend/tests/test_pack_1panel_backup.py` |

## 4. 新增测试规则

新增测试用例时必须同步：

1. 若新增用户需求，先更新 `docs/requirements/user-requirements.md`。
2. 若调整验收口径，更新 `docs/requirements/acceptance-and-tests.md`。
3. 若新增模块任务，更新 `docs/project/implementation-task-breakdown.md`。
4. 若新增自动化测试文件，更新本文对应用例的“自动化入口”。
5. 若只能手工验收，写入 `docs/testing/pre-release-testing.md` 的对应模块。

## 5. 合并前最低检查

每次涉及 P0/P1 行为变更，至少执行：

```bash
rtk proxy git diff --check -- docs backend frontend
rtk ./scripts/test-layer1.sh
```

只改文档且未触及代码时，至少执行：

```bash
rtk proxy git diff --check -- docs
```
