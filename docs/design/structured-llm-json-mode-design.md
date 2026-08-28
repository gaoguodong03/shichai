# 结构化 LLM 输出 JSON 模式设计

本文是结构化控制输出链路的正式设计说明。

## 目标

让所有通过 `invoke_pydantic_llm_output(...)` 的控制面 LLM 调用在生成阶段进入 JSON Object 模式并获得调用方 Pydantic Model 的精确 JSON Schema，在接收阶段继续使用同一个 Model 做严格校验，消除主持人围栏 JSON 和专家复杂字段结构漂移两类协议错误。

## 根因

当前主持人调度已经把 `HostSchedulerDecisionPayload` 传给共享结构化输出网关，但网关直接调用普通 `client.ainvoke(...)`。模型因此仍在自由文本模式生成内容；实测默认模型首次会返回带 ````json` 围栏的对象，而平台合同只接受一个裸 JSON 对象。

Pydantic 校验位于 JSON 文本解析之后。带围栏的响应会在进入 `model_validate(...)` 前被拒绝，所以“已经使用 Pydantic”并不能约束模型生成格式。

## 设计

在 `structured_llm_output.py` 内新增一个私有客户端绑定函数：

- 当客户端提供可调用的 `bind` 方法时，调用 `bind(response_format={"type": "json_object"})`；
- 当客户端没有 `bind` 方法时，保留原客户端，使测试替身和非标准客户端继续由现有严格解析与重试处理；
- 当客户端经过 `TracedLLMClient` 包装但底层没有 `bind` 方法时，追踪包装器返回自身，继续保留提示词追踪并调用底层 `ainvoke(...)`；
- 首次调用和协议重试必须复用同一个已绑定客户端；
- 不剥离 Markdown 围栏、不提取文本中的 JSON、不放宽额外字段规则；
- 返回结果仍依次经过裸 JSON 解析、Pydantic `model_validate(...)` 和调用方 `post_validate` 业务校验。

当前默认兼容 provider 支持 `response_format={"type":"json_object"}`，但不支持原生 `json_schema` response format。因此采用两层生成约束：provider 层启用 JSON Object 模式，提示词层追加 `model.model_json_schema()` 生成的精确 Pydantic JSON Schema。接收端仍以同一个 Pydantic Model 为唯一验证来源，不复制手写字段清单，也不为 provider 增加未经支持的原生 JSON Schema 分支。

## 文件范围

- 修改 `backend/app/agent/structured_llm_output.py`：集中绑定 JSON Object 模式，并向首次调用和协议重试追加同一份 Pydantic JSON Schema。
- 修改 `backend/app/agent/llm_prompt_trace.py`：让追踪包装器准确回退到底层客户端能力。
- 修改 `backend/tests/test_structured_llm_output.py`：验证首次调用、协议重试和无 `bind` 客户端的行为。

不修改主持人协议字段、提示词、前端展示、持久化会话或现有历史数据。

## 测试设计

1. 新增支持 `bind(...)` 的记录客户端，断言网关在第一次模型调用前绑定 `response_format={"type": "json_object"}`。
2. 让第一次响应仍为非法自由文本、第二次为合法 JSON，断言两次 `ainvoke(...)` 都发生在 JSON 模式客户端上。
3. 保留不实现 `bind(...)` 的现有测试客户端，并覆盖其经过 `TracedLLMClient` 包装后的真实边界，证明兼容回退不改变严格解析、提示词追踪和重试语义。
4. 运行主持人调度测试，确认 `HostSchedulerDecisionPayload`、目标专家业务校验和协议错误行为保持不变。
5. 使用当前默认模型做一次不落盘复现，确认首次响应直接为裸 JSON，且主持人决策通过现有 Pydantic 校验。
6. 使用 `ExpertFinalStatePayload` 构造含 `ArtifactRef` 的终态，断言首次调用和协议重试都收到精确 Schema，模型不得把 `artifacts` 对象数组简写为路径字符串数组。

## 成功标准

- 结构化输出网关在支持时统一启用 JSON Object 模式；
- 结构化输出网关从调用方 Pydantic Model 动态生成 Schema，并在每次模型调用前追加；
- 主持人不再依赖“第一次失败后提醒模型去掉 Markdown 围栏”的概率性重试；
- Pydantic 仍是字段、类型、额外字段和业务组合规则的唯一验证来源；
- 不支持 `bind` 的客户端仍按原有严格协议工作；
- 定向测试和主持人相关回归测试全部通过。

## 专家终态协议重试

主持人调度修复后，真实场景暴露了第二个同类边界：专家业务工具全部执行成功，但专家最终化第一次返回的 JSON 缺少 Pydantic 必填字段时，`simple_agent_streaming.py` 的两个结构化最终化入口没有提供 `retry_messages`，导致整轮直接以 `LLM_RESPONSE_INVALID` 失败。

专家最终化遵循与主持人一致的一次纠正原则：

- “模型停止调用工具但内容不是终态”和“工具预算耗尽”共用一个结构化最终化调用；
- 第一次终态未通过 `ExpertFinalStatePayload` 时，追加现有 `agent.after_tool_result.decision.v1` 作为严格纠正提示；
- 第二次调用仍使用 JSON Object 模式和同一个 Pydantic Model；
- 纠正阶段不再绑定业务工具，不重跑 MCP、HTTP、workspace 或脚本；
- 第二次仍不合格时使用统一的 `LLM_RESPONSE_INVALID` 失败语义，不补字段、不放宽 Schema。

新增测试分别覆盖两个入口，均以第一次缺少 `next_action.skill_session`、第二次返回合法终态为红绿用例。

## 专家复杂字段生成约束

真实失败终态进一步证明，仅启用 JSON Object 模式和事后 Pydantic 校验仍不足以约束嵌套结构。默认模型把 `message.artifacts` 生成为路径字符串数组，而合同要求每一项都是包含 `type`、`name`、`path` 的 `ArtifactRef` 对象，因此两次响应都在接收端被拒绝。

共享网关在首次调用和协议重试的消息末尾追加由当前 Model 动态生成的 Pydantic JSON Schema，并明确要求对象字段不得简写为字符串、数组元素必须符合 `items` 定义。这样 `ExpertFinalStatePayload`、`HostSchedulerDecisionPayload` 和技能选择等结构化调用都从各自唯一 Model 获得生成约束；运行时仍拒绝非法结果，不做字符串到对象的猜测性归一化。
