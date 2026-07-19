# 普通 Skill 迁移与流程控制测试资源实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 在当前工作区逐任务实现此计划。步骤使用复选框跟踪进度。

**目标：** 按两段式普通 Skill 模板改写指定用户的三个现有 Skill，并新增可确定性验证四种流程控制组合的专家、Skill 和脚本。

**架构：** 三个现有 Skill 只保留业务执行规则和结束条件。测试专家只绑定一个脚本型 Skill；脚本首次输出用户指定组合，`continue` 组合由同一专家再次调用脚本的完成阶段，以 `respond` 和原始 Skill 保留策略安全结束。

**技术栈：** Markdown/YAML、JSON、Python 3、pytest。

---

## 文件范围

- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-collab-web-research/SKILL.md`
- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-b604cfa284ca/SKILL.md`
- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-collab-image-generation/SKILL.md`
- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/流程控制测试专家/agent.json`
- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/flow-control-next-action-test/SKILL.md`
- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/flow-control-next-action-test/scripts/manifest.json`
- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/flow-control-next-action-test/scripts/emit_next_action.py`
- 创建：`backend/tests/test_flow_control_test_resources.py`
- 修改：`backend/tests/test_collaboration_scenario_resources.py`

## 任务 1：建立失败的资源契约测试

- [x] 新增 `backend/tests/test_flow_control_test_resources.py`，断言三个现有 Skill 都包含非空 `执行规则` 与 `结束条件`，且不包含专家身份、主持人调度、平台最终输出名称、流程控制字段或旧字段黑名单。
- [x] 断言流程控制测试专家符合专家通用模板，只绑定 `flow-control-next-action-test`。
- [x] 断言测试 Skill 符合两段式模板，manifest 只暴露 `agent_turn`、`skill_session`、`stage`。
- [x] 参数化执行脚本首次阶段的四种组合，断言 stdout 中的两个流程控制值与输入完全一致。
- [x] 参数化执行两个 `continue` 组合的完成阶段，断言安全收尾为 `respond` 且保留原始 `keep/release`。
- [x] 运行 `rtk pytest -q backend/tests/test_flow_control_test_resources.py`，预期因测试资源尚未创建和旧 Skill 尚未迁移而失败。

## 任务 2：迁移三个现有 Skill

- [x] 资料检索 Skill 保留检索/抓取工具选择、候选与逐来源素材保存、来源质量和等待/完成条件；删除身份、通用工具回灌、最终 JSON 与旧字段黑名单。
- [x] 文档合著 Skill 保留上下文收集、大纲确认、逐节写作、最终审阅门禁和等待/完成条件；删除身份、通用工作区 CRUD、最终 JSON 与旧字段黑名单。
- [x] 图片生成 Skill 保留做图大纲、生成、确认、图文装配门禁和等待/完成条件；删除身份、通用工具回灌、最终 JSON 与旧字段黑名单。
- [x] 更新 `backend/tests/test_collaboration_scenario_resources.py` 的旧断言，使其验证两段式业务模板而不是平台输出 JSON。

## 任务 3：创建流程控制测试专家与 Skill

- [x] 创建跨场景测试专家，`description` 明确四组合测试交付物，`system_prompt` 只包含职责边界、专业标准和两条通用判断原则。
- [x] 创建两段式测试 Skill：执行规则定义自然语言到脚本参数的映射、首次与完成阶段；结束条件定义歧义时保留 Skill、`respond` 直接结束、`continue` 自动收尾。
- [x] 创建只含 `entry`、`description`、`args` 的 manifest，三个参数均必填。
- [x] 创建无网络、无文件写入的脚本，使用 argparse 枚举校验并只向 stdout 输出平台当前严格对象。

## 任务 4：红绿与回归验证

- [x] 运行 `rtk pytest -q backend/tests/test_flow_control_test_resources.py`，预期全部通过。
- [x] 运行 `rtk pytest -q backend/tests/test_collaboration_scenario_resources.py backend/tests/test_skill_stdout_contracts.py backend/tests/test_skill_agent_tool_resolution.py backend/tests/test_expert_completion_contract.py backend/tests/test_agent_turn_controller.py backend/tests/test_expert_completion_coordinator.py`，预期全部通过。
- [x] 使用 `rtk jq -e` 验证新增 Agent 和 manifest；使用 `rtk python -m py_compile` 验证脚本语法。
- [x] 扫描三个业务 Skill，确认不存在平台最终输出名称、流程控制字段、JSON 合同或未替换占位符；测试 Skill 只保留业务所需的流程参数，不包含最终输出名称或 JSON 合同。
- [x] 运行 `rtk git diff --check`。

## 范围边界

- 不把测试专家加入现有“协作”场景。
- 不修改其他用户数据。
- 不修改当前正在模块化的专家完成结果运行时代码。
- 不恢复已删除的旧流程控制模块或旧设计文档。
