# Frontend Route Boundary and Workspace Context 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为工作空间、资源中心、设置建立真实前端路由边界，并把 `WorkspaceContent.vue` 的群聊大 provider 拆成 typed focused contexts。

**架构：** 保持单个 Vite/Vue 应用，新增 `/workspace`、`/resources/:section`、`/settings/:section` 作为 canonical 页面 URL；`MainView.vue` 从 route 派生活跃模块，不再用 `currentModule` 作为页面源状态。`WorkspaceContent.vue` 仍先作为 provider 宿主，但把原来的 `Record<string, any>` aggregate context 拆成 session/message/composer/workspace-panel 四个 typed context。

**技术栈：** Vue 3、vue-router、Playwright e2e、pytest 静态架构测试、vue-tsc/Vite build、RTK 命令包装。

---

## 文件结构

- 修改：`frontend/src/router/index.ts`
  - 注册 `/workspace`、`/resources/:section`、`/settings/:section`
  - 将 `/` 作为 `/workspace` 的兼容入口
  - 对非法 resource/settings section 做 canonical redirect
- 修改：`frontend/src/views/MainView.vue`
  - route 派生 `currentModule`、`resourceSubModule`、settings selected id
  - 导航按钮改为 `router.push()` canonical URL
  - 资源中心专家 URL 用 `agent`，不新增 `/resources/dha`
- 修改：`frontend/e2e/auth.spec.ts`
  - 登录后断言进入 `/workspace`
- 创建：`frontend/e2e/route-boundaries.spec.ts`
  - 覆盖 `/workspace`、`/resources/agent`、`/settings/sandbox`、非法 section redirect
- 修改：`frontend/e2e/resources-scenario-expert.spec.ts`
  - 专家页从 `/resources/agent` 进入，而不是依赖点击旧内部状态
- 修改：`frontend/src/features/workspace/components/group-chat/groupChatWorkspaceContext.ts`
  - 删除 aggregate any context
  - 定义四个 typed context 和对应 provide/use hooks
- 修改：
  - `frontend/src/features/workspace/WorkspaceContent.vue`
  - `frontend/src/features/workspace/components/group-chat/GroupChatHeader.vue`
  - `frontend/src/features/workspace/components/group-chat/GroupChatMessages.vue`
  - `frontend/src/features/workspace/components/group-chat/GroupChatComposer.vue`
  - `frontend/src/features/workspace/components/group-chat/GroupWorkspacePanel.vue`
- 创建：`backend/tests/test_frontend_route_and_context_contracts.py`
  - 静态锁定 route/context 合同，弥补没有 frontend unit test runner 的缺口

## 任务 1：路由边界与 `agent` URL 命名

**文件：**
- 创建：`backend/tests/test_frontend_route_and_context_contracts.py`
- 创建：`frontend/e2e/route-boundaries.spec.ts`
- 修改：`frontend/e2e/auth.spec.ts`
- 修改：`frontend/e2e/resources-scenario-expert.spec.ts`
- 修改：`frontend/src/router/index.ts`
- 修改：`frontend/src/views/MainView.vue`

- [ ] **步骤 1：编写失败的路由契约测试**

在 `backend/tests/test_frontend_route_and_context_contracts.py` 写入：

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_router_exposes_canonical_business_routes():
    src = read("frontend/src/router/index.ts")
    assert "path: '/workspace'" in src
    assert "path: '/resources/:section?'" in src
    assert "path: '/settings/:section?'" in src
    assert "'agent'" in src
    assert "/resources/dha" not in src


def test_main_view_uses_route_as_navigation_source():
    src = read("frontend/src/views/MainView.vue")
    assert "const currentModule = computed<ModuleId>" in src
    assert "router.push(resourceRoutePath(id))" in src
    assert "router.push(settingsRoutePath(" in src
    assert "type ResourceSubModule = 'scenario' | 'agent' | 'skill' | 'mcp' | 'llm' | 'files'" in src
```

在 `frontend/e2e/route-boundaries.spec.ts` 写入：

```ts
import { expect, test } from '@playwright/test'
import { bootLoggedInApp, mockApi } from './fixtures/mockApi'

