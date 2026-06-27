# Core File Decomposition With User Storage Safety 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在不破坏新用户存储结构的前提下，分阶段拆解 `group_chat.py`、`sandbox_service.py`、`useWorkspaceContentProviders.ts` 和 `MainView.vue`。

**架构：** 先拆后端群聊状态、上下文和主持人决策三个低耦合边界，让 `group_chat.py` 保留 FastAPI 路由和流式入口。沙箱与前端拆分分别作为后续独立计划执行，避免一个提交同时改变会话编排、沙箱挂载和 UI 状态管理。

**技术栈：** FastAPI、现有 JSON 文件存储、Vue 3 Composition API、pytest、vue-tsc、Vite、用户级 `UserContext` 路径 helper。

---

## 用户存储结构硬约束

当前用户目录标准来自 `docs/architecture/user-resource-store/storage-standard.md`、`docs/architecture/user-resource-store/new-window-prompt.md`、`backend/app/core/user_context.py` 和 `backend/app/core/user_settings_paths.py`。

实现过程中不得重新拼接旧路径，必须使用现有 helper：

- 用户根：`backend/data/users/<user_id>/`
- 资源：`UserContext.resources_dir` 下的 `scenarios/`、`agents/`、`skills/`、`tools/`、`models/`
- Skill：`skills_dir_path()` 或 `get_current_user_context().skills_dir`，即 `resources/skills`
- 配置：`app_settings_path()`、`api_secrets_path()`、`mcp_config_path()`、`session_presets_path()`、`sandbox_requirements_path()`
- 密钥：`vault_secrets_path()`，即 `vault/secrets.enc.json`
- 会话工作区：`get_workspace_root_path(session_id)`，当前物理路径为 `sessions/workspaces/<session_id>`
- 沙箱内会话路径：`sandbox_session_dir(session_id)`，即 `/workspace/<session_id>`
- 沙箱 host 挂载根：`host_sessions_root_from_workspace(workspace_path)`，不要写死 `agent-outputs`

本轮拆解的代码如果需要读写会话或工作区，只能通过上述 helper 或当前已有封装进入。不得新增 `backend/data/users/<username>`、裸 `skills/`、`agent-outputs/workspaces` 这类旧结构调用。注意：沙箱 UI 设置历史上存在路径混淆，相关实现必须核对当前真实调用点后再改，不能凭文档中的旧路径直接拼接。

## 总体拆分顺序

1. Phase B1：`group_chat.py` 状态与上下文抽离，本计划详细覆盖。
2. Phase B2：`group_chat.py` 主持人决策抽离，本计划给出任务骨架，执行前根据 B1 diff 补精确行号。
3. Phase C：`sandbox_service.py` 拆成 policy、handle pool、requirements、workspace fs、lifecycle，另开计划。
4. Phase D：`useWorkspaceContentProviders.ts` 拆成 session detail、runtime stream、composer、invite、archive TOC，另开计划。
5. Phase E：`MainView.vue` 拆成 navigation、scenario resource、share import、resource lists、workspace sidebar、middle column layout，另开计划。

---

## 文件结构

Phase B1 新建或修改：

- 新建：`backend/app/api/group_chat_state.py`
  - 负责群聊 meta/history 文件读写、session payload 构建、archive segments、runtime state、session event subscribers。
- 新建：`backend/app/agent/group_context.py`
  - 负责消息上下文、专家上下文、讨论目标、标题兜底、soft-stop 纯文本判定等纯函数。
- 修改：`backend/app/api/group_chat.py`
  - 删除已迁出的 helper，保留路由函数、Pydantic request model、`group_chat_stream()` 主入口。
- 测试：`backend/tests/test_group_chat_state.py`
  - 覆盖 runtime state、meta/history round trip、archive segments、session payload。
- 测试：`backend/tests/test_group_context.py`
  - 覆盖上下文截断、错误噪声过滤、讨论目标归一化、标题生成。
- 保留：`backend/tests/test_group_chat_stream_protocol.py`、`backend/tests/test_host_takeover.py`、`backend/tests/test_group_chat_group_memory.py`
  - 作为行为回归测试。

