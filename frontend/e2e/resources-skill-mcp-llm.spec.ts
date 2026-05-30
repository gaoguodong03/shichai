import { expect, test } from '@playwright/test'
import { bootLoggedInApp } from './fixtures/mockApi'

test.describe('验收 4/6：资源中心技能、工具与模型', () => {
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

  test('技能详情页不展示访问方式和分享入口，编辑按钮在编辑态变为保存', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/skill')

    await expect(page.getByPlaceholder('技能名称')).toHaveValue('问答技能')
    await expect(page.getByText('访问方式', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '分享', exact: true })).toHaveCount(0)
    await expect(page.locator('main main').getByText('访问方式', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('link', { name: /\/share\/run\?id=share-skill/ })).toHaveCount(0)

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

  test('工具详情页底部直接展示访问方式，不再使用分享按钮', async ({ page }) => {
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
    await expect(page.getByText('访问方式', { exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: /\/share\/run\?id=share-mcp/ })).toBeVisible()
    await expect.poll(async () =>
      page.evaluate(() => {
        const form = document.querySelector('form')
        const access = Array.from(form?.querySelectorAll('div') || []).find((el) => el.textContent?.trim() === '访问方式')
        const save = Array.from(form?.querySelectorAll('button') || []).find((el) => el.textContent?.trim() === '保存')
        return Boolean(access && save && (access.compareDocumentPosition(save) & Node.DOCUMENT_POSITION_FOLLOWING))
      }),
    ).toBe(true)
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
