# Session Memory Roundtrip Log 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将群聊 memory 收敛为只向下一位专家注入 `facts.md`，并把每次 LLM 输入/输出完整写入当前会话工作区的 `memory/llm_roundtrips.jsonl`。

**架构：** `group_memory_store.py` 作为会话工作区 memory 的唯一文件接口，新增 JSONL roundtrip 追加函数，并让 `build_dispatch_context()` 只读取 `facts.md`。`group_chat.py` 在已知 session 的 LLM 调用点写入 roundtrip，不再调用全局 `backend/logs/llm_trace.log`。

**技术栈：** FastAPI 后端、pytest、JSONL、现有 workspace path helper。

---

### 任务 1：收敛 memory 上下文为 facts-only

**文件：**
- 修改：`backend/app/agent/group_memory_store.py`
- 修改：`backend/tests/test_group_memory_store.py`

- [x] **步骤 1：编写失败测试**

在 `backend/tests/test_group_memory_store.py` 中加入测试：创建 `facts.md` 和旧 `memory/logs/*.md`，调用 `build_dispatch_context()`，断言返回不包含 logs/refs，也不渲染相关历史摘录。

- [x] **步骤 2：运行测试验证失败**

运行：`/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_group_memory_store.py::test_build_dispatch_context_uses_only_facts -q`
预期：FAIL，原因是当前实现仍返回 logs。

- [x] **步骤 3：实现 facts-only**

修改 `build_dispatch_context()`：只读取 `facts.md`，返回 `facts`、空 `logs`、空 `refs`、只包含“关键事实”的 `rendered`，`has_memory` 只由 facts 决定。

- [x] **步骤 4：运行测试验证通过**

运行：`/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_group_memory_store.py -q`
预期：PASS。

### 任务 2：新增 per-session LLM roundtrip JSONL

**文件：**
- 修改：`backend/app/agent/group_memory_store.py`
- 修改：`backend/tests/test_group_memory_store.py`

- [x] **步骤 1：编写失败测试**

在 `backend/tests/test_group_memory_store.py` 中加入测试：调用 `append_llm_roundtrip()` 两次，断言 `memory/llm_roundtrips.jsonl` 有两行，每行是 JSON，且完整保留 input/output。

- [x] **步骤 2：运行测试验证失败**

运行：`/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_group_memory_store.py::test_append_llm_roundtrip_writes_jsonl_without_truncation -q`
预期：FAIL，原因是函数不存在。

- [x] **步骤 3：实现追加函数**

在 `group_memory_store.py` 中新增 `append_llm_roundtrip()`，写入 `memory/llm_roundtrips.jsonl`，不做截断和轮转，确保 `ensure_ascii=False`。

- [x] **步骤 4：运行测试验证通过**

运行：`/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_group_memory_store.py -q`
预期：PASS。

### 任务 3：移除全局 llm_trace.log 写入

**文件：**
- 修改：`backend/app/api/group_chat.py`
- 修改：`backend/app/agent/leader_scheduler.py`
- 修改：`backend/app/agent/llm_client.py`
- 删除：`backend/app/core/llm_trace.py`
- 修改：相关测试

- [x] **步骤 1：编写失败测试**

加入或更新测试，断言 `_log_llm_roundtrip(..., session_id=..., workspace_root=...)` 写入 workspace JSONL，且不会创建 `backend/logs/llm_trace.log`。

- [x] **步骤 2：运行测试验证失败**

运行：`/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_group_chat_group_memory.py backend/tests/test_group_memory_store.py -q`
预期：FAIL，原因是旧代码仍写全局 trace 或新参数不存在。

- [x] **步骤 3：改调用点**

让 group chat 的 host/expert LLM 调用点把 `session_id` 和当前 workspace 传给 `append_llm_roundtrip()`。删除 `append_llm_trace` import 和全局文件写入；没有 session 上下文的 leader/global client 路径只保留 logger，不写全局文件。

- [x] **步骤 4：运行验证**

运行：`/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_group_chat_group_memory.py backend/tests/test_group_memory_store.py -q`
预期：PASS。

### 任务 4：文档与全量相关验证

**文件：**
- 修改：`docs/architecture/runtime-architecture.md`
- 修改：`docs/梳理.md`
- 修改：`docs/testing/layer1-regression.md`

- [x] **步骤 1：更新文档**

把 memory 描述改为 `facts.md` 注入和 `llm_roundtrips.jsonl` 排障日志；删除 `logs/messages` 参与派发的描述。

- [x] **步骤 2：运行最终验证**

运行：
`/Users/ggd/.local/bin/rtk conda run -n st49 python -m pytest backend/tests/test_group_memory_store.py backend/tests/test_group_chat_group_memory.py backend/tests/test_llm_config.py -q`
`/Users/ggd/.local/bin/rtk python -m py_compile backend/app/agent/group_memory_store.py backend/app/api/group_chat.py backend/app/agent/leader_scheduler.py backend/app/agent/llm_client.py`
`/Users/ggd/.local/bin/rtk git diff --check`

预期：所有命令 exit 0。
