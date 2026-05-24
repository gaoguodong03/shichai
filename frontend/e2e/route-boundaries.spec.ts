import { expect, test } from '@playwright/test'
import { bootLoggedInApp, mockApi } from './fixtures/mockApi'

test.describe('路由边界', () => {
  test('根路径登录后进入工作空间 canonical URL', async ({ page }) => {
    await bootLoggedInApp(page, '/')
    await expect(page).toHaveURL(/\/workspace$/)
    await expect(page.getByRole('heading', { name: '已有验收会话' })).toBeVisible()
  })

  test('资源中心专家页可以直接打开 /resources/agent', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/agent')
    await expect(page).toHaveURL(/\/resources\/agent$/)
    await expect(page.getByRole('button', { name: '专家', exact: true })).toHaveClass(/bg-nav-selected-bg/)
    await expect(page.getByRole('complementary').getByText('问答专家').first()).toBeVisible()
  })

  test('设置沙箱页可以直接打开 /settings/sandbox', async ({ page }) => {
    await bootLoggedInApp(page, '/settings/sandbox')
    await expect(page).toHaveURL(/\/settings\/sandbox$/)
    await expect(page.getByRole('button', { name: '沙箱', exact: true })).toHaveClass(/bg-accent-subtle/)
    await expect(page.getByText('普通版', { exact: true })).toBeVisible()
  })

  test('非法资源和设置 section 会归一化', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/dha')
    await expect(page).toHaveURL(/\/resources\/agent$/)

    await page.goto('/settings/unknown')
    await expect(page).toHaveURL(/\/settings\/app$/)
  })

  test('未登录访问受保护路由仍跳转登录并保留 redirect', async ({ page }) => {
    await mockApi(page)
    await page.goto('/resources/agent')
    await expect(page).toHaveURL(/\/login\?redirect=\/resources\/agent/)
  })
})