test.describe('路由边界', () => {
  test('根路径登录后进入工作空间 canonical URL', async ({ page }) => {
    await bootLoggedInApp(page, '/')
    await expect(page).toHaveURL(/\/workspace$/)
    await expect(page.getByRole('heading', { name: '已有验收会话' })).toBeVisible()
  })

  test('资源中心专家页可以直接打开 /resources/agent', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/agent')
    await expect(page).toHaveURL(/\/resources\/agent$/)
    await expect(page.getByRole('button', { name: '专家', exact: true })).toHaveClass(/bg-nav-selected-bg/)
    await expect(page.getByRole('complementary').getByText('问答专家').first()).toBeVisible()
  })

  test('设置沙箱页可以直接打开 /settings/sandbox', async ({ page }) => {
    await bootLoggedInApp(page, '/settings/sandbox')
    await expect(page).toHaveURL(/\/settings\/sandbox$/)
    await expect(page.getByRole('button', { name: '沙箱' })).toHaveClass(/bg-accent-subtle/)
    await expect(page.getByText('普通版')).toBeVisible()
  })

  test('非法资源和设置 section 会归一化', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/dha')
    await expect(page).toHaveURL(/\/resources\/agent$/)

    await page.goto('/settings/unknown')
    await expect(page).toHaveURL(/\/settings\/app$/)
  })

  test('未登录访问受保护路由仍跳转登录并保留 redirect', async ({ page }) => {
    await mockApi(page)
    await page.goto('/resources/agent')
    await expect(page).toHaveURL(/\/login\?redirect=%2Fresources%2Fagent/)
  })
})
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_frontend_route_and_context_contracts.py::test_router_exposes_canonical_business_routes tests/test_frontend_route_and_context_contracts.py::test_main_view_uses_route_as_navigation_source'
```

预期：FAIL，原因是 `/workspace`、`/resources/:section?`、`computed<ModuleId>` 等尚未实现。

运行：

```bash
/Users/ggd/.local/bin/rtk bash -lc 'cd frontend && npx playwright test e2e/route-boundaries.spec.ts --project=chrome'
```

预期：至少 `/resources/agent` 和 `/settings/sandbox` 相关用例失败，因为 router 还没有这些直接 URL。

- [ ] **步骤 3：实现最小路由代码**

在 `frontend/src/router/index.ts` 中：

```ts
const resourceSections = new Set(['scenario', 'agent', 'skill', 'mcp', 'llm', 'files'])
const settingsSections = new Set(['app', 'theme', 'secrets', 'account-security', 'sandbox'])

function normalizeSectionRoute(to: { path: string; params: Record<string, unknown>; query: Record<string, unknown>; hash: string }) {
  if (to.path.startsWith('/resources')) {
    const section = String(to.params.section || 'scenario')
    const target = resourceSections.has(section) ? section : (section === 'dha' ? 'agent' : 'scenario')
    if (to.path !== `/resources/${target}`) return { path: `/resources/${target}`, query: to.query, hash: to.hash }
  }
  if (to.path.startsWith('/settings')) {
    const section = String(to.params.section || 'app')
    const target = settingsSections.has(section) ? section : 'app'
    if (to.path !== `/settings/${target}`) return { path: `/settings/${target}`, query: to.query, hash: to.hash }
  }
}
```

并添加 routes：

```ts
{ path: '/', redirect: '/workspace' },
{ path: '/workspace', name: 'workspace', component: MainView, meta: { requiresAuth: true } },
{ path: '/resources/:section?', name: 'resources', component: MainView, meta: { requiresAuth: true } },
{ path: '/settings/:section?', name: 'settings', component: MainView, meta: { requiresAuth: true } },
```

在 `beforeEach` 中先处理 `requiresAuth`，再处理 `normalizeSectionRoute(to)`，登录页已登录时跳转 `/workspace`。

- [ ] **步骤 4：实现 MainView route-derived navigation**

在 `frontend/src/views/MainView.vue` 中：

```ts
type ModuleId = 'workspace' | 'resource' | 'settings'
type ResourceSubModule = 'scenario' | 'agent' | 'skill' | 'mcp' | 'llm' | 'files'
type SettingsCategoryId = 'app' | 'theme' | 'secrets' | 'account-security' | 'sandbox'

function resourceRoutePath(id: ResourceSubModule) {
  return `/resources/${id}`
}

