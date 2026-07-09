# 文档优先运行契约重写实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 以 `docs/contracts/runtime-interface-contract.md` 和 `docs/contracts/data-structure-and-field-logic.md` 为唯一运行契约，删除主路径旧字段兜底并重写不一致实现。

**架构：** 后端以 `session.json`、`history.json`、`runtime.json`、`orchestration_state.json` 和 checkpoint 对象为单一事实源；API 只做薄转发和 SSE 分发；前端只消费结构化事件和消息事实，不从正文反推业务状态。每个契约面先写失败测试，再改实现，再运行聚焦验证。

**技术栈：** FastAPI、Pydantic、pytest、Vue 3、TypeScript、Playwright mock、文件化 JSON 存储。

---

## 文件结构

- 修改：`backend/app/api/group_chat_state.py`，负责 `runtime.json` 和 `orchestration_state.json` 的读写、运行态事件发布。
- 修改：`backend/app/agent/group_session_service.py`，负责 `/events/stream` 的目标事件名和 payload。
- 修改：`backend/app/agent/group_chat_runtime.py`，负责 `/chat/stream` 的 `start` 事件、目标 phase、从 `orchestration_state.json` 读取路由状态。
- 修改：`backend/app/agent/group_chat_host_runtime.py`，负责主持人 `host_scheduler` 的读取输入和决策输出，不再写 `session.json.scheduler_state`。
- 修改：`backend/app/agent/expert_runtime.py`、`backend/app/agent/skill_session_locks.py`，负责用 `orchestration_state.json.continuation` 表示 Skill 接续，不再读写 `skill_session_owner_name` / `skill_session_skill`。
- 修改：`backend/app/api/settings_app.py`、`backend/app/api/sessions.py`，负责 `settings/app.json.host` 默认主持人契约。
- 重写：`backend/app/session_state/service.py`、`backend/app/session_state/store.py`、`backend/app/session_state/paths.py`，负责新 checkpoint 对象，不再暴露 Git commit 模型或 `chat.md` 消息快照。
- 修改：`frontend/src/api/chat.ts`，负责 `/chat/stream` 和 `/events/stream` 事件分发类型。
- 修改：`frontend/src/features/workspace/composables/useGroupOrchestrationState.ts`、`frontend/src/features/workspace/workspaceMessageUtils.ts`，删除正文正则和旧 routing debug 读取。
- 修改：`frontend/e2e/fixtures/mockApi.ts`，作为接口契约 mock，不再保留旧事件或旧字段。
- 测试：更新或重写 `backend/tests/test_group_chat_state.py`、`backend/tests/test_sessions_api.py`、`backend/tests/test_host_takeover.py`、`backend/tests/test_expert_runtime.py`、`backend/tests/test_session_state_gitlike.py`，并新增目标契约测试文件。

## 任务 1：SSE 事件契约

**文件：**
- 修改：`backend/app/agent/group_session_service.py`
- 修改：`backend/app/api/group_chat_state.py`
- 修改：`frontend/src/api/chat.ts`
- 修改：`frontend/e2e/fixtures/mockApi.ts`
- 测试：`backend/tests/test_group_chat_state.py`
- 测试：`backend/tests/test_sessions_api.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_session_events_stream_emits_snapshot_event_name_and_runtime_payload():
    ...
    assert raw.startswith("event: snapshot\n")
    assert data["runtime"]["running"] is False
    assert "runtime_state" not in data
```

- [ ] **步骤 2：运行测试验证失败**

运行：`rtk python -m pytest backend/tests/test_sessions_api.py::test_session_events_stream_emits_snapshot_event_name_and_runtime_payload -q`
预期：FAIL，当前实现输出 `event: session_update` 或 `runtime_state`。

- [ ] **步骤 3：实现最少代码**

将订阅初始包改为 `event: snapshot`，字段为 `session_id/server_time/runtime/last_message_id/updated_at`；运行态变化发布 `event: runtime`；保活包为 `server_time`。

- [ ] **步骤 4：运行测试验证通过**

运行：`rtk python -m pytest backend/tests/test_sessions_api.py::test_session_events_stream_emits_snapshot_event_name_and_runtime_payload -q`
预期：PASS。

## 任务 2：聊天流 start 与 phase 契约

