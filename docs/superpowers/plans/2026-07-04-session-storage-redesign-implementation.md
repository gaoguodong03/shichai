# 会话存储结构重设计实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将会话存储从 `meta.json` 扁平混合结构迁移到 `session.json`、`history.json`、`runtime.json` 三类事实源，并更新架构文档和代码。

**架构：** `session.json` 只保存会话元数据和资源引用，`history.json` 保存消息事实与 Skill 流程控制结果，`runtime.json` 保存可丢弃的运行镜像。后端提供旧数据读取兼容，新写入使用新结构，前端逐步消费 `speaker` 与 runtime 响应。

**技术栈：** FastAPI、现有 JSON 文件存储、Vue 3、pytest、现有 `UserContext` 会话路径 helper。

---

## 文件结构

- 修改：`docs/architecture/data-structure-and-field-logic.md`
  - 更新会话字段、消息字段、运行态边界和关键耦合图。
- 修改：`backend/app/session_state/paths.py`
  - 增加 `session_json`、`runtime_json` 路径。
- 修改：`backend/app/api/group_chat_state.py`
  - 支持 `session.json` / `runtime.json` 读写，保留旧 `meta.json` 读取兼容。
  - 新写入不写 `leader_agent_name`、`host_config`、`runtime_state`、`pending_*`、`skill_session_*`。
  - 读写消息时规范化新旧消息结构。
- 修改：`backend/app/agent/group_session_service.py`
  - 新建、更新、删除会话适配 `session.json` 字段。
- 修改：`backend/app/agent/group_chat_runtime.py`
  - 运行态写入 `runtime.json`。
  - 新消息写入 `speaker` / `created_at` / `skill_result`。
  - Skill 跨轮路由从历史消息推导。
- 修改：`backend/app/agent/group_chat_skill_session.py`
  - 从历史消息的 `skill_result.next_action.skill_session` 判断 keep/release。
- 修改：`backend/app/agent/expert_runtime.py`
  - 从历史推导的锁定 Skill 接入专家 Skill 选择。
- 修改：`frontend/src/**`
  - 会话详情和消息展示适配 `speaker`、`created_at` 和新的 runtime 字段。
- 测试：`backend/tests/test_group_chat_state.py`
- 测试：`backend/tests/test_group_chat_stream_protocol.py`
- 测试：前端现有类型检查和构建命令。

## 任务 1：更新架构文档

**文件：**
- 修改：`docs/architecture/data-structure-and-field-logic.md`

- [ ] **步骤 1：替换会话字段章节**

将第 8-12 节更新为 `session.json`、`history.json`、`runtime.json` 三文件结构，并明确删除旧字段：

```text
leader_agent_name
host_config
runtime_state
pending_*
skill_session_*
context.system_prompt
```

- [ ] **步骤 2：更新运行链路和检查顺序**

运行链路写明：

```text
session.json -> 解析场景/主持人/专家引用
history.json -> 推导 Skill keep/release
runtime.json -> 仅用于刷新恢复 UI
```

- [ ] **步骤 3：验证文档格式**

运行：

```bash
rtk git diff --check -- docs/architecture/data-structure-and-field-logic.md
```

预期：exit 0。

## 任务 2：后端路径和存储契约

**文件：**
- 修改：`backend/app/session_state/paths.py`
- 修改：`backend/app/api/group_chat_state.py`
- 测试：`backend/tests/test_group_chat_state.py`

- [ ] **步骤 1：编写失败测试**

新增或修改测试覆盖：

```python
def test_group_session_writes_session_json_not_meta_json(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_group_meta({"s1": {"title": "会话", "agent_names": ["专家A"], "created_at": "2026062908104800", "updated_at": "2026062908104800"}})

    assert (tmp_path / "s1" / "session.json").exists()
    assert not (tmp_path / "s1" / "meta.json").exists()
```

