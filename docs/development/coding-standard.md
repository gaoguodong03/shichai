# 代码书写规范

本文面向在书童四九项目中写代码的人和 AI 编程代理。目标是把字段、业务逻辑和文件职责收敛到同一套契约，避免再次出现同一条业务逻辑多套字段、多处实现和反复兜底。

## 1. 总原则

1. 契约先于代码。字段、接口、运行态、Prompt 输出和落盘结构先看 `docs/contracts/`，代码只能实现契约，不能在实现里私自新增口径。
2. 主路径不做旧字段兜底。历史数据兼容只能通过明确的数据迁移、一次性清理脚本或离线修复处理，不能写进运行时分支。
3. 单一事实源。消息事实只看 `history.json`，运行镜像只看 `runtime.json`，跨轮编排只看 `orchestration_state.json`，会话定义只看 `session.json`。
4. 字段有生产方、消费方和生命周期。新增字段前必须能回答：谁写、谁读、保存多久、是否进入 API、是否进入 LLM。
5. 失败要显式。非法请求、非法主持人 JSON、非法 Skill stdout 和缺失资源都应按协议失败或等待用户，不静默猜测。
6. Mock 和测试是契约的一部分。`frontend/e2e/fixtures/mockApi.ts` 不得使用旧字段维持旧前端逻辑。

## 2. 文档阅读顺序

改字段、路由或运行逻辑前，按顺序阅读：

1. `docs/README.md`
2. `docs/documentation-standard.md`
3. `docs/contracts/runtime-interface-contract.md`
4. `docs/contracts/data-structure-and-field-logic.md`
5. `docs/contracts/prompt-assembly-contract.md`
6. `docs/design/interface-document.md`
7. `docs/design/detailed-design-spec.md`
8. `docs/development/module-file-boundaries.md`

如果这些文档之间冲突，以 `docs/contracts/` 为当前目标契约；随后必须同步修正 `docs/design/`、`docs/testing/`、mock 和代码，不允许让冲突长期存在。

## 3. 字段和数据结构

### 3.1 命名规则

- 后端文件、函数和变量使用 `snake_case`。
- Python 类、Pydantic 模型和异常类使用 `PascalCase`。
- 常量使用 `UPPER_SNAKE_CASE`。
- 前端组合式函数使用 `useXxx`，类型使用 `PascalCase`，普通变量和函数使用 `camelCase`。
- 资源身份字段按契约固定：专家用 `name`，Skill 用 `directory_name`，工具用 `name`，模型用 `name`，会话用 `session_id`。

### 3.2 禁止新增的旧字段

新代码、测试、mock、示例和文档不得新增以下字段或把它们作为运行时依据：

- 会话旧字段：`leader`、`leader_agent_name`、`host_config`、`scenario_name`、`orchestration_profile`、`meta.json`、`chat.md`、`history.md`。
- 请求旧字段：`action`、`host_takeover_requested`、`ignore_auto_agent_name`、`ignore_auto_skill`、`agent_name`、`next_speaker`。
- 路由旧字段：`speaker_task`、`reason`、`invite`、`next_prompt`、`handoff_reason`、`resume_target_agent_name`、`pending_*`。
- 消息旧字段：顶层 `role`、顶层 `content`、顶层 `agent_name`、顶层 `skill`、`timestamp`、`turn_id`、`debug`、`required_user_fields`、`tool_results`、`tool_debug`、`tool_raw_results`。
- SSE 旧字段和事件：`meta.phase`、`discussion_ended`、`tool_start`、`tool_result`、`session_update`、`skill_route_debug`、`expert_route_debug`。
- 资源旧字段：`agent_id`、`agent_ids`、`skill_id`、`skill_names`、`folder_name`、模型展示用 `label`。

发现上述字段仍在运行时代码中出现时，默认处理方式是删除旧分支，并按契约补测试。只有数据迁移脚本可以读取旧字段，且脚本必须与主运行时隔离。

### 3.3 严格结构

所有进入主路径的结构化边界必须有显式 schema：

- FastAPI 请求体和响应体使用 Pydantic 模型，设置 `extra="forbid"` 或等价的多余字段拒绝策略。
- LLM 结构化输出使用独立 schema 解析，不允许从自然语言中正则猜字段。
- Skill 脚本 stdout 必须先解析为严格对象，再转换成消息和运行态。
- 前端 API 层先定义 TypeScript 类型，再进入组件和 composable。

禁止在多个调用点复制字段清洗逻辑。字段归一化、严格解析和视图转换应集中在专门模块。

## 4. 业务逻辑写法

### 4.1 API 入口保持薄

`backend/app/api/*.py` 只负责鉴权、请求模型、HTTP 状态码和调用服务。它不承载主持人调度、专家路由、Skill 选择、Prompt 拼接、工具组装或会话状态推导。

当 API 文件开始出现以下内容时，应拆到 `agent/`、`core/`、`session_state/` 或 `tools/`：

- 多步骤业务状态机。
- LLM Prompt 拼接。
- 旧字段兼容和结构转换。
- 文件系统扫描和持久化事务。
- 工具权限、工具 schema 或工具返回处理。

### 4.2 运行时只保留一条主链路

群聊运行时以 `group_chat_runtime.py` 为编排入口，但具体职责必须外拆：