后续 Phase B2 新建或修改：

- 新建：`backend/app/agent/group_host_decision.py`
  - 负责 `_extract_json_object_from_llm_text`、host response 解析、workspace scheduler state、@ 提及/显式专家提取。
- 修改：`backend/app/api/group_chat.py`
  - 只保留调用 `group_host_decision` 的编排 glue。
- 测试：扩展 `backend/tests/test_host_takeover.py` 或新增 `backend/tests/test_group_host_decision.py`。

---

## 任务 1：锁定用户存储路径约束和群聊现状

**文件：**
- 读取：`docs/architecture/user-resource-store/storage-standard.md`
- 读取：`docs/architecture/user-resource-store/new-window-prompt.md`
- 读取：`backend/app/core/user_context.py`
- 读取：`backend/app/core/user_settings_paths.py`
- 测试：`backend/tests/test_user_resource_paths.py`

- [x] **步骤 1：运行用户路径契约测试**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_user_resource_paths.py'
```

预期：PASS。若失败，先修用户路径 helper，不进入大文件拆分。

- [x] **步骤 2：运行群聊与沙箱相关基线**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_chat_stream_protocol.py tests/test_host_takeover.py tests/test_group_chat_group_memory.py tests/test_sandbox_service.py'
```

预期：PASS。若某测试因本地环境缺少服务而跳过或失败，记录具体测试名和错误，不把失败归咎于拆分。

- [x] **步骤 3：复核当前行数和调用点**

运行：

```bash
/Users/ggd/.local/bin/rtk wc -l backend/app/api/group_chat.py backend/app/agent/sandbox_service.py frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts frontend/src/views/MainView.vue
/Users/ggd/.local/bin/rtk rg -n "agent-outputs|resources/skills|sessions/workspaces|sandbox_requirements_path|skills_dir_path|get_workspace_root_path|host_sessions_root_from_workspace" backend/app backend/tests docs
```

预期：能看到 `resources/skills` 与 `sessions/workspaces` 是当前主路径；若业务代码仍有新增旧路径，要先判断是否测试 fixture 或兼容说明。

- [x] **步骤 4：Commit**

本任务只做基线确认，不提交。

---

## 任务 2：抽出 `group_chat_state.py`

**文件：**
- 新建：`backend/app/api/group_chat_state.py`
- 修改：`backend/app/api/group_chat.py`
- 测试：`backend/tests/test_group_chat_state.py`

- [x] **步骤 1：编写状态模块测试**

新增 `backend/tests/test_group_chat_state.py`：

```python
import asyncio

from app.api import group_chat_state as state


def test_group_meta_history_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    meta = {"s1": {"title": "会话", "agent_ids": ["agent-a"], "created_at": "t", "updated_at": "t"}}

    state.save_group_meta(meta)
    state.save_group_history("s1", [{"role": "user", "content": "你好"}])

    assert state.load_group_meta()["s1"]["title"] == "会话"
    assert state.load_group_history("s1")[0]["content"] == "你好"


def test_build_archive_segments_ignores_host_messages():
    messages = [
        {"role": "user", "message_id": "u1", "content": "目标", "timestamp": "t1"},
        {"role": "host", "message_id": "h1", "content": "下面请 A"},
        {"role": "assistant", "agent_id": "agent-a", "message_id": "a1", "content": "回答", "timestamp": "t2", "skill_id": "skill-a"},
    ]

    segments = state.build_archive_segments(messages)

    assert len(segments) == 1
    assert segments[0]["user"]["content"] == "目标"
    assert segments[0]["experts"][0]["agent_id"] == "agent-a"
    assert segments[0]["experts"][0]["messages"][0]["skill_id"] == "skill-a"


def test_runtime_state_clears_done_task(monkeypatch):
    async def done():
        return None

    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(done())
        loop.run_until_complete(task)
        state.ACTIVE_GROUP_RUNS["s1"] = {"run_id": "r1", "task": task, "phase": "running"}
        meta_item = {"runtime_state": {"running": True}}

        runtime = state.runtime_state_for_session("s1", meta_item)

        assert runtime == {"running": False}
        assert "runtime_state" not in meta_item
    finally:
        state.ACTIVE_GROUP_RUNS.clear()
        loop.close()
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_chat_state.py'
```

