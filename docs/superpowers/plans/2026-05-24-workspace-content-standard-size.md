# WorkspaceContent 标准大小重构实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 `WorkspaceContent.vue` 从大文件改成标准大小的轻量入口，并删除确认无引用的旧模块。

**架构：** `WorkspaceContent.vue` 只保留模板、props/emit 声明和调用组合式逻辑；群聊会话、消息、输入区、工作区面板 context 的装配迁移到 composable。用静态合同测试锁定文件体量和禁止关键业务函数回流到 `WorkspaceContent.vue`。

**技术栈：** Vue 3 `<script setup>`、组合式 API、pytest 静态架构测试、vue-tsc/Vite build、Playwright e2e、RTK 命令包装。

---

## 文件结构

- 修改：`backend/tests/test_frontend_route_and_context_contracts.py`
  - 增加 `WorkspaceContent.vue` 标准大小合同测试。
  - 检查父组件不再包含群聊发送、会话加载、流式事件、@ 提及、快捷场景、插入文件上传等业务函数。
- 创建：`frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts`
  - 暂时承接 `WorkspaceContent.vue` 原有 provider 组装逻辑。
  - 调用既有 `useGroupWorkspacePanel`、`createGroupChatStreamRunner` 和四个 focused context provider。
  - 返回模板需要的 `groupDetail`、`groupLoading`、`groupError`、`loadGroupDetail`。
- 修改：`frontend/src/features/workspace/WorkspaceContent.vue`
  - 保留模板和 `<style>` 引用。
  - `<script setup>` 只声明 props/emit，调用 `useWorkspaceContentProviders()`。
  - 删除已迁移的大段业务状态和方法。
- 删除：仅删除 `rg` 确认无引用、且不被路由或测试使用的模块。

## 任务 1：写标准大小合同测试

**文件：**
- 修改：`backend/tests/test_frontend_route_and_context_contracts.py`

- [ ] **步骤 1：编写失败的测试**

追加测试：

```python
def test_workspace_content_is_standard_size_shell():
    src = read("frontend/src/features/workspace/WorkspaceContent.vue")
    composable = read("frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts")
    assert len(src.splitlines()) <= 1000
    assert "useWorkspaceContentProviders" in src
    assert "export function useWorkspaceContentProviders" in composable
    for name in [
        "async function sendGroupMessage",
        "async function loadGroupDetail",
        "function handleStreamMessageEvent",
        "function onAtInput",
        "async function loadShortcutPresets",
        "async function onInsertLocalFile",
    ]:
        assert name not in src
        assert name in composable
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_frontend_route_and_context_contracts.py::test_workspace_content_is_standard_size_shell'
```

预期：FAIL，原因是 `useWorkspaceContentProviders.ts` 尚不存在，且 `WorkspaceContent.vue` 仍超过 1000 行。

## 任务 2：迁移 provider 组装逻辑

**文件：**
- 创建：`frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts`
- 修改：`frontend/src/features/workspace/WorkspaceContent.vue`

- [ ] **步骤 1：创建 composable**

将 `WorkspaceContent.vue` 当前 `<script setup>` 中除 `defineProps`、`defineEmits` 之外的 provider 状态和方法迁移到：

```ts
export function useWorkspaceContentProviders(args: {
  props: WorkspaceContentProps
  emit: WorkspaceContentEmit
  hostLogoUrl: string
}) {
  const { props, emit, hostLogoUrl } = args
  // 原 provider 逻辑
  return {
    groupDetail,
    groupLoading,
    groupError,
    loadGroupDetail,
  }
}
```

- [ ] **步骤 2：缩小 `WorkspaceContent.vue`**

`WorkspaceContent.vue` 的 `<script setup>` 改成：

```ts
import hostLogoUrl from '@/assets/49logo.png'
import GroupChatHeader from './components/group-chat/GroupChatHeader.vue'
import GroupChatMessages from './components/group-chat/GroupChatMessages.vue'
import GroupChatComposer from './components/group-chat/GroupChatComposer.vue'
import GroupWorkspacePanel from './components/group-chat/GroupWorkspacePanel.vue'
import {
  type WorkspaceContentEmit,
  type WorkspaceContentProps,
  useWorkspaceContentProviders,
} from './composables/useWorkspaceContentProviders'

const props = defineProps<WorkspaceContentProps>()
const emit = defineEmits<WorkspaceContentEmit>()

const { groupDetail, groupLoading, groupError, loadGroupDetail } = useWorkspaceContentProviders({
  props,
  emit,
  hostLogoUrl,
})
```

- [ ] **步骤 3：运行静态合同测试验证通过**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_frontend_route_and_context_contracts.py::test_workspace_content_is_standard_size_shell'
```

预期：PASS。

## 任务 3：验证并清理无用模块

**文件：**
- 修改或删除：仅限 `frontend/src/features/workspace/**`

- [ ] **步骤 1：检查引用关系**

运行：

```bash
/Users/ggd/.local/bin/rtk rg -n "useWorkspaceContentProviders|WorkspaceContent|GroupChatStatusBars|useGroupWorkspacePanel|useGroupChatStreamRunner" frontend/src frontend/e2e backend/tests
```

如果某个旧模块仅剩自身定义、没有任何 import 或路由引用，再删除它；否则保留。

- [ ] **步骤 2：运行完整验证**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_frontend_route_and_context_contracts.py'
/Users/ggd/.local/bin/rtk bash -lc 'cd frontend && npm run build'
/Users/ggd/.local/bin/rtk bash -lc 'cd frontend && npx playwright test e2e/workspace.spec.ts --project=chrome'
```

预期：pytest 全部通过；build exit 0；workspace e2e 全部通过。

- [ ] **步骤 3：Commit**

```bash
/Users/ggd/.local/bin/rtk git add backend/tests/test_frontend_route_and_context_contracts.py frontend/src/features/workspace/WorkspaceContent.vue frontend/src/features/workspace/composables/useWorkspaceContentProviders.ts
/Users/ggd/.local/bin/rtk git commit -m "refactor: 将 WorkspaceContent 缩为标准入口"
```