- 请求校验和附件解析进入独立解析模块。
- 主持人 JSON 解析进入主持人决策模块。
- 路由优先级进入 FSM 模块。
- 专家运行准备进入专家运行时模块。
- Prompt 组装进入 Prompt builder。
- 工具组装进入工具模块。
- Skill 会话状态进入 Skill session 模块。
- SSE 事件构造进入 streaming 模块。
- 历史和运行态写入进入状态服务。

如果一个函数同时读写文件、解析 LLM 输出、构造 Prompt、组装工具并生成 SSE，它已经越界，必须拆分。

### 4.3 不写反复兜底

禁止以下写法：

```python
value = data.get("agent_names") or data.get("agent_ids") or data.get("agents") or []
```

应改为：

```python
agent_names = validate_agent_names(data["agent_names"])
```

如果历史数据确实存在旧字段，处理方式是：

1. 写一个迁移入口或清理脚本。
2. 写迁移前后的 fixture。
3. 主运行时只读取新字段。
4. 测试证明旧字段不再触发主路径。

### 4.4 Prompt 不散落

平台内置 Prompt 必须按 `docs/contracts/prompt-assembly-contract.md` 集中管理，模板正文统一写入 `backend/app/agent/platform_prompt_templates.json`；`backend/app/agent/platform_prompts.py` 只负责按 `prompt_id` 读取、校验和渲染。其他文件只能通过 `prompt_id`、模板变量和专门的 Prompt 读取函数调取，不直接内嵌大段固定提示词。

任何 Prompt 要求模型输出的字段，必须与 Pydantic schema、契约文档和测试断言一致。提示词不得要求 `reason`、`speaker_task`、`next_prompt` 等已删除字段。

新增或修改平台内置 Prompt 时，必须同时更新 `platform_prompt_templates.json` 中的模板、调用点的 `prompt_id`、对应 schema 和测试。业务代码中出现三行以上固定 LLM 指令文本时，应迁移到 `platform_prompt_templates.json`。

### 4.5 注释写在文件开头或函数开头

项目要求保留一定量的解释性注释，但注释只能出现在文件开头或函数开头，用来说明职责、契约来源、输入输出边界或非显然的业务不变量。

必须写注释的场景：

- 新增承担业务责任的文件：文件开头说明该文件负责什么、不负责什么、对应哪份契约文档。
- API handler、运行时入口、schema 解析函数、Prompt 读取函数、工具网关函数：函数开头说明输入边界、输出结构和失败策略。
- 删除旧字段兜底或迁移旧协议时：函数开头说明为什么主路径只接受新字段。

禁止写的注释：

- 行尾解释变量名或重复代码表面含义。
- 在函数中间用注释分隔一长串职责；出现这种情况应拆函数。
- 用注释解释旧字段兼容分支；旧分支应删除或迁移到独立迁移文件。

### 4.6 前端不反推业务状态

前端只能消费后端结构化字段：

- 路由看 `route.agent_name` 和 `route.skill`。
- 阶段看 `progress.phase`、`runtime.phase` 和 `end.phase`。
- 等待用户看 `end.waiting_for_user`。
- 招募看 `suggested_add_agent_names`。
- 消息事实看 `speaker`、`message.content`、`message.attachments` 和 `skill_result`。

不得从 `message.content` 正则解析专家名、文件引用、招募建议、下一步动作或会话结束状态。

## 5. 测试要求

### 5.1 改契约必须补契约测试

字段、路由、运行态、Prompt 输出或 Skill stdout 变化时，至少补一类测试：

- 后端 schema 和非法字段拒绝测试。
- 主持人或 Skill 输出严格解析测试。
- SSE 事件 payload 测试。
- 前端 API/mock 对齐测试。
- E2E 关键路径测试。

### 5.2 先写失败测试

修复旧字段、旧兜底或重复逻辑时，先写能暴露问题的测试，再删实现。测试名称要写出契约边界，例如：

```python
def test_chat_request_rejects_legacy_action_field():
    ...
```

### 5.3 推荐验证命令

按改动范围选择最小验证集：

```bash
rtk python -m py_compile backend/app/api/sessions.py backend/app/agent/group_chat_runtime.py backend/app/agent/group_host_decision.py backend/app/agent/group_orchestration_fsm.py backend/app/agent/expert_runtime.py backend/app/agent/tools_for_skill.py
rtk python -m pytest backend/tests/test_group_host_decision.py backend/tests/test_group_orchestration_fsm.py backend/tests/test_group_chat_stream_protocol.py -q
rtk npm --prefix frontend run build
```

触达前端指定专家、邀请条、SSE mock 或资源导入导出时，再补：

```bash
rtk npx --prefix frontend playwright test frontend/e2e/workspace.spec.ts frontend/e2e/resources-scenario-expert.spec.ts
```

## 6. 代码提交前检查

提交前至少确认：

- 契约文档、设计文档、测试和 mock 没有字段漂移。
- 没有新增旧字段兜底。
- 新字段有生产方、消费方和生命周期说明。
- 业务逻辑没有被写进 API 薄入口或 Vue 大组件。
- Prompt 没有散落在业务代码中。
- `rtk git diff --check` 通过。
