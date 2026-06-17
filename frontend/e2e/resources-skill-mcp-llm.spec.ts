import { expect, test } from '@playwright/test'
import { bootLoggedInApp } from './fixtures/mockApi'

test.describe('验收 4/6：资源中心技能、工具与模型', () => {
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

  test('用户可以创建工具并进入工具配置页', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '资源中心' }).click()
    await page.getByRole('button', { name: '工具', exact: true }).click()
    await expect(page.getByRole('heading', { name: '配置工具' })).toBeVisible()

    await page.getByRole('button', { name: '创建工具' }).click()
    await expect(page.getByRole('heading', { name: '创建工具' })).toBeVisible()
    await page.getByPlaceholder('例如：文件系统 MCP').fill('自动化工具')
    await page.getByPlaceholder('例如：python').fill('python')
    await page.getByRole('button', { name: '创建', exact: true }).click()

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
