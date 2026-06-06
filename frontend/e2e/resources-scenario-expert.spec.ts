import { expect, test } from '@playwright/test'
import { bootLoggedInApp, createE2eState, loginByStorage, mockApi } from './fixtures/mockApi'

test.describe('验收 3/6：资源中心场景与专家', () => {
  test('用户可以查看并保存场景配置', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '资源中心' }).click()
    await page.getByRole('button', { name: '场景', exact: true }).click()
    await expect(page.getByRole('heading', { name: '配置场景' })).toBeVisible()
    await expect(page.getByPlaceholder('请输入场景名称')).toHaveValue('问答验收场景')
    await expect(page.getByText('场景主持人')).toBeVisible()
    await expect(page.getByText('协作专家')).toBeVisible()
    await expect(page.locator('form').getByText('访问方式', { exact: true })).toHaveCount(0)

    await page.getByPlaceholder('请输入场景描述').fill('通过 UI 自动化保存的场景说明')
    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('问答验收场景')).toBeVisible()
  })

  test('创建场景草稿未保存前不出现在场景列表', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/scenario')

    const sidebar = page.getByRole('complementary')
    await page.getByRole('button', { name: '创建场景' }).click()
    await page.getByRole('button', { name: '创建场景' }).click()
    await page.getByRole('button', { name: '创建场景' }).click()

    await expect(page.getByRole('heading', { name: '创建场景' })).toBeVisible()
    await expect(sidebar.getByText('0 位专家', { exact: true })).toHaveCount(0)
  })

  test('导入场景包后不会被工作区空快捷场景覆盖', async ({ page }) => {
    const state = createE2eState()
    state.scenarios = []
    let emptyPresetPutCount = 0
    let importCallCount = 0
    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/settings/session-presets/import-bundle', async (route) => {
      importCallCount += 1
      if (importCallCount >= 2) {
        state.scenarios = [
          {
            id: 'scenario-imported',
            name: '导入后场景',
            description: '导入后不能被空列表覆盖',
            agent_ids: ['agent-qa'],
            leader_agent_id: 'agent-qa',
            updated_at: '2026-05-29T06:43:22Z',
          },
        ]
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          data: {
            bundle_preview: {
              preset_id: 'scenario-imported',
              preset_name: '导入后场景',
              experts: [{ agent_id: 'agent-qa', name: '问答专家' }],
              skills: [],
              mcps: [],
            },
            summary: {
              preset_imported_ids: ['scenario-imported'],
              skills_imported: [],
              skills_skipped: [],
              skipped_by_name: [],
              overwritten_existing_ids: [],
              mcp_added: 0,
            },
          },
        }),
      })
    })
    await page.route('**/api/settings/session-presets', async (route) => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON() as { presets?: Array<{ id?: string }> }
        if (Array.isArray(body.presets) && body.presets.length === 0) {
          emptyPresetPutCount += 1
        }
      }
      await route.fallback()
    })

    await page.goto('/resources/scenario')
    await expect(page.getByTitle('导入场景包（ZIP）')).toBeVisible()
    await page.setInputFiles('input[type="file"][accept=".zip,application/zip"]', {
      name: 'scenario.zip',
      mimeType: 'application/zip',
      buffer: Buffer.from('mock zip'),
    })
    await expect(page.getByRole('heading', { name: '导入场景' })).toBeVisible()
    await page.getByRole('button', { name: '确认导入' }).click()
    await expect(page.getByText('导入成功')).toBeVisible()
    await page.waitForTimeout(300)

    expect(emptyPresetPutCount).toBe(0)
    expect(state.scenarios.map((item) => item.id)).toEqual(['scenario-imported'])
  })

  test('导入场景包预览展示冲突和依赖信息', async ({ page }) => {
    const state = createE2eState()
    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/settings/session-presets/import-bundle', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          data: {
            bundle_preview: {
              preset_id: 'scene-imported',
              preset_name: '冲突场景',
              experts: [{ agent_id: 'agent-new', name: '导入专家' }],
              skills: ['skill-new'],
              mcps: [{ id: 'mcp-new', name: '导入工具' }],
              name_conflict_existing_ids: ['scene-local'],
              would_overwrite_experts: { 'agent-new': ['agent-local'] },
              would_remap_skill_ids: { 'skill-local': 'skill-new' },
              would_remap_mcp_server_ids: { 'mcp-local': 'mcp-new' },
              missing_references: {
                experts: [],
                skills: [{ id: 'skill-missing', display_name: '技能 缺失技能', required_by: ['专家 导入专家'], type_label: '技能' }],
                tools: [],
              },
            },
          },
        }),
      })
    })

    await page.goto('/resources/scenario')
    await page.setInputFiles('input[type="file"][accept=".zip,application/zip"]', {
      name: 'scenario.zip',
      mimeType: 'application/zip',
      buffer: Buffer.from('mock zip'),
    })

    await expect(page.getByRole('heading', { name: '导入场景' })).toBeVisible()
    await expect(page.getByText('冲突预览')).toBeVisible()
    await expect(page.getByText('已有场景：scene-local')).toBeVisible()
    await expect(page.getByText('专家：导入专家 → 覆盖 agent-local')).toBeVisible()
    await expect(page.getByText('Skill：skill-local → skill-new')).toBeVisible()
    await expect(page.getByText('MCP：mcp-local → mcp-new')).toBeVisible()
    await expect(page.getByText('技能 缺失技能')).toBeVisible()
    await expect(page.getByRole('button', { name: '确认覆盖导入' })).toBeVisible()
  })

  test('用户可以创建专家并保存专家配置', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/agent')

    await expect(page).toHaveURL(/\/resources\/agent$/)
    await expect(page.getByRole('complementary').getByText('问答专家').first()).toBeVisible()

    await page.getByRole('button', { name: '创建专家' }).click()
    await expect(page.getByRole('heading', { name: '创建专家' })).toBeVisible()
    await page.getByPlaceholder('请输入专家名称').fill('自动化专家')
    await page.getByPlaceholder('请输入专家描述').fill('负责验收真实用户点击路径')
    await page.getByRole('button', { name: '保存' }).click()

    await expect(page.getByRole('complementary').getByText('自动化专家').first()).toBeVisible()
  })

  test('专家详情页不展示公开链接入口', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/agent')

    await expect(page.getByRole('heading', { name: '配置专家' })).toBeVisible()
    await expect(page.getByRole('button', { name: '分享', exact: true })).toHaveCount(0)
    await expect(page.locator('form').getByText('访问方式', { exact: true })).toHaveCount(0)
  })
})
