# 专家完成结果平台内部分层设计

## 1. 背景与问题

当前模型最终输出使用一个严格 JSON 对象，同时提供：

- `execution_status`：本次专家执行结果；
- `message`：需要成为聊天消息的专家输出；
- `next_action.agent_turn`：当前请求内是否继续执行同一专家；
- `next_action.skill_session`：同一专家以后再次被调度时是否复用当前 Skill。

模型协议本身能够表达这些事实，问题发生在平台内部：现有实现把 JSON 解析、脚本 stdout 选择、专家消息生成、历史落盘、SSE 推送、`agent_turn` 循环、Skill 跨轮绑定和编排状态更新集中在同一调用链中。特别是 `agent_turn=continue` 会提前返回，导致模型已经生成的非空 `message` 没有进入历史，也没有发送 SSE `message`。

该行为错误地让执行控制决定了专家输出是否存在。

## 2. 设计目标

1. 保持模型最终输出 JSON 的字段、层级和枚举完全不变。
2. 模型输出通过严格校验后，在平台内部投影为相互独立的领域对象。
3. 非空专家 `message` 必须发布；`agent_turn`、`skill_session` 和 `execution_status` 均不得吞掉消息。
4. `agent_turn` 只管理当前请求内的专家执行循环。
5. `skill_session` 只管理专家与 Skill 的跨轮绑定，不负责路由，也不保存专家消息。
6. 用户自然语言的含义由主持人模型判断，不允许通过关键词、正则或固定短语硬编码路由。
7. 删除名不副实的 FSM 和混合职责模块，以可独立测试的纯接口替代。

## 3. 非目标

- 不改变模型最终输出 JSON。
- 不改成原生 Tool Call 提交终态。
- 不增加模型调用次数。
- 不增加协议重试机制。
- 不修改 Linkup、Exa 或其他 Skill 内部工具选择与重试逻辑。
- 不从 `message.content` 推断路由、文件、Skill 或控制状态。

## 4. 外部模型协议保持不变

模型、Skill 脚本 stdout 和 finalizer 继续输出：

```json
{
  "execution_status": "succeeded",
  "message": {
    "content": "专家回复",
    "attachments": [],
    "artifacts": []
  },
  "next_action": {
    "agent_turn": "continue",
    "skill_session": "keep"
  }
}
```

平台仍然只接受一个严格 JSON 对象。字段缺失、额外字段、非法枚举或非法 workspace 路径继续按协议错误处理。平台不得要求模型改为新的嵌套结构，也不得要求模型调用平台内部提交工具。

## 5. 平台内部领域对象

严格解析成功后，适配器把同一个 `ExpertFinalStatePayload` 投影为四个不可变对象：

```text
ParsedExpertCompletion
├── ExpertExecutionOutcome
├── ExpertOutputSubmission
├── AgentTurnDirective
└── SkillSessionDirective
```

### 5.1 `ExpertExecutionOutcome`

只包含 `status=succeeded|blocked|failed`。它用于消息关联的执行结果、日志和失败可见性，不决定是否发布专家消息，不决定是否继续执行，也不修改 Skill 绑定。

### 5.2 `ExpertOutputSubmission`

只包含现有 `message` 对象：`content`、`attachments`、`artifacts` 和可选 `target_agent_name`。它是专家消息生成的唯一输入。

当 `message.content` 非空，或存在附件、产物时，输出视为非空，必须发布。`agent_turn=continue`、`execution_status=blocked|failed` 均不能取消发布。

专家 `target_agent_name` 原则上为空；如果现有严格契约允许该字段，输出模块只按消息事实保存，不用它直接执行专家路由。下一位发言人仍由主持人调度契约决定。

### 5.3 `AgentTurnDirective`

只包含 `continue|respond`，生命周期限于当前 `/chat/stream` 请求：

- `continue`：本轮输出发布后，同一专家立即进入下一次执行；
- `respond`：本轮输出发布后，当前专家执行结束，控制权交回主持人。

该对象不进入跨轮编排状态，不选择 Skill，不生成消息。

### 5.4 `SkillSessionDirective`

只包含 `keep|release`，由 Skill Session 管理器结合本轮 `agent_name` 和实际 `skill` 应用：

- `keep`：保存该专家与当前 Skill 的绑定；
- `release`：删除该专家现有 Skill 绑定。

它不决定当前请求是否继续，不决定下一位专家，不保存 `message`。

## 6. 模块划分

### 6.1 `expert_completion_contract.py`

负责模型边界契约与内部投影：

