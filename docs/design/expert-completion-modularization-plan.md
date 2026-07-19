# 专家完成结果平台内部分层实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在不改变模型 `expert_final_state.v2` JSON 的前提下，将专家输出发布、当前请求 Agent Turn 和跨轮 Skill Session 拆成独立平台模块，并保证 `agent_turn=continue` 不再吞掉非空专家消息。

**架构：** `expert_completion_contract.py` 负责严格解析并投影四个内部对象；`expert_output_publisher.py`、`agent_turn_controller.py`、`skill_session_manager.py` 分别消费自己的对象；`expert_completion_coordinator.py` 按“输出、Skill Session、Agent Turn”固定顺序协调。入口路由改为纯结构路由，不读取用户文本关键词，也不把 Skill 绑定当作下一位专家。

**技术栈：** Python 3、Pydantic v2、FastAPI SSE、pytest、JSON 文件会话状态。

---

## 文件结构

- 创建 `backend/app/agent/expert_completion_contract.py`：现有模型 JSON 的严格解析、唯一终态选择和内部对象投影。
- 创建 `backend/app/agent/expert_output_publisher.py`：标准专家消息构造、历史落盘、工具日志关联和 SSE 消息生成。
- 创建 `backend/app/agent/agent_turn_controller.py`：解释 `continue|respond`，只返回当前请求内部控制结果。
- 创建 `backend/app/agent/skill_session_manager.py`：按专家管理 `skill_sessions` 绑定。
- 创建 `backend/app/agent/expert_completion_coordinator.py`：按固定顺序调用三个领域模块。
- 创建 `backend/app/agent/group_entry_router.py`：替代名不副实的 FSM，仅处理结构化目标。
- 修改 `backend/app/agent/group_chat_expert_turn.py`：缩减为执行流收集与完成协调。
- 修改 `backend/app/agent/group_chat_runtime.py`：使用新入口路由和 Agent Turn 结果。
- 修改 `backend/app/agent/expert_runtime.py`：从 `SkillSessionManager` 获取锁定 Skill。
- 修改 `backend/app/agent/group_chat_host_runtime.py`、`backend/app/agent/group_context.py`：向主持人提供结构化 Skill Session 摘要，不做文本分类。
- 修改 `backend/app/agent/structured_output_contracts.py`：移出专家终态专属模型，保留其他严格输出契约。
- 删除 `backend/app/agent/group_chat_skill_session.py`、`backend/app/agent/skill_session_locks.py`、`backend/app/agent/group_orchestration_fsm.py`。
- 创建 `backend/tests/test_expert_completion_contract.py`、`backend/tests/test_expert_output_publisher.py`、`backend/tests/test_agent_turn_controller.py`、`backend/tests/test_skill_session_manager.py`、`backend/tests/test_group_entry_router.py`。
- 修改 `backend/tests/test_group_chat_stream_protocol.py`、`backend/tests/test_host_takeover.py`、`backend/tests/test_group_chat_state.py`、`backend/tests/test_expert_runtime.py`。
- 删除只验证旧 `continuation`、旧 FSM 或“continue 不发布消息”的失效测试。
- 修改 `docs/contracts/runtime-interface-contract.md`、`docs/contracts/data-structure-and-field-logic.md`、`docs/design/detailed-design-spec.md`、`docs/skills/skill-session-flow.md`、`docs/skills/skill-standard.md`。

### 任务 1：建立专家完成结果内部投影

**文件：**
- 创建：`backend/app/agent/expert_completion_contract.py`
- 修改：`backend/app/agent/structured_output_contracts.py`
- 创建：`backend/tests/test_expert_completion_contract.py`
- 删除：`backend/tests/test_group_chat_skill_session.py` 中终态解析测试迁移后的重复部分

- [ ] **步骤 1：编写失败的内部投影测试**

```python
def test_existing_model_json_projects_to_four_internal_objects():
    completion = parse_expert_completion(json.dumps(v2_payload(agent_turn="continue", skill_session="keep")))
    assert completion.execution.status == "succeeded"
    assert completion.output.message.content == "本轮专家回复已完成。"
    assert completion.agent_turn.action == "continue"
    assert completion.skill_session.action == "keep"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`rtk pytest -q backend/tests/test_expert_completion_contract.py`

预期：FAIL，`app.agent.expert_completion_contract` 尚不存在。

- [ ] **步骤 3：实现最小严格投影**

```python
@dataclass(frozen=True)
class ParsedExpertCompletion:
    execution: ExpertExecutionOutcome
    output: ExpertOutputSubmission
    agent_turn: AgentTurnDirective
    skill_session: SkillSessionDirective

