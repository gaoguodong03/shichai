import { expect, test } from '@playwright/test'
import { bootLoggedInApp, createE2eState, loginByStorage, mockApi } from './fixtures/mockApi'

test.describe('验收 3/6：资源中心场景与专家', () => {
  async function expectAlert(page: import('@playwright/test').Page, title: string, message: string) {
    const dialog = page.getByRole('dialog', { name: title })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText(message)).toBeVisible()
    await dialog.getByRole('button', { name: '知道了' }).click()
    await expect(dialog).toHaveCount(0)
  }

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
    await page.getByPlaceholder('写入仅适用于该场景的项目规则，会同时提供给主持人和场景内专家。').fill('场景级自动化验收规则')
    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('问答验收场景')).toBeVisible()
  })

  test('name-based 主持人 Skill 快照不显示为缺失技能', async ({ page }) => {
    const state = createE2eState()
    state.scenarios[0].host = {
      ...(state.scenarios[0].host || {}),
      skill_name: '问答技能',
      skill_directory: 'skill-qa',
    }

    await loginByStorage(page)
    await mockApi(page, state)
    await page.goto('/resources/scenario')

    await expect(page.getByText('缺失技能')).toHaveCount(0)
    await expect(page.getByText('问答技能')).toBeVisible()
  })

  test('刷新直达场景页会加载专家和技能依赖', async ({ page }) => {
    const state = createE2eState()
    let agentsFetchCount = 0
    let skillsFetchCount = 0

    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/agents', async (route) => {
      if (route.request().method() === 'GET') agentsFetchCount += 1
      await route.fallback()
    })
    await page.route('**/api/settings/skills', async (route) => {
      if (route.request().method() === 'GET') skillsFetchCount += 1
      await route.fallback()
    })

    await page.goto('/resources/scenario')

    await expect.poll(() => agentsFetchCount).toBeGreaterThan(0)
    await expect.poll(() => skillsFetchCount).toBeGreaterThan(0)
    await expect(page.getByRole('button', { name: '问答技能' })).toBeVisible()
    await expect(page.getByRole('main').getByText('问答专家')).toBeVisible()
    await expect(page.getByText('缺失技能')).toHaveCount(0)
    await expect(page.getByText('缺失专家')).toHaveCount(0)
  })

  test('新建场景草稿未保存前不出现在场景列表', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/scenario')

    const sidebar = page.getByRole('complementary')
    await page.getByRole('button', { name: '新建场景' }).click()
    await page.getByRole('button', { name: '新建场景' }).click()
    await page.getByRole('button', { name: '新建场景' }).click()

    await expect(page.getByRole('heading', { name: '新建场景' })).toBeVisible()
    await expect(sidebar.getByText('0 位专家', { exact: true })).toHaveCount(0)
  })

  test('新建场景和专家必填为空时弹窗阻止保存', async ({ page }) => {
    const state = createE2eState()
    let scenarioSaveCount = 0
    let agentCreateCount = 0

    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/settings/session-presets', async (route) => {
      if (route.request().method() === 'PUT') scenarioSaveCount += 1
      await route.fallback()
    })
    await page.route('**/api/agents', async (route) => {
      if (route.request().method() === 'POST') agentCreateCount += 1
      await route.fallback()
    })

    await page.goto('/resources/scenario')
    await page.getByRole('button', { name: '新建场景' }).click()
    await page.getByRole('button', { name: '保存' }).click()
    await expectAlert(page, '无法保存场景', '场景名称不能为空')
    expect(scenarioSaveCount).toBe(0)

    await page.goto('/resources/agent')
    await page.getByRole('button', { name: '新建专家' }).click()
    await page.getByRole('button', { name: '保存' }).click()
    await expectAlert(page, '无法保存专家', '专家名称不能为空')
    expect(agentCreateCount).toBe(0)
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
            name: '导入后场景',
            description: '导入后不能被空列表覆盖',
            agent_names: ['问答专家'],
            host: { name: '问答专家' },
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
              preset_name: '导入后场景',
              experts: [{ name: '问答专家' }],
              skills: [],
              mcps: [],
            },
            summary: {
              preset_imported_names: ['导入后场景'],
              overwritten_existing_names: [],
              agent_imported_names: ['问答专家'],
              overwritten_agent_names: [],
              skills_imported: [],
              skills_overwritten: [],
              mcp_added: 0,
              mcp_updated: 0,
            },
          },
        }),
      })
    })
    await page.route('**/api/settings/session-presets', async (route) => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON() as { presets?: Array<{ name?: string }> }
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
    await expect(page.getByRole('heading', { name: '导入成功' })).toBeVisible()
    await expect(page.getByText('场景：新增 1 个，覆盖 0 个')).toBeVisible()
    await expect(page.getByText('专家：新增 1 个，覆盖 0 个')).toBeVisible()
    await expect(page.getByText('技能：新增 0 个，覆盖 0 个')).toBeVisible()
    await expect(page.getByText('工具：新增 0 个，覆盖 0 个')).toBeVisible()
    await page.waitForTimeout(300)

    expect(emptyPresetPutCount).toBe(0)
    expect(state.scenarios.map((item) => item.name)).toEqual(['导入后场景'])
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
              preset_name: '冲突场景',
              experts: [{ name: '导入专家' }],
              skills: ['skill-new'],
              mcps: [{ name: '导入工具' }],
              name_conflict_existing_names: ['本地场景'],
              would_overwrite_experts: { '导入专家': ['本地专家'] },
              would_remap_skills: { 'skill-local': 'skill-new' },
              would_remap_tools: { '本地工具': '导入工具' },
              missing_references: {
                experts: [],
                skills: [{ name: '缺失技能', display_name: '技能 缺失技能', required_by: ['专家 导入专家'], type_label: '技能' }],
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
    await expect(page.getByText('同名内容将覆盖本地内容')).toBeVisible()
    await expect(page.getByText('场景：冲突场景')).toBeVisible()
    await expect(page.getByText('专家：导入专家')).toBeVisible()
    await expect(page.getByText('技能 缺失技能')).toBeVisible()
    await expect(page.getByRole('button', { name: '确认导入' })).toBeVisible()
  })

  test('用户可以新建专家并保存专家配置', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/agent')

    await expect(page).toHaveURL(/\/resources\/agent$/)
    await expect(page.getByRole('complementary').getByText('问答专家').first()).toBeVisible()

    await page.getByRole('button', { name: '新建专家' }).click()
    await expect(page.getByRole('heading', { name: '新建专家' })).toBeVisible()
    await page.getByPlaceholder('请输入专家名称').fill('自动化专家')
    await page.getByPlaceholder('请输入专家描述').fill('负责验收真实用户点击路径')
    await page.getByRole('button', { name: '保存' }).click()

    await expect(page.getByRole('complementary').getByText('自动化专家').first()).toBeVisible()
  })

  test('专家详情页不展示公开链接入口', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/agent')

    await expect(page.getByRole('heading', { name: '配置专家' })).toBeVisible()
    await expect(page.getByTitle('导入专家包（ZIP）')).toBeVisible()
    await expect(page.getByRole('button', { name: '导出' })).toBeVisible()
    await expect(page.getByRole('button', { name: '分享', exact: true })).toHaveCount(0)
    await expect(page.locator('form').getByText('访问方式', { exact: true })).toHaveCount(0)
  })

  test('专家详情页不展示右侧专家预览卡', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/agent')

    await expect(page.getByRole('heading', { name: '配置专家' })).toBeVisible()
    await expect(page.getByPlaceholder('请输入专家名称')).toBeVisible()
    await expect(page.getByText('Expert', { exact: true })).toHaveCount(0)
    await expect(page.getByText('CARD', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Role Card', { exact: true })).toHaveCount(0)
    await expect(page.getByText('书童四九', { exact: true })).toHaveCount(0)
  })

  test('专家导入成功后展示统一新增覆盖摘要', async ({ page }) => {
    const state = createE2eState()
    let importCallCount = 0
    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/agents/import-bundle', async (route) => {
      importCallCount += 1
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          data: importCallCount === 1
            ? {
                bundle_preview: {
                  name: '导入专家',
                  skills: ['skill-imported'],
                  skill_display_names: { 'skill-imported': '导入技能' },
                  mcps: [{ name: '导入工具' }],
                },
              }
            : {
                summary: {
                  imported_agent_name: '导入专家',
                  overwritten_agent_names: [],
                  skills_imported: ['skill-imported'],
                  skills_overwritten: [],
                  mcp_added: 1,
                  mcp_updated: 0,
                },
              },
        }),
      })
    })

    await page.goto('/resources/agent')
    await expect(page.getByTitle('导入专家包（ZIP）')).toBeVisible()
    await page.setInputFiles('input[type="file"][accept=".zip,application/zip"]', {
      name: 'expert.zip',
      mimeType: 'application/zip',
      buffer: Buffer.from('mock zip'),
    })
    await expect(page.getByRole('heading', { name: '导入专家' })).toBeVisible()
    await page.getByRole('button', { name: '确认导入' }).click()
    await expect(page.getByRole('heading', { name: '导入成功' })).toBeVisible()
    await expect(page.getByText('专家：新增 1 个，覆盖 0 个')).toBeVisible()
    await expect(page.getByText('技能：新增 1 个，覆盖 0 个')).toBeVisible()
    await expect(page.getByText('工具：新增 1 个，覆盖 0 个')).toBeVisible()
  })
})