**文件：**
- 修改：`backend/app/agent/group_chat_runtime.py`
- 修改：`frontend/src/api/chat.ts`
- 修改：`frontend/e2e/fixtures/mockApi.ts`
- 测试：`backend/tests/test_group_chat_stream_protocol.py`

- [ ] **步骤 1：编写失败测试**

```python
async def test_chat_stream_starts_with_start_event_and_uses_target_phase_enum():
    events = await collect_chat_events(...)
    assert events[0][0] == "start"
    assert all(payload.get("phase") != "agent_running" for _, payload in events)
    assert all(payload.get("phase") != "message_ready" for _, payload in events)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`rtk python -m pytest backend/tests/test_group_chat_stream_protocol.py::test_chat_stream_starts_with_start_event_and_uses_target_phase_enum -q`
预期：FAIL，当前没有 `start` 事件且仍有旧 phase。

- [ ] **步骤 3：实现最少代码**

`group_chat_stream()` 注册运行后立即发送 `start`；专家执行阶段使用 `executing`，消息落盘阶段使用 `finalizing`，正常结束使用 `completed/awaiting_user/recruiting`。

- [ ] **步骤 4：运行测试验证通过**

运行：`rtk python -m pytest backend/tests/test_group_chat_stream_protocol.py::test_chat_stream_starts_with_start_event_and_uses_target_phase_enum -q`
预期：PASS。

## 任务 3：`orchestration_state.json` 主路径

**文件：**
- 修改：`backend/app/api/group_chat_state.py`
- 修改：`backend/app/agent/group_chat_runtime.py`
- 修改：`backend/app/agent/group_chat_host_runtime.py`
- 修改：`backend/app/agent/expert_runtime.py`
- 修改：`backend/app/agent/skill_session_locks.py`
- 测试：`backend/tests/test_group_chat_state.py`
- 测试：`backend/tests/test_host_takeover.py`
- 测试：`backend/tests/test_expert_runtime.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_host_scheduler_state_writes_orchestration_state_not_session_json():
    ...
    assert state["host_scheduler"]["next_speaker"] == "写作专家"
    assert "scheduler_state" not in session_definition
```

- [ ] **步骤 2：运行测试验证失败**

运行：`rtk python -m pytest backend/tests/test_host_takeover.py::test_host_scheduler_state_writes_orchestration_state_not_session_json -q`
预期：FAIL，当前实现写 `session.json.scheduler_state`。

- [ ] **步骤 3：实现最少代码**

新增 `load_group_orchestration_state()`、`write_group_orchestration_state()`、`update_group_orchestration_state()`；主持人决策只接收 `host_scheduler.current_phase` 并回写 `host_scheduler`；Skill 接续只读写 `continuation`。

- [ ] **步骤 4：运行测试验证通过**

运行：`rtk python -m pytest backend/tests/test_host_takeover.py backend/tests/test_expert_runtime.py backend/tests/test_group_chat_state.py -q`
预期：相关契约测试 PASS。

## 任务 4：`settings/app.json.host`

**文件：**
- 修改：`backend/app/api/settings_app.py`
- 修改：`backend/app/api/sessions.py`
- 修改：`frontend/src/features/settings/AppSettingsView.vue`
- 修改：`frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts`
- 修改：`frontend/e2e/fixtures/mockApi.ts`
- 测试：`backend/tests/test_sessions_api.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_app_settings_store_default_host_under_host_field():
    client.put("/api/settings/host-profile", json={"name": "测试主持人"})
    raw = json.loads(app_settings_path().read_text(encoding="utf-8"))
    assert raw["host"]["name"] == "测试主持人"
    assert "host_profile" not in raw