def project_expert_completion(payload: ExpertFinalStatePayload) -> ParsedExpertCompletion:
    return ParsedExpertCompletion(
        execution=ExpertExecutionOutcome(status=payload.execution_status),
        output=ExpertOutputSubmission(message=payload.message),
        agent_turn=AgentTurnDirective(action=payload.next_action.agent_turn),
        skill_session=SkillSessionDirective(action=payload.next_action.skill_session),
    )
```

把现有 finalizer JSON、脚本 stdout 和冲突检测逻辑迁入本模块；模型 JSON 和错误码不变。

- [ ] **步骤 4：验证契约测试通过**

运行：`rtk pytest -q backend/tests/test_expert_completion_contract.py backend/tests/test_structured_llm_output.py backend/tests/test_skill_stdout_contracts.py`

预期：全部通过。

### 任务 2：拆出专家输出发布器并修复吞消息行为

**文件：**
- 创建：`backend/app/agent/expert_output_publisher.py`
- 创建：`backend/tests/test_expert_output_publisher.py`
- 修改：`backend/app/agent/group_chat_expert_turn.py`
- 修改：`backend/tests/test_group_chat_stream_protocol.py`

- [ ] **步骤 1：把旧反向断言改成失败回归测试**

将 `test_expert_turn_continue_does_not_persist_or_emit_message` 替换为：

在现有 async 测试装配中，把 finalizer 内容改为非空，并把断言替换为：

```python
assert [payload["message"]["content"] for event, payload in events if event == "message"] == [
    "本轮先报告已完成的结果。"
]
assert messages[-1]["message"]["content"] == "本轮先报告已完成的结果。"
assert state.load_group_history("s-expert-continue")[-1]["message"]["content"] == "本轮先报告已完成的结果。"
assert outcome.agent_turn == "continue"
```

新增发布器边界测试，静态确认发布器不引用 `AgentTurnDirective`、`SkillSessionDirective` 或 `next_action`。

- [ ] **步骤 2：运行测试验证当前实现失败**

运行：`rtk pytest -q backend/tests/test_expert_output_publisher.py backend/tests/test_group_chat_stream_protocol.py::test_expert_turn_continue_persists_and_emits_message_before_next_turn`

预期：FAIL，当前 `continue` 分支在消息生成前返回。

- [ ] **步骤 3：实现独立发布器**

```python
@dataclass(frozen=True)
class PublishedExpertMessage:
    record: dict[str, Any]

def build_expert_message_record(
    *,
    submission: ExpertOutputSubmission,
    execution: ExpertExecutionOutcome,
    agent_name: str,
    skill: str,
    message_id: str,
    created_at: str,
) -> PublishedExpertMessage | None:
    if submission.is_empty:
        return None
    record = {
        "message_id": message_id,
        "speaker": {"type": "expert", "agent_name": agent_name, "skill": skill},
        "message": submission.message.model_dump(exclude_none=True, exclude_defaults=True),
        "created_at": created_at,
        "skill_result": {"execution_status": execution.status},
    }
    return PublishedExpertMessage(record=record)
```

`run_one_expert_turn()` 必须先调用发布器并 yield SSE，再应用任何控制结果。

- [ ] **步骤 4：验证输出与流协议测试通过**

运行：`rtk pytest -q backend/tests/test_expert_output_publisher.py backend/tests/test_group_chat_stream_protocol.py`

预期：全部通过。

### 任务 3：拆分 Agent Turn 与 Skill Session

**文件：**
- 创建：`backend/app/agent/agent_turn_controller.py`
- 创建：`backend/app/agent/skill_session_manager.py`
- 创建：`backend/app/agent/expert_completion_coordinator.py`
- 创建：`backend/tests/test_agent_turn_controller.py`
- 创建：`backend/tests/test_skill_session_manager.py`
- 修改：`backend/app/agent/expert_runtime.py`
- 修改：`backend/tests/test_expert_runtime.py`
- 删除：`backend/app/agent/group_chat_skill_session.py`
- 删除：`backend/app/agent/skill_session_locks.py`

- [ ] **步骤 1：编写两个生命周期的失败测试**

```python
def test_agent_turn_continue_has_no_persisted_state():
    assert apply_agent_turn(AgentTurnDirective("continue")) == AgentTurnResult.CONTINUE_EXPERT

def test_skill_sessions_are_isolated_by_expert():
    state = {"skill_sessions": {"检索专家": {"skill": "research"}}}
    apply_skill_session(state, agent_name="写作专家", skill="writer", action="keep")
    assert state["skill_sessions"] == {
        "检索专家": {"skill": "research"},
        "写作专家": {"skill": "writer"},
    }

