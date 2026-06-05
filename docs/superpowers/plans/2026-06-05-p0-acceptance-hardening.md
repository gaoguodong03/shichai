# P0 验收补强实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 完成工程任务拆分中 6 个 `ready` P0 批次：T-UR01-02、T-UR02-02、T-UR03-01、T-UR05-01、T-UR06-01、T-UR07-01，并保留自动化验收入口。

**架构：** 每个批次先读对应 UR、详细设计和现有测试，再用 TDD 补齐缺口，最后做最小代码变更。批次之间尽量按边界提交，避免把认证、会话、调度、Skill、MCP、沙箱改动混成一个不可审查补丁。

**技术栈：** FastAPI/Python 后端、pytest、Vue 3/TypeScript 前端、Playwright E2E、OpenSandbox 相关服务。

---

## 文件结构

- 修改：`backend/app/core/user_context.py`、`backend/app/core/user_settings_paths.py`、`backend/app/core/resource_store.py`
  - 负责当前用户资源根、资源路径派生和跨用户路径隔离。
- 修改：`backend/app/api/sessions.py`、`frontend/src/features/workspace/WorkspaceContent.vue`、`frontend/src/features/workspace/components/group-chat/GroupChatStatusBars.vue`
  - 负责会话刷新恢复、状态提示和前端可见状态条。
- 修改：`backend/app/agent/leader_scheduler.py`、`backend/app/core/scene_scheduler.py`、`backend/app/agent/group_host_decision.py`
  - 负责普通会话、场景会话和 `@专家` 路由边界。
- 修改：`backend/app/skills/loader.py`、`backend/app/agent/skill_session_contract.py`、`frontend/src/features/resources/SkillDetailView.vue`
  - 负责 Skill 契约校验、依赖提示和资源中心展示。
- 修改：`backend/app/mcp/manager.py`、`backend/app/mcp/tool_arg_normalizers.py`、`backend/app/agent/tool_gateway.py`
  - 负责 MCP 工具权限过滤、参数归一化和错误诊断。
- 修改：`backend/app/api/sandbox_settings.py`、`backend/app/agent/sandbox_service.py`、`backend/app/agent/sandbox_policy_runtime.py`
  - 负责沙箱版本、依赖安装、网络策略和错误诊断。

## 任务 1：T-UR01-02 用户资源路径隔离回归

**文件：**
- 修改：`backend/app/core/user_context.py`
- 修改：`backend/app/core/user_settings_paths.py`
- 修改：`backend/app/core/resource_store.py`
- 测试：`backend/tests/test_user_resource_paths.py`
- 测试：`backend/tests/test_workspace_files.py`

- [ ] **步骤 1：读取需求和现有测试**
  - 阅读 `docs/requirements/user-requirements.md` 的 UR-01、UR-04、UR-08。
  - 阅读 `docs/architecture/detailed-design.md` 中用户与资源根、工作区文件边界。
  - 阅读 `backend/tests/test_user_resource_paths.py` 和 `backend/tests/test_workspace_files.py`。

- [ ] **步骤 2：编写或确认失败测试**
  - 若测试缺少某类资源路径从当前用户根目录派生的覆盖，新增一个最小测试。
  - 若测试缺少路径穿越或跨用户访问拒绝覆盖，新增一个最小测试。
  - 运行：`rtk conda run --no-capture-output -n st49 python -m pytest backend/tests/test_user_resource_paths.py backend/tests/test_workspace_files.py -q`
  - 预期：新增测试在实现前失败，或现有覆盖已足够且全部通过。

- [ ] **步骤 3：最小实现**
  - 只修正用户资源路径派生、路径归一化或拒绝逻辑。
  - 不迁移历史数据，不重写资源目录结构。

- [ ] **步骤 4：验证**
  - 运行：`rtk conda run --no-capture-output -n st49 python -m pytest backend/tests/test_user_resource_paths.py backend/tests/test_workspace_files.py -q`
  - 运行：`rtk ./scripts/test-layer1.sh`

