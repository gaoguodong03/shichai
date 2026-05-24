import { expect, test } from '@playwright/test'
import { bootLoggedInApp, createE2eState, expectMainShell, loginByStorage, mockApi } from './fixtures/mockApi'

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

  test('服务端无场景时不会把本地历史快捷场景带给新账号', async ({ page }) => {
    const state = createE2eState()
    state.scenarios = []
    await loginByStorage(page)
    await page.addInitScript(() => {
      localStorage.setItem(
        'dha.group.shortcuts.v1',
        JSON.stringify([
          {
            id: 'scenario-local-history',
            name: '历史本地场景',
            agent_ids: ['agent-qa'],
            leader_agent_id: 'agent-qa',
          },
        ]),
      )
    })
    await mockApi(page, state)
    await page.goto('/')
    await expectMainShell(page)

    await page.getByRole('heading', { name: '已有验收会话' }).click()
    await page.locator('.group-chat-toolbar-btn').filter({ hasText: /^场景$/ }).click()

    await expect(page.getByPlaceholder('搜索场景（名称/专家）')).toBeVisible()
    await expect(page.getByText('历史本地场景', { exact: true })).toHaveCount(0)
  })

  test('空白会话中选择场景会复用当前会话', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '新建会话' }).click()
    await expect(page.getByRole('heading', { name: '新对话' })).toBeVisible()
    const sessionList = page.locator('.middle-column-scrollbar')
    await expect(sessionList.getByText('空白会话', { exact: true })).toHaveCount(1)

    await page.locator('.group-chat-toolbar-btn').filter({ hasText: /^场景$/ }).click()
    const modal = page.locator('.group-chat-modal').filter({ hasText: '场景' })
    await modal.getByRole('button', { name: /问答验收场景/ }).click()

    await expect(page.getByRole('heading', { name: '问答验收场景' })).toBeVisible()
    await expect(sessionList.getByText('空白会话', { exact: true })).toHaveCount(0)
  })

  test('场景创建后不会被旧会话列表响应切回上一会话', async ({ page }) => {
    const state = createE2eState()
    await loginByStorage(page)
    await mockApi(page, state)
    await page.goto('/')
    await expectMainShell(page)

    await page.getByRole('heading', { name: '已有验收会话' }).click()

    let returnedStaleList = false
    const staleSessions = state.sessions.map((s) => ({ ...s }))
    await page.route('**/api/sessions', async (route) => {
      if (route.request().method() === 'GET' && !returnedStaleList) {
        returnedStaleList = true
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'ok', data: { sessions: staleSessions } }),
        })
        return
      }
      await route.fallback()
    })

    await page.locator('.group-chat-toolbar-btn').filter({ hasText: /^场景$/ }).click()
    const modal = page.locator('.group-chat-modal').filter({ hasText: '场景' })
    await modal.getByRole('button', { name: /问答验收场景/ }).click()

    await expect(page.getByRole('heading', { name: '问答验收场景' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '已有验收会话' })).toHaveCount(0)
  })
})