预期：FAIL，错误包含 `cannot import name 'group_chat_state'` 或缺少目标函数。

- [x] **步骤 3：新建状态模块并迁移函数**

新建 `backend/app/api/group_chat_state.py`，从 `group_chat.py` 迁出以下完整函数体并去掉下划线前缀：

- `_ACTIVE_GROUP_RUNS` -> `ACTIVE_GROUP_RUNS`
- `_ACTIVE_GROUP_RUNS_LOCK` -> `ACTIVE_GROUP_RUNS_LOCK`
- `_GROUP_SESSION_EVENT_SUBSCRIBERS` -> `GROUP_SESSION_EVENT_SUBSCRIBERS`
- `_GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK` -> `GROUP_SESSION_EVENT_SUBSCRIBERS_LOCK`
- `_ensure_sessions_dir` -> `ensure_sessions_dir`
- `_load_group_meta` -> `load_group_meta`
- `_save_group_meta` -> `save_group_meta`
- `_load_group_history` -> `load_group_history`
- `_save_group_history` -> `save_group_history`
- `_cleanup_orphan_group_histories` -> `cleanup_orphan_group_histories`
- `_build_archive_segments` -> `build_archive_segments`
- `_publish_group_session_event` -> `publish_group_session_event`
- `_schedule_group_session_event` -> `schedule_group_session_event`
- `_write_group_runtime_state` -> `write_group_runtime_state`
- `_runtime_state_for_active_run` -> `runtime_state_for_active_run`
- `_runtime_state_for_session` -> `runtime_state_for_session`
- `_register_group_run` -> `register_group_run`
- `_update_group_run` -> `update_group_run`
- `_finish_group_run` -> `finish_group_run`
- `_cancel_group_session_run` -> `cancel_group_session_run`

`group_chat_state.py` 顶部需要导入当前函数体实际使用的 `asyncio`、`json`、`uuid`、`suppress`、`datetime`、`timezone`、`Path`、`Any`、`Dict`、`List`、`Optional` 和 `logger`。`GROUP_SESSIONS_ROOT`、`GROUP_META_FILE`、`GROUP_HISTORY_PREFIX` 的来源保持与迁移前一致。

在 `group_chat.py` 中导入时先用别名保持 diff 小：

```python
from app.api.group_chat_state import (
    build_archive_segments as _build_archive_segments,
    cancel_group_session_run as _cancel_group_session_run,
    cleanup_orphan_group_histories as _cleanup_orphan_group_histories,
    finish_group_run as _finish_group_run,
    load_group_history as _load_group_history,
    load_group_meta as _load_group_meta,
    register_group_run as _register_group_run,
    runtime_state_for_session as _runtime_state_for_session,
    save_group_history as _save_group_history,
    save_group_meta as _save_group_meta,
    update_group_run as _update_group_run,
)
```

不要在新模块里新增用户目录拼接；继续复用 `GROUP_SESSIONS_ROOT` 当前来源。

- [x] **步骤 4：运行状态测试**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_chat_state.py'
```

预期：PASS。

- [x] **步骤 5：运行群聊回归**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_chat_stream_protocol.py tests/test_host_takeover.py tests/test_group_chat_group_memory.py'
```

预期：PASS。

- [x] **步骤 6：Commit**

```bash
/Users/ggd/.local/bin/rtk git add backend/app/api/group_chat.py backend/app/api/group_chat_state.py backend/tests/test_group_chat_state.py
/Users/ggd/.local/bin/rtk git commit -m "refactor(group-chat): 拆出会话状态存储"
```

---

## 任务 3：抽出 `group_context.py`

**文件：**
- 新建：`backend/app/agent/group_context.py`
- 修改：`backend/app/api/group_chat.py`
- 测试：`backend/tests/test_group_context.py`

