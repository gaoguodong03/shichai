import { expect, test } from '@playwright/test'
import { bootLoggedInApp, createE2eState, expectMainShell, loginByStorage, mockApi } from './fixtures/mockApi'

test.describe('验收 5/6：设置中心', () => {
  test('用户可以配置主持人和配色', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '设置' }).click()
    await page.getByRole('button', { name: '主持人设置' }).click()
    await expect(page.getByText('主持人是专家分支角色')).toBeVisible()
    await page.getByPlaceholder('例如：你是群聊主持人，只负责决定下一位发言人与 next_prompt，不代写专家正文。').fill('自动化验收主持人提示词')
    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('已保存')).toBeVisible()

    await page.getByRole('button', { name: '配色' }).click()
    await page.getByRole('button', { name: /浅蓝/ }).click()
    await expect(page.locator('body')).toBeVisible()
  })

  test('修改全局主持人名称后工作空间同步显示新名称', async ({ page }) => {
    const state = createE2eState()
    state.sessions[0] = {
      ...state.sessions[0],
      leader_agent_id: 'agent-scene-host',
      messages: [
        {
          message_id: 'host-global-name',
          role: 'host',
          agent_id: 'agent-scene-host',
          content: '请问答专家继续。',
        } as never,
      ],
    }
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
            leader_agent_id: 'agent-scene-host',
            agent_map: {
              'agent-scene-host': { name: '四九', role: '群聊主持人' },
              'agent-qa': { name: '问答专家', role: '回答用户问题' },
            },
            orchestration_profile: 'recruitment',
          },
        }),
      })
    })

    await page.goto('/settings/app')
    await page.getByPlaceholder('例如：四九').fill('全局新主持')
    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('已保存')).toBeVisible()

    await page.goto('/')
    await expectMainShell(page)
    await page.getByRole('heading', { name: '已有验收会话' }).click()

    await expect(page.locator('.group-chat-bubble-meta').filter({ hasText: '全局新主持' })).toBeVisible()
    await expect(page.locator('.group-chat-bubble-meta').filter({ hasText: '四九' })).toHaveCount(0)
  })

  test('用户可以管理密钥与账号安全', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '设置' }).click()
    await page.getByRole('button', { name: '密钥' }).click()
    await expect(page.getByRole('heading', { name: '密钥管理' })).toBeVisible()
    await page.getByRole('button', { name: '创建密钥' }).click()
    await page.getByPlaceholder('例如：Jeniya 主密钥').fill('自动化密钥')
    await page.getByPlaceholder('例如：QWEN_API_KEY').fill('auto-key')
    await page.getByPlaceholder('sk-...').fill('sk-test')
    await page.getByRole('button', { name: '创建', exact: true }).click()
    await expect(page.getByText('自动化密钥')).toBeVisible()

    await page.getByRole('button', { name: '账号' }).click()
    await page.getByPlaceholder('请输入新账号').fill('updated@example.test')
    await page.getByPlaceholder('请输入当前密码').first().fill('password123')
    await expect(page.getByText('修改密码')).toBeVisible()
  })

  test('用户可以切换沙箱版本并维护 requirements', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '设置' }).click()
    await page.getByRole('button', { name: '沙箱' }).click()
    await expect(page.getByRole('heading', { name: '沙箱' })).toBeVisible()
    await expect(page.getByText('Playwright 版包含浏览器运行时，体积更大；普通版更省资源。')).toBeVisible()

    await page.getByRole('radio', { name: /Playwright 版/ }).check()
    await page.getByRole('button', { name: '保存沙箱版本' }).click()
    await page.getByRole('textbox').last().fill('requests==2.31.0\npandas==2.2.2\n')
    await page.getByRole('button', { name: '保存' }).last().click()
    await expect(page.getByText('已保存')).toBeVisible()
  })
})