def test_release_removes_only_current_expert_binding():
    state = {"skill_sessions": {"检索专家": {"skill": "research"}, "写作专家": {"skill": "writer"}}}
    apply_skill_session(state, agent_name="写作专家", skill="writer", action="release")
    assert state == {"skill_sessions": {"检索专家": {"skill": "research"}}}
```

- [ ] **步骤 2：运行测试验证失败**

运行：`rtk pytest -q backend/tests/test_agent_turn_controller.py backend/tests/test_skill_session_manager.py`

预期：FAIL，新模块尚不存在。

- [ ] **步骤 3：实现两个独立控制模块和薄协调器**

```python
def apply_skill_session(state, *, agent_name, skill, directive) -> bool:
    sessions = state.setdefault("skill_sessions", {})
    if directive.action == "keep":
        previous = sessions.get(agent_name)
        sessions[agent_name] = {"skill": skill}
        return previous != sessions[agent_name]
    removed = sessions.pop(agent_name, None) is not None
    if not sessions:
        state.pop("skill_sessions", None)
    return removed
```

协调器顺序固定为 output publisher → skill session manager → agent turn controller，不允许控制模块读取消息正文。

- [ ] **步骤 4：迁移专家 Skill 锁定读取**

`resolve_expert_skill()` 只调用：

```python
locked = skill_session_for_expert(orchestration_state, agent_name, skill_directories)
```

失效绑定只删除该专家键，不清理其他专家，不提供路由结果。

- [ ] **步骤 5：验证控制与专家运行时测试**

运行：`rtk pytest -q backend/tests/test_agent_turn_controller.py backend/tests/test_skill_session_manager.py backend/tests/test_expert_runtime.py backend/tests/test_group_chat_stream_protocol.py`

预期：全部通过。

### 任务 4：删除 FSM 并建立纯结构入口路由

**文件：**
- 创建：`backend/app/agent/group_entry_router.py`
- 创建：`backend/tests/test_group_entry_router.py`
- 修改：`backend/app/agent/group_chat_runtime.py`
- 修改：`backend/tests/test_host_takeover.py`
- 删除：`backend/app/agent/group_orchestration_fsm.py`
- 删除：`backend/tests/test_group_orchestration_fsm.py`

- [ ] **步骤 1：编写结构路由测试**

```python
def test_explicit_target_routes_without_touching_skill_sessions():
    state = {"skill_sessions": {"检索专家": {"skill": "research"}}}
    decision, changed = resolve_group_entry_route(
        request=_request(target_agent_name="写作专家"),
        orchestration_state=state,
        agent_names=["检索专家", "写作专家"],
        default_next_action="默认动作",
    )
    assert decision.next_speaker == "写作专家"
    assert changed is False
    assert state["skill_sessions"]["检索专家"]["skill"] == "research"

def test_no_structured_target_returns_none_even_with_skill_binding():
    state = {"skill_sessions": {"检索专家": {"skill": "research"}}}
    decision, changed = resolve_group_entry_route(
        request=_request("任意自然语言"),
        orchestration_state=state,
        agent_names=["检索专家", "写作专家"],
        default_next_action="默认动作",
    )
    assert decision is None
    assert changed is False
```

- [ ] **步骤 2：运行测试验证失败**

运行：`rtk pytest -q backend/tests/test_group_entry_router.py`

预期：FAIL，新模块尚不存在。

- [ ] **步骤 3：迁移纯结构逻辑并删除旧 FSM**

路由只读取 `request.target_agent_name` 和 `host_scheduler.message.target_agent_name`。删除 `skill_session`、`skill` 和 continuation 清理副作用等路由返回字段；删除 `suppress_host_message` 中已失效的 `continuation` route source。

- [ ] **步骤 4：验证路由与主持人接管测试**

运行：`rtk pytest -q backend/tests/test_group_entry_router.py backend/tests/test_host_takeover.py backend/tests/test_group_chat_stream_protocol.py`

预期：全部通过。

### 任务 5：把 Skill Session 摘要交给主持人模型

**文件：**
- 修改：`backend/app/agent/group_context.py`
- 修改：`backend/app/agent/group_chat_host_runtime.py`
- 修改：`backend/app/agent/platform_prompt_templates.json`
- 创建或修改：`backend/tests/test_platform_prompts.py`
- 修改：`backend/tests/test_host_takeover.py`

- [ ] **步骤 1：编写失败的主持人上下文测试**

```python
def test_host_prompt_receives_structured_skill_sessions_without_keyword_rules():
    prompt = render_platform_prompt(
        "host.select_next_speaker.v1",
        {
            "agent_names": "信息检索专家",
            "current_phase": "等待用户确认",
            "user_message": "由用户自由表达",
            "recent_history": "上一轮检索已经完成",
            "skill_sessions": '{"信息检索专家":{"skill":"research"}}',
        },
    )
    assert '"信息检索专家"' in prompt
    assert '"skill": "research"' in prompt
    assert "确认 / 查看 / 素材" not in prompt