- [x] **步骤 1：编写上下文纯函数测试**

新增 `backend/tests/test_group_context.py`：

```python
from app.agent import group_context


def test_messages_to_expert_context_filters_repeated_technical_errors():
    messages = [
        {"role": "user", "content": "请分析数据"},
        {"role": "assistant", "agent_id": "agent-a", "content": "Error code: 400 context length is only"},
        {"role": "assistant", "agent_id": "agent-a", "content": "有效业务结论"},
        {"role": "assistant", "agent_id": "agent-a", "content": "有效业务结论"},
    ]

    text = group_context.messages_to_expert_context(messages)

    assert "请分析数据" in text
    assert "有效业务结论" in text
    assert "Error code: 400" not in text
    assert text.count("有效业务结论") == 1


def test_normalize_discussion_goal_removes_frontend_prefix():
    assert group_context.normalize_discussion_goal("【讨论目标】\n写一份方案") == "写一份方案"


def test_title_from_first_message_limits_text():
    assert group_context.title_from_first_message("【讨论目标】\n这是一个很长很长的标题", max_chars=6) == "这是一个很长"
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_context.py'
```

预期：FAIL，错误包含 `cannot import name 'group_context'`。

- [x] **步骤 3：新建 `group_context.py` 并迁移纯函数**

从 `group_chat.py` 迁出：

迁移以下完整函数体：

- `_messages_to_context` -> `messages_to_context`
- `_is_group_context_noise` -> `is_group_context_noise`
- `_messages_to_expert_context` -> `messages_to_expert_context`
- `_scheduler_recent_context` -> `scheduler_recent_context`
- `_normalize_discussion_goal` -> `normalize_discussion_goal`
- `_title_from_first_message` -> `title_from_first_message`
- `_shorten_text` -> `shorten_text`
- `_normalize_compare_text` -> `normalize_compare_text`
- `_looks_like_conclusion_text` -> `looks_like_conclusion_text`
- `_has_tool_failure` -> `has_tool_failure`
- `_has_auto_continue_signal` -> `has_auto_continue_signal`

在 `group_chat.py` 中使用别名导入：

```python
from app.agent.group_context import (
    has_auto_continue_signal as _has_auto_continue_signal,
    has_tool_failure as _has_tool_failure,
    is_group_context_noise as _is_group_context_noise,
    looks_like_conclusion_text as _looks_like_conclusion_text,
    messages_to_context as _messages_to_context,
    messages_to_expert_context as _messages_to_expert_context,
    normalize_compare_text as _normalize_compare_text,
    normalize_discussion_goal as _normalize_discussion_goal,
    scheduler_recent_context as _scheduler_recent_context,
    shorten_text as _shorten_text,
    title_from_first_message as _title_from_first_message,
)
```

此模块不得导入 `get_current_user_context()` 或任何磁盘路径 helper；它必须保持纯文本处理模块。

- [x] **步骤 4：运行上下文测试**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_context.py'
```

预期：PASS。

- [x] **步骤 5：运行群聊回归**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_chat_stream_protocol.py tests/test_host_takeover.py tests/test_group_chat_group_memory.py'
```

预期：PASS。

- [x] **步骤 6：Commit**

```bash
/Users/ggd/.local/bin/rtk git add backend/app/api/group_chat.py backend/app/agent/group_context.py backend/tests/test_group_context.py
/Users/ggd/.local/bin/rtk git commit -m "refactor(group-chat): 拆出上下文格式化逻辑"
```

---

## 任务 4：抽出 `group_host_decision.py`

**文件：**
- 新建：`backend/app/agent/group_host_decision.py`
- 修改：`backend/app/api/group_chat.py`
- 测试：`backend/tests/test_group_host_decision.py`
- 保留：`backend/tests/test_host_takeover.py`

- [x] **步骤 1：编写主持人决策测试**

新增 `backend/tests/test_group_host_decision.py`：

