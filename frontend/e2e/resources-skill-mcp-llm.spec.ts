import { expect, test } from '@playwright/test'
import { bootLoggedInApp, createE2eState, loginByStorage, mockApi } from './fixtures/mockApi'

test.describe('验收 4/6：资源中心技能、工具与模型', () => {
  async function expectAlert(page: import('@playwright/test').Page, title: string, message: string) {
    const dialog = page.getByRole('dialog', { name: title })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText(message)).toBeVisible()
    await dialog.getByRole('button', { name: '知道了' }).click()
    await expect(dialog).toHaveCount(0)
  }

  test('技能、工具和模型左栏展示名称、描述和悬停删除入口', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/skill')

    const sidebar = page.getByRole('complementary')

    const skillItem = sidebar.getByRole('button', { name: /问答技能.*用于前端点击验收/ })
    await expect(skillItem).toBeVisible()
    const skillDelete = sidebar.getByRole('button', { name: '删除技能 问答技能' })
    await expect(skillDelete).toHaveCSS('opacity', '0')
    await skillItem.hover()
    await expect(skillDelete).toHaveCSS('opacity', '1')

    await page.getByRole('button', { name: '工具', exact: true }).click()
    const toolItem = sidebar.getByRole('button', { name: /文件系统工具.*读写工作区文件/ })
    await expect(toolItem).toBeVisible()
    const toolDelete = sidebar.getByRole('button', { name: '删除工具 文件系统工具' })
    await expect(toolDelete).toHaveCSS('opacity', '0')
    await toolItem.hover()
    await expect(toolDelete).toHaveCSS('opacity', '1')

    await page.getByRole('button', { name: '模型', exact: true }).click()
    const modelItem = sidebar.getByRole('button', { name: /Qwen.*qwen3-max/ })
    await expect(modelItem).toBeVisible()
    const modelDelete = sidebar.getByRole('button', { name: '删除模型 Qwen' })
    await expect(modelDelete).toHaveCSS('opacity', '0')
    await modelItem.hover()
    await expect(modelDelete).toHaveCSS('opacity', '1')
  })

  test('用户可以查看技能详情、依赖和文件树', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '资源中心' }).click()
    await page.getByRole('button', { name: '技能', exact: true }).click()

    await expect(page.getByText('问答技能')).toBeVisible()
    await expect(page.getByPlaceholder('技能名称')).toHaveValue('问答技能')
    await expect(page.getByText('技能运行时依赖')).toBeVisible()
    await expect(page.getByText('文件系统工具')).toBeVisible()
    await expect(page.getByText('requests==2.31.0')).toBeVisible()
    await expect(page.getByRole('button', { name: /References/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /Scripts/ })).toBeVisible()
  })

  test('技能详情页不展示公开链接入口，编辑按钮在编辑态变为保存', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/skill')

    await expect(page.getByPlaceholder('技能名称')).toHaveValue('问答技能')
    await expect(page.getByText('访问方式', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '分享', exact: true })).toHaveCount(0)
    await expect(page.locator('main main').getByText('访问方式', { exact: true })).toHaveCount(0)

    await expect(page.getByRole('button', { name: '保存', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '编辑', exact: true }).click()
    await expect(page.getByRole('button', { name: '保存', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '编辑', exact: true })).toHaveCount(0)
  })

  test('技能详情操作按钮样式和新建态与场景保持一致', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/skill')

    const exportButton = page.getByRole('button', { name: '导出', exact: true })
    const editButton = page.getByRole('button', { name: '编辑', exact: true })
    const deleteButton = page.getByRole('button', { name: '删除', exact: true })

    await expect(exportButton).toHaveClass(/bg-list-hover/)
    await expect(exportButton).toHaveClass(/text-primary/)
    await expect(editButton).toHaveClass(/bg-accent/)
    await expect(editButton).toHaveClass(/text-text-inverse/)
    await expect(deleteButton).toHaveClass(/bg-danger-subtle/)
    await expect(deleteButton).toHaveClass(/text-danger/)

    await editButton.click()
    await expect(page.getByRole('button', { name: '保存', exact: true })).toHaveClass(/bg-accent/)
    await expect(page.getByRole('button', { name: '导出', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '删除', exact: true })).toBeVisible()

    await page.getByRole('button', { name: '新建技能' }).click()
    await expect(page.getByRole('button', { name: '导出', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '保存', exact: true })).toHaveClass(/bg-accent/)
    await expect(page.getByRole('button', { name: '删除', exact: true })).toHaveClass(/bg-danger-subtle/)
  })

  test('新建技能先进入草稿编辑，空草稿不保存，已修改草稿切走时自动保存', async ({ page }) => {
    const state = createE2eState()
    let createSkillCount = 0
    let updateExistingSkillCount = 0

    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/settings/skills**', async (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname.replace(/^\/api/, '')
      const method = route.request().method()
      if (path === '/settings/skills' && method === 'POST') createSkillCount += 1
      if (path === '/settings/skills/skill-qa' && method === 'PUT') updateExistingSkillCount += 1
      await route.fallback()
    })

    await page.goto('/resources/skill')
    const sidebar = page.getByRole('complementary')
    const qaSkillButton = sidebar.getByRole('button', { name: /问答技能.*用于前端点击验收/ })
    const writerSkillButton = sidebar.getByRole('button', { name: /写作技能.*把讨论整理为说明文档/ })
    await expect(page.getByPlaceholder('技能名称')).toHaveValue('问答技能')

    await page.getByRole('button', { name: '新建技能' }).click()
    await expect(page.getByRole('button', { name: '保存', exact: true })).toBeVisible()
    await expect(page.getByPlaceholder('技能名称')).toBeEnabled()
    await qaSkillButton.click()
    await expect.poll(() => createSkillCount).toBe(0)

    await page.getByRole('button', { name: '新建技能' }).click()
    await page.getByPlaceholder('技能名称').fill('自动保存技能')
    await page.getByPlaceholder('简短描述，用于技能选择').fill('切换时保存草稿')
    await page.getByPlaceholder('SKILL.md 正文内容').fill('# 自动保存技能\n\n用于验证草稿保存。')
    await qaSkillButton.click()
    await expect.poll(() => createSkillCount).toBe(1)
    await expect(sidebar.getByRole('button', { name: /自动保存技能.*切换时保存草稿/ })).toBeVisible()

    await qaSkillButton.click()
    await page.getByRole('button', { name: '编辑', exact: true }).click()
    await page.getByPlaceholder('技能名称').fill('不应自动保存')
    await writerSkillButton.click()
    await expect.poll(() => updateExistingSkillCount).toBe(0)
    await qaSkillButton.click()
    await expect(page.getByPlaceholder('技能名称')).toHaveValue('问答技能')
  })

  test('新建技能、工具和模型必填为空时弹窗阻止保存', async ({ page }) => {
    const state = createE2eState()
    let skillCreateCount = 0
    let mcpCreateCount = 0
    let llmSaveCount = 0

    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/settings/skills', async (route) => {
      if (route.request().method() === 'POST') skillCreateCount += 1
      await route.fallback()
    })
    await page.route('**/api/settings/mcp', async (route) => {
      if (route.request().method() === 'POST') mcpCreateCount += 1
      await route.fallback()
    })
    await page.route('**/api/settings/app', async (route) => {
      if (route.request().method() === 'PUT') llmSaveCount += 1
      await route.fallback()
    })

    await page.goto('/resources/skill')
    await page.getByRole('button', { name: '新建技能' }).click()
    await page.getByRole('button', { name: '保存', exact: true }).click()
    await expectAlert(page, '无法保存技能', '技能名称不能为空')
    expect(skillCreateCount).toBe(0)

    await page.goto('/resources/mcp')
    await page.getByRole('button', { name: '新建工具' }).click()
    await page.getByRole('button', { name: '新建', exact: true }).click()
    await expectAlert(page, '无法保存工具', '工具名称不能为空')
    expect(mcpCreateCount).toBe(0)

    await page.goto('/resources/llm')
    await page.getByRole('button', { name: '新建模型' }).click()
    await page.getByRole('button', { name: '新建', exact: true }).click()
    await expectAlert(page, '无法保存模型', '模型标识不能为空')
    expect(llmSaveCount).toBe(0)
  })

  test('用户可以新建工具并进入工具配置页', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '资源中心' }).click()
    await page.getByRole('button', { name: '工具', exact: true }).click()
    await expect(page.getByRole('heading', { name: '配置工具' })).toBeVisible()

    await page.getByRole('button', { name: '新建工具' }).click()
    await expect(page.getByRole('heading', { name: '新建工具' })).toBeVisible()
    await page.getByPlaceholder('例如：文件系统 MCP').fill('自动化工具')
    await page.getByPlaceholder('例如：uvx').fill('python')
    await page.getByRole('button', { name: '新建', exact: true }).click()

    await expect(page.getByRole('heading', { name: '配置工具' })).toBeVisible()
    await expect(page.getByText('自动化工具')).toBeVisible()
    await expect.poll(async () =>
      page.evaluate(() => {
        const toolButton = Array.from(document.querySelectorAll('button')).find((el) => el.textContent?.includes('自动化工具'))
        return toolButton?.querySelectorAll('div').length || 0
      }),
    ).toBeGreaterThanOrEqual(2)
  })

  test('工具详情页不展示公开链接入口', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/mcp')

    await expect(page.getByRole('heading', { name: '配置工具' })).toBeVisible()
    await expect(page.getByText(/^ID:/)).toHaveCount(0)
    await expect.poll(async () =>
      page.evaluate(() => {
        const form = document.querySelector('form')
        const nameLabel = Array.from(form?.querySelectorAll('label') || []).find((el) => el.textContent?.trim() === '名称 *')
        const descriptionLabel = Array.from(form?.querySelectorAll('label') || []).find((el) => el.textContent?.trim() === '描述')
        const transportLabel = Array.from(form?.querySelectorAll('label') || []).find((el) => el.textContent?.trim() === '传输类型 *')
        if (!nameLabel || !descriptionLabel || !transportLabel) return false
        const afterName = Boolean(nameLabel.compareDocumentPosition(descriptionLabel) & Node.DOCUMENT_POSITION_FOLLOWING)
        const beforeTransport = Boolean(descriptionLabel.compareDocumentPosition(transportLabel) & Node.DOCUMENT_POSITION_FOLLOWING)
        return afterName && beforeTransport
      }),
    ).toBe(true)
    await expect(page.getByLabel('启用')).toHaveCount(0)
    await expect(page.getByText(/状态:|工具数|已连接|未连接/)).toHaveCount(0)
    await expect(page.getByRole('button', { name: '分享', exact: true })).toHaveCount(0)
    await expect(page.getByText('访问方式', { exact: true })).toHaveCount(0)
  })

  test('用户可以进入模型配置并保存模型参数', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '资源中心' }).click()
    await page.getByRole('button', { name: '模型', exact: true }).click()
    await expect(page.getByRole('heading', { name: '配置模型' })).toBeVisible()
    await page.getByPlaceholder('gemini-3-pro-preview').fill('qwen3-max')
    await page.getByRole('button', { name: '保存' }).click()

    await expect(page.getByText('已保存')).toBeVisible()
  })
})