```

- [ ] **步骤 2：运行测试验证失败**

运行：`rtk pytest -q backend/tests/test_platform_prompts.py backend/tests/test_host_takeover.py`

预期：至少新增上下文断言失败。

- [ ] **步骤 3：实现结构化上下文组装**

主持人提示词明确：Skill Session 只是可复用 Skill 信息；是否选择该专家必须根据完整用户输入、历史和当前任务判断，并通过标准 `message.target_agent_name` 表达。不得加入关键词示例或后端文本分类器。

- [ ] **步骤 4：验证主持人相关测试**

运行：`rtk pytest -q backend/tests/test_platform_prompts.py backend/tests/test_host_takeover.py backend/tests/test_group_chat_stream_protocol.py`

预期：全部通过。

### 任务 6：迁移持久化契约、文档并删除失效测试

**文件：**
- 修改：`backend/app/api/group_chat_state.py`
- 修改：`backend/tests/test_group_chat_state.py`
- 修改：`backend/tests/test_group_chat_cleanup_contract.py`
- 修改：`docs/contracts/runtime-interface-contract.md`
- 修改：`docs/contracts/data-structure-and-field-logic.md`
- 修改：`docs/design/detailed-design-spec.md`
- 修改：`docs/skills/skill-session-flow.md`
- 修改：`docs/skills/skill-standard.md`

- [ ] **步骤 1：把状态测试改成 `skill_sessions` 严格结构**

测试保存、加载、空 map 清理、多专家绑定和旧 `continuation` 不再作为运行时兜底。删除只断言旧结构的测试文件或测试函数。

- [ ] **步骤 2：运行状态与文档契约测试验证失败**

运行：`rtk pytest -q backend/tests/test_group_chat_state.py backend/tests/test_group_chat_cleanup_contract.py backend/tests/test_docs_contract_alignment.py`

预期：旧 continuation 文档和代码引用导致失败。

- [ ] **步骤 3：同步权威契约和设计文档**

所有文档保持模型 JSON 不变，只把平台内部结构从 `continuation` 改为 `skill_sessions`，明确输出发布早于两个控制模块，并删除“Skill continuation 自动路由”的表述。

- [ ] **步骤 4：运行状态、文档与静态残留检查**

运行：

```bash
rtk pytest -q backend/tests/test_group_chat_state.py backend/tests/test_group_chat_cleanup_contract.py backend/tests/test_docs_contract_alignment.py
rtk rg -n "group_orchestration_fsm|group_chat_skill_session|skill_session_locks|continuation\.message|CONTINUATION_CONFIRMATION|HOST_TAKEOVER_TOKENS" backend/app backend/tests docs/contracts docs/skills
```

预期：测试全部通过；残留检查无运行时或目标文档命中。

### 任务 7：完整验证

**文件：**
- 验证本计划全部变更，不修改 `backend/data/users`。

- [ ] **步骤 1：运行 Python 编译检查**

运行：`rtk python -m compileall -q backend/app/agent backend/app/api/group_chat_state.py`

预期：退出码 0。

- [ ] **步骤 2：运行专家、编排、消息和文档测试集**

运行：

```bash
rtk pytest -q \
  backend/tests/test_expert_completion_contract.py \
  backend/tests/test_expert_output_publisher.py \
  backend/tests/test_agent_turn_controller.py \
  backend/tests/test_skill_session_manager.py \
  backend/tests/test_group_entry_router.py \
  backend/tests/test_expert_runtime.py \
  backend/tests/test_group_chat_stream_protocol.py \
  backend/tests/test_host_takeover.py \
  backend/tests/test_group_chat_state.py \
  backend/tests/test_message_contracts.py \
  backend/tests/test_platform_prompts.py \
  backend/tests/test_docs_contract_alignment.py
```

预期：全部通过。

- [ ] **步骤 3：运行前端流事件回归测试**

运行：`rtk pytest -q backend/tests/test_frontend_route_and_context_contracts.py`

预期：本次相关断言通过；若仍存在已记录的 `useWorkspaceContentProviders.ts` 行数阈值失败，单独报告且不扩大本任务范围。

- [ ] **步骤 4：检查工作区边界**

运行：`rtk git status --short && rtk git diff --check`

预期：没有修改 `backend/data/users`；没有空白错误；所有无关既有改动保持原样。
