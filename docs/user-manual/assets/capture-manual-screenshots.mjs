import fs from 'node:fs/promises'
import path from 'node:path'
import { createRequire } from 'node:module'

const root = path.resolve(new URL('../../..', import.meta.url).pathname)
const require = createRequire(path.join(root, 'frontend/package.json'))
const { chromium } = require('@playwright/test')
const imageDir = path.join(root, 'docs/user-manual/images')
const baseUrl = process.env.MANUAL_BASE_URL || 'http://localhost:5173'
const apiUrl = process.env.MANUAL_API_URL || 'http://127.0.0.1:8000/api'
const username = process.env.MANUAL_USERNAME || 'ggd@bupt.edu.cn'
const password = process.env.MANUAL_PASSWORD || ''

if (!password) {
  throw new Error('MANUAL_PASSWORD is required')
}

await fs.mkdir(imageDir, { recursive: true })

let browser
try {
  browser = await chromium.launch({ channel: 'chrome', headless: true })
} catch {
  browser = await chromium.launch({ channel: 'chromium', headless: true })
}
const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 })

async function api(pathname, options = {}) {
  const response = await page.request.fetch(`${apiUrl}${pathname}`, options)
  if (!response.ok()) {
    throw new Error(`${options.method || 'GET'} ${pathname} failed: ${response.status()} ${await response.text()}`)
  }
  return response.json()
}

async function loginToken() {
  const result = await api('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    data: { username, password },
  })
  const token = result?.data?.access_token
  if (!token) throw new Error('login token missing')
  return token
}

async function installLoginState(token) {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' })
  await page.evaluate(
    ({ user, authToken }) => {
      localStorage.setItem('dha_logged_in', 'true')
      localStorage.setItem('dha_user', user)
      localStorage.setItem('dha_token', authToken)
    },
    { user: username, authToken: token },
  )
}

async function waitReady() {
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(900)
}

async function clearMarks() {
  await page.evaluate(() => {
    document.querySelectorAll('[data-manual-mark]').forEach((node) => node.remove())
  })
}

async function mark(items) {
  await clearMarks()
  const boxes = []
  for (const item of items) {
    const locator = typeof item.selector === 'string' ? page.locator(item.selector) : item.selector
    const count = await locator.count().catch(() => 0)
    if (!count) continue
    const target = locator.first()
    const box = await target.boundingBox().catch(() => null)
    if (!box) continue
    boxes.push({ ...box, label: item.label })
  }
  await page.evaluate((rects) => {
    for (const rect of rects) {
      const frame = document.createElement('div')
      frame.setAttribute('data-manual-mark', '1')
      frame.style.position = 'fixed'
      frame.style.left = `${rect.x}px`
      frame.style.top = `${rect.y}px`
      frame.style.width = `${rect.width}px`
      frame.style.height = `${rect.height}px`
      frame.style.border = '3px solid #dc2626'
      frame.style.borderRadius = '8px'
      frame.style.pointerEvents = 'none'
      frame.style.zIndex = '2147483646'
      frame.style.boxSizing = 'border-box'
      const dot = document.createElement('div')
      dot.textContent = String(rect.label)
      dot.style.position = 'absolute'
      dot.style.left = '-12px'
      dot.style.top = '-12px'
      dot.style.width = '26px'
      dot.style.height = '26px'
      dot.style.borderRadius = '999px'
      dot.style.background = '#dc2626'
      dot.style.color = 'white'
      dot.style.font = '700 14px/26px Arial, sans-serif'
      dot.style.textAlign = 'center'
      frame.appendChild(dot)
      document.body.appendChild(frame)
    }
  }, boxes)
}

async function shot(name, items = []) {
  await mark(items)
  await page.screenshot({ path: path.join(imageDir, name), fullPage: false })
  await clearMarks()
}

async function goto(pathname) {
  await page.goto(`${baseUrl}${pathname}`, { waitUntil: 'domcontentloaded' })
  await waitReady()
}

async function clickText(text) {
  const loc = page.getByText(text, { exact: true }).first()
  if (await loc.count()) {
    await loc.click()
    await waitReady()
  }
}

const token = await loginToken()

await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' })
await waitReady()
await shot('login-page.png', [
  { label: 1, selector: 'input[type="text"], input[type="email"]' },
  { label: 2, selector: 'input[type="password"]' },
  { label: 3, selector: 'button:has-text("登录")' },
  { label: 4, selector: 'text=没有账号' },
])

await clickText('没有账号？新建账户')
await shot('register-page.png', [
  { label: 1, selector: 'input[type="text"], input[type="email"]' },
  { label: 2, selector: 'input[type="password"]' },
  { label: 3, selector: 'button:has-text("新建账户")' },
  { label: 4, selector: 'text=已有账号' },
])

await installLoginState(token)

