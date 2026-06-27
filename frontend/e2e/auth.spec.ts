import { expect, test } from '@playwright/test'
import { expectMainShell, mockApi } from './fixtures/mockApi'

test.describe('验收 1/6：登录与账号入口', () => {
  test('未登录用户可以注册账号并进入工作空间', async ({ page }) => {
    await mockApi(page)

    await page.goto('/')
    await expect(page).toHaveURL(/\/login/)
    await page.getByRole('button', { name: '没有账号？新建账户' }).click()
    await page.getByLabel('账号').fill('e2e@example.test')
    await page.getByLabel('密码', { exact: true }).fill('password123')
    await page.getByLabel('确认密码').fill('password123')
    await page.getByRole('button', { name: '新建账户' }).click()

    await expectMainShell(page)
    await expect(page).toHaveURL(/\/workspace$/)
    await expect(page.getByRole('heading', { name: '已有验收会话' })).toBeVisible()
  })

  test('用户可以从登录页登录到主工作台', async ({ page }) => {
    await mockApi(page)

    await page.goto('/login')
    await page.getByLabel('账号').fill('e2e@example.test')
    await page.getByLabel('密码', { exact: true }).fill('password123')
    await page.getByRole('button', { name: '登录' }).click()

    await expectMainShell(page)
    await expect(page).toHaveURL(/\/workspace$/)
  })

  test('登录页和其他用户不会继承上一位用户的暗色配色', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('dha_logged_in', 'true')
      localStorage.setItem('dha_user', 'alice@example.test')
      localStorage.setItem('dha_token', 'test-token-alice')
    })
    await mockApi(page)
    page.on('dialog', (dialog) => dialog.accept())

    await page.goto('/settings/theme')
    await page.getByRole('button', { name: /纯黑/ }).click()
    await expect(page.locator('html')).toHaveClass(/dark/)

    await page.getByRole('button', { name: '登出' }).click()
    await page.getByRole('dialog', { name: '退出账号' }).getByRole('button', { name: '退出' }).click()
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.locator('html')).not.toHaveClass(/dark/)

    await page.getByLabel('账号').fill('bob@example.test')
    await page.getByLabel('密码', { exact: true }).fill('password123')
    await page.getByRole('button', { name: '登录' }).click()

    await expectMainShell(page)
    await expect(page).toHaveURL(/\/workspace$/)
    await expect(page.locator('html')).not.toHaveClass(/dark/)
  })
})
