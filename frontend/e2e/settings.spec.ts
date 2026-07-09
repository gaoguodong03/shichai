import { expect, test } from '@playwright/test'
import { bootLoggedInApp, createE2eState, expectMainShell, loginByStorage, mockApi } from './fixtures/mockApi'

test.describe('验收 5/6：设置中心', () => {
  test('用户可以配置主持人和配色', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '设置', exact: true }).click()
    await expect(page).toHaveURL(/\/settings\/app$/)
    await expect(page.getByText('配置平台级上下文规则')).toHaveCount(0)
    await expect(page.locator('form > section')).toHaveCount(2)
    await expect(page.locator('form > section').nth(0).getByText('项目整体系统提示词（可选）')).toBeVisible()
    await expect(page.locator('form > section').nth(1).getByRole('heading', { name: '配置主持人' })).toBeVisible()
    await expect(page.getByRole('button', { name: '恢复默认' })).toHaveCount(0)
    await page.getByPlaceholder('写入适用于所有会话、场景、主持人和专家的项目规则。').fill('自动化验收全局规则')
    await page.getByPlaceholder('例如：你是群聊主持人，只负责决定下一位发言人与 next_action，不代写专家正文。').fill('自动化验收主持人提示词')
    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('已保存')).toBeVisible()

    await page.getByRole('button', { name: '配色' }).click()
    await page.getByRole('button', { name: /浅蓝/ }).click()
    await expect(page.locator('body')).toBeVisible()
  })

  test('设置入口重复点击仍默认停留在全局', async ({ page }) => {
    await bootLoggedInApp(page, '/settings/app')
    await expect(page.getByText('配置平台级上下文规则')).toHaveCount(0)

    await page.getByRole('button', { name: '设置', exact: true }).click()

    await expect(page).toHaveURL(/\/settings\/app$/)
    await expect(page.getByRole('button', { name: '全局' })).toHaveClass(/bg-accent-subtle/)
    await expect(page.getByText('配置平台级上下文规则')).toHaveCount(0)
  })

  test('修改全局主持人名称后工作空间同步显示新名称', async ({ page }) => {
    const state = createE2eState()
    state.sessions[0] = {
      ...state.sessions[0],
      host: { name: '四九' },
      messages: [
        {
          message_id: 'host-global-name',
          speaker: { type: 'host', agent_name: '四九' },
          message: { content: '请问答专家继续。' },
        },
      ],
    }
    await loginByStorage(page)
    await mockApi(page, state)
    await page.route('**/api/sessions/session-existing', async (route) => {
      if (route.request().method() !== 'GET') return route.fallback()
      const hostName = String(state.hostProfile.display_name || state.hostProfile.name || '四九')
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
            host: { name: hostName },
            agent_map: {
              [hostName]: { name: hostName, role: '群聊主持人' },
              '问答专家': { name: '问答专家', role: '回答用户问题' },
            },
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

    await page.getByRole('button', { name: '设置', exact: true }).click()
    await page.getByRole('button', { name: '密钥' }).click()
    await expect(page.getByRole('heading', { name: '密钥管理' })).toBeVisible()
    await page.getByRole('button', { name: '新建密钥' }).click()
    await page.getByPlaceholder('例如：Jeniya 主密钥').fill('自动化密钥')
    await page.getByPlaceholder('例如：QWEN_API_KEY').fill('auto-key')
    await page.getByPlaceholder('sk-...').fill('sk-test')
    await page.getByRole('button', { name: '新建', exact: true }).click()
    await expect(page.getByText('自动化密钥')).toBeVisible()

    await page.getByRole('button', { name: '账号' }).click()
    const accountHintText = page.getByText('账号支持手机号或是电子邮箱。')
    await expect(accountHintText).toBeVisible()
    await expect(page.getByRole('button', { name: '账号格式说明' })).toHaveCount(0)
    const accountInputs = page.locator('#new-account, #account-password, #current-password, #new-password, #confirm-password')
    await expect(accountInputs).toHaveCount(5)
    await expect
      .poll(async () =>
        page.evaluate(() => {
          const probe = document.createElement('div')
          probe.style.backgroundColor = getComputedStyle(document.documentElement)
            .getPropertyValue('--color-input-bg')
            .trim()
          document.body.appendChild(probe)
          const expected = getComputedStyle(probe).backgroundColor
          probe.remove()
          return Array.from(
            document.querySelectorAll<HTMLInputElement>(
              '#new-account, #account-password, #current-password, #new-password, #confirm-password',
            ),
          ).every((input) => getComputedStyle(input).backgroundColor === expected)
        }),
      )
      .toBe(true)
    await page.getByPlaceholder('请输入新账号').fill('updated@example.test')
    await page.getByPlaceholder('请输入当前密码').first().fill('password123')
    await expect(page.getByText('修改密码')).toBeVisible()
  })

  test('修改密码当前密码错误时停留在账号页', async ({ page }) => {
    await bootLoggedInApp(page, '/settings/account-security')
    await page.route('**/api/auth/password', async (route) => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '当前密码错误' }),
      })
    })

    await page.locator('#current-password').fill('wrong-pass-123')
    await page.locator('#new-password').fill('new-pass-456')
    await page.locator('#confirm-password').fill('new-pass-456')
    await page
      .locator('section')
      .filter({ hasText: '修改密码' })
      .getByRole('button', { name: '保存' })
      .click()

    await expect(page.getByText('当前密码错误')).toBeVisible()
    await expect(page).toHaveURL(/\/settings\/account-security$/)
    await expect
      .poll(async () => page.evaluate(() => localStorage.getItem('dha_token')))
      .toBe('test-token')
  })

  test('用户可以切换沙箱版本并维护 requirements', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '设置', exact: true }).click()
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
