# 结构化 LLM 输出 JSON 模式实现计划

本文按项目正式设计目录约定记录实现与验证步骤。

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:test-driven-development 按本计划顺序执行。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 让共享 Pydantic 输出网关在模型生成前统一启用 JSON Object 模式并注入精确 Pydantic JSON Schema，同时保持现有严格解析、Pydantic 校验与协议重试语义。

**架构：** 在 `structured_llm_output.py` 内集中完成 capability-safe 的 `client.bind(response_format={"type": "json_object"})`，并从调用方 Model 动态生成 JSON Schema 提示。首次调用与重试复用绑定后的客户端和同一份 Schema；调用方不重复管理 provider 输出模式或手写字段清单。

**技术栈：** Python 3.11、Pydantic v2、项目本地 OpenAI 兼容客户端、pytest、pytest-asyncio。

---

## 文件结构

- 修改 `backend/app/agent/structured_llm_output.py`：拥有结构化 LLM 调用的 JSON 模式绑定与 Pydantic 校验流程。
- 修改 `backend/app/agent/llm_prompt_trace.py`：底层无 `bind` 时安全保留追踪包装器。
- 修改 `backend/tests/test_structured_llm_output.py`：覆盖绑定、重试复用和无绑定能力回退。

### 任务 1：共享网关绑定 JSON Object 模式

**文件：**
- 修改：`backend/app/agent/structured_llm_output.py`
- 修改：`backend/app/agent/llm_prompt_trace.py`
- 测试：`backend/tests/test_structured_llm_output.py`

- [ ] **步骤 1：编写失败的首次调用 JSON 模式测试**

新增带 `bind(...)` 的记录客户端，调用 `invoke_pydantic_llm_output(...)` 后断言：

```python
assert client.bind_calls == [{"response_format": {"type": "json_object"}}]
assert client.json_mode_calls == 1
```

- [ ] **步骤 2：运行测试并验证正确失败**

运行：

```bash
rtk conda run -n st49 pytest backend/tests/test_structured_llm_output.py::test_invoke_pydantic_llm_output_binds_json_object_mode -q
```

预期：FAIL；当前网关从未调用客户端 `bind(...)`。

- [ ] **步骤 3：编写失败的重试复用测试**

让绑定客户端依次返回 `说明：{"selected_skill":"writer"}` 和 `{"selected_skill":"research"}`，断言只绑定一次且两次模型调用都处于 JSON 模式。

- [ ] **步骤 4：运行重试测试并验证正确失败**

运行：

```bash
rtk conda run -n st49 pytest backend/tests/test_structured_llm_output.py::test_invoke_pydantic_llm_output_reuses_json_mode_for_retry -q
```

预期：FAIL；当前首次调用和重试均使用未绑定客户端。

- [ ] **步骤 5：实现最小 JSON 模式绑定**

在 `structured_llm_output.py` 新增：

```python
def _bind_json_object_mode(client: Any) -> Any:
    bind = getattr(client, "bind", None)
    if not callable(bind):
        return client
    return bind(response_format={"type": "json_object"})
```

并在第一次 `ainvoke(...)` 前绑定一次，首次调用和重试都使用返回的客户端。

为经过提示词追踪包装、但底层没有 `bind` 的客户端补充失败测试；在 `TracedLLMClient.bind(...)` 中仅当底层 `bind` 可调用时才转发，否则返回当前包装器。

- [ ] **步骤 6：运行结构化网关测试确认通过**

运行：

```bash
rtk conda run -n st49 pytest backend/tests/test_structured_llm_output.py -q
```

预期：全部通过；裸客户端和经过提示词追踪包装的无 `bind` 客户端都继续证明兼容回退。

- [ ] **步骤 7：运行主持人和专家结构化输出回归测试**

运行：

```bash
rtk conda run -n st49 pytest backend/tests/test_host_takeover.py backend/tests/test_group_host_decision.py backend/tests/test_platform_prompts.py -q
```

预期：全部通过，主持人严格字段和业务校验语义不变。

