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

  test('资源文件详情页把编辑、删除、下载集中在顶部操作区', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/files')

    await expect(page.getByRole('heading', { name: '文件' })).toBeVisible()
    const fileList = page.getByRole('complementary').filter({ hasText: '当前目录：/' })
    await fileList.getByRole('button', { name: '[FILE] brief.md brief.md' }).click()

    const detailHeader = page.locator('main header').filter({ hasText: 'brief.md' })
    await expect(detailHeader.getByRole('button', { name: '编辑内容' })).toBeVisible()
    await expect(detailHeader.getByRole('button', { name: '删除' })).toBeVisible()
    await expect(detailHeader.getByRole('link', { name: '下载' })).toBeVisible()
    await expect(page.getByRole('button', { name: '删除文件' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '显示源文件' })).toHaveCount(0)

    await expect(page.getByRole('heading', { name: '验收说明' })).toBeVisible()
    await detailHeader.getByRole('button', { name: '编辑内容' }).click()
    await expect(page.locator('textarea')).toHaveValue(/# 验收说明/)
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

  test('加载服务端场景列表不会立刻写回覆盖', async ({ page }) => {
    const state = createE2eState()
    let sessionPresetPutCount = 0
    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/settings/session-presets', async (route) => {
      if (route.request().method() === 'PUT') {
        sessionPresetPutCount += 1
      }
      await route.fallback()
    })

    const loadedPresets = page.waitForResponse((response) =>
      response.url().includes('/api/settings/session-presets')
      && response.request().method() === 'GET'
      && response.status() === 200,
    )
    await page.goto('/')
    await loadedPresets
    await expectMainShell(page)
    await page.waitForTimeout(300)

    expect(sessionPresetPutCount).toBe(0)
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

  test('自动切换专家提示使用专家名称而不是 agent id', async ({ page }) => {
    const state = createE2eState()
    state.sessions[0].agent_ids = ['agent-qa', 'agent-writer']
    state.sessions[0].messages = [
      {
        message_id: 'assistant-history',
        role: 'assistant',
        agent_id: 'agent-qa',
        skill_id: 'skill-qa',
        content: '历史回复：这里可以继续追问。',
      } as never,
    ]
    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/sessions/session-existing', async (route) => {
      if (route.request().method() !== 'GET') return route.fallback()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          data: {
            id: 'session-existing',
            title: '已有验收会话',
            updated_at: '2026-05-23T08:00:00Z',
            messages: state.sessions[0].messages,
            agent_ids: state.sessions[0].agent_ids,
            agent_map: {
              'agent-qa': { name: '问答专家', role: '回答用户问题' },
            },
            orchestration_profile: 'scene',
          },
        }),
      })
    })
    await page.route('**/api/sessions/session-existing/chat/stream', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
        body: [
          `event: route\ndata: ${JSON.stringify({ agent_id: 'agent-writer', skill_id: 'skill-write' })}\n\n`,
          `event: end\ndata: ${JSON.stringify({ waiting_for_user: true, interrupted: false })}\n\n`,
        ].join(''),
      })
    })

    await page.goto('/')
    await expectMainShell(page)
    await page.getByRole('heading', { name: '已有验收会话' }).click()
    await page.getByPlaceholder('输入 @ 可提及主持人或专家').fill('请换一个专家继续')
    await page.getByRole('button', { name: '发送' }).click()

    await expect(page.getByText('四九已帮您切换专家：写作专家')).toBeVisible()
    await expect(page.getByText('四九已帮您切换专家：agent-writer')).toHaveCount(0)
  })

  test('场景会话工作空间显示场景主持人名称', async ({ page }) => {
    const state = createE2eState()
    state.hostProfile.display_name = '全局主持'
    state.sessions[0] = {
      ...state.sessions[0],
      leader_agent_id: 'agent-scene-host',
      host_config: { display_name: '场景主持', skill_ids: [] },
      messages: [
        {
          message_id: 'host-scene-name',
          role: 'host',
          agent_id: 'agent-scene-host',
          content: '请问答专家继续。',
        } as never,
      ],
    }
    await loginByStorage(page)
    await mockApi(page, state)
    await page.goto('/')
    await expectMainShell(page)

    await page.getByRole('heading', { name: '已有验收会话' }).click()

    await expect(page.locator('.group-chat-bubble-meta').filter({ hasText: '场景主持' })).toBeVisible()
    await expect(page.locator('.group-chat-bubble-meta').filter({ hasText: '全局主持' })).toHaveCount(0)
  })

  test('正在运行的会话在列表显示转圈，离开后完成显示新回复提示', async ({ page }) => {
    const state = createE2eState()
    state.sessions = [
      state.sessions[0],
      {
        id: 'session-other',
        title: '另一个会话',
        updated_at: '2026-05-23T07:00:00Z',
        agent_ids: [],
        messages: [],
      },
    ]
    await loginByStorage(page)
    await mockApi(page, state)

    let releaseStream: (() => void) | null = null
    const streamStarted = new Promise<void>((resolve) => {
      page.route('**/api/sessions/session-existing/chat/stream', async (route) => {
        resolve()
        await new Promise<void>((release) => {
          releaseStream = release
        })
        const session = state.sessions.find((s) => s.id === 'session-existing')
        if (session) {
          session.messages.push({ message_id: 'assistant-late', role: 'assistant', agent_id: 'agent-qa', content: '后台完成的回复' })
        }
        await route.fulfill({
          status: 200,
          headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
          body: [
            `event: message\ndata: ${JSON.stringify({ message_id: 'assistant-late', role: 'assistant', agent_id: 'agent-qa', content: '后台完成的回复' })}\n\n`,
            `event: end\ndata: ${JSON.stringify({ waiting_for_user: true, interrupted: false })}\n\n`,
          ].join(''),
        })
      })
    })

    await page.goto('/')
    await expectMainShell(page)
    await page.getByRole('heading', { name: '已有验收会话' }).click()
    await page.getByPlaceholder('输入 @ 可提及主持人或专家').fill('请后台运行一下')
    await page.getByRole('button', { name: '发送' }).click()
    await streamStarted

    const runningRow = page.locator('[data-session-id="session-existing"]')
    await expect(runningRow.getByLabel('会话正在运行')).toBeVisible()

    await page.getByText('另一个会话', { exact: true }).click()
    releaseStream?.()

    await expect(runningRow.getByLabel('会话正在运行')).toHaveCount(0)
    await expect(runningRow.getByLabel('会话有新回复')).toBeVisible()

    await runningRow.click()
    await expect(runningRow.getByLabel('会话有新回复')).toHaveCount(0)
  })
})
