# 场景与专家新建默认提示词实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让资源中心新建场景和新建专家时，分别把后端唯一来源的默认模板写入各自真实的顶层 `system_prompt` 字段。

**架构：** 后端 Prompt 注册表新增场景模板并复用现有专家模板，通过一个只读设置接口返回两个资源形态的默认值。前端使用一个带失败后清缓存能力的共享加载器，在选中新建草稿之前先取得模板，再把模板作为普通字段初始值交给现有场景编辑器和专家表单；已有资源和用户主动清空的值不做回填。

**技术栈：** Python、FastAPI、Pydantic、Vue 3、TypeScript、pytest、Playwright。

---

## 文件范围

- 创建：`backend/app/agent/scenario_prompt.py`，只负责读取场景默认 Prompt。
- 修改：`backend/app/agent/platform_prompt_templates.json`，维护 `scenario.system.default.v1` 唯一正文。
- 修改：`backend/app/api/settings_app.py`，提供资源默认模板只读接口。
- 修改：`backend/tests/test_platform_prompts.py`，验证场景模板注册与访问函数。
- 修改：`backend/tests/test_sessions_api.py`，验证资源默认模板接口的精确响应结构。
- 创建：`frontend/src/features/resources/resourcePromptDefaults.ts`，定义返回类型、请求校验和可重试缓存。
- 修改：`frontend/src/features/resources/useScenarioEditor.ts`，让新场景草稿接收场景默认 Prompt。
- 修改：`frontend/src/features/resources/AgentView.vue`，让新专家表单接收专家默认 Prompt。
- 修改：`frontend/src/views/MainView.vue`，模板加载成功后才进入场景或专家新建状态。
- 修改：`backend/tests/test_frontend_route_and_context_contracts.py`，静态验证前端初始化边界。
- 修改：`frontend/e2e/fixtures/mockApi.ts`，模拟资源默认模板接口。
- 修改：`frontend/e2e/resources-scenario-expert.spec.ts`，验证真实浏览器中的预填与保存行为。

## 任务 1：建立后端模板与接口

- [ ] **步骤 1：编写场景模板和接口失败测试**

在 `backend/tests/test_platform_prompts.py` 增加：

```python
def test_default_scenario_system_prompt_is_registered_and_editable():
    scenario_prompt = importlib.import_module("app.agent.scenario_prompt")
    rendered = scenario_prompt.get_default_scenario_system_prompt()

    assert rendered == render_platform_prompt("scenario.system.default.v1", {})
    for required in ["场景目标", "适用范围", "共同要求", "完成标准"]:
        assert required in rendered
```

在 `backend/tests/test_sessions_api.py` 增加：

```python
def test_resource_prompt_defaults_expose_resource_shaped_system_prompt_fields(client: TestClient):
    from app.agent.platform_prompts import render_platform_prompt

    response = client.get("/api/settings/resource-prompt-defaults")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "data": {
            "scenario": {
                "system_prompt": render_platform_prompt("scenario.system.default.v1", {}),
            },
            "expert": {
                "system_prompt": render_platform_prompt("expert.system.default.v1", {}),
            },
        },
    }
```

- [ ] **步骤 2：运行测试验证正确失败**

运行：

```bash
rtk pytest -q \
  backend/tests/test_platform_prompts.py::test_default_scenario_system_prompt_is_registered_and_editable \
  backend/tests/test_sessions_api.py::test_resource_prompt_defaults_expose_resource_shaped_system_prompt_fields
```

预期：FAIL；第一项因 `app.agent.scenario_prompt` 不存在失败，第二项因接口返回 404 失败。

- [ ] **步骤 3：实现最少后端代码**

创建 `backend/app/agent/scenario_prompt.py`：

```python
"""Scenario-level prompt access for resource draft initialization."""
from __future__ import annotations

from app.agent.platform_prompts import render_platform_prompt


def get_default_scenario_system_prompt() -> str:
    """Return the editable default prompt for a new scenario resource."""
    return render_platform_prompt("scenario.system.default.v1", {})
```

在 `backend/app/agent/platform_prompt_templates.json` 注册设计规格中的完整 `scenario.system.default.v1` 正文。

在 `backend/app/api/settings_app.py` 导入 `get_default_scenario_system_prompt` 和 `get_default_expert_system_prompt`，新增：

```python
@router.get("/settings/resource-prompt-defaults")
async def get_resource_prompt_defaults():
    return {
        "status": "ok",
        "data": {
            "scenario": {"system_prompt": get_default_scenario_system_prompt()},
            "expert": {"system_prompt": get_default_expert_system_prompt()},
        },
    }
```

- [ ] **步骤 4：运行测试验证通过**

运行任务 1 步骤 2 的命令。预期：2 passed。

- [ ] **步骤 5：提交后端合同**

```bash
rtk git add \
  backend/app/agent/scenario_prompt.py \
  backend/app/agent/platform_prompt_templates.json \
  backend/app/api/settings_app.py \
  backend/tests/test_platform_prompts.py \
  backend/tests/test_sessions_api.py
rtk git commit -m "feat: 提供资源默认提示词"
```