```python
from app.agent import group_host_decision as hd


def test_extract_host_scheduler_state_from_json_block():
    text = """安排如下：
```json
{"current_phase":"阶段1","next_speaker":"教师","speaker_task":"给出主题"}
```"""

    out = hd.extract_host_scheduler_state(text)

    assert out == {
        "current_phase": "阶段1",
        "next_speaker": "教师",
        "speaker_task": "给出主题",
    }


def test_forced_at_mention_matches_agent_name():
    agents = [{"agent_id": "agent-teacher", "name": "教师", "role": "出题"}]

    assert hd.extract_forced_at_mention_agent_id("@教师 请继续", agents) == "agent-teacher"


def test_host_decision_from_scheduler_state_maps_user():
    out = hd.host_decision_from_scheduler_state(
        {"current_phase": "补充信息", "next_speaker": "用户", "speaker_task": "请补充年级"},
        [],
    )

    assert out["next_speaker"] == "user"
    assert out["next_prompt"] == "请补充年级"
    assert out["decision_source"] == "host_scheduler_state"
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_host_decision.py'
```

预期：FAIL，错误包含 `cannot import name 'group_host_decision'`。

- [x] **步骤 3：迁移主持人决策纯函数**

从 `group_chat.py` 迁出：

迁移以下完整函数体：

- `_extract_json_object_from_llm_text` -> `extract_json_object_from_llm_text`
- `_parse_host_response` -> `parse_host_response`
- `_match_workspace_speaker_to_agent_id` -> `match_workspace_speaker_to_agent_id`
- `_host_text_field` -> `host_text_field`
- `_extract_host_scheduler_state` -> `extract_host_scheduler_state`
- `_host_decision_from_scheduler_state` -> `host_decision_from_scheduler_state`
- `_user_requests_host_takeover` -> `user_requests_host_takeover`
- `_heuristic_recommend_dhas` -> `heuristic_recommend_dhas`
- `_extract_candidate_agent_ids_from_text` -> `extract_candidate_agent_ids_from_text`
- `_extract_explicit_requested_agent_ids` -> `extract_explicit_requested_agent_ids`
- `_extract_forced_at_mention_agent_id` -> `extract_forced_at_mention_agent_id`

暂时不要迁移 `_host_decide_by_dha()`，因为它同时依赖 LLM、Skill loader、workspace 文件落盘和 roundtrip 日志。等纯函数迁出且测试稳定后，再单独计划运行时对象化。

- [x] **步骤 4：处理 workspace scheduler 文件落盘调用**

`_persist_host_scheduler_state_files()` 需要写入会话工作区。它可以留在 `group_chat.py`，或迁入 `group_host_decision.py` 但必须通过注入函数实现：

```python
def persist_host_scheduler_state_files(session_id: str, state: dict[str, str], *, workspace_root_loader: Callable[[str], Path]) -> None:
    phase = str((state or {}).get("current_phase") or "").strip()
    speaker = str((state or {}).get("next_speaker") or "").strip()
    task = str((state or {}).get("speaker_task") or "").strip()
    if not any((phase, speaker, task)):
        return
    root = workspace_root_loader(session_id)
    root.mkdir(parents=True, exist_ok=True)
    if phase:
        (root / "current_phase.txt").write_text(phase + "\n", encoding="utf-8")
    if speaker:
        (root / "next_speaker.txt").write_text(speaker + "\n", encoding="utf-8")
    if task:
        (root / "speaker_task.txt").write_text(task + "\n", encoding="utf-8")
```

执行本计划时推荐先留在 `group_chat.py`，避免在纯决策模块里直接导入 `get_workspace_root_path()`。

