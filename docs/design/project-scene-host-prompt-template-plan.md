# 项目、场景与主持人提示词模板实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 将已确认的项目系统提示词、场景共享提示词快照、主持人长期提示词和四列表主持人 Skill 落入当前严格运行合同。

**架构：** `scenario.json.system_prompt` 在创建或复用会话时复制为 `session.json.scenario_prompt`；项目提示词与场景快照通过一个纯函数组成共享系统提示词，同时进入主持人调度、专家 Skill 选择和专家执行。主持人长期提示词成为账号/场景主持人可编辑的默认文本，主持人 Skill 正文只描述四列表阶段流程。

**技术栈：** Python、Pydantic、FastAPI、Vue 3、TypeScript、JSON、pytest。

---

## 文件范围

- 创建：`backend/app/agent/session_prompt.py`，读取场景快照并组装项目与场景共享提示词。
- 修改：`backend/app/agent/session_contracts.py`，允许创建和更新会话携带 `scenario_prompt`。
- 修改：`backend/app/agent/group_session_service.py`，保存和更新场景提示词快照。
- 修改：`backend/app/api/group_chat_state.py`，把 `scenario_prompt` 纳入 `session.json` 与 API payload。
- 修改：`backend/app/api/sessions.py`，把创建请求中的场景快照交给服务层。
- 修改：`backend/app/agent/group_chat_runtime.py`，主持人调用使用项目与场景共享提示词。
- 修改：`backend/app/agent/group_chat_expert_turn.py`、`backend/app/agent/expert_runtime.py`，专家选择和执行均使用同一场景快照。
- 修改：`backend/app/agent/platform_prompt_templates.json`，加入主持人长期默认提示词并收敛主持人运行时输入模板。
- 修改：`backend/app/api/settings_app.py`，账号默认主持人使用长期提示词模板。
- 修改：`frontend/src/features/workspace/composables/useShortcutPresets.ts`，场景创建/复用会话时发送 `scenario_prompt` 快照。
- 修改：`frontend/src/features/settings/AppSettingsView.vue`、`frontend/src/views/MainView.vue`，明确三类提示词的职责和默认模板用途。
- 修改：`docs/skills/host-skill.md`，主持人 Skill 正文收敛成四列表。
- 修改：`docs/contracts/prompt-assembly-contract.md`、`docs/contracts/runtime-interface-contract.md`、`docs/contracts/data-structure-and-field-logic.md`，同步字段和 Prompt 组装合同。
- 测试：`backend/tests/test_group_chat_state.py`、`backend/tests/test_sessions_api.py`、`backend/tests/test_platform_prompts.py`、`backend/tests/test_host_takeover.py`、`backend/tests/test_expert_runtime.py`、`backend/tests/test_frontend_route_and_context_contracts.py`、`backend/tests/test_docs_contract_alignment.py`。

## 任务 1：建立场景快照与共享 Prompt 的失败测试

- [ ] 在 `backend/tests/test_group_chat_state.py` 增加测试：`scenario_prompt` 能写入并读回 `session.json`，未允许的旧字段仍被清理。
- [ ] 在 `backend/tests/test_sessions_api.py` 增加测试：`POST /api/sessions` 接收 `scenario_prompt` 并返回相同快照；`PUT` 更新空白复用会话时替换快照。
- [ ] 在 `backend/tests/test_platform_prompts.py` 增加纯函数测试，断言项目提示词在前、场景提示词在后，各出现一次，空场景不产生多余块。
- [ ] 运行以上定向测试并确认因字段被过滤、函数不存在而失败。

## 任务 2：实现会话场景 Prompt 快照

- [ ] 创建 `backend/app/agent/session_prompt.py`，实现 `get_session_scenario_prompt(session_item)` 与 `build_shared_session_prompt(app_settings, session_item)`。
- [ ] 为 `SessionCreateRequest` 增加默认空字符串 `scenario_prompt`，为 `SessionUpdateRequest` 增加可选 `scenario_prompt`。
- [ ] 让 `create_session_internal()` 保存场景快照，让 `update_group_session()` 在明确传入时更新快照并清理主持人阶段状态。
- [ ] 让 `_clean_session_definition()` 和 `build_session_payload()`保留并返回 `scenario_prompt`。
- [ ] 运行任务 1 测试并确认通过。