```python
def test_runtime_state_writes_runtime_json_not_session_json(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_group_meta({"s1": {"title": "会话", "created_at": "2026062908104800", "updated_at": "2026062908104800"}})
    state.write_group_runtime_state("s1", {"running": True, "run_id": "r1", "phase": "routing", "started_at": "2026062908104800"})

    assert (tmp_path / "s1" / "runtime.json").exists()
    assert "runtime_state" not in state.load_group_meta()["s1"]
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_chat_state.py'
```

预期：新测试失败，原因是仍写 `meta.json` 或 `runtime_state`。

- [ ] **步骤 3：实现路径和读写**

在 `SessionLayoutPaths` 增加：

```python
session_json: Path
runtime_json: Path
```

在 `group_chat_state.py` 中增加 `session.json` 优先、`meta.json` 兼容读取；新写入只写 `session.json` 和 `sessions/index.json`。

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_chat_state.py'
```

预期：PASS。

## 任务 3：消息结构和 Skill 流程事实源

**文件：**
- 修改：`backend/app/api/group_chat_state.py`
- 修改：`backend/app/agent/group_chat_skill_session.py`
- 修改：`backend/app/agent/group_chat_runtime.py`
- 测试：`backend/tests/test_group_chat_stream_protocol.py`

- [ ] **步骤 1：编写失败测试**

新增测试覆盖 `speaker` 结构和 `skill_result.next_action.skill_session=keep` 推导锁定。

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_chat_stream_protocol.py'
```

预期：新测试失败。

- [ ] **步骤 3：实现消息规范化和历史推导**

新写消息使用：

```json
{
  "speaker": {"type": "expert", "agent_name": "...", "skill": "..."},
  "created_at": "...",
  "skill_result": {"execution_status": "...", "next_action": {"agent_turn": "...", "skill_session": "..."}}
}
```

旧消息读取时转换为等价 `speaker` 结构。

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_chat_stream_protocol.py tests/test_expert_runtime.py'
```

预期：PASS。

## 任务 4：会话创建和运行时适配

**文件：**
- 修改：`backend/app/agent/group_session_service.py`
- 修改：`backend/app/agent/group_chat_runtime.py`
- 修改：`backend/app/agent/scene_runtime.py`
- 测试：相关后端会话和主持人测试。

- [ ] **步骤 1：编写失败测试**

覆盖新建场景会话返回 `scenario_name`，且新写入不含 `host_config` / `leader_agent_name`。

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_chat_state.py tests/test_host_takeover.py'
```

- [ ] **步骤 3：实现会话创建和主持人解析**

创建会话时只写 `scenario_name`、`agent_names`、`orchestration_profile`、`system_prompt`。主持人配置运行时由 `scenario_name` 或通用主持人配置解析。

- [ ] **步骤 4：运行测试验证通过**

运行同上，预期 PASS。

## 任务 5：前端适配

**文件：**
- 修改：`frontend/src/features/workspace/**`
- 修改：`frontend/src/features/shell/**`
- 修改：`frontend/src/api/chat.ts`

- [ ] **步骤 1：更新类型和消息读取**

前端消息优先读取 `message.speaker`，兼容旧 `role` / `agent_name` / `skill`。

- [ ] **步骤 2：更新运行态读取**

会话运行态读取后端返回的 runtime 结构，不再假定它来自 `meta.runtime_state`。

- [ ] **步骤 3：运行前端验证**

运行：

```bash
rtk npm --prefix frontend run build
```

预期：PASS。

## 任务 6：整体验证

**文件：**
- 全部相关变更。

- [ ] **步骤 1：运行后端重点测试**

运行：

```bash
rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_chat_state.py tests/test_group_chat_stream_protocol.py tests/test_expert_runtime.py tests/test_host_takeover.py'
```

预期：PASS。

- [ ] **步骤 2：运行格式检查**

运行：

```bash
rtk git diff --check
```

预期：PASS。

- [ ] **步骤 3：目标审计**

核对：

- `docs/architecture/data-structure-and-field-logic.md` 已更新。
- 新写入不再使用 `meta.json`。
- 新写入不再使用 `leader_agent_name`、`host_config`、`pending_*`、`skill_session_*`。
- `runtime.json` 存在且只作为运行镜像。
- `history.json` 支持 `speaker` 和 `skill_result`。
