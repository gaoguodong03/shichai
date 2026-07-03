import { expect, test } from '@playwright/test'
import { bootLoggedInApp, createE2eState, expectMainShell, loginByStorage, mockApi } from './fixtures/mockApi'

test.describe('验收 2/6：工作空间会话与文件', () => {
  test('用户可以新建会话、发送消息并看到专家回复', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '新建会话' }).click()
    await page.getByRole('menuitem', { name: '空会话' }).click()
    await expect(page.getByRole('heading', { name: '新对话' })).toBeVisible()

    await page.getByPlaceholder('输入 @ 可提及主持人或专家').fill('请回答这条 UI 自动化消息')
    await page.getByRole('button', { name: '发送' }).click()

    await expect(page.getByText('自动化测试回复：需求已收到。')).toBeVisible()
  })

  test('新建会话菜单提供空会话和场景入口', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '新建会话' }).click()

    const menu = page.getByRole('menu', { name: '新建会话' })
    await expect(menu).toBeVisible()
    await expect(menu.getByRole('menuitem', { name: '空会话' })).toBeVisible()
    await expect(menu.getByRole('menuitem', { name: /问答验收场景/ })).toBeVisible()

    await menu.getByRole('menuitem', { name: /问答验收场景/ }).click()

    await expect(page.getByRole('heading', { name: '问答验收场景' })).toBeVisible()
  })

  test('专家回复结束后刷新会话工作区文件与预览', async ({ page }) => {
    const state = createE2eState()
    state.sessions[0].messages = []
    state.fileContent['session-existing:brief.md'] = '# 验收说明\n\n旧文件内容。\n'
    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/sessions/session-existing/chat/stream', async (route) => {
      const session = state.sessions.find((s) => s.id === 'session-existing')
      if (session) {
        session.messages.push({ message_id: 'assistant-file', role: 'assistant', agent_name: '问答专家', content: '我已经更新工作区文件。' } as never)
      }
      state.fileContent['session-existing:brief.md'] = '# 验收说明\n\n专家已更新文件内容。\n'
      state.files['session-existing:'] = [
        ...(state.files['session-existing:'] || []),
        { name: 'expert-output.md', path: 'expert-output.md', is_dir: false, size: 64, updated_at: '2026-05-30T09:00:00Z' },
      ]
      state.fileContent['session-existing:expert-output.md'] = '# 专家输出\n\n已写入工作区。\n'
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
        body: [
          `event: message\ndata: ${JSON.stringify({ message_id: 'assistant-file', role: 'assistant', agent_name: '问答专家', content: '我已经更新工作区文件。' })}\n\n`,
          `event: end\ndata: ${JSON.stringify({ waiting_for_user: true, interrupted: false })}\n\n`,
        ].join(''),
      })
    })

    await page.goto('/')
    await expectMainShell(page)
    await page.getByRole('heading', { name: '已有验收会话' }).click()
    await page.locator('.group-chat-header-right').getByRole('button', { name: '文件' }).click()
    await page.locator('.group-chat-workspace-item-btn-main').filter({ hasText: 'brief.md' }).click()
    await expect(page.locator('.group-chat-workspace-preview').getByRole('heading', { name: '验收说明' })).toBeVisible()
    await expect(page.getByText('旧文件内容。')).toBeVisible()
    await page.locator('.group-chat-workspace-preview').getByRole('button', { name: '编辑' }).click()
    await expect(page.locator('.group-chat-workspace-preview-textarea')).toHaveValue(/# 验收说明/)
    await page.locator('.group-chat-workspace-preview').getByRole('button', { name: '取消' }).click()

    await page.getByPlaceholder('输入 @ 可提及主持人或专家').fill('请更新工作区文件')
    await expect(page.getByPlaceholder('输入 @ 可提及主持人或专家')).toHaveValue('请更新工作区文件')
    await page.getByRole('button', { name: '发送' }).click()

    await expect(page.getByText('我已经更新工作区文件。')).toBeVisible()
    await expect(page.locator('.group-chat-workspace-item-btn-main').filter({ hasText: 'expert-output.md' })).toBeVisible()
    await expect(page.getByText('专家已更新文件内容。')).toBeVisible()
  })

  test('用户可以从工作区右侧工具栏刷新当前目录', async ({ page }) => {
    const state = createE2eState()
    await loginByStorage(page)
    await mockApi(page, state)
    await page.goto('/')
    await expectMainShell(page)

    await page.locator('.group-chat-header-right').getByRole('button', { name: '文件' }).click()
    await expect(page.locator('.group-chat-workspace-item-btn-main').filter({ hasText: 'brief.md' })).toBeVisible()

    state.files['session-existing:'] = [
      ...state.files['session-existing:'],
      { name: 'refreshed.md', path: 'refreshed.md', is_dir: false, size: 32, updated_at: '2026-06-17T09:00:00Z' },
    ]

    const refreshButton = page.locator('.group-chat-workspace-toolbar-actions').getByRole('button', { name: '刷新工作区' })
    await expect(refreshButton).toBeVisible()
    await expect(refreshButton).toHaveClass(/group-chat-workspace-toolbar-sm/)
    await expect(page.locator('.group-chat-workspace-heading').getByRole('button', { name: '刷新工作区' })).toHaveCount(0)

    await refreshButton.click()
    await expect(page.locator('.group-chat-workspace-item-btn-main').filter({ hasText: 'refreshed.md' })).toBeVisible()

    await page.locator('.group-chat-workspace-item-btn-main').filter({ hasText: 'docs' }).click()
    const toolbar = page.locator('.group-chat-workspace-toolbar')
    await expect(toolbar.locator('.group-chat-workspace-path-actions').getByRole('button', { name: '上一级' })).toBeVisible()
    const rootButton = toolbar.locator('.group-chat-workspace-path-actions').getByRole('button', { name: '根目录' })
    const nestedRefreshButton = toolbar.locator('.group-chat-workspace-file-actions').getByRole('button', { name: '刷新工作区' })
    await expect(rootButton).toBeVisible()
    await expect(nestedRefreshButton).toBeVisible()
    const rootBox = await rootButton.boundingBox()
    const refreshBox = await nestedRefreshButton.boundingBox()
    expect(rootBox).not.toBeNull()
    expect(refreshBox).not.toBeNull()
    expect(refreshBox!.x).toBeGreaterThan(rootBox!.x)
  })

  test('工作区文件名截断时 hover 显示完整文件名', async ({ page }) => {
    const state = createE2eState()
    const longFileName = 'AI时代工程团队领导力提升-20260611T153000Z.md'
    state.files['session-existing:'] = [
      { name: longFileName, path: longFileName, is_dir: false, size: 512, updated_at: '2026-06-17T09:00:00Z' },
    ]
    state.fileContent[`session-existing:${longFileName}`] = '# 长文件名验证\n\n用于验证 hover 全名提示。\n'
    await loginByStorage(page)
    await mockApi(page, state)
    await page.goto('/')
    await expectMainShell(page)

    await page.getByRole('heading', { name: '已有验收会话' }).click()
    await page.locator('.group-chat-header-right').getByRole('button', { name: '文件' }).click()

    const fileName = page.locator('.group-chat-workspace-item-btn-main .truncate', { hasText: longFileName })
    await expect(fileName).toHaveAttribute('title', longFileName)

    await fileName.click()
    await expect(page.locator('.group-chat-workspace-preview-title')).toHaveAttribute('title', longFileName)
  })

  test('专家消息操作栏在气泡外并支持拷贝正文', async ({ page }) => {
    const state = createE2eState()
    const assistantContent = '历史回复：这里可以继续追问。'
    let workspaceFilePostCount = 0
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'http://127.0.0.1:5173' })
    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/workspaces/session-existing/files', async (route) => {
      if (route.request().method() === 'POST') workspaceFilePostCount += 1
      await route.fallback()
    })
    await page.goto('/')
    await expectMainShell(page)

    await page.getByRole('heading', { name: '已有验收会话' }).click()

    const row = page.locator('[data-message-id="assistant-history"]')
    await expect(row.locator('.group-chat-bubble .group-chat-bubble-actions')).toHaveCount(0)
    await expect(row.locator('.group-chat-message-stack > .group-chat-bubble-actions')).toBeVisible()
    await expect(row.locator('.group-chat-bubble-action-btn')).toHaveCount(3)
    await expect(row.getByRole('button', { name: '删除该发言' })).toHaveAttribute('title', '删除该发言')
    await expect(row.getByRole('button', { name: '从此刻分叉会话' })).toHaveCount(0)
    await expect(row.getByRole('button', { name: '回溯到此发言' })).toHaveCount(0)

    await row.getByRole('button', { name: '拷贝发言内容' }).click()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(assistantContent)

    await row.getByRole('button', { name: '保存到工作区' }).click()
    await expect(page.getByRole('dialog', { name: '保存为工作区文件' })).toBeVisible()
    await page.getByRole('button', { name: '取消' }).click()
    expect(workspaceFilePostCount).toBe(0)
  })

  test('切换到历史会话时消息列表自动定位到末尾', async ({ page }) => {
    const state = createE2eState()
    const longHistorySession = {
      id: 'session-long-history',
      title: '长历史会话',
      updated_at: '2026-05-23T09:00:00Z',
      agent_names: ['问答专家'],
      messages: Array.from({ length: 36 }, (_, idx) => ({
        message_id: `long-${idx + 1}`,
        role: idx % 2 === 0 ? 'user' : 'assistant',
        agent_name: idx % 2 === 0 ? undefined : '问答专家',
        content: `历史消息 ${idx + 1}\n\n这是一段用于撑开消息列表高度的内容，确保会话切换后必须滚动才能看到结尾。`,
      })),
    }
    state.sessions = [...state.sessions, longHistorySession]

    await loginByStorage(page)
    await mockApi(page, state)
    await page.goto('/')
    await expectMainShell(page)

    await expect(page.locator('[data-message-id="assistant-history"]')).toBeVisible()

    await page.locator('[data-session-id="session-long-history"]').click()
    await expect(page.locator('[data-message-id="long-36"]')).toBeVisible()

    const scrollState = await page.locator('.group-chat-messages').evaluate((el) => ({
      scrollTop: el.scrollTop,
      maxTop: el.scrollHeight - el.clientHeight,
    }))
    expect(scrollState.scrollTop).toBeGreaterThan(0)
    expect(scrollState.maxTop - scrollState.scrollTop).toBeLessThanOrEqual(4)
  })

  test('多个 sandbox 调用默认折叠到一个图标按钮', async ({ page }) => {
    const state = createE2eState()
    state.sessions[0].messages = [
      {
        message_id: 'assistant-sandbox-tools',
        role: 'assistant',
        agent_name: '问答专家',
        content: '沙箱调用结果如下。',
        tool_raw_results: [
          JSON.stringify({ _sandbox_trace: {}, result: 'one' }),
          JSON.stringify({ _sandbox_trace: {}, result: 'two' }),
          JSON.stringify({ _sandbox_trace: {}, result: 'three' }),
        ],
      } as never,
    ]

    await loginByStorage(page)
    await mockApi(page, state)
    await page.goto('/')
    await expectMainShell(page)
    await page.getByRole('heading', { name: '已有验收会话' }).click()

    const row = page.locator('[data-message-id="assistant-sandbox-tools"]')
    const toggle = row.getByRole('button', { name: '显示沙箱调用 (3)' })
    await expect(toggle).toBeVisible()
    await expect(row.getByRole('button', { name: 'sandbox' })).toHaveCount(0)

    await toggle.click()
    await expect(row.getByRole('button', { name: 'sandbox' })).toHaveCount(3)

    await row.getByRole('button', { name: '隐藏沙箱调用 (3)' }).click()
    await expect(row.getByRole('button', { name: 'sandbox' })).toHaveCount(0)
  })

  test('Skill 调度状态入口使用 sandbox 同款图标按钮', async ({ page }) => {
    const state = createE2eState()
    state.sessions[0].messages = [
      {
        message_id: 'assistant-scheduler-state',
        role: 'assistant',
        agent_name: '问答专家',
        content: '下面由写作专家继续。',
        meta: {
          scheduler_state: {
            current_phase: 'draft',
            next_speaker: '写作专家',
            speaker_task: '整理正文',
          },
        },
      } as never,
    ]

    await loginByStorage(page)
    await mockApi(page, state)
    await page.goto('/')
    await expectMainShell(page)
    await page.getByRole('heading', { name: '已有验收会话' }).click()

    const row = page.locator('[data-message-id="assistant-scheduler-state"]')
    const toggle = row.getByRole('button', { name: '显示 Skill 调度状态 (1)' })
    await expect(toggle).toBeVisible()
    await expect(row.getByRole('button', { name: 'skill', exact: true })).toHaveCount(0)

    await toggle.click()
    await expect(row.getByText('Skill 调度状态')).toBeVisible()
  })

  test('专家运行时先显示占位气泡并随状态更新', async ({ page }) => {
    const state = createE2eState()
    state.sessions[0].agent_names = ['问答专家', '写作专家']
    await loginByStorage(page)
    await mockApi(page, state)

    const streamReachedFileWrite = new Promise<void>((resolve) => {
      page.route('**/api/sessions/session-existing/chat/stream', async (route) => {
        await route.fulfill({
          status: 200,
          headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
          body: [
            `event: route\ndata: ${JSON.stringify({ agent_name: '写作专家', skill: 'skill-write' })}\n\n`,
            `event: content\ndata: ${JSON.stringify({ agent_name: '写作专家', text: '', meta: { phase: 'file_writing' } })}\n\n`,
          ].join(''),
        })
        resolve()
      })
    })
    let releaseFallback: (() => void) | null = null
    const fallbackStarted = new Promise<void>((resolve) => {
      page.route('**/api/sessions/session-existing/chat', async (route) => {
        if (route.request().method() !== 'POST') return route.fallback()
        resolve()
        await new Promise<void>((release) => {
          releaseFallback = release
        })
        await route.fulfill({
          status: 200,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            status: 'ok',
            data: {
              messages: [
                {
                  message_id: 'assistant-writer-final',
                  role: 'assistant',
                  agent_name: '写作专家',
                  skill: 'skill-write',
                  content: '文章草稿已经写入工作区。',
                },
              ],
              end: { waiting_for_user: true, interrupted: false },
            },
          }),
        })
      })
    })

    await page.goto('/')
    await expectMainShell(page)
    await page.getByRole('heading', { name: '已有验收会话' }).click()
    await page.getByPlaceholder('输入 @ 可提及主持人或专家').fill('请写一篇文章')
    await page.getByRole('button', { name: '发送' }).click()

    await streamReachedFileWrite
    await fallbackStarted
    const placeholder = page.locator('.group-chat-msg-row-other').filter({ hasText: '写作专家' }).last()
    await expect(placeholder.getByText('写入文件中...')).toBeVisible()

    releaseFallback?.()

    await expect(page.getByText('文章草稿已经写入工作区。')).toBeVisible()
    await expect(page.getByText('写入文件中...')).toHaveCount(0)
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

  test('从输入区上传并插入文件时默认上传到工作区根目录', async ({ page }) => {
    const state = createE2eState()
    const uploadPathParams: string[] = []
    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/workspaces/session-existing/files/upload**', async (route) => {
      const url = new URL(route.request().url())
      uploadPathParams.push(url.searchParams.get('path') || '')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          data: { path: 'upload-root.md' },
        }),
      })
    })

    await page.goto('/')
    await expectMainShell(page)
    await page.getByRole('heading', { name: '已有验收会话' }).click()
    await page.locator('.group-chat-header-right').getByRole('button', { name: '文件' }).click()
    await page.locator('.group-chat-workspace-item-btn-main').filter({ hasText: 'docs' }).click()
    await expect(page.getByText('当前：docs')).toBeVisible()

    await page.locator('.group-chat-toolbar-btn').filter({ hasText: /^文件$/ }).click()
    await expect(page.getByText('从本地上传并插入')).toBeVisible()
    await page.locator('.group-chat-input-wrap input[type="file"]').setInputFiles({
      name: 'upload-root.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# 上传到根目录\n'),
    })

    await expect(page.getByText('【文件引用：upload-root.md】')).toBeVisible()
    expect(uploadPathParams).toEqual([''])
  })

  test('资源文件详情页把编辑、删除、下载集中在顶部操作区', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/files')

    await expect(page.getByRole('heading', { name: '文件' })).toBeVisible()
    const fileList = page.getByRole('complementary').filter({ hasText: '当前目录：/' })
    await fileList.getByRole('button', { name: 'brief.md brief.md' }).click()

    const detailHeader = page.locator('main header').filter({ hasText: 'brief.md' })
    await expect(detailHeader.getByRole('button', { name: '编辑内容' })).toBeVisible()
    await expect(detailHeader.getByRole('button', { name: '删除' })).toBeVisible()
    await expect(detailHeader.getByRole('link', { name: '下载' })).toBeVisible()
    await expect(page.getByRole('button', { name: '删除文件' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '显示源文件' })).toHaveCount(0)

    await expect(page.getByRole('heading', { name: '验收说明' })).toBeVisible()
    await detailHeader.getByRole('button', { name: '编辑内容' }).click()
    await expect(detailHeader.getByRole('button', { name: '保存' })).toBeVisible()
    await expect(detailHeader.getByRole('button', { name: '取消' })).toBeVisible()
    await expect(detailHeader.getByRole('button', { name: '删除' })).toBeVisible()
    await expect(detailHeader.getByRole('link', { name: '下载' })).toHaveCount(0)
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
            agent_names: ['问答专家'],
            leader_agent_name: '问答专家',
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
    await page.getByRole('menuitem', { name: '空会话' }).click()
    await expect(page.getByRole('heading', { name: '新对话' })).toBeVisible()
    const sessionList = page.locator('.middle-column-scrollbar')
    await expect(sessionList.getByText('空白会话', { exact: true })).toHaveCount(1)

    await page.locator('.group-chat-toolbar-btn').filter({ hasText: /^场景$/ }).click()
    const modal = page.locator('.group-chat-modal').filter({ hasText: '场景' })
    await modal.getByRole('button', { name: /问答验收场景/ }).click()

    await expect(page.getByRole('heading', { name: '问答验收场景' })).toBeVisible()
    await expect(sessionList.getByText('空白会话', { exact: true })).toHaveCount(0)
  })

  test('场景新建后不会被旧会话列表响应切回上一会话', async ({ page }) => {
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
    state.sessions[0].agent_names = ['问答专家', '写作专家']
    state.sessions[0].messages = [
      {
        message_id: 'assistant-history',
        role: 'assistant',
        agent_name: '问答专家',
        skill: 'skill-qa',
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
            agent_names: state.sessions[0].agent_names,
            agent_map: {
              '问答专家': { name: '问答专家', role: '回答用户问题' },
              '写作专家': { name: '写作专家', role: '整理文档与结论' },
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
          `event: route\ndata: ${JSON.stringify({ agent_name: '写作专家', skill: 'skill-write' })}\n\n`,
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

  test('达到轮次上限时显示自动暂停提示', async ({ page }) => {
    await bootLoggedInApp(page)
    await page.route('**/api/sessions/session-existing/chat/stream', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
        body: [
          `event: end\ndata: ${JSON.stringify({
            waiting_for_user: true,
            turns_limit_reached: true,
            suggested_next_speaker: '问答专家',
            interrupted: false,
          })}\n\n`,
        ].join(''),
      })
    })

    await page.getByRole('heading', { name: '已有验收会话' }).click()
    await page.getByPlaceholder('输入 @ 可提及主持人或专家').fill('请连续处理到暂停')
    await page.getByRole('button', { name: '发送' }).click()

    await expect(page.getByText('已达轮次上限')).toBeVisible()
    await expect(page.getByRole('button', { name: '确认并继续' })).toBeVisible()
  })

  test('场景会话工作空间显示场景主持人名称', async ({ page }) => {
    const state = createE2eState()
    state.hostProfile.display_name = '全局主持'
    state.sessions[0] = {
      ...state.sessions[0],
      leader_agent_name: '场景主持',
      host_config: { leader_agent_name: '场景主持', skill_name: '', skill_directory: '' },
      messages: [
        {
          message_id: 'host-scene-name',
          role: 'host',
          agent_name: '场景主持',
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
        agent_names: [],
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
          session.messages.push({ message_id: 'assistant-late', role: 'assistant', agent_name: '问答专家', content: '后台完成的回复' })
        }
        await route.fulfill({
          status: 200,
          headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
          body: [
            `event: message\ndata: ${JSON.stringify({ message_id: 'assistant-late', role: 'assistant', agent_name: '问答专家', content: '后台完成的回复' })}\n\n`,
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