- [ ] **步骤 8：运行静态编译检查**

运行：

```bash
rtk conda run -n st49 python -m compileall -q backend/app/agent/structured_llm_output.py backend/app/agent/llm_prompt_trace.py backend/tests/test_structured_llm_output.py
```

预期：退出码 0。

- [ ] **步骤 9：不落盘验证当前模型**

使用当前用户的默认模型和协作主持人配置调用 `_host_decide_by_agent(...)`，记录原始响应并确认：

```text
响应以 { 开始并以 } 结束
主持人决策 current_phase != 协议错误
```

诊断脚本不得调用会话保存函数，不得修改 `history.json`、`orchestration_state.json` 或执行日志。

- [ ] **步骤 10：检查差异并选择性提交**

只暂存以下文件，不包含工作区既有修改：

```bash
rtk git add backend/app/agent/structured_llm_output.py backend/app/agent/llm_prompt_trace.py backend/tests/test_structured_llm_output.py docs/design/structured-llm-json-mode-design.md docs/design/structured-llm-json-mode-plan.md
rtk git diff --cached --check
rtk git commit -m "fix(协议): 为 Pydantic 输出启用 JSON 模式"
```

### 任务 2：专家终态增加一次 Pydantic 协议纠正

**文件：**
- 修改：`backend/app/agent/simple_agent_streaming.py`
- 测试：`backend/tests/test_simple_agent_tool_intent.py`

- [x] **步骤 1：建立两个失败用例**

分别覆盖模型停止工具和工具预算耗尽路径。第一次最终化返回缺少 `next_action.skill_session` 的 JSON，第二次返回合法 `ExpertFinalStatePayload`；修复前预期首次校验后直接抛出 `StructuredOutputProtocolError`。

- [x] **步骤 2：实现共享最终化调用**

新增嵌套 `_invoke_structured_finalizer(...)`，首次调用使用当前消息，协议重试使用当前消息加 `_post_tool_decision_instruction(...)`；两个最终化入口都调用该函数。

- [x] **步骤 3：验证不重跑业务工具**

断言最终化客户端调用两次且均为 JSON 模式，工具调用计数保持一次，最终消息来自第二次合法响应。

- [x] **步骤 4：运行回归**

```bash
rtk conda run -n st49 pytest backend/tests/test_simple_agent_tool_intent.py backend/tests/test_structured_llm_output.py backend/tests/test_expert_runtime.py backend/tests/test_group_chat_stream_protocol.py -q
```

预期：全部通过。

### 任务 3：把 Pydantic Schema 前移到模型生成阶段

**文件：**
- 修改：`backend/app/agent/structured_llm_output.py`
- 测试：`backend/tests/test_structured_llm_output.py`
- 测试：`backend/tests/test_simple_agent_tool_intent.py`

- [x] **步骤 1：建立复杂字段失败用例**

使用 `ExpertFinalStatePayload` 让第一次响应把 `message.artifacts` 错误生成为路径字符串数组，第二次返回合法 `ArtifactRef` 对象；断言首次调用和重试消息都必须包含 Model 的 Pydantic JSON Schema。修复前测试应因消息中不存在 Schema 而失败。

- [x] **步骤 2：在共享网关动态生成 Schema 提示**

调用 `model.model_json_schema()`，以紧凑 JSON 追加到模型消息末尾；明确要求对象字段不得简写、数组元素服从 `items`，且只返回一个 JSON 对象。首次调用与协议重试使用同一份提示。

- [x] **步骤 3：保持接收端严格语义**

继续使用 `parse_strict_pydantic_object(...)` 和调用方 `post_validate`；不把字符串路径自动补成 `ArtifactRef`，第二次仍不合格时继续抛出 `StructuredOutputProtocolError`。

- [x] **步骤 4：运行专家链路和真实模型不落盘验证**

确认专家最终化生成合法 `ArtifactRef` 对象，且诊断过程不保存会话、不重跑业务工具、不修改现有历史。
