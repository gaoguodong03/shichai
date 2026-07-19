# 协作提示词与 Skill 对齐实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将指定账号的协作场景、主持人和三个专家资源迁移到当前提示词与 Skill 分层合同。

**架构：** 场景提示词保存共享任务契约；主持人和专家的非空长期提示词分别保存完整平台合同与角色特化内容；主持人 Skill 只保存四列表，普通 Skill 只保存业务执行规则和自然结束条件。通过账号资源契约测试验证每层边界，不修改平台运行时代码。

**技术栈：** JSON、Markdown/YAML Frontmatter、Python、pytest。

---

## 文件结构

- `backend/tests/test_collaboration_scenario_resources.py`：验证账号协作资源的提示词分层、Skill 结构和工具声明。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/scenarios/协同写作/scenario.json`：保存场景共享契约和主持人长期提示词。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-0909791c1d74/SKILL.md`：保存协作场景唯一四列表。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/{信息检索专家,文档合著专家,图片生成专家}/agent.json`：保存完整专家长期提示词。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/{skill-collab-web-research,skill-b604cfa284ca,skill-collab-image-generation}/SKILL.md`：保存三类业务能力的执行规则与结束条件。

### 任务 1：建立新的资源分层契约

**文件：**

- 修改：`backend/tests/test_collaboration_scenario_resources.py`

- [ ] **步骤 1：改写场景与主持人资源测试**

将主持人 Skill 持有 JSON 的旧断言替换为以下结构断言：

```python
scenario_prompt = str(scenario.get("system_prompt") or "").strip()
host_prompt = str(host.get("system_prompt") or "").strip()
assert "场景目标" in scenario_prompt
assert "完成标准" in scenario_prompt
assert '"current_phase"' not in scenario_prompt
assert "只负责调度" in host_prompt
assert "阶段表使用规则" in host_prompt
assert '"current_phase"' in host_prompt
assert "信息检索专家" not in host_prompt

assert host_body.count("| 决策前阶段 | 判定条件 | 本轮动作 | 决策后阶段 |") == 1
assert "| （无） |" in host_body
assert "\n## " not in host_body
assert '"current_phase"' not in host_body
```

- [ ] **步骤 2：改写专家长期提示词与普通 Skill 测试**

对三个专家分别断言专业短语，同时统一断言完整合同：

```python
for agent in agents:
    prompt = str(agent.get("system_prompt") or "").strip()
    for heading in ("职责边界：", "专业标准：", "执行要求：", "输出：", "流程控制："):
        assert heading in prompt
    for fragment in ('"execution_status"', '"next_action"', "continue + keep", "respond + release"):
        assert fragment in prompt
    assert "不选择下一位专家" in prompt
    assert "不得填写 target_agent_name" in prompt

for body in expert_skill_bodies:
    assert body.count("## 执行规则") == 1
    assert body.count("## 结束条件") == 1
    assert "- 等待用户：" in body
    assert "- 完成：" in body
```

- [ ] **步骤 3：运行测试并确认红灯**

运行：

```bash
rtk pytest -q backend/tests/test_collaboration_scenario_resources.py
```

预期：测试失败，原因包括场景提示词为空、主持人 Skill 仍包含额外章节和 JSON、专家长期提示词缺少完整输出合同。

### 任务 2：迁移场景提示词与主持人资源

**文件：**

- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/scenarios/协同写作/scenario.json`
- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-0909791c1d74/SKILL.md`
- 测试：`backend/tests/test_collaboration_scenario_resources.py`

- [ ] **步骤 1：写入场景共享任务契约**

将 `scenario.json.system_prompt` 写成包含“场景目标”“共同要求”“完成标准”的共享文本；只描述用户可选的资料、文档、图片与图文版交付，不包含阶段表、专家职责和 JSON。

- [ ] **步骤 2：写入完整主持人长期提示词**

将 `host.system_prompt` 对齐 `frontend/src/features/resources/resourceSystemPromptDefaults.ts` 中 `DEFAULT_HOST_SYSTEM_PROMPT` 的职责形状，包含调度职责、工作区边界、阶段表使用规则和主持人 JSON 输出合同，不写死三个专家名称。

- [ ] **步骤 3：将主持人 Skill 重写为四列表**

保留当前 Frontmatter；正文只保留标题和设计规格中已经确认的四列表。首轮使用 `（无）`，后续阶段使用 `资料检索`、`文档合著`、`图片生成`，结束进入 `end`。

- [ ] **步骤 4：运行主持人定向契约测试**

运行：

```bash
rtk pytest -q backend/tests/test_collaboration_scenario_resources.py::test_collaboration_scenario_has_three_current_protocol_experts
```

预期：PASS。

### 任务 3：迁移三个专家长期提示词和普通 Skill

**文件：**

- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/信息检索专家/agent.json`
- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/文档合著专家/agent.json`
- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/图片生成专家/agent.json`
- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-collab-web-research/SKILL.md`
- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-b604cfa284ca/SKILL.md`
- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-collab-image-generation/SKILL.md`
- 测试：`backend/tests/test_collaboration_scenario_resources.py`

- [ ] **步骤 1：写入三个完整专家长期提示词**

每个提示词都包含五个固定部分：`职责边界`、`专业标准`、`执行要求`、`输出`、`流程控制`。专业边界和质量标准按专家分别填写；执行、JSON 和流程控制使用当前前端 `DEFAULT_EXPERT_SYSTEM_PROMPT` 合同。

- [ ] **步骤 2：收敛三个普通 Skill**

保留现有业务顺序与工具绑定，将执行规则统一为编号规则；将结束条件明确标记为 `等待用户`、`完成` 和适用时的 `失败`。正文不加入角色身份、跨专家调度或平台字段。

- [ ] **步骤 3：运行专家定向契约测试**

运行：

```bash
rtk pytest -q \
  backend/tests/test_collaboration_scenario_resources.py::test_collaboration_web_and_image_skills_use_the_business_template \
  backend/tests/test_collaboration_scenario_resources.py::test_collaboration_experts_follow_cross_scenario_prompt_template \
  backend/tests/test_collaboration_scenario_resources.py::test_collaboration_host_owns_dispatch_output_while_coauthor_uses_business_template
```

预期：PASS。

### 任务 4：完成回归验证

**文件：**

- 验证：上述所有修改文件

- [ ] **步骤 1：解析资源文件**

运行：

```bash
rtk jq -e . backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/scenarios/协同写作/scenario.json
rtk jq -e . backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/*/agent.json
```

预期：所有 JSON 均解析成功。

- [ ] **步骤 2：运行提示词与协作运行时回归**

运行：

```bash
rtk pytest -q \
  backend/tests/test_collaboration_scenario_resources.py \
  backend/tests/test_platform_prompts.py \
  backend/tests/test_expert_runtime.py \
  backend/tests/test_host_takeover.py
```

预期：全部测试通过。

- [ ] **步骤 3：运行格式和变更范围检查**

运行：

```bash
rtk git diff --check
rtk git status --short
```

预期：无格式错误；状态仅包含本计划内的已跟踪测试修改、账号资源修改，以及实施前已经存在的无关未跟踪文件。