- 保存 `ExpertFinalStatePayload` 及其严格子模型；
- 解析 finalizer JSON；
- 解析脚本 stdout；
- 检测同一轮多个终态是否冲突；
- 返回 `ParsedExpertCompletion`。

该模块不落盘、不发送 SSE、不修改编排状态。

### 6.2 `expert_output_publisher.py`

负责专家输出提交：

- 根据 `ExpertOutputSubmission` 生成标准专家消息；
- 为消息附加发言专家、实际 Skill 和执行结果快照；
- 写入 `history.json`；
- 记录关联工具日志；
- 生成 SSE `message` 事件。

该模块不得读取 `AgentTurnDirective` 或 `SkillSessionDirective`，不得决定是否继续专家执行。

### 6.3 `agent_turn_controller.py`

负责当前请求内的执行权：

- 接收 `AgentTurnDirective`；
- `continue` 时返回“再次执行当前专家”的内部结果；
- `respond` 时返回“交回主持人”的内部结果；
- 维护当前请求内的专家 turn 预算。

该模块不读写 `orchestration_state.json`，不接触消息正文。

### 6.4 `skill_session_manager.py`

负责跨轮 Skill 绑定：

- 读取某专家已有 Skill 绑定；
- 应用 `keep|release`；
- 校验绑定 Skill 仍属于该专家且仍可加载；
- 为专家 Skill 选择阶段提供可复用 Skill。

该模块不读取用户自然语言，不返回下一位专家，不保存专家消息。

### 6.5 `expert_turn_runner.py`

负责一次专家执行的基础设施流程：

- 构建专家运行时；
- 发送 route/progress；
- 收集模型终态、无工具 finalizer 输出与完整工具结果；
- 调用 `expert_completion_contract` 得到 `ParsedExpertCompletion`。

它不直接解释 `agent_turn` 或 `skill_session`，也不直接操作历史和跨轮状态。

### 6.6 `expert_completion_coordinator.py`

负责固定顺序协调，不承载领域判断：

1. 确认完整终态已经严格校验；
2. 调用输出发布器；
3. 调用 Skill Session 管理器；
4. 调用 Agent Turn 控制器；
5. 返回下一步内部运行结果。

协调器不得根据消息文字、专家名称或 Skill 名称增加特殊分支。

## 7. Skill Session 持久化结构

删除当前 `continuation` 同时保存消息、Skill 绑定和隐含路由所有权的设计。新的短期编排状态把 Skill Session 与主持人调度分开：

```json
{
  "skill_sessions": {
    "信息检索专家": {
      "skill": "skill-collab-web-research"
    }
  },
  "host_scheduler": {
    "current_phase": "等待用户确认",
    "message": {
      "content": "请确认下一步。",
      "attachments": [],
      "artifacts": []
    }
  }
}
```

设计规则：

- `skill_sessions` 按专家名称索引，因此不同专家可以各自保持一个 Skill 绑定；
- 绑定只包含实际 Skill，不复制专家消息，不保存 `next_action`，不声明下一位发言人；
- 最近专家输出从 `history.json` 获取，不重复写入 Skill Session；
- 主持人调度状态只保存主持人自己的结构化状态；
- 主持人选择其他专家时，不自动删除原专家 Skill 绑定；只有该专家输出 `release`、绑定失效或会话删除时才清理。

## 8. 路由与主持人边界

删除 `group_orchestration_fsm.py`。现有代码并不存在需要 FSM 表达的状态迁移图，只是结构化入口路由优先级，不应继续以 FSM 命名或扩展。

替换为纯结构路由模块 `group_entry_router.py`，它只处理：

1. 请求明确提供的 `target_agent_name`；
2. 已经通过严格校验的 `host_scheduler.message.target_agent_name`；
3. 无明确结构化目标时返回空，让主持人模型判断。

主持人模型的上下文构建器额外接收：

- 最近标准历史消息；
- 当前 `host_scheduler` 状态；
- 当前 `skill_sessions` 的结构化摘要。

主持人根据完整用户输入、历史和结构化上下文生成标准 JSON。平台不得使用“继续”“确认”“查看”“素材”“资料”“下一步”等任何关键词列表、正则或字符串包含判断替代主持人决策。

当主持人选择某专家时，专家运行时再向 `SkillSessionManager` 查询该专家是否存在有效绑定。路由模块不读取 Skill 绑定来决定下一位发言人。

## 9. 固定数据流