- [x] **步骤 5：运行主持人和群聊回归**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_group_host_decision.py tests/test_host_takeover.py tests/test_group_chat_stream_protocol.py tests/test_group_chat_group_memory.py'
```

预期：PASS。

- [x] **步骤 6：Commit**

```bash
/Users/ggd/.local/bin/rtk git add backend/app/api/group_chat.py backend/app/agent/group_host_decision.py backend/tests/test_group_host_decision.py backend/tests/test_host_takeover.py
/Users/ggd/.local/bin/rtk git commit -m "refactor(group-chat): 拆出主持人决策解析"
```

---

## 任务 5：行数复核和用户存储回归

**文件：**
- 修改：`docs/superpowers/plans/2026-05-24-core-file-decomposition-user-storage-safe.md`

- [x] **步骤 1：复核目标文件行数**

运行：

```bash
/Users/ggd/.local/bin/rtk wc -l backend/app/api/group_chat.py backend/app/api/group_chat_state.py backend/app/agent/group_context.py backend/app/agent/group_host_decision.py
```

预期：`group_chat.py` 明显下降；新增文件职责聚焦。不要为了行数移动强依赖运行时的代码。

- [x] **步骤 2：复核禁止旧路径**

运行：

```bash
/Users/ggd/.local/bin/rtk rg -n "agent-outputs|/skills|data/users/.*/skills|config/sandbox/settings.json" backend/app backend/tests
```

预期：业务代码中不新增旧用户路径。若命中测试 fixture，确认它是在覆盖兼容行为，而不是新主路径。

- [x] **步骤 3：运行后端回归包**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_user_resource_paths.py tests/test_group_chat_state.py tests/test_group_context.py tests/test_group_host_decision.py tests/test_group_chat_stream_protocol.py tests/test_host_takeover.py tests/test_group_chat_group_memory.py tests/test_sandbox_service.py'
```

预期：PASS。

- [x] **步骤 4：语法验证**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m py_compile app/api/group_chat.py app/api/group_chat_state.py app/agent/group_context.py app/agent/group_host_decision.py'
```

预期：无输出，exit 0。

- [x] **步骤 5：Commit 计划状态**

如执行过程中勾选了本计划：

```bash
/Users/ggd/.local/bin/rtk git add docs/superpowers/plans/2026-05-24-core-file-decomposition-user-storage-safe.md
/Users/ggd/.local/bin/rtk git commit -m "docs: 更新群聊拆分执行状态"
```

---

## 后续独立计划边界

### SandboxService 拆分计划

单独新建 `docs/superpowers/plans/YYYY-MM-DD-sandbox-service-decomposition.md`，只覆盖：

- `backend/app/agent/sandbox_policy_builder.py`
- `backend/app/agent/sandbox_handle_pool.py`
- `backend/app/agent/sandbox_requirements.py`
- `backend/app/agent/sandbox_workspace_fs.py`
- `backend/app/agent/sandbox_lifecycle.py`

该计划必须重新跑 `tests/test_sandbox_service.py`，并明确保护：

- `resources/skills` 挂载
- `sessions/workspaces` 工作区
- `config/sandbox/requirements.txt` requirements
- 当前沙箱 UI 设置真实路径
- `vault/` 不进入沙箱挂载

### WorkspaceContent provider 拆分计划

单独新建 `docs/superpowers/plans/YYYY-MM-DD-workspace-provider-decomposition.md`，只覆盖：

- `useGroupSessionDetail.ts`
- `useGroupRuntimeStreamState.ts`
- `useGroupComposerState.ts`
- `useGroupInviteSuggestions.ts`
- `useGroupArchiveToc.ts`

该计划必须跑：

```bash
/Users/ggd/.local/bin/rtk npm --prefix frontend run build
```

如存在 Playwright UI 用例，补跑工作区会话选择、发送消息、停止流、文件面板、邀请专家 smoke。

### MainView shell 拆分计划

单独新建 `docs/superpowers/plans/YYYY-MM-DD-main-view-shell-decomposition.md`，只覆盖：

- `useMainNavigation.ts`
- `useScenarioResourcePanel.ts`
- `useShareImportFlow.ts`
- `useResourceLists.ts`
- `useWorkspaceSidebarSessions.ts`
- `useMiddleColumnLayout.ts`

该计划必须保持路由和 API 不变：

- `/workspace`
- `/resources/scenario`
- `/resources/agent`
- `/resources/skill`
- `/resources/mcp`
- `/resources/llm`
- `/resources/files`
- `/settings/app`
- `/share/run?id=<share_id>`