```

- [ ] **步骤 2：运行测试验证失败**

运行：`rtk python -m pytest backend/tests/test_sessions_api.py::test_app_settings_store_default_host_under_host_field -q`
预期：FAIL，当前写入 `host_profile`。

- [ ] **步骤 3：实现最少代码**

保留 HTTP 路径 `/settings/host-profile` 作为界面命名，但磁盘字段只读写 `host`；创建普通会话从 `settings["host"]` 取默认主持人。

- [ ] **步骤 4：运行测试验证通过**

运行：`rtk python -m pytest backend/tests/test_sessions_api.py::test_app_settings_store_default_host_under_host_field backend/tests/test_sessions_api.py::test_new_regular_session_uses_latest_default_host_profile -q`
预期：PASS。

## 任务 5：checkpoint 新对象契约

**文件：**
- 修改：`backend/app/session_state/paths.py`
- 修改：`backend/app/session_state/store.py`
- 重写：`backend/app/session_state/service.py`
- 删除或停用：`backend/app/session_state/markdown.py`
- 测试：重写 `backend/tests/test_session_state_gitlike.py`
- 删除或重写：`backend/tests/test_session_state_markdown.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_checkpoint_object_uses_contract_fields_and_no_chat_md(client):
    checkpoint = client.post(f"/api/sessions/{session_id}/snapshot").json()["data"]
    assert "checkpoint_id" in checkpoint
    assert "session_blob" in checkpoint
    assert "history_blob" in checkpoint
    assert "orchestration_state_blob" in checkpoint
    assert "memory_tree" in checkpoint
    assert "commit_id" not in checkpoint
    assert not (session_dir / "chat.md").exists()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`rtk python -m pytest backend/tests/test_session_state_gitlike.py::test_checkpoint_object_uses_contract_fields_and_no_chat_md -q`
预期：FAIL，当前仍输出旧 commit 字段并写 `chat.md`。

- [ ] **步骤 3：实现最少代码**

对象存储直接保存 `session.json`、`history.json`、`orchestration_state.json` bytes；树对象分别保存 `workspace/` 和 `memory/`；`HEAD.json` 和 `chain.json` 只保存 `checkpoint_id`；rollback/clone 通过 blobs 恢复文件。

- [ ] **步骤 4：运行测试验证通过**

运行：`rtk python -m pytest backend/tests/test_session_state_gitlike.py -q`
预期：PASS。

## 任务 6：前端不从正文反推业务状态

**文件：**
- 修改：`frontend/src/features/workspace/composables/useGroupOrchestrationState.ts`
- 修改：`frontend/src/features/workspace/workspaceMessageUtils.ts`
- 修改：`frontend/src/features/workspace/composables/useGroupStreamEvents.ts`
- 修改：`frontend/e2e/fixtures/mockApi.ts`

- [ ] **步骤 1：编写失败检查**

运行：`rtk rg -n "suggested_add_agent_name|expert_route_debug|skill_route_debug|scheduler_state|lastMsg\\.content|parseAgentNamesFromHostContent|session_update|agent_running|message_ready" frontend/src frontend/e2e`
预期：命中旧结构。

- [ ] **步骤 2：实现删除**

删除旧字段读取和正文解析分支；招募、等待用户、下一位专家只从 `end` 或结构化 `message.skill_result.next_action` 读取。

- [ ] **步骤 3：运行检查验证通过**

运行：`rtk rg -n "suggested_add_agent_name|expert_route_debug|skill_route_debug|scheduler_state|lastMsg\\.content|parseAgentNamesFromHostContent|session_update|agent_running|message_ready" frontend/src frontend/e2e`
预期：无命中。

## 任务 7：全量验证与提交

**文件：**
- 所有上述文件

- [ ] **步骤 1：编译后端**

运行：`rtk python -m compileall -q backend/app`
预期：exit 0。

- [ ] **步骤 2：跑后端测试**

运行：`rtk python -m pytest backend/tests -q`
预期：全部通过。

- [ ] **步骤 3：构建前端**

运行：`rtk npm --prefix frontend run build`
预期：exit 0。

- [ ] **步骤 4：旧字段扫描**

运行：`rtk rg -n "scheduler_state|skill_session_owner_name|skill_session_skill|session_update|agent_running|message_ready|host_profile|chat_blob|commit_id|message_count|chat\\.md" backend/app frontend/src frontend/e2e backend/tests docs/contracts`
预期：只允许迁移脚本、历史说明或明确的否定性测试命中；主运行时代码、mock 和目标契约文档不得命中。

- [ ] **步骤 5：Commit 和 push**

```bash
rtk git status --short
rtk git add .
rtk git commit -m "refactor: 按文档契约重写运行主路径"
rtk git push origin dev-ggd
```
