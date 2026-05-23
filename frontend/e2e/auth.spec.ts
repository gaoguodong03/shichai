import { expect, test } from '@playwright/test'
import { expectMainShell, mockApi } from './fixtures/mockApi'

test.describe('验收 1/6：登录与账号入口', () => {
  test('未登录用户可以注册账号并进入工作空间', async ({ page }) => {
    await mockApi(page)

    await page.goto('/')
    await expect(page).toHaveURL(/\/login/)
    await page.getByRole('button', { name: '没有账号？创建账户' }).click()
    await page.getByLabel('账号').fill('e2e@example.test')
    await page.getByLabel('密码', { exact: true }).fill('password123')
    await page.getByLabel('确认密码').fill('password123')
    await page.getByRole('button', { name: '创建账户' }).click()

    await expectMainShell(page)
    await expect(page.getByRole('heading', { name: '已有验收会话' })).toBeVisible()
  })

  test('用户可以从登录页登录到主工作台', async ({ page }) => {
    await mockApi(page)

    await page.goto('/login')
    await page.getByLabel('账号').fill('e2e@example.test')
    await page.getByLabel('密码', { exact: true }).fill('password123')
    await page.getByRole('button', { name: '登录' }).click()

    await expectMainShell(page)
  })
})