function settingsRoutePath(id: SettingsCategoryId) {
  return `/settings/${id}`
}

const currentModule = computed<ModuleId>(() => {
  if (route.path.startsWith('/resources')) return 'resource'
  if (route.path.startsWith('/settings')) return 'settings'
  return 'workspace'
})

const resourceSubModule = computed<ResourceSubModule>(() => {
  const section = String(route.params.section || 'scenario')
  return section === 'agent' || section === 'skill' || section === 'mcp' || section === 'llm' || section === 'files'
    ? section
    : 'scenario'
})
```

将 `onNavClick` 改为 `router.push('/workspace')`、`router.push('/resources/scenario')`、`router.push('/settings/app')`。将 `onResourceChildClick(id)` 改为 `router.push(resourceRoutePath(id))`。settings 列表按钮改为 `router.push(settingsRoutePath(c.id))`。

保留内部数据变量名 `dhaInstances` 等，但 UI/URL 层的资源 section 命名用 `agent`。

- [ ] **步骤 5：运行路由测试验证通过**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_frontend_route_and_context_contracts.py::test_router_exposes_canonical_business_routes tests/test_frontend_route_and_context_contracts.py::test_main_view_uses_route_as_navigation_source'
```

预期：PASS。

运行：

```bash
/Users/ggd/.local/bin/rtk bash -lc 'cd frontend && npx playwright test e2e/route-boundaries.spec.ts --project=chrome'
```

预期：PASS。

- [ ] **步骤 6：Commit**

```bash
/Users/ggd/.local/bin/rtk git add backend/tests/test_frontend_route_and_context_contracts.py frontend/e2e/route-boundaries.spec.ts frontend/e2e/auth.spec.ts frontend/e2e/resources-scenario-expert.spec.ts frontend/src/router/index.ts frontend/src/views/MainView.vue
/Users/ggd/.local/bin/rtk git commit -m "feat: 建立前端业务路由边界（任务 1/2）"
```

## 任务 2：拆分 Workspace 群聊 provider contexts

**文件：**
- 修改：`backend/tests/test_frontend_route_and_context_contracts.py`
- 修改：`frontend/src/features/workspace/components/group-chat/groupChatWorkspaceContext.ts`
- 修改：`frontend/src/features/workspace/WorkspaceContent.vue`
- 修改：`frontend/src/features/workspace/components/group-chat/GroupChatHeader.vue`
- 修改：`frontend/src/features/workspace/components/group-chat/GroupChatMessages.vue`
- 修改：`frontend/src/features/workspace/components/group-chat/GroupChatComposer.vue`
- 修改：`frontend/src/features/workspace/components/group-chat/GroupWorkspacePanel.vue`

- [ ] **步骤 1：编写失败的 provider 契约测试**

追加到 `backend/tests/test_frontend_route_and_context_contracts.py`：

```python
def test_group_chat_context_is_split_and_typed():
    src = read("frontend/src/features/workspace/components/group-chat/groupChatWorkspaceContext.ts")
    assert "Record<string, any>" not in src
    for name in [
        "GroupChatSessionContext",
        "GroupChatMessageContext",
        "GroupChatComposerContext",
        "GroupChatWorkspacePanelContext",
        "useGroupChatSessionContext",
        "useGroupChatMessageContext",
        "useGroupChatComposerContext",
        "useGroupChatWorkspacePanelContext",
    ]:
        assert name in src
    assert "useGroupChatWorkspaceContext" not in src


def test_group_chat_components_do_not_use_aggregate_context():
    files = [
        "frontend/src/features/workspace/WorkspaceContent.vue",
        "frontend/src/features/workspace/components/group-chat/GroupChatHeader.vue",
        "frontend/src/features/workspace/components/group-chat/GroupChatMessages.vue",
        "frontend/src/features/workspace/components/group-chat/GroupChatComposer.vue",
        "frontend/src/features/workspace/components/group-chat/GroupWorkspacePanel.vue",
    ]
    combined = "\n".join(read(path) for path in files)
    assert "provideGroupChatWorkspaceContext" not in combined
    assert "useGroupChatWorkspaceContext" not in combined
    assert "provideGroupChatSessionContext" in combined
    assert "provideGroupChatMessageContext" in combined
    assert "provideGroupChatComposerContext" in combined
    assert "provideGroupChatWorkspacePanelContext" in combined
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_frontend_route_and_context_contracts.py::test_group_chat_context_is_split_and_typed tests/test_frontend_route_and_context_contracts.py::test_group_chat_components_do_not_use_aggregate_context'
```