## 任务 2：让前端新建草稿使用真实默认字段

- [ ] **步骤 1：编写前端合同失败测试**

在 `backend/tests/test_frontend_route_and_context_contracts.py` 增加：

```python
def test_resource_creation_prefills_real_system_prompt_fields_from_backend_defaults():
    loader = read("frontend/src/features/resources/resourcePromptDefaults.ts")
    main = read("frontend/src/views/MainView.vue")
    scenario = read("frontend/src/features/resources/useScenarioEditor.ts")
    agent = read("frontend/src/features/resources/AgentView.vue")

    assert "/settings/resource-prompt-defaults" in loader
    assert "resourcePromptDefaultsPromise = null" in loader
    assert "await loadResourcePromptDefaults()" in main
    assert "createScenarioPreset(defaults.scenario.system_prompt)" in main
    assert "expertDefaultSystemPrompt.value = defaults.expert.system_prompt" in main
    assert "system_prompt: defaultSystemPrompt" in scenario
    assert "defaultSystemPrompt: string" in agent
    assert "system_prompt: props.defaultSystemPrompt" in agent
```

- [ ] **步骤 2：运行测试验证正确失败**

运行：

```bash
rtk pytest -q backend/tests/test_frontend_route_and_context_contracts.py::test_resource_creation_prefills_real_system_prompt_fields_from_backend_defaults
```

预期：FAIL，报错 `resourcePromptDefaults.ts` 不存在。

- [ ] **步骤 3：实现共享默认值加载器**

创建 `frontend/src/features/resources/resourcePromptDefaults.ts`：

```typescript
import { apiRequest } from '@/api/base'

export type ResourcePromptDefaults = {
  scenario: { system_prompt: string }
  expert: { system_prompt: string }
}

let resourcePromptDefaultsPromise: Promise<ResourcePromptDefaults> | null = null

export function loadResourcePromptDefaults(): Promise<ResourcePromptDefaults> {
  if (!resourcePromptDefaultsPromise) {
    resourcePromptDefaultsPromise = apiRequest('/settings/resource-prompt-defaults')
      .then(async (response) => {
        const payload = await response.json().catch(() => ({}))
        const scenarioPrompt = payload?.data?.scenario?.system_prompt
        const expertPrompt = payload?.data?.expert?.system_prompt
        if (payload?.status !== 'ok' || typeof scenarioPrompt !== 'string' || typeof expertPrompt !== 'string') {
          throw new Error(payload?.detail || '默认提示词响应无效')
        }
        return {
          scenario: { system_prompt: scenarioPrompt },
          expert: { system_prompt: expertPrompt },
        }
      })
      .catch((error) => {
        resourcePromptDefaultsPromise = null
        throw error
      })
  }
  return resourcePromptDefaultsPromise
}
```

- [ ] **步骤 4：让新建入口等待模板后再创建草稿**

修改 `useScenarioEditor.ts`：

```typescript
function createScenarioPreset(defaultSystemPrompt: string) {
  // 保留现有草稿过滤逻辑
  const next: ScenarioPreset = {
    name: '',
    agent_names: [],
    description: '',
    system_prompt: defaultSystemPrompt,
    host: {},
  }
  // 保留现有列表、selectedId 和同步逻辑
}
```

修改 `AgentView.vue` props 与新建分支：

```typescript
const props = defineProps<{
  selectedAgentId: string | null
  agentInstances: AgentItem[]
  defaultSystemPrompt: string
}>()

// selectedAgentId === '__new__' 时
form.value = {
  name: '',
  description: '',
  system_prompt: props.defaultSystemPrompt,
  skills: [],
  llm_name: '',
}
```

修改 `MainView.vue`：

```typescript
const expertDefaultSystemPrompt = ref('')

async function createScenarioWithDefaultPrompt() {
  try {
    const defaults = await loadResourcePromptDefaults()
    createScenarioPreset(defaults.scenario.system_prompt)
  } catch (error) {
    await appAlert({ title: '无法新建场景', message: (error as Error).message || '默认提示词加载失败', variant: 'danger' })
  }
}

async function createAgentWithDefaultPrompt() {
  try {
    const defaults = await loadResourcePromptDefaults()
    expertDefaultSystemPrompt.value = defaults.expert.system_prompt
    selectedId.value = '__new__'
  } catch (error) {
    await appAlert({ title: '无法新建专家', message: (error as Error).message || '默认提示词加载失败', variant: 'danger' })
  }
}
```

模板绑定改为 `@click="createScenarioWithDefaultPrompt"`、`@click="createAgentWithDefaultPrompt"`，并向 `AgentView` 传入 `:default-system-prompt="expertDefaultSystemPrompt"`。

- [ ] **步骤 5：运行前端合同与构建验证通过**

运行：

