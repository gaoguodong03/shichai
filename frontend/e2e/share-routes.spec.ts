import { expect, test } from '@playwright/test'
import { bootLoggedInApp } from './fixtures/mockApi'

test.describe('验收 6/6：分享链接与公开场景路由', () => {
  test('用户打开 /share/run 分享链接后可以预览并确认导入', async ({ page }) => {
    await bootLoggedInApp(page, '/share/run?id=share-scenario')

    await expect(page.getByRole('heading', { name: '分享预览' })).toBeVisible()
    await expect(page.getByText('问答验收场景', { exact: true }).first()).toBeVisible()
    await page.getByRole('button', { name: '确认导入' }).click()
    await expect(page.getByText('导入完成')).toBeVisible()
  })

  test('用户打开 /scenario/run 旧链接后可以看到场景导入确认', async ({ page }) => {
    await bootLoggedInApp(page, '/scenario/run?id=scenario-public')

    await expect(page.getByRole('heading', { name: '导入场景' })).toBeVisible()
    await expect(page.getByText('公开分享场景', { exact: true }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: '确认导入' })).toBeVisible()
  })
})
