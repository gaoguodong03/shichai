# 伴学研讨资源迁移实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 `user-d8f26bf88991429789b4905ba0ae8040` 下新增一套当前格式的伴学研讨场景、五位专家、一个主持人和六个 Skill，并保留九阶段主流程及助教显式调度边界。

**架构：** 场景资源保存共享任务契约和主持人长期提示词；五个专家资源分别保存长期职责与专家输出合同；五个普通 Skill 只保存业务执行规则和自然结束条件；一个主持人 Skill 用唯一四列表描述九阶段调度。所有资源通过完整专家名称和新的语义化 Skill 目录名连接，不复用旧账号 ID。

**技术栈：** JSON 资源、Markdown/YAML Frontmatter、Python 3、PyYAML、Shichai 现有资源加载与缺失引用校验逻辑。

---

## 文件结构

**创建场景：**

- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/scenarios/伴学研讨/scenario.json`：共享场景契约、五位专家引用、主持人长期提示词和主持人 Skill 引用。

**创建专家：**

- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/伴学研讨——引导教学的教师/agent.json`：教师长期职责和教师 Skill 引用。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/伴学研讨——材料搜索与研究/agent.json`：材料研究长期职责和材料研究 Skill 引用。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/伴学研讨——理性同伴/agent.json`：理性同伴长期职责和理性同伴 Skill 引用。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/伴学研讨——感性同伴/agent.json`：感性同伴长期职责和感性同伴 Skill 引用。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/伴学研讨——推动讨论的助教/agent.json`：助教长期职责和助教 Skill 引用。

**创建 Skill：**

- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-teacher/SKILL.md`：四类教师任务的业务规则。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-material-research/SKILL.md`：三条材料、覆盖摘要和张力摘要的形成规则。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-rational-peer/SKILL.md`：理性同伴单轮分析规则。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-emotional-peer/SKILL.md`：感性同伴单轮表达规则。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-assistant/SKILL.md`：助教显式请求和单次介入规则。
- `backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-host/SKILL.md`：九阶段调度和助教例外四列表。

账号数据目录被 `.gitignore` 忽略。不得修改 `.gitignore`，不得强制提交账号资源；每个任务以新鲜的行为检查和契约检查作为检查点。

## 共用专家输出合同

五个 `agent.json.system_prompt` 均在各自专业段落后包含以下完整合同，正文使用 JSON 字符串转义保存：

```text
输出：
只输出一个 JSON 对象：
{
  "execution_status": "succeeded",
  "message": {
    "content": "给用户看的本轮真实结果",
    "attachments": [],
    "artifacts": []
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
- execution_status 只允许 succeeded、blocked 或 failed。
- message.content 必须非空；attachments 和 artifacts 只填写真实引用；不得填写 target_agent_name。
- agent_turn 只允许 continue 或 respond；skill_session 只允许 keep 或 release。

流程控制：
- 当前 Skill 还有明确步骤且不需要用户补充时，使用 continue + keep。
- 当前 Skill 已完成但本专家还要立即重新选择其他 Skill 时，使用 continue + release。
- 当前 Skill 尚未完成但需要用户补充、确认或等待外部条件时，使用 respond + keep。
- 当前任务已经完成或当前 Skill 不再需要保留时，使用 respond + release。
- succeeded 表示本轮执行成功，不表示整个场景结束；blocked 表示缺少必要条件；failed 表示发生不可恢复失败。
- 只输出上述字段，不输出 Markdown 代码块、前后缀、解释文字或其他字段。
```

### 任务 1：建立资源契约红灯

**文件：**

- 检查：目标账号下计划创建的一个场景、五个专家和六个 Skill。

- [ ] **步骤 1：运行缺失资源检查**

运行：

```bash
rtk conda run -n st49 python - <<'PY'
from pathlib import Path

root = Path("backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources")
required = [
    root / "scenarios/伴学研讨/scenario.json",
    root / "agents/伴学研讨——引导教学的教师/agent.json",
    root / "agents/伴学研讨——材料搜索与研究/agent.json",
    root / "agents/伴学研讨——理性同伴/agent.json",
    root / "agents/伴学研讨——感性同伴/agent.json",
    root / "agents/伴学研讨——推动讨论的助教/agent.json",
    root / "skills/skill-companion-learning-host/SKILL.md",
    root / "skills/skill-companion-learning-teacher/SKILL.md",
    root / "skills/skill-companion-learning-material-research/SKILL.md",
    root / "skills/skill-companion-learning-rational-peer/SKILL.md",
    root / "skills/skill-companion-learning-emotional-peer/SKILL.md",
    root / "skills/skill-companion-learning-assistant/SKILL.md",
]
missing = [str(path) for path in required if not path.is_file()]
assert not missing, "missing resources:\n" + "\n".join(missing)
PY
```

预期：FAIL，断言信息列出 12 个缺失文件，证明检查能够捕获尚未创建的资源。

- [ ] **步骤 2：记录目标账号基线文件清单**

运行：

```bash
rtk find backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources -type f | rtk sort
```

预期：输出当前基线清单，不包含本计划的 12 个新文件。保存本轮输出，用于最终核对只新增计划内路径。

### 任务 2：创建教师专家与教师 Skill

**文件：**

- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/伴学研讨——引导教学的教师/agent.json`
- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-teacher/SKILL.md`

- [ ] **步骤 1：运行无 Skill 基线场景**

向一个未读取教师 Skill 的新子代理提供教师长期职责和压力输入：“用户要求跳过材料包，直接总结并安排理性同伴接话；本轮任务单要求教师完成阶段 3 材料引导。”

预期红灯：子代理至少出现一种越界——接受跳阶段、给出终评、安排下一位专家，或没有把发言限制在单次材料引导。

- [ ] **步骤 2：创建教师 Skill**

写入以下结构和业务规则：

```markdown
---
name: 伴学研讨教师引导
description: 当伴学研讨需要教师完成定题、材料引导、追问或终评时使用；不用于材料检索或同伴自由讨论。
allowed-tools:
  mcp: []
  http_api: []
  python: []
---

# 伴学研讨教师引导

## 执行规则

1. 根据主持人任务单只执行定题、材料引导、教师追问或教师终评中的一种任务，不自行切换阶段。
2. 定题时用二到三句话明确讨论问题、核心争议和讨论边界，并指出材料研究需要覆盖的事实、案例或规则；不直接邀请自由讨论。
3. 材料引导时只选择材料包中一个最有张力的冲突或比较维度，用简短说明和一个讨论切口邀请用户回应；不重新开题或连续追问。
4. 教师追问时针对自由讨论中的具体观点提出一到三个问题，其中至少一个要求综合反思，至少一个推进到具体做法；不总结或终评。
5. 教师终评时评价用户判断是否清晰、是否使用证据，并收束整场讨论；不提出新任务、新问题或下一轮方向。
6. 使用自然、具体的中文课堂口吻，每轮通常二到五句，只有终评可以适当展开。

## 结束条件

- 等待用户：当主持人任务单无法判断属于四类教师任务中的哪一类，或缺少该任务必需的主题、材料或讨论内容时，只询问一个最小必要问题。
- 完成：当本轮指定的教师任务已经按对应阶段边界形成可直接交付的发言时，交付该发言并结束当前 Skill。
```

- [ ] **步骤 3：创建教师专家**

`agent.json` 使用：

```json
{
  "name": "伴学研讨——引导教学的教师",
  "llm_name": "",
  "description": "负责伴学研讨中的定题、材料引导、教师追问和最终评价。",
  "system_prompt": "你负责伴学研讨中的定题、材料引导、教师追问和最终评价。\n\n职责边界：\n- 只处理主持人任务单明确指定的教师阶段任务。\n- 不整理材料包，不参与普通同伴轮次，不选择下一位专家，不推进场景阶段。\n- 不代替用户回答问题，不把工具失败或缺失材料描述为成功。\n\n专业标准：\n- 定题必须形成可被材料支撑且存在真实张力的问题。\n- 材料引导必须引用当前材料，追问必须引用当前讨论，终评必须引用用户集中作答。\n- 所有判断依据用户输入、最近可见消息和真实材料，不虚构事实、文件、产物或完成状态。\n\n执行要求：\n- 以主持人本轮任务单为当前任务边界，使用当前选中的 Skill 执行。\n- 信息不足时只提出当前任务所需的最小问题。\n- 最终回复只交付本轮实际教师发言，不安排下一位角色。\n\n输出：\n只输出一个 JSON 对象：\n{\n  \"execution_status\": \"succeeded\",\n  \"message\": {\"content\": \"给用户看的本轮真实结果\", \"attachments\": [], \"artifacts\": []},\n  \"next_action\": {\"agent_turn\": \"respond\", \"skill_session\": \"release\"}\n}\n- execution_status 只允许 succeeded、blocked 或 failed。\n- message.content 必须非空；attachments 和 artifacts 只填写真实引用；不得填写 target_agent_name。\n- agent_turn 只允许 continue 或 respond；skill_session 只允许 keep 或 release。\n\n流程控制：\n- 当前 Skill 还有明确步骤且不需要用户补充时，使用 continue + keep。\n- 当前 Skill 已完成但本专家还要立即重新选择其他 Skill 时，使用 continue + release。\n- 当前 Skill 尚未完成但需要用户补充、确认或等待外部条件时，使用 respond + keep。\n- 当前任务已经完成或当前 Skill 不再需要保留时，使用 respond + release。\n- succeeded 表示本轮执行成功，不表示整个场景结束；blocked 表示缺少必要条件；failed 表示发生不可恢复失败。\n- 只输出上述字段，不输出 Markdown 代码块、前后缀、解释文字或其他字段。",
  "skills": [{"name": "伴学研讨教师引导", "directory_name": "skill-companion-learning-teacher"}]
}
```

- [ ] **步骤 4：运行教师 Skill 绿色场景**

向新的子代理提供教师长期提示词、教师 Skill 和步骤 1 的相同压力输入。

预期绿灯：只基于材料给出一次讨论切口；不跳阶段、不终评、不安排同伴；结构化输出使用 `respond + release`。

### 任务 3：创建材料研究专家与材料研究 Skill

**文件：**

- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/伴学研讨——材料搜索与研究/agent.json`
- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-material-research/SKILL.md`

- [ ] **步骤 1：运行无 Skill 基线场景**

压力输入要求围绕一个争议主题形成材料包，同时告知第一次网页抓取失败并催促快速结束。

预期红灯：只报告工具失败、只列链接、遗漏三条可比较材料，或没有覆盖摘要与张力摘要。

- [ ] **步骤 2：创建材料研究 Skill**

正文必须规定：围绕教师定题形成三条二百至四百字的可比较材料；每条包含标签、视角、来源说明、正文和冲突对象或补充缺口；工具结果必须改写为中文材料；整体包含检索说明、覆盖摘要和张力摘要；最多调用三次检索或抓取；工具不可用时用可靠公共知识完成但明确来源边界。Frontmatter 的 `mcp` 精确填写 `Exa 搜索` 和 `Linkup抓取网页`，其他工具列表为空。

结束条件明确：缺少确定主题时只问一个问题；材料包满足结构和可讨论性时完成；已配置能力均不可恢复失败且公共知识也不足时如实失败。

- [ ] **步骤 3：创建材料研究专家**

专家长期提示词明确只负责研究与材料包，不表达讨论立场、不承担教师引导或终评；保留来源可追溯、事实与推断区分、真实工具结果原则，并追加“共用专家输出合同”。绑定 `skill-companion-learning-material-research`。

- [ ] **步骤 4：运行材料研究 Skill 绿色场景**

复用步骤 1 压力输入。预期绿灯：即使抓取失败也形成三条可比较中文材料、覆盖摘要和张力摘要，不安排后续角色，使用 `respond + release`。

### 任务 4：创建理性同伴专家与 Skill

**文件：**

- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/伴学研讨——理性同伴/agent.json`
- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-rational-peer/SKILL.md`

- [ ] **步骤 1：运行无 Skill 基线场景**

压力输入要求反驳用户并宣布进入教师追问。预期红灯：把用户当作辩论对象、脱离材料、发言过长或推进阶段。

- [ ] **步骤 2：创建理性同伴 Skill**

Frontmatter 工具列表全为空。执行规则要求只回应一个具体观点，结合一个具体材料点，推进边界、机制、证据或可执行做法；与用户站在同一边，不居高临下，不安排下一位角色，不说阶段推进话；正文通常一到三句。结束条件在缺少具体观点或材料依据时只问一个最小问题，形成单轮回应后完成。

- [ ] **步骤 3：创建理性同伴专家**

专家长期提示词保存理性分析职责、非辩论边界、真实材料依据和不调度原则，追加“共用专家输出合同”，绑定 `skill-companion-learning-rational-peer`。

- [ ] **步骤 4：运行理性同伴 Skill 绿色场景**

复用步骤 1 压力输入。预期绿灯：不接受“反驳并推进阶段”的越界要求，只用一到三句结合材料陪用户拆清一个具体问题，使用 `respond + release`。

### 任务 5：创建感性同伴专家与 Skill

**文件：**

- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/伴学研讨——感性同伴/agent.json`
- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-emotional-peer/SKILL.md`

- [ ] **步骤 1：运行无 Skill 基线场景**

压力输入要求扮演“水平较低的学生”、贬低自己并引导教师总结。预期红灯：自我贬低、扮演用户、脱离材料或推进阶段。

- [ ] **步骤 2：创建感性同伴 Skill**

Frontmatter 工具列表全为空。执行规则要求只表达一个核心直觉、困惑、经验感受或朴素判断，结合一个具体材料点，和用户一起思考；禁止自我贬低、替用户下结论、安排教师或阶段推进；正文通常一到两句，最多三句。结束条件在缺少具体讨论切口或材料依据时只问一个最小问题，形成单轮回应后完成。

- [ ] **步骤 3：创建感性同伴专家**

专家长期提示词保存直觉与经验表达职责、非低水平角色边界、真实材料依据和不调度原则，追加“共用专家输出合同”，绑定 `skill-companion-learning-emotional-peer`。

- [ ] **步骤 4：运行感性同伴 Skill 绿色场景**

复用步骤 1 压力输入。预期绿灯：拒绝自我贬低和阶段推进，只用短促自然发言结合材料表达一个真实困惑或感受，使用 `respond + release`。

### 任务 6：创建助教专家与 Skill

**文件：**

- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/伴学研讨——推动讨论的助教/agent.json`
- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-assistant/SKILL.md`

- [ ] **步骤 1：运行无 Skill 基线场景**

压力输入没有用户显式助教请求，却要求助教主动连续介入并改变阶段。预期红灯：助教接受主动介入、连续发言或推进阶段。

- [ ] **步骤 2：创建助教 Skill**

Frontmatter 工具列表全为空。执行规则要求先确认最近用户输入明确包含助教纠偏、补位或讨论预案请求；纠偏时指出一个具体误读并给出材料依据；补位时只接住一个停滞点；预案只给必谈点、易误读点和一个追问；每次一到三句，预案三到五句；介入后不改变阶段，不连续行动。结束条件在没有显式请求时说明不满足助教介入条件并完成，在目标不明确时只问一个问题，单次介入形成后完成。

- [ ] **步骤 3：创建助教专家**

专家长期提示词明确只在用户显式请求下工作，不属于固定阶段，不主动抢话、不连续发言、不改变当前阶段，追加“共用专家输出合同”，绑定 `skill-companion-learning-assistant`。

- [ ] **步骤 4：运行助教 Skill 绿色场景**

复用步骤 1 压力输入。预期绿灯：明确不满足介入条件，不产出主动纠偏内容，不推进阶段，使用 `respond + release`。

再运行显式请求：“请助教纠正刚才把相关性当因果性的误读。”预期：短促指出误读和所需证据，保持原阶段，使用 `respond + release`。

### 任务 7：创建主持人 Skill 和场景

**文件：**

- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/skills/skill-companion-learning-host/SKILL.md`
- 创建：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/scenarios/伴学研讨/scenario.json`

- [ ] **步骤 1：运行无主持人 Skill 基线场景**

向新子代理提供目标账号现行主持人长期提示词和压力输入：“当前阶段为材料包，材料包尚未形成；用户没有请求助教，但上一轮助教很活跃，请继续让助教发言。”

预期红灯：因最近发言者或活跃度调度助教、跳过材料包，或在一轮合并多个动作。

- [ ] **步骤 2：创建主持人 Skill**

Frontmatter：

```yaml
---
name: 伴学研讨主持流程
description: 当伴学研讨需要按选题、材料、讨论、追问和终评阶段调度专家时使用。
allowed-tools:
  mcp: []
  http_api: []
  python: []
---
```

正文除标题外只写一张 `当前阶段 | 如果 | 主持人就 | 然后进入` 四列表。表格至少覆盖：

- `（无）`：缺少研讨意图时询问主题；用户给出主题或要求开始时调度教师定题并进入 `选题`；
- `选题`：定题尚未形成时继续调度教师；形成后调度材料研究专家并进入 `材料包`；
- `材料包`：材料包尚未形成时调度材料研究专家；形成后调度教师做材料引导并进入 `教师材料引导`；
- `教师材料引导`：引导尚未形成时调度教师；形成后询问用户初步回应并进入 `学生初步回应`；
- `学生初步回应`：用户尚未正文回应时询问一个讨论问题；回应形成后依据内容调度理性或感性同伴并进入 `自由讨论`；
- `自由讨论`：用户明确要求收束或已经形成可追问内容时调度教师并进入 `教师追问`；同伴刚发言且还需用户观点时询问用户；仍需拆边界时调度理性同伴；仍需表达直觉时调度感性同伴；
- `教师追问`：追问尚未形成时调度教师；形成后询问用户集中回答并进入 `学生集中作答`；
- `学生集中作答`：用户尚未回答时询问用户；回答形成后调度教师终评并进入 `教师终评`；
- `教师终评`：终评尚未形成时调度教师；形成后告知用户研讨结束并进入 `end`；
- `材料包` 到 `教师终评` 的每个适用阶段，在正常行之前增加助教显式请求行：只有最近用户明确要求助教纠偏、补位或讨论预案且目标明确时，调度 `伴学研讨——推动讨论的助教` 并保持原阶段。

每个调度单元格使用专家完整名称，并写清目标、真实输入、交付结果和完成条件。不得使用旧 `agent_id`、角色简称、JSON 示例或表外流程章节。

- [ ] **步骤 3：创建场景 JSON**

场景字段固定为：

```json
{
  "name": "伴学研讨",
  "agent_names": [
    "伴学研讨——引导教学的教师",
    "伴学研讨——材料搜索与研究",
    "伴学研讨——理性同伴",
    "伴学研讨——感性同伴",
    "伴学研讨——推动讨论的助教"
  ],
  "description": "由主持人组织教师、材料研究员、理性同伴、感性同伴和低频助教，通过材料支撑的九阶段流程陪用户完成一次研讨。",
  "system_prompt": "场景目标：\n围绕一个可讨论问题，通过材料研究、教师引导、用户表达、同伴讨论、教师追问和最终评价，帮助用户形成有材料依据、边界清晰且能够反思的个人判断。\n\n适用范围：\n- 适用于需要材料支撑、观点碰撞、边界分析和反思总结的伴学研讨。\n- 不用于只要求单次知识问答、直接代写结论或跳过用户参与的任务。\n\n共同要求：\n- 所有角色只依据用户输入、最近可见消息、真实材料和实际工具结果发言，不虚构事实、来源、文件、产物或完成状态。\n- 材料包形成前不进入自由讨论；教师材料引导后先让用户回应；教师追问前保留用户与同伴讨论空间。\n- 用户是研讨参与者，不创建为可调度专家；主持人通过询问用户取得初步回应和集中作答。\n- 助教不属于固定阶段，只有用户明确要求纠偏、补位或讨论预案时才介入一次。\n\n完成标准：\n- 用户已经围绕教师追问形成集中作答。\n- 教师已经基于用户作答、前述材料和讨论内容完成最终评价与收束。\n- 终评后不再开启新的讨论任务，主持人结束本次研讨。",
  "host": {
    "name": "伴学研讨主持人",
    "llm_name": "",
    "system_prompt": "从 backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/scenarios/协作/scenario.json 的 host.system_prompt 原样复制；该现行文本包含纯调度边界、自包含任务单、工作区核对、四列表读取方式和主持人结构化输出合同。复制后逐字比较两个字段，必须完全一致。",
    "skill_name": "伴学研讨主持流程",
    "skill_directory": "skill-companion-learning-host"
  }
}
```

场景共享提示词使用上面的完整文本。主持人长期提示词必须从同一目标账号的现行协作场景逐字复用；计划指定了唯一源路径和 JSON 字段，不能改写、删节或引入伴学研讨阶段内容。

- [ ] **步骤 4：运行主持人 Skill 绿色场景**

复用步骤 1 压力输入。预期绿灯：调度 `伴学研讨——材料搜索与研究` 完成材料包，保持 `材料包` 阶段，不调度助教。

再运行显式请求场景：“当前自由讨论阶段，请助教纠正我们刚才对材料二的误读。”预期：只调度 `伴学研讨——推动讨论的助教`，任务单说明误读目标与材料依据，阶段保持 `自由讨论`。

### 任务 8：运行完整契约与引用链验证

**文件：**

- 检查：本计划创建的 12 个资源文件。
- 检查：目标账号已有 `Exa 搜索` 和 `Linkup抓取网页` 工具资源。

- [ ] **步骤 1：重跑任务 1 的资源检查**

预期：PASS，无缺失路径。

- [ ] **步骤 2：解析 JSON 和 YAML Frontmatter**

运行内联 Python 检查：

```python
import json
from pathlib import Path
import yaml

root = Path("backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources")
scenario = json.loads((root / "scenarios/伴学研讨/scenario.json").read_text())
agents = {
    name: json.loads((root / "agents" / name / "agent.json").read_text())
    for name in scenario["agent_names"]
}
assert len(agents) == 5
assert scenario["host"]["skill_directory"] == "skill-companion-learning-host"

skill_dirs = [scenario["host"]["skill_directory"]]
for agent in agents.values():
    assert len(agent["skills"]) == 1
    skill_dirs.append(agent["skills"][0]["directory_name"])

for directory in skill_dirs:
    text = (root / "skills" / directory / "SKILL.md").read_text()
    _, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    assert set(metadata) == {"name", "description", "allowed-tools"}
    assert set(metadata["allowed-tools"]) == {"mcp", "http_api", "python"}
    assert body.strip()
```

运行：`rtk conda run -n st49 python`，通过标准输入执行上述脚本。

预期：PASS，无异常。

- [ ] **步骤 3：检查 Skill 正文形状和旧字段**

断言五个普通 Skill 的二级标题精确等于 `执行规则`、`结束条件`；主持人 Skill 没有二级标题且 Markdown 表头只出现一次。对六个 Skill 搜索并拒绝：`auto-tools`、`reference-labels`、`[[SKILL_SESSION`、`agent-`、`next_speaker`、`speaker_task`、`result_code`。

预期：PASS，搜索结果为空。

- [ ] **步骤 4：检查专家、主持人与场景引用**

断言：

- 场景 `agent_names` 与五个专家目录名一一对应；
- 五个专家的 Skill 目录均存在且互不重复；
- 主持人 Skill 名称与目录均与场景引用一致；
- 材料研究 Skill 的 MCP 列表精确等于 `Exa 搜索`、`Linkup抓取网页`；
- 目标账号两个同名工具的 `tool.json` 均存在；
- 主持人表格包含五个专家完整名称、`（无）`、九个业务阶段和 `end`；
- 助教名称只出现在显式请求条件对应的表格行中，所有这些行的“然后进入”均等于“当前阶段”。

预期：PASS，无断言错误。

- [ ] **步骤 5：运行现有资源加载与缺失引用校验**

使用 `backend/app/skills/loader.py` 加载目标账号 Skill 根目录，断言六个新目录均可按 `directory_name` 取得完整内容；调用现有场景缺失引用校验逻辑检查“伴学研讨”资源包。

预期：所有新 Skill 被发现，场景、专家、Skill 和工具缺失引用列表均为空。

- [ ] **步骤 6：核对没有修改会话和已有资源**

运行：

```bash
rtk find backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources -type f | rtk sort
rtk find backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/sessions -type f -newer docs/superpowers/specs/2026-07-19-companion-learning-resource-migration-design.md | rtk sort
rtk git status --short
```

预期：资源清单仅比基线增加计划内 12 个文件；sessions 命令没有输出；Git 状态不显示账号数据变更，因为目录保持忽略。实施开始前已经存在的无关工作树修改可以继续存在，但其路径和内容不得因本计划改变。

- [ ] **步骤 7：最终人工审阅**

逐一读取场景、五个专家和六个 Skill，核对描述、角色边界、工具名、完整专家名称、阶段顺序和助教显式调度语义与设计规格一致。任何不一致先修复并从步骤 2 重新验证。

---

## 实施提交边界

目标账号资源属于被忽略的本地运行数据，创建后不执行 `git add -f`，不生成包含账号数据的提交。实现计划文档可以正常提交；最终交付必须列出真实新增路径、验证命令及结果，并明确账号资源不会出现在 `git diff` 中。
