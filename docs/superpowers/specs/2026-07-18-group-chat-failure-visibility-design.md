# 群聊专家失败可见性与追踪设计

## 目标

修复群聊中“主持人已显示发送给专家，但专家没有回复且页面没有错误提示”的问题，并确保同类失败可以从会话数据中追溯到稳定错误码和脱敏错误摘要。

本次只收口失败链路，不改变成功消息、主持人调度、专家选择、Skill 路由或工具调用语义。

## 已确认根因

后端专家运行失败时会发送 `error`，随后发送 `end(phase=failed)`。前端在收到 `end` 后把请求视为已经正常结束，现有错误兜底条件不再成立；同时前端没有读取 SSE 错误对象的 `message` 字段。因此错误既没有形成可见消息，也没有可靠写入会话历史或执行日志。

当前故障会话只保留用户消息、主持人交接消息和主持人执行日志，无法在事后恢复专家失败的精确异常。这是观测链路缺口，不应通过猜测补全历史事实。

## 方案

采用标准失败消息加运行日志的方案，不新增 `speaker.type=system`。

### 后端失败消息

专家已经确定时，失败消息使用：

- `speaker.type = expert`
- `speaker.agent_name = 当前专家`
- `speaker.skill = 已解析 Skill`，未知时省略
- `message.content = 面向用户的中文失败说明，包含稳定错误码，不包含堆栈、密钥、请求头或原始工具正文`
- `skill_result.execution_status = failed`
- `skill_result.next_action.agent_turn = respond`
- `skill_result.next_action.skill_session = release`

专家尚未确定的流级异常使用主持人消息承载，避免引入新的消息类型。失败消息必须先写入 `history.json`，再作为 SSE `message` 发出，随后发送 `end(phase=failed)`。

### 运行日志

为失败消息写一条与 `message_id` 关联的运行日志。日志记录：

- 稳定错误码
- 异常类型
- 脱敏后的错误摘要
- 失败阶段
- 当前专家和 Skill（已知时）

运行日志不保存 Python traceback、认证信息、完整提示词、原始 MCP/HTTP 正文或用户密钥。完整堆栈仍只进入服务端日志。

### SSE 与前端

失败事件顺序固定为：

1. `error`
2. 已持久化的失败 `message`
3. `end`，其中 `phase=failed`、`waiting_for_user=true`

前端需要：

- 从 SSE 错误对象的 `message`、`detail`、`error` 中依次提取可见摘要。
- 不能因为随后收到 `end` 就清除 `streamServerErrored`。
- 如果本轮已经收到后端失败消息，不再追加第二条本地错误消息。
- 如果连接中断、旧后端没有发送失败消息或消息事件解析失败，则追加一条本地错误提示。
- 失败结束不能被当作成功的 `messageSent` 结果。

## 数据边界

- `history.json` 继续只保存标准消息对象；失败状态通过 `skill_result.execution_status` 表达。
- `execution_logs/tool-execution.jsonl` 保存运行诊断事实，并通过 `message_id` 与失败消息关联。
- `orchestration_state.json` 不保留已经失败的主持人调度或 continuation 锁，避免刷新后继续错误路线。
- 不修改已有会话历史；修复只影响修复后的新运行。

## 测试设计

后端回归测试覆盖：

1. 专家最终态非法时，历史中保存一条 `failed` 专家消息，并写入关联运行日志。
2. 专家运行时抛出异常时，SSE 顺序为 `error -> message -> end`。
3. 失败后清理短期编排状态。
4. 失败消息和日志不包含 traceback 或敏感字段。

前端回归测试覆盖：

1. `error -> end(failed)` 仍显示错误。
2. 正确读取 SSE 的 `message` 字段。
3. 已收到后端失败消息时不重复追加本地错误。
4. `end(phase=failed)` 不返回成功的消息发送结果。

真实验证使用一个新建测试会话复现“沈腾演艺生涯资料检索”场景，检查页面失败可见性、`history.json`、运行日志和 `orchestration_state.json`。不回写或修补旧会话历史。

## 完成标准

- 用户不再看到只有主持人交接、没有专家回复或错误的空白结尾。
- 任一专家失败都能从失败消息和关联日志定位到稳定错误码与失败阶段。
- 成功场景行为不变。
- 定向后端测试、前端测试、前端构建和相关回归全部通过。
- 真实场景要么完整返回专家结果，要么返回可见、可追踪的失败；不得静默结束。