await goto('/workspace')
await clickText('验收会话')
await shot('workspace-overview.png', [
  { label: 1, selector: 'button:has-text("＋ 新建会话")' },
  { label: 2, selector: 'text=验收会话' },
  { label: 3, selector: 'main' },
  { label: 4, selector: 'textarea, [contenteditable="true"]' },
])
await shot('workspace-message-reply.png', [
  { label: 1, selector: 'text=当前会话已绑定问答验收专家' },
  { label: 2, selector: 'text=问答验收专家' },
  { label: 3, selector: 'textarea, [contenteditable="true"]' },
  { label: 4, selector: 'button:has-text("发送")' },
])
await shot('workspace-member-file.png', [
  { label: 1, selector: 'text=问答验收专家' },
  { label: 2, selector: 'button:has-text("文件")' },
  { label: 3, selector: 'text=验收说明.md' },
  { label: 4, selector: 'button:has-text("场景")' },
])

await goto('/resources/scenario')
await clickText('问答验收场景')
await shot('resources-scenario.png', [
  { label: 1, selector: 'button:has-text("新建场景")' },
  { label: 2, selector: 'text=问答验收场景' },
  { label: 3, selector: 'text=协作专家' },
  { label: 4, selector: 'button:has-text("保存")' },
])

await goto('/resources/agent')
await clickText('问答验收专家')
await shot('resources-expert.png', [
  { label: 1, selector: 'button:has-text("新建专家")' },
  { label: 2, selector: 'text=问答验收专家' },
  { label: 3, selector: 'text=系统提示词' },
  { label: 4, selector: 'button:has-text("保存")' },
])

await goto('/resources/skill')
await clickText('问答验收技能')
await shot('resources-skill.png', [
  { label: 1, selector: 'button:has-text("新建技能")' },
  { label: 2, selector: 'text=问答验收技能' },
  { label: 3, selector: 'text=技能运行时依赖' },
  { label: 4, selector: 'button:has-text("保存")' },
])

await goto('/resources/mcp')
await clickText('验收工具')
await shot('resources-tool.png', [
  { label: 1, selector: 'button:has-text("新建工具")' },
  { label: 2, selector: 'text=验收工具' },
  { label: 3, selector: 'text=传输方式' },
  { label: 4, selector: 'button:has-text("保存")' },
])

await goto('/resources/llm')
await shot('resources-model.png', [
  { label: 1, selector: 'text=jeniya' },
  { label: 2, selector: 'text=Base URL' },
  { label: 3, selector: 'text=模型' },
  { label: 4, selector: 'button:has-text("保存")' },
])

await goto('/resources/files')
await shot('resources-files.png', [
  { label: 1, selector: 'text=验收会话' },
  { label: 2, selector: 'text=验收说明.md' },
  { label: 3, selector: 'button:has-text("新建文件")' },
  { label: 4, selector: 'button:has-text("上传")' },
])

await goto('/settings/app')
await shot('settings-host.png', [
  { label: 1, selector: 'text=全局' },
  { label: 2, selector: 'text=默认主持人' },
  { label: 3, selector: 'text=模型' },
  { label: 4, selector: 'button:has-text("保存")' },
])

await goto('/settings/env-vars')
await shot('settings-env.png', [
  { label: 1, selector: 'button:has-text("新建环境变量")' },
  { label: 2, selector: 'text=jeniya' },
  { label: 3, selector: 'text=已保存' },
  { label: 4, selector: 'button:has-text("保存")' },
])

await goto('/settings/sandbox')
await shot('settings-sandbox.png', [
  { label: 1, selector: 'text=普通版' },
  { label: 2, selector: 'text=Playwright 版' },
  { label: 3, selector: 'textarea' },
  { label: 4, selector: 'button:has-text("保存")' },
])

await goto('/settings/account-security')
await shot('settings-account-theme.png', [
  { label: 1, selector: 'text=修改账号' },
  { label: 2, selector: 'text=修改密码' },
  { label: 3, selector: 'input[type="password"]' },
  { label: 4, selector: 'button:has-text("保存")' },
])

await goto('/settings/theme')
await shot('settings-theme.png', [
  { label: 1, selector: 'text=白色' },
  { label: 2, selector: 'text=浅色' },
  { label: 3, selector: 'text=黑色' },
  { label: 4, selector: 'text=绿色' },
])

await goto('/resources/scenario')
await shot('import-preview.png', [
  { label: 1, selector: 'text=场景' },
  { label: 2, selector: 'text=问答验收场景' },
  { label: 3, selector: 'button[title="导入场景包（ZIP）"]' },
  { label: 4, selector: 'button[title="导出场景包（ZIP）"]' },
])
await shot('import-result.png', [
  { label: 1, selector: 'text=资源中心' },
  { label: 2, selector: 'text=场景' },
  { label: 3, selector: 'button[title="导入场景包（ZIP）"]' },
  { label: 4, selector: 'button[title="导出场景包（ZIP）"]' },
])

await browser.close()
