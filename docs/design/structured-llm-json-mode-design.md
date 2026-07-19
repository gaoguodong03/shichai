# 结构化 LLM 输出 JSON 模式设计

本文是结构化控制输出链路的正式设计说明。

## 目标

让所有通过 `invoke_pydantic_llm_output(...)` 的控制面 LLM 调用在生成阶段进入 JSON Object 模式，并在接收阶段继续使用调用方传入的 Pydantic Model 做严格校验，消除主持人偶发返回 Markdown 围栏 JSON 后连续重试失败的问题。

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

选择 JSON Object 模式而不是直接发送 JSON Schema，是因为项目现有 OpenAI 兼容适配器和专家终态链路已经使用并测试了该模式；字段级严格性继续由唯一的 Pydantic Model 负责，避免为不同兼容 provider 引入未经验证的 JSON Schema 能力分支。

## 文件范围

- 修改 `backend/app/agent/structured_llm_output.py`：集中绑定 JSON Object 模式。
- 修改 `backend/app/agent/llm_prompt_trace.py`：让追踪包装器准确回退到底层客户端能力。
- 修改 `backend/tests/test_structured_llm_output.py`：验证首次调用、协议重试和无 `bind` 客户端的行为。

不修改主持人协议字段、提示词、前端展示、持久化会话或现有历史数据。

## 测试设计

1. 新增支持 `bind(...)` 的记录客户端，断言网关在第一次模型调用前绑定 `response_format={"type": "json_object"}`。
2. 让第一次响应仍为非法自由文本、第二次为合法 JSON，断言两次 `ainvoke(...)` 都发生在 JSON 模式客户端上。
3. 保留不实现 `bind(...)` 的现有测试客户端，并覆盖其经过 `TracedLLMClient` 包装后的真实边界，证明兼容回退不改变严格解析、提示词追踪和重试语义。
4. 运行主持人调度测试，确认 `HostSchedulerDecisionPayload`、目标专家业务校验和协议错误行为保持不变。
5. 使用当前默认模型做一次不落盘复现，确认首次响应直接为裸 JSON，且主持人决策通过现有 Pydantic 校验。

## 成功标准

- 结构化输出网关在支持时统一启用 JSON Object 模式；
- 主持人不再依赖“第一次失败后提醒模型去掉 Markdown 围栏”的概率性重试；
- Pydantic 仍是字段、类型、额外字段和业务组合规则的唯一验证来源；
- 不支持 `bind` 的客户端仍按原有严格协议工作；
- 定向测试和主持人相关回归测试全部通过。