- [ ] **步骤 5：提交**
  - `rtk git add backend/app/core/user_context.py backend/app/core/user_settings_paths.py backend/app/core/resource_store.py backend/tests/test_user_resource_paths.py backend/tests/test_workspace_files.py`
  - `rtk git commit -m "test: 补强用户资源路径隔离回归"`

## 任务 2：T-UR02-02 工作区刷新恢复和状态提示

**文件：**
- 修改：`frontend/src/features/workspace/WorkspaceContent.vue`
- 修改：`frontend/src/features/workspace/components/group-chat/GroupChatStatusBars.vue`
- 修改：`backend/app/api/sessions.py`
- 测试：`frontend/e2e/workspace.spec.ts`
- 测试：`backend/tests/test_sessions_api.py`

- [ ] **步骤 1：读取需求和现有测试**
  - 阅读 UR-02、UR-08。
  - 阅读 `frontend/e2e/workspace.spec.ts` 中刷新、成员、文件和运行状态用例。
  - 阅读 `backend/tests/test_sessions_api.py` 中会话详情和删除后发送契约。

- [ ] **步骤 2：编写或确认失败测试**
  - 补齐刷新后消息、成员、文件、等待用户、工具失败或轮次上限可见提示中的缺口。
  - 运行目标 E2E 或后端单测，确认失败或确认已有覆盖。

- [ ] **步骤 3：最小实现**
  - 修正会话详情返回字段或前端状态条展示逻辑。
  - 不改动群聊协议格式，除非测试证明后端缺字段。

- [ ] **步骤 4：验证**
  - `rtk conda run --no-capture-output -n st49 python -m pytest backend/tests/test_sessions_api.py -q`
  - `rtk proxy npm --prefix frontend run test:e2e:full -- e2e/workspace.spec.ts`
  - `rtk ./scripts/test-layer1.sh`

- [ ] **步骤 5：提交**
  - 窄暂存本任务涉及文件。
  - `rtk git commit -m "fix: 补强工作区刷新恢复状态提示"`

## 任务 3：T-UR03-01 普通会话和场景会话调度边界

**文件：**
- 修改：`backend/app/agent/leader_scheduler.py`
- 修改：`backend/app/core/scene_scheduler.py`
- 修改：`backend/app/agent/group_host_decision.py`
- 测试：`backend/tests/test_scene_scheduler.py`
- 测试：`backend/tests/test_group_host_decision.py`
- 测试：`backend/tests/test_host_takeover.py`

- [ ] **步骤 1：读取需求和现有测试**
  - 阅读 UR-03。
  - 阅读现有调度、场景调度和 host takeover 测试。

- [ ] **步骤 2：编写或确认失败测试**
  - 覆盖普通会话可推荐专家、场景会话只使用场景内专家、`@专家` 优先。

- [ ] **步骤 3：最小实现**
  - 修正调度边界，不改变主持人消息可见性契约。

- [ ] **步骤 4：验证**
  - `rtk conda run --no-capture-output -n st49 python -m pytest backend/tests/test_scene_scheduler.py backend/tests/test_group_host_decision.py backend/tests/test_host_takeover.py -q`
  - `rtk ./scripts/test-layer1.sh`

- [ ] **步骤 5：提交**
  - `rtk git commit -m "fix: 收紧会话调度边界"`

## 任务 4：T-UR05-01 Skill 契约校验和依赖提示

**文件：**
- 修改：`backend/app/skills/loader.py`
- 修改：`backend/app/agent/skill_session_contract.py`
- 修改：`frontend/src/features/resources/SkillDetailView.vue`
- 测试：`backend/tests/test_skill_mcp_and_script_requirements.py`
- 测试：`backend/tests/test_skill_agent_tool_resolution.py`

- [ ] **步骤 1：读取需求和现有测试**
  - 阅读 UR-05、UR-07 和 `docs/skills/skill-standard.md` 的契约要求。