## 任务 3：把场景快照注入主持人和专家

- [ ] 在 `backend/tests/test_host_takeover.py` 修改主持人 Prompt 测试，传入 `scenario_prompt` 并断言顺序为项目提示词、场景提示词、主持人长期提示词、主持人 Skill。
- [ ] 在 `backend/tests/test_expert_runtime.py` 增加专家 Skill 选择和执行测试，断言场景提示词与项目提示词均进入系统消息且各出现一次。
- [ ] 运行定向测试并确认场景提示词缺失导致失败。
- [ ] 在 `group_chat_runtime.py` 和 `group_chat_expert_turn.py` 使用 `build_shared_session_prompt()`。
- [ ] 在 `expert_runtime.py` 让多 Skill 选择复用传入的共享系统提示词，不再独立重读项目提示词。
- [ ] 运行主持人和专家定向测试并确认通过。

## 任务 4：建立主持人前端创建模板并删除后端兜底

- [ ] 在前端静态合同测试中断言 `DEFAULT_HOST_SYSTEM_PROMPT` 包含纯调度边界、四列表读取规则和当前 JSON 字段，不包含具体阶段或专家名称。
- [ ] 在 `backend/tests/test_host_takeover.py` 调整装配断言：主持人长期提示词承担通用边界，运行时模板只承载本轮变量，不重复第二份主持人职责。
- [ ] 在 `resourceSystemPromptDefaults.ts` 增加 `DEFAULT_HOST_SYSTEM_PROMPT`；将 `host.select_next_speaker.v1` 收敛为本轮可选专家、阶段、用户输入、最近讨论和 Skill Session 数据块。
- [ ] 从主持人系统消息装配中移除重复的 `host.system.boundary.v1`，保留严格协议重试提示。
- [ ] 删除主持人 defaults/reset 接口和运行时空值回退；设置页与场景创建表单直接预填前端模板，保存时传原值。
- [ ] 运行平台 Prompt、设置和主持人测试并确认通过。

## 任务 5：让前端保存场景快照并解释模板职责

- [ ] 在 `backend/tests/test_frontend_route_and_context_contracts.py` 先增加失败断言：场景会话请求发送 `scenario_prompt: p.system_prompt`；设置页和场景页文案分别说明项目、场景、主持人长期职责。
- [ ] 修改 `useShortcutPresets.ts`，创建或复用会话时发送规范化的 `scenario_prompt`。
- [ ] 修改设置页项目提示词和主持人提示词的标签、说明与占位文案；不把完整默认提示词复制到 Vue 文件。
- [ ] 修改场景编辑器文案，明确场景提示词会形成会话快照并共享给主持人和专家；主持人字段改称“主持人长期提示词”。
- [ ] 运行前端静态合同测试并确认通过。

## 任务 6：把主持人 Skill 收敛为四列表

- [ ] 在 `backend/tests/test_docs_contract_alignment.py` 先增加失败测试，断言 `docs/skills/host-skill.md` 只定义“决策前阶段、判定条件、本轮动作、决策后阶段”四列，不再要求多章节正文和七列阶段表。
- [ ] 重写 `docs/skills/host-skill.md`：平台/长期提示词边界保持简短，通用模板只保留 Frontmatter、标题和四列表。
- [ ] 同步 Prompt、会话字段和数据结构合同中的 `scenario_prompt`、主持人长期提示词和四列表职责。
- [ ] 运行文档合同测试并确认通过。

## 任务 7：回归验证

- [ ] 运行场景快照、主持人、专家、平台 Prompt、前端静态合同和文档合同定向测试。
- [ ] 运行 Layer 1 核心回归集合。
- [ ] 运行前端类型检查或构建。
- [ ] 运行 `rtk git diff --check`。
- [ ] 审查最终 diff，确认未修改 `backend/data/users`，未覆盖用户其他工作区改动，专家提示词保持不变。
