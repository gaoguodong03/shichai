import { expect, test } from '@playwright/test'
import { bootLoggedInApp } from './fixtures/mockApi'

test.describe('验收 3/6：资源中心场景与专家', () => {
  test('用户可以查看并保存场景配置', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '资源中心' }).click()
    await page.getByRole('button', { name: '场景', exact: true }).click()
    await expect(page.getByRole('heading', { name: '配置场景' })).toBeVisible()
    await expect(page.getByPlaceholder('请输入场景名称')).toHaveValue('问答验收场景')
    await expect(page.getByText('场景主持人')).toBeVisible()
    await expect(page.getByText('协作专家')).toBeVisible()

    await page.getByPlaceholder('请输入场景描述').fill('通过 UI 自动化保存的场景说明')
    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('问答验收场景')).toBeVisible()
  })

  test('用户可以创建专家并保存专家配置', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '资源中心' }).click()
    await page.getByRole('button', { name: '专家', exact: true }).click()
    await expect(page.getByRole('complementary').getByText('问答专家').first()).toBeVisible()

    await page.getByRole('button', { name: '创建专家' }).click()
    await expect(page.getByRole('heading', { name: '创建专家' })).toBeVisible()
    await page.getByPlaceholder('请输入专家名称').fill('自动化专家')
    await page.getByPlaceholder('请输入专家描述').fill('负责验收真实用户点击路径')
    await page.getByRole('button', { name: '保存' }).click()

    await expect(page.getByRole('complementary').getByText('自动化专家').first()).toBeVisible()
  })
})