- [ ] **步骤 2：编写或确认失败测试**
  - 覆盖缺失 `SKILL.md`、frontmatter 非法、requirements 缺失或沙箱版本不匹配诊断。

- [ ] **步骤 3：最小实现**
  - 在 loader 或契约层返回结构化诊断；前端只展示已有诊断，不新增复杂编辑流程。

- [ ] **步骤 4：验证**
  - `rtk conda run --no-capture-output -n st49 python -m pytest backend/tests/test_skill_mcp_and_script_requirements.py backend/tests/test_skill_agent_tool_resolution.py -q`
  - `rtk ./scripts/test-layer1.sh`

- [ ] **步骤 5：提交**
  - `rtk git commit -m "fix: 补强 Skill 契约依赖诊断"`

## 任务 5：T-UR06-01 MCP 工具权限和错误诊断

**文件：**
- 修改：`backend/app/mcp/manager.py`
- 修改：`backend/app/mcp/tool_arg_normalizers.py`
- 修改：`backend/app/agent/tool_gateway.py`
- 测试：`backend/tests/test_skill_agent_tool_resolution.py`
- 测试：`backend/tests/test_file_ref_and_gateway.py`

- [ ] **步骤 1：读取需求和现有测试**
  - 阅读 UR-06。
  - 阅读 MCP manager、工具解析和 gateway 测试。

- [ ] **步骤 2：编写或确认失败测试**
  - 覆盖未授权 MCP 不进工具集，以及断连、鉴权失败、参数错误包含 server/tool 维度诊断。

- [ ] **步骤 3：最小实现**
  - 修正权限过滤或错误消息组装；不改变现有 MCP 配置格式。

- [ ] **步骤 4：验证**
  - `rtk conda run --no-capture-output -n st49 python -m pytest backend/tests/test_skill_agent_tool_resolution.py backend/tests/test_file_ref_and_gateway.py -q`
  - `rtk ./scripts/test-layer1.sh`

- [ ] **步骤 5：提交**
  - `rtk git commit -m "fix: 补强 MCP 权限和错误诊断"`

## 任务 6：T-UR07-01 沙箱镜像、依赖和网络策略回归

**文件：**
- 修改：`backend/app/api/sandbox_settings.py`
- 修改：`backend/app/agent/sandbox_service.py`
- 修改：`backend/app/agent/sandbox_policy_runtime.py`
- 测试：`backend/tests/test_sandbox_service.py`
- 测试：`backend/tests/test_sandbox_policy_runtime.py`
- 测试：`backend/tests/test_sandbox_requirements_runtime.py`

- [ ] **步骤 1：读取需求和现有测试**
  - 阅读 UR-07、UR-11 和沙箱相关测试。

- [ ] **步骤 2：编写或确认失败测试**
  - 覆盖普通/Playwright 版保存、默认禁网策略、冷启动/依赖/超时/工具不可用诊断。

- [ ] **步骤 3：最小实现**
  - 修正沙箱设置读取、策略判定或错误诊断；不改部署默认镜像策略。

- [ ] **步骤 4：验证**
  - `rtk conda run --no-capture-output -n st49 python -m pytest backend/tests/test_sandbox_service.py backend/tests/test_sandbox_policy_runtime.py backend/tests/test_sandbox_requirements_runtime.py -q`
  - `rtk ./scripts/test-layer1.sh`

- [ ] **步骤 5：提交**
  - `rtk git commit -m "fix: 补强沙箱策略诊断回归"`

## 最终验收

- [ ] 运行：`rtk ./scripts/test-layer1.sh`
- [ ] 运行：`rtk ./scripts/test-ui-flow.sh`
- [ ] 运行：`rtk proxy npm --prefix frontend run build`
- [ ] 检查：`rtk git status --short`
- [ ] 汇总每个批次的测试证据和剩余手工验收项。