```text
模型或脚本 stdout
  -> 严格解析并选择唯一终态
  -> 投影为四个内部对象
  -> 发布非空专家输出
  -> 应用该专家 Skill Session keep/release
  -> 应用当前请求 Agent Turn continue/respond
       -> continue：同一专家进入下一次 turn
       -> respond：主持人重新调度
```

关键不变量：

- 输出发布发生在两类控制应用之前；
- `continue` 不能跳过输出发布；
- `failed` 和 `blocked` 仍然发布模型提供的用户可见说明；
- Skill Session 不触发路由；
- 路由不通过自然语言硬编码完成。

## 10. 错误处理

### 10.1 模型终态非法

完整 JSON 在任何内部投影前严格校验。校验失败时四个领域模块均不执行，平台写入标准失败消息和执行日志，返回稳定错误码。

### 10.2 输出发布失败

输出尚未成功落盘时，不应用 `skill_session` 和 `agent_turn`。本轮按平台运行失败结束，避免出现“控制已经继续但用户看不到上一轮输出”的状态。

### 10.3 Skill 绑定失效

如果保存的 Skill 不再属于该专家、无法加载或已删除，Skill Session 管理器删除该绑定。本轮专家按正常 Skill 选择流程重新选择，不通过旧字段兜底。

### 10.4 控制字段非法

控制字段属于完整模型 JSON 的严格校验范围，因此不会进入输出发布之后才发现非法值。不得对非法值默认成 `respond` 或 `release`。

## 11. 测试范围

### 11.1 契约测试

- 现有模型 JSON 继续通过校验；
- 模型无需输出新的内部模块结构；
- 非法字段、额外字段和非法枚举继续失败；
- 脚本 stdout 与 finalizer 冲突时失败。

### 11.2 输出测试

- 四种 `agent_turn × skill_session` 组合只要 `message` 非空都生成专家消息；
- `continue` 先产生 SSE `message`，再进入下一次 route/progress；
- `blocked` 和 `failed` 的用户可见消息正常落盘；
- 输出发布器代码不读取控制字段。

### 11.3 Agent Turn 测试

- `continue` 只在当前请求中重入同一专家；
- `respond` 返回主持人；
- turn 预算仍能终止无限执行；
- Agent Turn 控制器不读写跨轮状态。

### 11.4 Skill Session 测试

- `keep` 保存当前专家与实际 Skill；
- `release` 只删除当前专家绑定；
- 切换其他专家不会清理原专家绑定；
- 再次调度原专家时复用有效 Skill；
- 失效绑定被删除并重新选 Skill；
- Skill Session 不产生路由结果。

### 11.5 路由测试

- 显式 `target_agent_name` 优先；
- 严格主持人 JSON 的 `message.target_agent_name` 可路由；
- 无结构化目标时调用主持人模型；
- 代码和提示词不存在用户输入关键词路由表；
- Skill 绑定不会直接决定下一位专家。

### 11.6 回归场景

复现“用户要求先查看或确认检索素材”的会话：主持人读取自然语言、历史和 Skill Session 摘要后选择信息检索专家；专家产生非空消息且选择 `agent_turn=continue` 时，该消息必须先出现在 `history.json` 和 SSE 中，然后才开始下一次专家执行。

## 12. 删除与迁移范围

实现时删除或拆解：

- `group_chat_skill_session.py` 的混合职责；
- `group_orchestration_fsm.py`；
- `agent_turn=continue` 直接返回并吞掉消息的分支；
- `continuation.message`、`continuation.owner_agent_name`、`continuation.skill_session` 的混合状态结构；
- 所有基于用户文本关键词判断 continuation owner 的代码和测试；
- 已失效且只验证旧模块、旧状态结构或旧吞消息行为的测试。

保留并迁移：

- 模型 `expert_final_state.v2` JSON 外部协议；
- `execution_status`、`message`、`next_action.agent_turn`、`next_action.skill_session` 枚举；
- workspace 路径和产物严格校验；
- 工具执行日志与 `message_id` 的关联；
- 当前专家 turn 预算和主持人严格 JSON 调度。

## 13. 验收标准

1. 模型提示词和脚本 stdout 示例不需要改变 JSON 结构。
2. 平台内部存在独立的输出、Agent Turn、Skill Session 模块。
3. 任意合法控制组合下，非空专家消息均不会被丢弃。
4. `agent_turn` 不写跨轮状态，`skill_session` 不执行路由。
5. `orchestration_state.json` 不再用同一个 `continuation` 对象混存消息、Skill 和路由含义。
6. 不存在用户自然语言关键词路由代码。
7. 原失败场景通过端到端或等价集成测试。
8. 旧模块和失效测试被删除，不保留兼容兜底。
