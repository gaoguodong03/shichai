# 四类协作提示词模板实现计划

> **面向 AI 代理的工作者：** 在当前工作区内按 TDD 顺序执行；现有未提交改动属于用户，不能回退或覆盖。

**目标：** 将项目整体系统提示词、场景提示词、主持人长期提示词、专家长期提示词以及两类 Skill 模板收敛到已确认的职责边界，并让场景提示词作为会话快照持续进入主持人和专家调用。

**架构：** 用户可编辑长期模板由稳定 `prompt_id` 提供默认值并保存到现有配置字段；场景资源的 `system_prompt` 在建会话时复制为 `session.json.scenario_prompt`；主持人和专家运行时按“项目 → 场景 → 角色 → Skill → 本轮输入”组装。主持人 Skill 仅保留四列阶段表，专家 Skill 仅保留执行规则和结束条件。

**技术栈：** Python、Pydantic、FastAPI、Vue 3、TypeScript、JSON、Markdown、pytest、Playwright/Vitest 契约测试。

---

## 文件范围

- 创建或修改 `backend/app/agent/project_prompt.py`、`host_prompt.py`、`expert_prompt.py`、`session_prompt.py`：四类长期默认模板和共享会话 Prompt 访问入口。
- 修改 `backend/app/agent/platform_prompt_templates.json`：保存项目、主持人和专家可编辑默认模板；运行时模板只保留动态输入。
- 修改 `backend/app/agent/session_contracts.py`、`group_session_service.py`、`group_chat_runtime.py`、`group_chat_expert_turn.py`、`expert_runtime.py`：场景快照和角色 Prompt 注入。
- 修改 `frontend/src/features/settings/AppSettingsView.vue`、`frontend/src/features/resources/AgentView.vue`、场景编辑与建会话代码：展示职责明确的模板说明并传递 `scenario_prompt`。
- 修改 `docs/skills/host-skill.md`、`docs/skills/skill-standard.md`：两类 Skill 最小模板。
- 修改 `docs/contracts/prompt-assembly-contract.md`、`runtime-interface-contract.md`、`data-structure-and-field-logic.md`：字段、生命周期和组装顺序。
- 修改相关 pytest 与前端契约测试：保护默认模板、快照、注入顺序和 Skill 文档结构。

## 任务 1：锁定场景快照和共享 Prompt

- [ ] 运行 `rtk pytest -q backend/tests/test_group_chat_state.py backend/tests/test_platform_prompts.py backend/tests/test_expert_runtime.py backend/tests/test_host_takeover.py`，记录当前失败。
- [ ] 为场景建会话请求补充测试：`scenario.json.system_prompt` 必须作为 `scenario_prompt` 发送并写入 `session.json`。
- [ ] 为主持人、专家 Skill 选择和专家执行分别断言项目提示词只出现一次、场景提示词只出现一次，且项目在场景之前。
- [ ] 实现最少缺失代码并重新运行上述测试。

## 任务 2：专家长期提示词

- [ ] 在前端静态合同测试中断言 `DEFAULT_EXPERT_SYSTEM_PROMPT` 包含职责边界、专业标准、统一 JSON 和四种流程组合，不包含具体场景或 Skill 名称。
- [ ] 在专家资源或运行时测试中断言新建表单预填模板并保存原值；空 `agent.system_prompt` 在运行时保持为空，不做回退。
- [ ] 新建 `backend/app/agent/expert_prompt.py`，通过 `render_platform_prompt()` 返回默认模板并归一化专家长期提示词。
- [ ] 在专家 Skill 选择和执行组装中只注入一次专家长期提示词。
- [ ] 运行专家与 Prompt 定向测试，确认红灯转绿。

## 任务 3：主持人和专家 Skill 模板

- [ ] 在 `backend/tests/test_docs_contract_alignment.py` 或资源契约测试中新增失败断言：主持人 Skill 规范必须使用“决策前阶段 / 判定条件 / 本轮动作 / 决策后阶段”四列表，且不得保留旧多章节模板。
- [ ] 新增失败断言：专家 Skill 规范固定为“执行规则 + 结束条件”，结束条件包含等待用户、完成和可选失败，不再定义固定按需章节体系。
- [ ] 最小修改 `docs/skills/host-skill.md` 和 `docs/skills/skill-standard.md` 使契约通过。
- [ ] 迁移仓库内受当前测试覆盖的模板或示例资源，禁止批量改写 `backend/data/users` 中与本任务无关的数据。

## 任务 4：前端可用性

- [ ] 在前端契约测试中断言设置页说明项目提示词包含全局规则和工作区函数，主持人提示词说明纯调度与长期合同，专家提示词说明长期专业职责，场景提示词说明共享任务契约和会话快照。
- [ ] 更新对应标签、placeholder 或帮助文字；不增加新的配置包装字段。
- [ ] 确认从场景创建或复用空白会话时都发送 `scenario_prompt`。
- [ ] 运行前端定向测试和 TypeScript 构建。

## 任务 5：正式契约同步

- [ ] 更新 Prompt 组装契约中的字段来源、默认模板、注入顺序和角色边界。
- [ ] 更新会话字段契约，确认 `session.json.scenario_prompt` 是创建时快照，既有会话不回读场景资源。
- [ ] 更新数据结构文档和测试索引，删除与新模板冲突的旧表述。
- [ ] 对设计和契约执行占位符、矛盾、范围和旧术语扫描。

## 任务 6：验证

- [ ] 运行后端提示词、会话、主持人、专家和文档契约测试。
- [ ] 运行受影响前端测试和构建。
- [ ] 运行 `rtk git diff --check`。
- [ ] 核对 `rtk git diff --stat` 和逐文件差异，确认没有覆盖用户其他未提交改动。
