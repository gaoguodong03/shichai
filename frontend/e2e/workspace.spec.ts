import { expect, test } from '@playwright/test'
import { bootLoggedInApp } from './fixtures/mockApi'

test.describe('验收 2/6：工作空间会话与文件', () => {
  test('用户可以新建会话、发送消息并看到专家回复', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '新建会话' }).click()
    await expect(page.getByRole('heading', { name: '新对话' })).toBeVisible()

    await page.getByPlaceholder('输入 @ 可提及主持人或专家').fill('请回答这条 UI 自动化消息')
    await page.getByRole('button', { name: '发送' }).click()

    await expect(page.getByText('自动化测试回复：需求已收到。')).toBeVisible()
  })

  test('用户可以管理成员、插入文件并打开场景快捷入口', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('heading', { name: '已有验收会话' }).click()
    await page.getByTitle('当前焦点角色（点击管理成员）').click()
    await expect(page.getByText('成员管理')).toBeVisible()
    await expect(page.getByText('可邀请的专家')).toBeVisible()
    await expect(page.getByText('写作专家')).toBeVisible()
    await page.locator('.group-chat-modal').getByRole('button', { name: '×' }).click()

    await page.locator('.group-chat-toolbar-btn').filter({ hasText: /^文件$/ }).click()
    await expect(page.getByText('从本地上传并插入')).toBeVisible()
    await expect(page.getByText('brief.md')).toBeVisible()
    await page.locator('.group-chat-modal').getByRole('button', { name: '×' }).click()

    await page.locator('.group-chat-toolbar-btn').filter({ hasText: /^场景$/ }).click()
    await expect(page.getByPlaceholder('搜索场景（名称/专家）')).toBeVisible()
    await expect(page.getByText('问答验收场景', { exact: true }).first()).toBeVisible()
  })
})