预期：FAIL，原因是当前 context 仍是 `Record<string, any>` 且组件仍使用 aggregate hook。

- [ ] **步骤 3：定义 typed focused contexts**

在 `groupChatWorkspaceContext.ts` 中定义四个 context。类型可以先使用 `unknown` / function signatures 做边界约束，不能使用 `Record<string, any>`：

```ts
import { inject, provide } from 'vue'

export type GroupChatSessionContext = {
  props: unknown
  emit: unknown
  groupDetail: unknown
  sessionMetaPopoverRootRef: unknown
  sessionMetaPopoverOpen: unknown
  toggleSessionMetaPopover: () => void
  sessionTitleDraft: unknown
  saveSessionTitle: () => unknown
  titleSaving: unknown
  archiveItems: unknown
  tocActiveKey: unknown
  jumpToSessionTopic: (key: string) => unknown
  renderSnippetMarkdown: (text: string) => string
}
```

继续定义 `GroupChatMessageContext`、`GroupChatComposerContext`、`GroupChatWorkspacePanelContext`，每个 context 配套 `provide*Context()` 和 `use*Context()`。

- [ ] **步骤 4：WorkspaceContent 提供四个 context**

把原来的：

```ts
provideGroupChatWorkspaceContext({ ... })
```

替换为：

```ts
provideGroupChatSessionContext({ ... })
provideGroupChatMessageContext({ ... })
provideGroupChatComposerContext({ ... })
provideGroupChatWorkspacePanelContext({ ... })
```

每个对象只包含对应组件当前 destructure 需要的字段。

- [ ] **步骤 5：迁移子组件 imports**

将子组件从 aggregate hook 改为 focused hooks：

```ts
import {
  useGroupChatComposerContext,
  useGroupChatMessageContext,
} from './groupChatWorkspaceContext'
```

`GroupChatHeader.vue` 只使用 session/message 相关 hook，`GroupChatMessages.vue` 使用 message hook，`GroupChatComposer.vue` 使用 composer hook 加少量 display hook，`GroupWorkspacePanel.vue` 使用 workspace-panel hook。

- [ ] **步骤 6：运行 provider 测试和前端构建**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_frontend_route_and_context_contracts.py'
```

预期：PASS。

运行：

```bash
/Users/ggd/.local/bin/rtk bash -lc 'cd frontend && npm run build'
```

预期：PASS。

- [ ] **步骤 7：Commit**

```bash
/Users/ggd/.local/bin/rtk git add backend/tests/test_frontend_route_and_context_contracts.py frontend/src/features/workspace/components/group-chat/groupChatWorkspaceContext.ts frontend/src/features/workspace/WorkspaceContent.vue frontend/src/features/workspace/components/group-chat/GroupChatHeader.vue frontend/src/features/workspace/components/group-chat/GroupChatMessages.vue frontend/src/features/workspace/components/group-chat/GroupChatComposer.vue frontend/src/features/workspace/components/group-chat/GroupWorkspacePanel.vue
/Users/ggd/.local/bin/rtk git commit -m "refactor: 拆分工作区群聊上下文（任务 2/2）"
```

## 最终验证

- [ ] **步骤 1：运行架构契约测试**

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_frontend_route_and_context_contracts.py'
```

- [ ] **步骤 2：运行相关 e2e**

```bash
/Users/ggd/.local/bin/rtk bash -lc 'cd frontend && npx playwright test e2e/route-boundaries.spec.ts e2e/auth.spec.ts e2e/resources-scenario-expert.spec.ts --project=chrome'
```

- [ ] **步骤 3：运行前端构建**

```bash
/Users/ggd/.local/bin/rtk bash -lc 'cd frontend && npm run build'
```

- [ ] **步骤 4：静态确认没有 aggregate hook**

```bash
/Users/ggd/.local/bin/rtk rg -n "useGroupChatWorkspaceContext|provideGroupChatWorkspaceContext|Record<string, any>|/resources/dha" frontend/src backend/tests/test_frontend_route_and_context_contracts.py
```

预期：无输出。
