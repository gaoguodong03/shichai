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
