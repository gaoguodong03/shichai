# `next_action` 流程控制测试专家设计

## 1. 目标

在后端用户资源目录中新增一个专用测试专家和一个脚本型 Skill，使测试人员可以用自然语言触发并验证 `expert_final_state.v2.next_action` 的全部四种合法组合：

| 用户意图 | `next_action.agent_turn` | `next_action.skill_session` |
| --- | --- | --- |
| 继续执行，并保留当前 Skill | `continue` | `keep` |
| 继续执行，并释放当前 Skill | `continue` | `release` |
| 回复用户，并保留当前 Skill | `respond` | `keep` |
| 回复用户，并释放当前 Skill | `respond` | `release` |

该资源用于真实群聊链路的人工验证和后端自动化测试，不新增测试专用 API，也不修改四种组合的运行时语义。

## 2. 资源位置与范围

所有新增运行资源放入：

```text
backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/
  agents/流程控制测试专家/agent.json
  skills/flow-control-next-action-test/
    SKILL.md
    scripts/
      manifest.json
      emit_next_action.py
```

专家名称为“流程控制测试专家”，Skill 名称为“流程控制测试”。专家只绑定该 Skill。

本次不把专家加入已有“协作”场景，不修改现有专家、Skill、场景、主持人或平台运行时代码。资源创建后可由测试人员在需要测试的会话或场景中显式选择。

## 3. 用户交互

Skill 接受自然语言测试指令。以下表达作为标准验收输入：

- “继续执行，并保留技能”
- “继续执行，但释放技能”
- “现在回复，并保留技能”
- “现在回复，并释放技能”

专家负责把同义自然语言归一化为脚本参数：

```text
agent_turn = continue | respond
skill_session = keep | release
stage = trigger | complete
```

用户意图缺少任一维度或存在歧义时，专家不猜测目标组合，而是返回一个简短选择提示；该澄清回复使用 `blocked + respond + keep`，以便用户补充后继续当前测试 Skill。

## 4. 组件职责

### 4.1 专家配置

`agent.json` 只声明专家身份、测试边界和绑定 Skill。系统提示要求专家：

1. 只处理 `next_action` 四组合测试；
2. 从用户输入识别两个控制维度；
3. 使用脚本产生最终状态，不徒手拼接测试结果；
4. 不把 `continue` 解释为“给用户回复后继续”；
5. 对其他业务问题说明测试边界。

### 4.2 Skill

`SKILL.md` 定义自然语言映射、脚本调用规则、二阶段 `continue` 流程、歧义处理和最终输出合同。Skill 不授权 MCP、HTTP API 或额外 Python 依赖。

### 4.3 脚本

`emit_next_action.py` 是确定性状态生成器。它校验三个枚举参数并只向 stdout 输出一个完整 `expert_final_state.v2` JSON 对象；诊断信息只写 stderr，非法参数使用非零退出码。

脚本不访问网络，不修改业务数据，不直接写聊天历史，也不自行推断用户意图。

## 5. 四种组合的数据流

### 5.1 `respond + keep`

脚本直接返回可见测试消息和 `respond + keep`。平台落专家消息，并在 `orchestration_state.json.continuation` 中保留该专家与该 Skill。

### 5.2 `respond + release`

脚本直接返回可见测试消息和 `respond + release`。平台落专家消息，并清除已有 continuation。

### 5.3 `continue + keep`

第一次脚本调用返回 `continue + keep`。其 `message.content` 是只供下一次专家回合使用的内部测试指令，包含原始组合和 `stage=complete` 标记；该中间消息不进入聊天历史。平台立即再次调度同一专家，并保留当前 Skill。

第二次脚本调用返回可见验证总结和 `respond + keep`，使本次请求停止自动续跑，同时保留 Skill continuation，便于下一轮继续测试。

### 5.4 `continue + release`

第一次脚本调用返回 `continue + release`。中间消息同样不进入聊天历史，平台立即再次调度同一专家，但不保留 Skill continuation；下一次专家回合走正常 Skill 选择。由于该专家只绑定一个 Skill，仍会选择“流程控制测试”。

第二次脚本调用返回可见验证总结和 `respond + release`，结束本次请求并保持 continuation 已清除。

二阶段设计避免 `continue` 无限循环。用户可见总结必须明确区分“首次触发组合”和“收尾组合”，不能把第二次的 `respond` 错报成首次测试结果。

## 6. 输出内容

直接回复模式的 `message.content` 示例：

```text
已触发流程控制测试：agent_turn=respond，skill_session=keep。
预期行为：落一条专家消息，并保留当前专家的当前 Skill。
```

自动续跑后的可见总结示例：

```text
流程控制测试完成：首次状态为 agent_turn=continue，skill_session=release；平台已再次调度同一专家，本次以 respond+release 安全结束。
```

所有脚本结果使用：

- `execution_status: "succeeded"`；
- 完整 `message.content / attachments / artifacts`；
- 只含 `agent_turn` 和 `skill_session` 的 `next_action`；
- 空 `attachments` 和 `artifacts`，因为该测试不产生文件产物。

## 7. 错误处理

- 枚举值非法：脚本向 stderr 输出稳定错误说明并非零退出。
- 参数缺失：脚本拒绝执行，不补默认组合。
- 用户输入歧义：由专家返回澄清消息，不调用脚本猜测。
- 脚本 stdout 缺字段或含非法额外字段：沿用平台现有 `EXPERT_FINAL_STATE_INVALID` 处理，不添加兼容分支。
- 自动续跑超过平台预算：沿用现有 `timeout_or_budget_exceeded` 保护。

## 8. 测试与验收

### 8.1 资源契约测试

验证专家配置只绑定目标 Skill，Skill frontmatter 和 manifest 可解析，正文包含四种组合与二阶段停止规则，不包含旧控制字段。

### 8.2 脚本单元测试

分别调用四种 `trigger` 组合，断言 stdout 中的 `execution_status`、`message` 和 `next_action` 精确匹配；再验证两个 `complete` 收尾结果以及缺参、非法枚举的失败行为。

### 8.3 编排集成测试

验证：

1. `respond` 只执行一次专家回合并落专家消息；
2. `continue` 连续执行两次同一专家，第一次不落消息，且两次之间不调用主持人；
3. `keep` 写入同专家、同 Skill 的 continuation；
4. `release` 清除 continuation；
5. 四种标准自然语言输入均能得到包含实际字段值的可读结果；
6. `continue` 测试在第二次专家回合停止，不进入无限循环。

### 8.4 完成标准

- 目标用户资源目录中可以发现并加载“流程控制测试专家”和“流程控制测试” Skill；
- 四种组合均有确定性脚本结果和自动化断言；
- 人工测试时，直接回复和自动续跑行为与当前契约一致；
- 未修改已有“协作”场景和业务资源；
- 针对性测试、相关回归测试和 `git diff --check` 均通过。