```bash
rtk pytest -q backend/tests/test_frontend_route_and_context_contracts.py::test_resource_creation_prefills_real_system_prompt_fields_from_backend_defaults
cd frontend && rtk npm run build
```

预期：静态合同 1 passed；Vue 构建退出码 0。

- [ ] **步骤 6：提交前端初始化链路**

```bash
rtk git add \
  frontend/src/features/resources/resourcePromptDefaults.ts \
  frontend/src/features/resources/useScenarioEditor.ts \
  frontend/src/features/resources/AgentView.vue \
  frontend/src/views/MainView.vue \
  backend/tests/test_frontend_route_and_context_contracts.py
rtk git commit -m "feat: 新建资源预填默认提示词"
```

## 任务 3：用浏览器流程验证预填和保存

- [ ] **步骤 1：编写 Playwright 失败断言**

在 `frontend/e2e/fixtures/mockApi.ts` 的 mock 路由中返回短且唯一的测试模板：

```typescript
if (path === '/settings/resource-prompt-defaults' && method === 'GET') {
  return ok(route, {
    scenario: { system_prompt: '默认场景提示词' },
    expert: { system_prompt: '默认专家提示词' },
  })
}
```

先在 `frontend/e2e/resources-scenario-expert.spec.ts` 添加用例，暂不添加上述 mock 路由：

```typescript
test('新建场景和专家分别预填并保存各自默认提示词', async ({ page }) => {
  const state = createE2eState()
  await loginByStorage(page)
  await mockApi(page, state)
  await page.goto('/resources/scenario')

  await page.getByRole('button', { name: '新建场景' }).click()
  await expect(page.getByPlaceholder('写入场景目标、适用范围、共同要求和完成标准。创建会话时保存快照，并持续提供给主持人和专家。')).toHaveValue('默认场景提示词')

  await page.goto('/resources/agent')
  await page.getByRole('button', { name: '新建专家' }).click()
  await expect(page.getByPlaceholder('定义专家跨场景、跨 Skill 不变的长期职责、专业标准和输出合同。')).toHaveValue('默认专家提示词')
})
```

- [ ] **步骤 2：运行测试验证正确失败**

运行：

```bash
cd frontend && rtk npx playwright test e2e/resources-scenario-expert.spec.ts --grep "分别预填并保存各自默认提示词"
```

预期：FAIL，请求默认模板接口时没有取得有效响应或 textarea 未出现预期值。

- [ ] **步骤 3：补齐 mock 接口并验证修改、清空和旧值边界**

加入步骤 1 的 mock 路由，并把用例扩展为：

- 场景默认值出现后改为“自定义场景提示词”，填写必需名称和专家并保存，断言 `state.scenarios` 中保存的是自定义值。
- 专家默认值出现后清空，填写名称并保存，断言 `state.agents` 中保存的是空字符串。
- 打开已有专家“问答专家”，断言仍显示 fixture 中已有的 `system_prompt`，未被默认专家模板覆盖。

同时将 `upsertAgent()` 的 `system_prompt` 合并从 `body.system_prompt || existing?.system_prompt` 改为检查字段是否存在，确保显式空字符串不会被旧值覆盖：

```typescript
system_prompt: Object.prototype.hasOwnProperty.call(body, 'system_prompt')
  ? String(body.system_prompt ?? '')
  : String(existing?.system_prompt || ''),
```

- [ ] **步骤 4：运行 Playwright 验证通过**

运行任务 3 步骤 2 的命令。预期：1 passed。

- [ ] **步骤 5：提交浏览器验收链路**

```bash
rtk git add frontend/e2e/fixtures/mockApi.ts frontend/e2e/resources-scenario-expert.spec.ts
rtk git commit -m "test: 覆盖资源默认提示词流程"
```

## 任务 4：完整回归与交付核对

- [ ] **步骤 1：运行后端定向测试**

```bash
rtk pytest -q \
  backend/tests/test_platform_prompts.py \
  backend/tests/test_sessions_api.py
```

预期：全部通过。

- [ ] **步骤 2：运行前端合同测试，记录既有基线失败边界**

```bash
rtk pytest -q backend/tests/test_frontend_route_and_context_contracts.py
```

预期：本次新增合同通过；允许且只允许保留实现前已经确认的既有失败 `test_workspace_content_is_standard_size_shell`（`useWorkspaceContent.ts` 711 行，大于 700 行限制）。若出现其他失败，必须修复后继续。

- [ ] **步骤 3：运行前端构建与浏览器定向用例**

```bash
cd frontend
rtk npm run build
rtk npx playwright test e2e/resources-scenario-expert.spec.ts --grep "分别预填并保存各自默认提示词"
```

预期：构建退出码 0，Playwright 1 passed。

- [ ] **步骤 4：检查工作区和需求边界**

```bash
rtk git diff --check
rtk git status --short
rtk git log -5 --oneline
```

核对：未修改 `backend/data/users`；场景和专家仍只保存顶层 `system_prompt`；旧资源不被回填；显式空字符串可保存；没有把完整默认正文复制进 Vue 或 E2E fixture。
